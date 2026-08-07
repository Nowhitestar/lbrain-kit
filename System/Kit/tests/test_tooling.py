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
            result = self.run_check(copy)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing frontmatter fields", result.stdout)
            self.assertIn("public note links non-public note", result.stdout)
            self.assertIn("unresolved Wikilink", result.stdout)
            self.assertIn("woven Source has no backlink", result.stdout)

    def test_isolated_runtime_adapters_and_conflict_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            for runtime in ("codex", "claude", "hermes"):
                target = base / runtime
                result = subprocess.run(
                    [sys.executable, str(INSTALL), "--runtime", runtime, "--target", str(target)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                installed = sorted(target.glob("*/SKILL.md"))
                self.assertEqual(len(installed), 6)
                self.assertTrue(all(path.parent.is_symlink() for path in installed))

                conflict = subprocess.run(
                    [sys.executable, str(INSTALL), "--runtime", runtime, "--target", str(target)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(conflict.returncode, 0)
                self.assertIn("refusing to overwrite", conflict.stderr)

            copy_target = base / "copy"
            copied = subprocess.run(
                [sys.executable, str(INSTALL), "--runtime", "codex", "--target", str(copy_target), "--mode", "copy"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(copied.returncode, 0, copied.stdout + copied.stderr)
            self.assertFalse(next(copy_target.glob("*/SKILL.md")).parent.is_symlink())

            dry_target = base / "dry"
            preview = subprocess.run(
                [sys.executable, str(INSTALL), "--runtime", "codex", "--target", str(dry_target), "--dry-run"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
            self.assertFalse(dry_target.exists())


if __name__ == "__main__":
    unittest.main()
