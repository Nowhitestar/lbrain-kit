from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RETRIEVAL = ROOT / "Skills/Kit/lbrain-retrieve/scripts/retrieval.py"


class RetrievalAdapterTest(unittest.TestCase):
    def fixture(self, base: Path) -> Path:
        root = base / "lbrain"
        for directory in (
            "System/Kit",
            "Knowledge/Wiki/Concepts",
            "Skills/Kit/lbrain-retrieve",
            "Outputs/Context-Packs/Candidates/generated",
        ):
            (root / directory).mkdir(parents=True, exist_ok=True)
        (root / "System/Kit/OWNERSHIP.md").write_text("# Ownership\n", encoding="utf-8")
        (root / "Knowledge/Wiki/Index.md").write_text(
            "# Index\n\n[[Knowledge/Wiki/Concepts/Retrieval-Decision]]\n",
            encoding="utf-8",
        )
        (root / "Knowledge/Wiki/Concepts/Retrieval-Decision.md").write_text(
            "# Retrieval Decision\n\nThe portable retrieval phrase is quartz-memory-signal.\n",
            encoding="utf-8",
        )
        (root / "Skills/Kit/lbrain-retrieve/SKILL.md").write_text(
            "---\nname: lbrain-retrieve\ndescription: Retrieve fixture context.\n---\n# Retrieve\n",
            encoding="utf-8",
        )
        (root / "Outputs/Context-Packs/Candidates/generated/Hidden.md").write_text(
            "# Hidden\n\nquartz-memory-signal\n",
            encoding="utf-8",
        )
        return root

    def run_adapter(
        self,
        *arguments: str,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        variables = os.environ.copy()
        variables["LBRAIN_QMD_BIN"] = str(Path("/missing/qmd"))
        if env:
            variables.update(env)
        return subprocess.run(
            [sys.executable, str(RETRIEVAL), *arguments],
            text=True,
            capture_output=True,
            check=False,
            env=variables,
            cwd=cwd,
        )

    def test_filesystem_fallback_is_explicit_and_excludes_generated_packs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.fixture(Path(temporary))
            doctor = self.run_adapter("doctor", "--root", str(root))
            self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
            report = json.loads(doctor.stdout)
            self.assertEqual(report["provider"], "filesystem")
            self.assertTrue(report["degraded"])

            query = self.run_adapter(
                "query",
                "quartz-memory-signal",
                "--provider",
                "filesystem",
                "--root",
                str(root),
            )
            self.assertEqual(query.returncode, 0, query.stdout + query.stderr)
            results = json.loads(query.stdout)
            self.assertEqual(results[0]["file"], "Knowledge/Wiki/Concepts/Retrieval-Decision.md")
            self.assertTrue(results[0]["degraded"])
            self.assertFalse(any("Candidates" in item["file"] for item in results))

    def test_get_rejects_paths_outside_lbrain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.fixture(Path(temporary))
            result = self.run_adapter("get", "../outside.md", "--root", str(root))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("escapes", result.stderr)

    def test_bounded_reads_and_index_names_reject_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.fixture(base)
            cases = (
                ("query", "quartz", "--provider", "filesystem", "--limit", "0"),
                ("get", "Knowledge/Wiki/Index.md", "--max-lines", "-1"),
                ("get", "Knowledge/Wiki/Index.md", "--from-line", "0"),
                ("multi-get", "Knowledge/Wiki/**/*.md", "--limit", "-1"),
                ("multi-get", "Knowledge/Wiki/**/*.md", "--max-lines", "0"),
            )
            for arguments in cases:
                with self.subTest(arguments=arguments):
                    result = self.run_adapter(*arguments, "--root", str(root))
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("greater than zero", result.stderr)

            config = base / "qmd-config"
            escaped = self.run_adapter(
                "configure",
                "--root",
                str(root),
                "--index",
                "../escaped",
                "--apply",
                env={"QMD_CONFIG_DIR": str(config)},
            )
            self.assertNotEqual(escaped.returncode, 0)
            self.assertIn("qmd index", escaped.stderr)
            self.assertFalse((base / "escaped.yml").exists())

    def test_multi_get_applies_file_and_line_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.fixture(Path(temporary))
            (root / "Knowledge/Wiki/Concepts/Second.md").write_text(
                "# Second\n\nline two\nline three\n",
                encoding="utf-8",
            )
            result = self.run_adapter(
                "multi-get",
                "Knowledge/Wiki/Concepts/*.md",
                "--limit",
                "1",
                "--max-lines",
                "2",
                "--root",
                str(root),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.count("--- Knowledge/"), 1)
            self.assertEqual(len(result.stdout.splitlines()), 3)

    def test_configure_is_dry_run_idempotent_and_conflict_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.fixture(base)
            config_dir = base / "qmd-config"
            environment = {"QMD_CONFIG_DIR": str(config_dir)}
            preview = self.run_adapter("configure", "--root", str(root), env=environment)
            self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
            self.assertIn("DRY RUN", preview.stdout)
            self.assertFalse((config_dir / "lbrain.yml").exists())

            applied = self.run_adapter("configure", "--root", str(root), "--apply", env=environment)
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            config_path = config_dir / "lbrain.yml"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config["collections"]["brain"]["path"], str(root.resolve()))
            self.assertIn("Outputs/Context-Packs/Repos/**", config["collections"]["brain"]["ignore"])

            repeated = self.run_adapter("configure", "--root", str(root), "--apply", env=environment)
            self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
            self.assertIn("ALREADY CONFIGURED", repeated.stdout)

            config_path.write_text("different: true\n", encoding="utf-8")
            conflict = self.run_adapter("configure", "--root", str(root), "--apply", env=environment)
            self.assertNotEqual(conflict.returncode, 0)
            self.assertIn("refusing to overwrite", conflict.stderr)

    def test_root_registry_is_dry_run_idempotent_and_enables_copy_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.fixture(base)
            config = base / "lbrain-config"
            environment = {"LBRAIN_CONFIG_DIR": str(config)}

            preview = self.run_adapter("register", "--root", str(root), env=environment)
            self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
            self.assertIn("DRY RUN", preview.stdout)
            self.assertFalse((config / "root").exists())

            applied = self.run_adapter("register", "--root", str(root), "--apply", env=environment)
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            self.assertEqual((config / "root").read_text(encoding="utf-8"), f"{root.resolve()}\n")

            elsewhere = base / "elsewhere"
            elsewhere.mkdir()
            from_elsewhere = self.run_adapter("doctor", env=environment, cwd=elsewhere)
            self.assertEqual(from_elsewhere.returncode, 0, from_elsewhere.stdout + from_elsewhere.stderr)
            self.assertEqual(json.loads(from_elsewhere.stdout)["root"], str(root.resolve()))

            repeated = self.run_adapter("register", "--root", str(root), "--apply", env=environment)
            self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
            self.assertIn("ALREADY REGISTERED", repeated.stdout)

            (config / "root").write_text(f"{base / 'different'}\n", encoding="utf-8")
            conflict = self.run_adapter("register", "--root", str(root), "--apply", env=environment)
            self.assertNotEqual(conflict.returncode, 0)
            self.assertIn("refusing to overwrite divergent LBrain root registry", conflict.stderr)

    def test_root_discovery_supports_environment_cwd_and_canonical_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.fixture(base)
            empty_config = base / "empty-config"
            elsewhere = base / "elsewhere"
            elsewhere.mkdir()

            from_environment = self.run_adapter(
                "doctor",
                env={"LBRAIN_ROOT": str(root), "LBRAIN_CONFIG_DIR": str(empty_config)},
                cwd=elsewhere,
            )
            self.assertEqual(from_environment.returncode, 0, from_environment.stdout + from_environment.stderr)
            self.assertEqual(json.loads(from_environment.stdout)["root"], str(root.resolve()))

            from_cwd = self.run_adapter(
                "doctor",
                env={"LBRAIN_ROOT": "", "LBRAIN_CONFIG_DIR": str(empty_config)},
                cwd=root / "Knowledge/Wiki/Concepts",
            )
            self.assertEqual(from_cwd.returncode, 0, from_cwd.stdout + from_cwd.stderr)
            self.assertEqual(json.loads(from_cwd.stdout)["root"], str(root.resolve()))

            scripts = root / "Skills/Kit/lbrain-retrieve/scripts"
            scripts.mkdir()
            shutil.copy2(RETRIEVAL, scripts / "retrieval.py")
            installed = base / "installed/lbrain-retrieve"
            installed.parent.mkdir()
            installed.symlink_to(root / "Skills/Kit/lbrain-retrieve", target_is_directory=True)
            variables = os.environ.copy()
            variables.update(
                {
                    "LBRAIN_ROOT": "",
                    "LBRAIN_CONFIG_DIR": str(empty_config),
                    "LBRAIN_QMD_BIN": "/missing/qmd",
                }
            )
            from_symlink = subprocess.run(
                [sys.executable, str(installed / "scripts/retrieval.py"), "doctor"],
                text=True,
                capture_output=True,
                check=False,
                env=variables,
                cwd=elsewhere,
            )
            self.assertEqual(from_symlink.returncode, 0, from_symlink.stdout + from_symlink.stderr)
            self.assertEqual(json.loads(from_symlink.stdout)["root"], str(root.resolve()))

    def test_matching_qmd_provider_routes_query_and_maintenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.fixture(base)
            fake = base / "qmd"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                f"root = {str(root)!r}\n"
                "args = sys.argv[1:]\n"
                "mode = os.environ.get('FAKE_QMD_MODE', '')\n"
                "if 'collection' in args and 'show' in args:\n"
                "    print('Collection: brain')\n"
                "    print('  Path:     ' + root)\n"
                "elif 'status' in args:\n"
                "    if mode == 'status-fail':\n"
                "        print('status failed', file=sys.stderr)\n"
                "        raise SystemExit(3)\n"
                "    print('QMD STATUS OK')\n"
                "    print('  Updated:  5m ago')\n"
                "elif 'ls' in args:\n"
                "    if mode == 'unsafe-index' and 'Candidates' in args[-1]:\n"
                "        print('qmd://brain/Outputs/Context-Packs/Candidates/private.md')\n"
                "    else:\n"
                "        print('No files found under ' + args[-1])\n"
                "elif 'query' in args:\n"
                "    if mode == 'query-fail':\n"
                "        print('query failed', file=sys.stderr)\n"
                "        raise SystemExit(4)\n"
                "    path = ('qmd://brain/Outputs/Context-Packs/Candidates/private.md'\n"
                "            if mode == 'unsafe-result' else\n"
                "            'qmd://brain/Knowledge/Wiki/Concepts/Retrieval-Decision.md')\n"
                "    print(json.dumps([{'file':path,'score':0.99}]))\n"
                "elif 'update' in args:\n"
                "    print('QMD UPDATE OK')\n"
                "elif 'embed' in args:\n"
                "    print('QMD EMBED OK')\n"
                "elif 'mcp' in args:\n"
                "    print('QMD MCP OK')\n"
                "else:\n"
                "    print('unsupported', file=sys.stderr)\n"
                "    raise SystemExit(2)\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            environment = {"LBRAIN_QMD_BIN": str(fake)}
            doctor = self.run_adapter("doctor", "--root", str(root), env=environment)
            self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
            report = json.loads(doctor.stdout)
            self.assertEqual(report["provider"], "qmd")
            self.assertTrue(report["qmd"]["healthy"])
            self.assertEqual(report["qmd"]["updated"], "5m ago")

            required = self.run_adapter("doctor", "--require-qmd", "--root", str(root), env=environment)
            self.assertEqual(required.returncode, 0, required.stdout + required.stderr)

            query = self.run_adapter("query", "quartz", "--root", str(root), env=environment)
            self.assertEqual(query.returncode, 0, query.stdout + query.stderr)
            self.assertIn("qmd://brain/Knowledge/Wiki", query.stdout)

            update = self.run_adapter("update", "--root", str(root), env=environment)
            self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
            self.assertIn("QMD UPDATE OK", update.stdout)

            embed = self.run_adapter("embed", "--root", str(root), env=environment)
            self.assertEqual(embed.returncode, 0, embed.stdout + embed.stderr)
            self.assertIn("QMD EMBED OK", embed.stdout)

            status = self.run_adapter("status", "--root", str(root), env=environment)
            self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
            self.assertIn("QMD STATUS OK", status.stdout)

            mcp = self.run_adapter("mcp", "--root", str(root), env=environment)
            self.assertEqual(mcp.returncode, 0, mcp.stdout + mcp.stderr)
            self.assertIn("QMD MCP OK", mcp.stdout)

            unhealthy = self.run_adapter(
                "doctor",
                "--require-qmd",
                "--root",
                str(root),
                env={**environment, "FAKE_QMD_MODE": "status-fail"},
            )
            self.assertNotEqual(unhealthy.returncode, 0)
            self.assertTrue(json.loads(unhealthy.stdout)["degraded"])

            unsafe_index = self.run_adapter(
                "doctor",
                "--require-qmd",
                "--root",
                str(root),
                env={**environment, "FAKE_QMD_MODE": "unsafe-index"},
            )
            self.assertNotEqual(unsafe_index.returncode, 0)
            self.assertFalse(json.loads(unsafe_index.stdout)["qmd"]["exclusions"]["Outputs/Context-Packs/Candidates"])

            for mode in ("query-fail", "unsafe-result"):
                with self.subTest(mode=mode):
                    automatic = self.run_adapter(
                        "query",
                        "quartz-memory-signal",
                        "--root",
                        str(root),
                        env={**environment, "FAKE_QMD_MODE": mode},
                    )
                    self.assertEqual(automatic.returncode, 0, automatic.stdout + automatic.stderr)
                    self.assertEqual(json.loads(automatic.stdout)[0]["provider"], "filesystem")

                    explicit = self.run_adapter(
                        "query",
                        "quartz-memory-signal",
                        "--provider",
                        "qmd",
                        "--root",
                        str(root),
                        env={**environment, "FAKE_QMD_MODE": mode},
                    )
                    self.assertNotEqual(explicit.returncode, 0)


if __name__ == "__main__":
    unittest.main()
