from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "System/Kit"))

from transaction import mutation_locks  # noqa: E402


CHECK = ROOT / "System/Kit/check.py"
INSTALL = ROOT / "Skills/Kit/lbrain-skill-manager/scripts/install.py"
CORE_SKILLS = {
    "lbrain-capture",
    "lbrain-weave",
    "lbrain-retrieve",
    "lbrain-review",
    "lbrain-write",
    "lbrain-skill-manager",
    "lbrain-context-pack",
}


class ToolingSmokeTest(unittest.TestCase):
    def run_check(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECK), "--root", str(root)],
            text=True,
            capture_output=True,
            check=False,
        )

    def copy_repo(self, destination: Path) -> Path:
        copy = destination / "lbrain"
        shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        return copy

    def test_validator_accepts_kit(self) -> None:
        result = self.run_check(ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_validator_rejects_metadata_links_and_unwoven_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copy = self.copy_repo(Path(temporary))
            (copy / "Inbox/bare.md").write_text("# No metadata\n", encoding="utf-8")
            (copy / "Inbox/private.md").write_text(
                "---\ntype: note\nsummary: private\nstatus: active\nvisibility: private\ncreated: 2026-08-07\nupdated: 2026-08-07\n---\n# Private\n",
                encoding="utf-8",
            )
            (copy / "Inbox/public.md").write_text(
                "---\ntype: note\nsummary: public\nstatus: active\nvisibility: public\ncreated: 2026-08-07\nupdated: 2026-08-07\n---\n[[Inbox/private]] [[missing-note]]\n",
                encoding="utf-8",
            )
            (copy / "Knowledge/Sources/unwoven.md").write_text(
                "---\ntype: source\nsummary: source\nstatus: active\nvisibility: private\norigin: synthetic\ncapture: reference\nweaving: woven\ncreated: 2026-08-07\nupdated: 2026-08-07\n---\n# Source\n",
                encoding="utf-8",
            )
            duplicate_definition = (
                "---\ntype: context-pack\npack_id: duplicate-pack\nsummary: duplicate\n"
                "status: draft\nvisibility: private\ncreated: 2026-08-07\nupdated: 2026-08-07\n---\n"
                "# Duplicate Pack\n"
            )
            (copy / "Outputs/Context-Packs/duplicate-a.md").write_text(duplicate_definition, encoding="utf-8")
            (copy / "Outputs/Context-Packs/duplicate-b.md").write_text(duplicate_definition, encoding="utf-8")
            result = self.run_check(copy)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing frontmatter fields", result.stdout)
            self.assertIn("public note links non-public note", result.stdout)
            self.assertIn("unresolved Wikilink", result.stdout)
            self.assertIn("woven Source has no backlink", result.stdout)
            self.assertIn("context-pack pack_id duplicates", result.stdout)

    def test_validator_preserves_wikilink_markup_in_source_body(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copy = self.copy_repo(Path(temporary))
            (copy / "Knowledge/Sources/imported.md").write_text(
                "---\ntype: source\nsummary: imported source\nstatus: active\nvisibility: private\n"
                "origin: synthetic\ncapture: full\nweaving: pending\ncreated: 2026-08-07\nupdated: 2026-08-07\n"
                "---\n# Imported Source\n\nThe captured body contains author markup: [[not-an-lbrain-link]].\n",
                encoding="utf-8",
            )
            result = self.run_check(copy)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("not-an-lbrain-link", result.stdout)

    def test_validator_rejects_nonportable_skill_frontmatter_and_missing_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copy = self.copy_repo(Path(temporary))
            skill = copy / "Skills/Kit/lbrain-capture/SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8").replace("description:", "version: 1.0.0\ndescription:", 1),
                encoding="utf-8",
            )
            (copy / "Skills/Kit/lbrain-capture/lbrain.json").unlink()
            result = self.run_check(copy)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("non-portable SKILL.md frontmatter fields: version", result.stdout)
            self.assertIn("LBrain skill manifest is missing", result.stdout)

    def test_validator_scans_public_manifests_without_echoing_sensitive_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copy = self.copy_repo(Path(temporary))
            manifest = copy / "Skills/Kit/lbrain-capture/lbrain.json"
            data = manifest.read_text(encoding="utf-8").rstrip()
            sensitive_value = "fixture-secret-value-12345"
            data = data[:-1] + f',"provenance":{{"path":"/Users/example/private/file","api_key":"{sensitive_value}"}}}}\n'
            manifest.write_text(data, encoding="utf-8")
            result = self.run_check(copy)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("possible secret", result.stdout)
            self.assertIn("absolute private path", result.stdout)
            self.assertNotIn(sensitive_value, result.stdout + result.stderr)

            manifest.write_text(
                data[: data.index(',"provenance"')]
                + ',"next_cursor":"opaque-runtime-state-12345"}\n',
                encoding="utf-8",
            )
            runtime_state = self.run_check(copy)
            self.assertNotEqual(runtime_state.returncode, 0)
            self.assertIn("possible connector runtime state", runtime_state.stdout)

            manifest.write_text(data[: data.index(',"provenance"')] + "}\n", encoding="utf-8")
            disguised_secret = "api_key=response.real-" + "secret-token-12345"
            leak = copy / "System/Kit/leak.txt"
            leak.write_text(disguised_secret + "\n", encoding="utf-8")
            disguised = self.run_check(copy)
            self.assertNotEqual(disguised.returncode, 0)
            self.assertIn("possible secret", disguised.stdout)
            self.assertNotIn(disguised_secret, disguised.stdout + disguised.stderr)

            leak.unlink()
            (copy / "System/Kit/reference.py").write_text(
                'api_key = os.getenv("API_KEY")\n'
                'api_key = config.get("api_key")\n'
                'OPENAI_API_KEY: str = config.get("api_key")\n'
                'config["api_key"] = settings.api_key\n'
                "cursor = response.get_cursor(page)\n"
                "cursor==response.next_cursor\n",
                encoding="utf-8",
            )
            code_reference = self.run_check(copy)
            self.assertEqual(code_reference.returncode, 0, code_reference.stdout + code_reference.stderr)

            (copy / "System/Kit/reference.py").write_text(
                "# don't hardcode credentials\n"
                'config["auth"].api_key = rf"""\nfixture-generic-secret-12345\n"""\n'
                'cursor = str("opaque-real-cursor-12345")\n',
                encoding="utf-8",
            )
            hardcoded = self.run_check(copy)
            self.assertNotEqual(hardcoded.returncode, 0)
            self.assertIn("possible secret", hardcoded.stdout)
            self.assertIn("possible connector runtime state", hardcoded.stdout)

            (copy / "System/Kit/reference.py").unlink()
            concrete = "ghp_" + "abcdefghijklmnopqrstuvwxyz123456"
            (copy / "System/Kit/reference.ts").write_text(
                f'const apiKey = "{concrete}";\n',
                encoding="utf-8",
            )
            typescript = self.run_check(copy)
            self.assertNotEqual(typescript.returncode, 0)
            self.assertIn("possible secret", typescript.stdout)
            self.assertNotIn(concrete, typescript.stdout + typescript.stderr)

            (copy / "System/Kit/reference.ts").write_text(
                "const openaiApiKey: string = `\nfixture-generic-secret-12345\n`;\n"
                "let nextCursor: string = `\nopaque-real-cursor-12345\n`;\n",
                encoding="utf-8",
            )
            multiline_typescript = self.run_check(copy)
            self.assertNotEqual(multiline_typescript.returncode, 0)
            self.assertIn("possible secret", multiline_typescript.stdout)
            self.assertIn("possible connector runtime state", multiline_typescript.stdout)

            (copy / "System/Kit/reference.ts").write_text(
                "const apiKey = this.#secret;\n"
                "client.setApiKey(config.apiKey);\n",
                encoding="utf-8",
            )
            safe_typescript = self.run_check(copy)
            self.assertEqual(
                safe_typescript.returncode,
                0,
                safe_typescript.stdout + safe_typescript.stderr,
            )
            (copy / "System/Kit/reference.ts").write_text(
                'const apiKey = this.#secret || "fixture-secret-value-12345";\n'
                'client.setAccessToken("fixture-secret-value-12345");\n',
                encoding="utf-8",
            )
            unsafe_typescript = self.run_check(copy)
            self.assertNotEqual(unsafe_typescript.returncode, 0)
            self.assertIn("possible secret", unsafe_typescript.stdout)

            (copy / "System/Kit/reference.ts").unlink()
            shell = copy / "System/Kit/reference.sh"
            shell.write_text("API_KEY=$API_KEY command\n", encoding="utf-8")
            safe_shell = self.run_check(copy)
            self.assertEqual(safe_shell.returncode, 0, safe_shell.stdout + safe_shell.stderr)
            shell.write_text(
                "API_KEY=$API_KEY#fixture-secret-value-12345\n",
                encoding="utf-8",
            )
            unsafe_shell = self.run_check(copy)
            self.assertNotEqual(unsafe_shell.returncode, 0)
            self.assertIn("possible secret", unsafe_shell.stdout)

            shell.unlink()
            module = copy / "System/Kit/reference.mjs"
            module.write_text("const apiKey = config.apiKey;\n", encoding="utf-8")
            safe_module = self.run_check(copy)
            self.assertEqual(safe_module.returncode, 0, safe_module.stdout + safe_module.stderr)
            module.write_text(
                'updateApiKey("fixture-secret-value-12345");\n',
                encoding="utf-8",
            )
            (copy / "System/Kit/connector.cfg").write_text(
                "next_cursor=opaque-runtime-state-12345\n",
                encoding="utf-8",
            )
            extra_suffixes = self.run_check(copy)
            self.assertNotEqual(extra_suffixes.returncode, 0)
            self.assertIn("possible secret", extra_suffixes.stdout)
            self.assertIn("possible connector runtime state", extra_suffixes.stdout)

    def test_isolated_runtime_adapters_and_conflict_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = self.copy_repo(base)
            ignored = fixture / "Skills/Kit/lbrain-capture/__pycache__"
            ignored.mkdir()
            (ignored / "cache.pyc").write_bytes(b"generated")
            (fixture / "Skills/Kit/lbrain-capture/.git").write_text("runtime-irrelevant\n", encoding="utf-8")
            locked_target = base / "locked"
            with mutation_locks([locked_target]):
                locked = subprocess.run(
                    [
                        sys.executable,
                        str(INSTALL),
                        "--root",
                        str(fixture),
                        "--runtime",
                        "codex",
                        "--target",
                        str(locked_target),
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )
            self.assertNotEqual(locked.returncode, 0)
            self.assertIn("another LBrain mutation", locked.stderr)
            self.assertFalse(locked_target.exists())

            for runtime in ("codex", "claude", "hermes", "openclaw"):
                target = base / runtime
                result = subprocess.run(
                    [sys.executable, str(INSTALL), "--root", str(fixture), "--runtime", runtime, "--target", str(target)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                installed = sorted(target.glob("*/SKILL.md"))
                installed_names = {path.parent.name for path in installed}
                self.assertTrue(CORE_SKILLS <= installed_names)
                self.assertEqual(result.stdout.count("INSTALLED "), len(installed))
                if runtime == "openclaw":
                    self.assertTrue(all(not path.parent.is_symlink() for path in installed))
                    self.assertFalse((target / "lbrain-capture/.git").exists())
                    self.assertFalse((target / "lbrain-capture/__pycache__").exists())
                else:
                    self.assertTrue(all(path.parent.is_symlink() for path in installed))
                self.assertTrue(all((path.parent / "lbrain.json").is_file() for path in installed))

                conflict = subprocess.run(
                    [sys.executable, str(INSTALL), "--root", str(fixture), "--runtime", runtime, "--target", str(target)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(conflict.returncode, 0, conflict.stdout + conflict.stderr)
                self.assertIn("ALREADY INSTALLED", conflict.stdout)

            personal = fixture / "Skills/Personal/incremental-skill"
            (personal / "tests").mkdir(parents=True)
            (personal / "SKILL.md").write_text(
                "---\nname: incremental-skill\ndescription: Tests incremental installation.\n---\n# Incremental\n",
                encoding="utf-8",
            )
            (personal / "lbrain.json").write_text(
                '{"schema":"lbrain.skill.v1","version":"0.1.0","status":"active",'
                '"visibility":"private","created":"2026-08-07","updated":"2026-08-07"}\n',
                encoding="utf-8",
            )
            (personal / "tests/cases.md").write_text("# Cases\n", encoding="utf-8")
            with (fixture / "Skills/Enabled.md").open("a", encoding="utf-8") as file:
                file.write("\n- [[Skills/Personal/incremental-skill/SKILL]] — codex\n")
            incremental = subprocess.run(
                [sys.executable, str(INSTALL), "--root", str(fixture), "--runtime", "codex", "--target", str(base / "codex")],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(incremental.returncode, 0, incremental.stdout + incremental.stderr)
            self.assertTrue((base / "codex/incremental-skill/SKILL.md").is_file())

            conflict_path = base / "codex/lbrain-capture"
            conflict_path.unlink()
            conflict_path.mkdir()
            blocked = subprocess.run(
                [sys.executable, str(INSTALL), "--root", str(fixture), "--runtime", "codex", "--target", str(base / "codex")],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("refusing to overwrite", blocked.stderr)

            copy_target = base / "copy"
            copied = subprocess.run(
                [sys.executable, str(INSTALL), "--root", str(fixture), "--runtime", "codex", "--target", str(copy_target), "--mode", "copy"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(copied.returncode, 0, copied.stdout + copied.stderr)
            self.assertFalse(next(copy_target.glob("*/SKILL.md")).parent.is_symlink())
            copied_again = subprocess.run(
                [sys.executable, str(INSTALL), "--root", str(fixture), "--runtime", "codex", "--target", str(copy_target), "--mode", "copy"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(copied_again.returncode, 0, copied_again.stdout + copied_again.stderr)
            self.assertIn("ALREADY INSTALLED", copied_again.stdout)

            rejected_openclaw_symlink = subprocess.run(
                [
                    sys.executable,
                    str(INSTALL),
                    "--root",
                    str(fixture),
                    "--runtime",
                    "openclaw",
                    "--target",
                    str(base / "openclaw-symlink"),
                    "--mode",
                    "symlink",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(rejected_openclaw_symlink.returncode, 0)
            self.assertIn("OpenClaw rejects Skill symlinks", rejected_openclaw_symlink.stderr)

            leak = fixture / "Skills/Kit/lbrain-capture/private-link.md"
            leak.symlink_to(fixture / "Context/Identity/Profile.md")
            rejected_package_symlink = subprocess.run(
                [
                    sys.executable,
                    str(INSTALL),
                    "--root",
                    str(fixture),
                    "--runtime",
                    "openclaw",
                    "--target",
                    str(base / "openclaw-package-symlink"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(rejected_package_symlink.returncode, 0)
            self.assertIn("must not contain symlinks", rejected_package_symlink.stderr)
            self.assertFalse((base / "openclaw-package-symlink/lbrain-capture").exists())
            validator = self.run_check(fixture)
            self.assertNotEqual(validator.returncode, 0)
            self.assertIn("Skill packages must not contain symlinks", validator.stdout)
            leak.unlink()

            outside = base / "outside-skill"
            (outside / "tests").mkdir(parents=True)
            (outside / "SKILL.md").write_text(
                "---\nname: outside-skill\ndescription: Must not install.\n---\n# Outside\n",
                encoding="utf-8",
            )
            (outside / "lbrain.json").write_text(
                '{"schema":"lbrain.skill.v1","version":"0.1.0","status":"active",'
                '"visibility":"private","created":"2026-08-07","updated":"2026-08-07"}\n',
                encoding="utf-8",
            )
            (outside / "tests/cases.md").write_text("# Cases\n", encoding="utf-8")
            with (fixture / "Skills/Enabled.md").open("a", encoding="utf-8") as file:
                file.write("\n- [[../outside-skill/SKILL]] — codex\n")
            rejected_escape = subprocess.run(
                [
                    sys.executable,
                    str(INSTALL),
                    "--root",
                    str(fixture),
                    "--runtime",
                    "codex",
                    "--target",
                    str(base / "escaped-target"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(rejected_escape.returncode, 0)
            self.assertIn("enabled skill target", rejected_escape.stderr)
            self.assertFalse((base / "escaped-target/outside-skill").exists())
            enabled = fixture / "Skills/Enabled.md"
            enabled.write_text(
                enabled.read_text(encoding="utf-8").replace("\n- [[../outside-skill/SKILL]] — codex\n", "\n"),
                encoding="utf-8",
            )

            dry_target = base / "dry"
            preview = subprocess.run(
                [sys.executable, str(INSTALL), "--root", str(fixture), "--runtime", "codex", "--target", str(dry_target), "--dry-run"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
            self.assertFalse(dry_target.exists())


if __name__ == "__main__":
    unittest.main()
