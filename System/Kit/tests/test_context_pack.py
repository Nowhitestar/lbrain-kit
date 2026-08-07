from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PACK = ROOT / "Skills/Kit/lbrain-context-pack/scripts/pack.py"


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file() and ".git" not in item.parts):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class ContextPackTest(unittest.TestCase):
    def copy_repo(self, destination: Path) -> Path:
        copy = destination / "lbrain"
        shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__", ".scratch"))
        return copy

    def run_pack(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(root / PACK.relative_to(ROOT)), "--root", str(root), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def write_note(self, root: Path, relative: str, metadata: str, body: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\n{metadata.strip()}\n---\n{body}", encoding="utf-8")

    def test_create_writes_a_private_definition_without_remote_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))

            result = self.run_pack(root, "create", "agentkey-growth", "--summary", "AgentKey growth context")

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            definition = root / "Outputs/Context-Packs/agentkey-growth.md"
            self.assertTrue(definition.is_file())
            text = definition.read_text(encoding="utf-8")
            self.assertIn("type: context-pack", text)
            self.assertIn("pack_id: agentkey-growth", text)
            self.assertIn("visibility: private", text)
            self.assertIn("status: draft", text)
            self.assertIn("## Includes", text)
            self.assertNotIn("repository:", text)
            self.assertFalse((root / ".gitmodules").exists())
            self.assertIn("CREATED Outputs/Context-Packs/agentkey-growth.md", result.stdout)

    def test_preview_resolves_paths_queries_exclusions_and_dependencies_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            self.write_note(
                root,
                "Context/Projects/AgentKey.md",
                """
type: project
summary: AgentKey project
status: active
visibility: public
outcome: Grow the product
source_of_truth: synthetic
created: 2026-08-07
updated: 2026-08-07
""",
                "# AgentKey\n\n[[Knowledge/Wiki/Analyses/Growth-Learnings]]\n",
            )
            self.write_note(
                root,
                "Knowledge/Wiki/Analyses/Growth-Learnings.md",
                """
type: knowledge
kind: analysis
summary: Growth lessons
status: active
visibility: public
sources:
  - synthetic
created: 2026-08-07
updated: 2026-08-07
""",
                "# Growth Learnings\n",
            )
            self.write_note(
                root,
                "Knowledge/Wiki/Analyses/Excluded.md",
                """
type: knowledge
kind: analysis
summary: Excluded analysis
status: active
visibility: public
sources:
  - synthetic
created: 2026-08-07
updated: 2026-08-07
""",
                "# Excluded\n",
            )
            definition = root / "Outputs/Context-Packs/agentkey-growth.md"
            definition.parent.mkdir(parents=True, exist_ok=True)
            definition.write_text(
                """---
type: context-pack
pack_id: agentkey-growth
summary: AgentKey growth context
status: draft
visibility: public
license: MIT
created: 2026-08-07
updated: 2026-08-07
---
# AgentKey Growth

## Purpose

Share reusable growth context.

## Includes

- path: Context/Projects/AgentKey.md
- query: type=knowledge, kind=analysis

## Excludes

- path: Knowledge/Wiki/Analyses/Excluded.md

## Skills

## Build Notes
""",
                encoding="utf-8",
            )
            before = tree_digest(root)

            result = self.run_pack(root, "preview", "Outputs/Context-Packs/agentkey-growth.md")

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(tree_digest(root), before)
            self.assertIn("PACK agentkey-growth", result.stdout)
            self.assertIn("DIRECT Context/Projects/AgentKey.md", result.stdout)
            self.assertIn("DIRECT Knowledge/Wiki/Analyses/Growth-Learnings.md", result.stdout)
            self.assertIn("EXCLUDED Knowledge/Wiki/Analyses/Excluded.md", result.stdout)
            self.assertIn("SUMMARY direct=2 dependencies=0 excluded=1 blocked=0", result.stdout)

    def test_preview_reports_private_dependency_and_invalid_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            self.write_note(
                root,
                "Context/Projects/Public.md",
                """
type: project
summary: Public project
status: active
visibility: public
outcome: Share safely
source_of_truth: synthetic
created: 2026-08-07
updated: 2026-08-07
""",
                "# Public\n\n[[Context/Projects/Private]]\n",
            )
            self.write_note(
                root,
                "Context/Projects/Private.md",
                """
type: project
summary: Private project
status: active
visibility: private
outcome: Keep private
source_of_truth: synthetic
created: 2026-08-07
updated: 2026-08-07
""",
                "# Private\n",
            )
            definition = root / "Outputs/Context-Packs/public-pack.md"
            definition.parent.mkdir(parents=True, exist_ok=True)
            definition.write_text(
                """---
type: context-pack
pack_id: public-pack
summary: Public pack
status: draft
visibility: public
license: MIT
created: 2026-08-07
updated: 2026-08-07
---
# Public Pack

## Purpose

Test safety.

## Includes

- path: Context/Projects/Public.md
- path: ../outside.md

## Excludes

## Skills

## Build Notes
""",
                encoding="utf-8",
            )

            result = self.run_pack(root, "preview", "Outputs/Context-Packs/public-pack.md")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("DEPENDENCY Context/Projects/Private.md", result.stdout)
            self.assertIn("BLOCK private dependency: Context/Projects/Private.md", result.stdout)
            self.assertIn("BLOCK selector escapes LBrain root: ../outside.md", result.stdout)


if __name__ == "__main__":
    unittest.main()
