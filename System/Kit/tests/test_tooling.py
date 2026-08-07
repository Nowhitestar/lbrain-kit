from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
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

    def test_isolated_runtime_adapters_and_conflict_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = self.copy_repo(base)
            for runtime in ("codex", "claude", "hermes"):
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
                self.assertTrue(all(path.parent.is_symlink() for path in installed))

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
            (personal / "SKILL.md").write_text("---\nname: incremental-skill\ndescription: Tests incremental installation.\nversion: 0.1.0\nstatus: active\nvisibility: private\ncreated: 2026-08-07\nupdated: 2026-08-07\n---\n# Incremental\n", encoding="utf-8")
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
