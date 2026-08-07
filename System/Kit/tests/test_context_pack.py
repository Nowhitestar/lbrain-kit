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

    def test_build_creates_a_portable_deterministic_candidate_without_git_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            self.write_note(
                root,
                "Context/Projects/AgentKey.md",
                """
type: project
summary: AgentKey project context
status: active
visibility: public
outcome: Grow the product
source_of_truth: synthetic
created: 2026-08-07
updated: 2026-08-07
""",
                "# AgentKey\n\nUse [[Knowledge/Wiki/Analyses/Growth-Learnings|growth lessons]].\n",
            )
            self.write_note(
                root,
                "Knowledge/Wiki/Analyses/Growth-Learnings.md",
                """
type: knowledge
kind: analysis
summary: Reusable growth lessons
status: active
visibility: public
sources:
  - synthetic
created: 2026-08-07
updated: 2026-08-07
""",
                "# Growth Learnings\n\nPrefer durable evidence.\n",
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

Help an agent understand AgentKey growth decisions.

## Includes

- path: Context/Projects/AgentKey.md

## Excludes

## Skills

## Build Notes
""",
                encoding="utf-8",
            )

            result = self.run_pack(root, "build", "Outputs/Context-Packs/agentkey-growth.md")

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            candidate = root / "Outputs/Context-Packs/Candidates/agentkey-growth"
            self.assertTrue((candidate / "PACK.md").is_file())
            self.assertTrue((candidate / "SOURCES.md").is_file())
            self.assertTrue((candidate / "context/AgentKey.md").is_file())
            self.assertTrue((candidate / "knowledge/Growth-Learnings.md").is_file())
            self.assertFalse((candidate / "artifacts").exists())
            manifest = (candidate / "PACK.md").read_text(encoding="utf-8")
            self.assertIn("pack_id: agentkey-growth", manifest)
            self.assertIn("release_status: candidate", manifest)
            self.assertIn("## Loading Order", manifest)
            context = (candidate / "context/AgentKey.md").read_text(encoding="utf-8")
            self.assertIn("[growth lessons](../knowledge/Growth-Learnings.md)", context)
            self.assertNotIn("[[", context)
            sources = (candidate / "SOURCES.md").read_text(encoding="utf-8")
            self.assertIn("AgentKey project context", sources)
            self.assertNotIn(str(root), sources)
            self.assertFalse((root / ".gitmodules").exists())
            first_digest = tree_digest(candidate)

            rebuilt = self.run_pack(root, "build", "Outputs/Context-Packs/agentkey-growth.md")

            self.assertEqual(rebuilt.returncode, 0, rebuilt.stdout + rebuilt.stderr)
            self.assertEqual(tree_digest(candidate), first_digest)
            self.assertIn("BUILT Outputs/Context-Packs/Candidates/agentkey-growth", rebuilt.stdout)

    def test_build_includes_resources_referenced_by_a_selected_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            skill = root / "Skills/Personal/growth-advisor"
            (skill / "references").mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                """---
name: growth-advisor
description: Applies a synthetic growth review.
version: 1.0.0
status: active
visibility: public
created: 2026-08-07
updated: 2026-08-07
---
# Growth Advisor

Read `references/guide.md` before reviewing growth.
""",
                encoding="utf-8",
            )
            (skill / "references/guide.md").write_text("# Guide\n\nUse evidence.\n", encoding="utf-8")
            (skill / "LICENSE").write_text("Synthetic license fixture.\n", encoding="utf-8")
            (skill / "tests").mkdir()
            (skill / "tests/cases.md").write_text("# Cases\n", encoding="utf-8")
            definition = root / "Outputs/Context-Packs/growth-skill.md"
            definition.parent.mkdir(parents=True, exist_ok=True)
            definition.write_text(
                """---
type: context-pack
pack_id: growth-skill
summary: Growth Skill Pack
status: draft
visibility: private
created: 2026-08-07
updated: 2026-08-07
---
# Growth Skill

## Purpose

Share one Skill.

## Includes

## Excludes

## Skills

- path: Skills/Personal/growth-advisor/SKILL.md

## Build Notes
""",
                encoding="utf-8",
            )

            result = self.run_pack(root, "build", "Outputs/Context-Packs/growth-skill.md")

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            candidate = root / "Outputs/Context-Packs/Candidates/growth-skill"
            self.assertTrue((candidate / "skills/growth-advisor/SKILL.md").is_file())
            self.assertTrue((candidate / "skills/growth-advisor/references/guide.md").is_file())

    def test_public_preview_blocks_disclosure_risks_without_echoing_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            secret_value = "super-secret-value-12345"
            self.write_note(
                root,
                "Context/Projects/Unsafe.md",
                """
type: project
summary: Unsafe public project
status: active
visibility: public
outcome: Demonstrate blocking
source_of_truth: synthetic
created: 2026-08-07
updated: 2026-08-07
""",
                f"# Unsafe\n\napi_key={secret_value}\n\n/Users/example/private.md\n\nhttps://admin.internal/dashboard\n",
            )
            self.write_note(
                root,
                "Context/Projects/Private-Direct.md",
                """
type: project
summary: Private direct selection
status: active
visibility: private
outcome: Stay private
source_of_truth: synthetic
created: 2026-08-07
updated: 2026-08-07
""",
                "# Private\n",
            )
            definition = root / "Outputs/Context-Packs/unsafe.md"
            definition.parent.mkdir(parents=True, exist_ok=True)
            definition.write_text(
                """---
type: context-pack
pack_id: unsafe
summary: Unsafe public Pack
status: draft
visibility: public
created: 2026-08-07
updated: 2026-08-07
---
# Unsafe

## Purpose

Exercise disclosure checks.

## Includes

- path: Context/Projects/Unsafe.md
- path: Context/Projects/Private-Direct.md

## Excludes

## Skills

## Build Notes
""",
                encoding="utf-8",
            )

            result = self.run_pack(root, "preview", "Outputs/Context-Packs/unsafe.md")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("BLOCK public Definition missing license", result.stdout)
            self.assertIn("BLOCK non-public selected content: Context/Projects/Private-Direct.md", result.stdout)
            self.assertIn("BLOCK possible secret in Context/Projects/Unsafe.md", result.stdout)
            self.assertIn("BLOCK absolute private path in Context/Projects/Unsafe.md", result.stdout)
            self.assertIn("BLOCK private URL in Context/Projects/Unsafe.md", result.stdout)
            self.assertIn("RESOLVE sanitize, omit, or cancel", result.stdout)
            self.assertNotIn(secret_value, result.stdout + result.stderr)

    def test_public_build_succeeds_after_unsafe_source_is_replaced_and_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            self.write_note(
                root,
                "Context/Projects/Private-Original.md",
                """
type: project
summary: Private original
status: active
visibility: private
outcome: Internal result
source_of_truth: synthetic
created: 2026-08-07
updated: 2026-08-07
""",
                "# Private Original\n\npassword=do-not-publish-this\n",
            )
            self.write_note(
                root,
                "Outputs/Writing/Public-Sanitized.md",
                """
type: writing
summary: Sanitized public result
status: draft
visibility: public
sources:
  - synthetic
created: 2026-08-07
updated: 2026-08-07
""",
                "# Sanitized Result\n\nOnly the approved reusable conclusion.\n",
            )
            definition = root / "Outputs/Context-Packs/sanitized.md"
            definition.parent.mkdir(parents=True, exist_ok=True)
            definition.write_text(
                """---
type: context-pack
pack_id: sanitized
summary: Sanitized public Pack
status: draft
visibility: public
license: MIT
created: 2026-08-07
updated: 2026-08-07
---
# Sanitized

## Purpose

Publish only the safe replacement.

## Includes

- path: Context/Projects/Private-Original.md
- path: Outputs/Writing/Public-Sanitized.md

## Excludes

- path: Context/Projects/Private-Original.md

## Skills

## Build Notes

Private original replaced by the sanitized Output.
""",
                encoding="utf-8",
            )

            result = self.run_pack(root, "build", "Outputs/Context-Packs/sanitized.md")

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            candidate = root / "Outputs/Context-Packs/Candidates/sanitized"
            self.assertTrue((candidate / "artifacts/Public-Sanitized.md").is_file())
            combined = "\n".join(path.read_text(encoding="utf-8") for path in candidate.rglob("*.md"))
            self.assertNotIn("do-not-publish-this", combined)
            self.assertNotIn("Private original", combined)

    def test_public_preview_requires_a_license_for_each_personal_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            skill = root / "Skills/Personal/unlicensed"
            (skill / "tests").mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                """---
name: unlicensed
description: Synthetic unlicensed Skill.
version: 1.0.0
status: active
visibility: public
created: 2026-08-07
updated: 2026-08-07
---
# Unlicensed
""",
                encoding="utf-8",
            )
            (skill / "tests/cases.md").write_text("# Cases\n", encoding="utf-8")
            definition = root / "Outputs/Context-Packs/unlicensed.md"
            definition.parent.mkdir(parents=True, exist_ok=True)
            definition.write_text(
                """---
type: context-pack
pack_id: unlicensed
summary: Unlicensed Skill Pack
status: draft
visibility: public
license: MIT
created: 2026-08-07
updated: 2026-08-07
---
# Unlicensed

## Purpose

Exercise Skill licensing.

## Includes

## Excludes

## Skills

- path: Skills/Personal/unlicensed/SKILL.md

## Build Notes
""",
                encoding="utf-8",
            )

            result = self.run_pack(root, "preview", "Outputs/Context-Packs/unlicensed.md")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("BLOCK public Personal Skill missing license: Skills/Personal/unlicensed", result.stdout)


if __name__ == "__main__":
    unittest.main()
