from __future__ import annotations

import json
import os
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

    def test_matching_qmd_provider_routes_query_and_maintenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.fixture(base)
            fake = base / "qmd"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                f"root = {str(root)!r}\n"
                "args = sys.argv[1:]\n"
                "if 'collection' in args and 'show' in args:\n"
                "    print('Collection: brain')\n"
                "    print('  Path:     ' + root)\n"
                "elif 'query' in args:\n"
                "    print(json.dumps([{'file':'qmd://brain/Knowledge/Wiki/Concepts/Retrieval-Decision.md','score':0.99}]))\n"
                "elif 'update' in args:\n"
                "    print('QMD UPDATE OK')\n"
                "elif 'status' in args:\n"
                "    print('QMD STATUS OK')\n"
                "else:\n"
                "    print('unsupported', file=sys.stderr)\n"
                "    raise SystemExit(2)\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            environment = {"LBRAIN_QMD_BIN": str(fake)}
            doctor = self.run_adapter("doctor", "--root", str(root), env=environment)
            self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
            self.assertEqual(json.loads(doctor.stdout)["provider"], "qmd")

            query = self.run_adapter("query", "quartz", "--root", str(root), env=environment)
            self.assertEqual(query.returncode, 0, query.stdout + query.stderr)
            self.assertIn("qmd://brain/Knowledge/Wiki", query.stdout)

            update = self.run_adapter("update", "--root", str(root), env=environment)
            self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
            self.assertIn("QMD UPDATE OK", update.stdout)


if __name__ == "__main__":
    unittest.main()
