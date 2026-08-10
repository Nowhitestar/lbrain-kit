from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CAPTURE_OPERATIONS = ROOT / "Skills/Kit/lbrain-capture/scripts/operations.py"
WEAVE_OPERATIONS = ROOT / "Skills/Kit/lbrain-weave/scripts/operations.py"


class IntelligenceOperationTest(unittest.TestCase):
    def copy_repo(self, destination: Path) -> Path:
        copy = destination / "lbrain"
        shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        return copy

    def run_capture_operation(
        self,
        root: Path,
        operation: str,
        payload: dict[str, object],
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        result = subprocess.run(
            [sys.executable, str(CAPTURE_OPERATIONS), operation, "--root", str(root)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )
        output = json.loads(result.stdout) if result.stdout else {}
        return result, output

    def run_weave_operation(
        self,
        root: Path,
        operation: str,
        payload: dict[str, object],
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        result = subprocess.run(
            [sys.executable, str(WEAVE_OPERATIONS), operation, "--root", str(root)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )
        output = json.loads(result.stdout) if result.stdout else {}
        return result, output

    def add_enabled_personal_skill(
        self,
        root: Path,
        name: str = "synthetic-writing",
        *,
        enabled: bool = True,
    ) -> Path:
        skill = root / f"Skills/Personal/{name}"
        (skill / "tests").mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Improves synthetic writing.\n---\n"
            "# Synthetic Writing\n\nUse concrete verbs.\n",
            encoding="utf-8",
        )
        (skill / "lbrain.json").write_text(
            '{"schema":"lbrain.skill.v1","version":"1.0.0","status":"active",'
            '"visibility":"private","created":"2026-08-10","updated":"2026-08-10"}\n',
            encoding="utf-8",
        )
        (skill / "tests/cases.md").write_text(
            "# Cases\n\n- Draft with concrete verbs.\n",
            encoding="utf-8",
        )
        if enabled:
            with (root / "Skills/Enabled.md").open("a", encoding="utf-8") as file:
                file.write(f"\n- [[Skills/Personal/{name}/SKILL]] — codex\n")
        return skill

    def test_project_configure_previews_applies_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            project = root / "Context/Projects/Synthetic-Research.md"
            payload: dict[str, object] = {
                "mode": "preview",
                "project_path": "Context/Projects/Synthetic-Research.md",
                "title": "Synthetic Research",
                "summary": "A non-code research project.",
                "outcome": "Publish an evidence-backed decision brief.",
                "profile_markdown": (
                    "## Context Intake Profile\n\n"
                    "### Sources and anchors\n\n"
                    "- Web articles: saved reading list\n\n"
                    "### Retained domains\n\n"
                    "- Evidence and decisions\n\n"
                    "### Schedule\n\n"
                    "- Cadence: weekly\n"
                    "- Baseline: baseline_pending\n"
                ),
            }

            preview_result, preview = self.run_capture_operation(root, "project.configure", payload)
            self.assertEqual(preview_result.returncode, 0, preview_result.stderr)
            self.assertEqual(preview["status"], "applied")
            self.assertEqual(preview["mode"], "preview")
            self.assertFalse(project.exists())
            self.assertIsNone(preview["before_hash"])
            self.assertTrue(preview["after_hash"])

            payload["mode"] = "apply"
            payload["expected_hash"] = preview["before_hash"]
            apply_result, applied = self.run_capture_operation(root, "project.configure", payload)
            self.assertEqual(apply_result.returncode, 0, apply_result.stderr)
            self.assertEqual(applied["status"], "applied")
            self.assertEqual(applied["affected_paths"], ["Context/Projects/Synthetic-Research.md"])
            project_text = project.read_text(encoding="utf-8")
            self.assertEqual(project_text.count("## Context Intake Profile"), 1)
            self.assertIn("<!-- lbrain:intake-profile:v1:start -->", project_text)
            self.assertIn("<!-- lbrain:intake-profile:end -->", project_text)
            self.assertIn("baseline_pending", project_text)

            payload["expected_hash"] = applied["after_hash"]
            repeat_result, repeated = self.run_capture_operation(root, "project.configure", payload)
            self.assertEqual(repeat_result.returncode, 0, repeat_result.stderr)
            self.assertEqual(repeated["status"], "noop")
            self.assertEqual(project.read_text(encoding="utf-8"), project_text)

    def test_project_configure_migrates_legacy_profile_without_changing_its_body(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            project = root / "Context/Projects/Legacy.md"
            legacy_profile = (
                "## Context Intake Profile\n\n"
                "### 来源与优先级\n\n"
                "- Notion > chat\n\n"
                "### Schedule\n\n"
                "- Baseline: complete\n"
            )
            project.write_text(
                "---\n"
                "type: project\nsummary: legacy\nstatus: active\nvisibility: private\n"
                "outcome: preserve\nsource_of_truth: internal\nreview_after: 2026-09-01\n"
                "created: 2026-08-01\nupdated: 2026-08-01\n---\n"
                "# Legacy\n\n"
                f"{legacy_profile}\n"
                "## Current state\n\nPreserve this section.\n",
                encoding="utf-8",
            )
            before_hash = hashlib.sha256(project.read_bytes()).hexdigest()
            payload: dict[str, object] = {
                "mode": "apply",
                "project_path": "Context/Projects/Legacy.md",
                "profile_markdown": legacy_profile,
                "expected_hash": before_hash,
            }

            result, output = self.run_capture_operation(root, "project.configure", payload)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output["status"], "applied")
            migrated = project.read_text(encoding="utf-8")
            self.assertIn(
                "<!-- lbrain:intake-profile:v1:start -->\n"
                f"{legacy_profile.strip()}\n"
                "<!-- lbrain:intake-profile:end -->\n\n"
                "## Current state",
                migrated,
            )
            self.assertIn("Preserve this section.", migrated)

    def test_project_configure_rejects_stale_preview_and_escaped_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            project = root / "Context/Projects/Existing.md"
            project.write_text(
                "---\ntype: project\nsummary: existing\nstatus: active\nvisibility: private\n"
                "outcome: unchanged\nsource_of_truth: internal\nreview_after: 2026-09-01\n"
                "created: 2026-08-01\nupdated: 2026-08-01\n---\n# Existing\n",
                encoding="utf-8",
            )
            original = project.read_text(encoding="utf-8")
            profile = "## Context Intake Profile\n\n- Baseline: baseline_pending\n"

            stale_result, stale = self.run_capture_operation(
                root,
                "project.configure",
                {
                    "mode": "apply",
                    "project_path": "Context/Projects/Existing.md",
                    "profile_markdown": profile,
                    "expected_hash": "stale",
                },
            )
            self.assertNotEqual(stale_result.returncode, 0)
            self.assertEqual(stale["status"], "failed")
            self.assertIn("changed after preview", stale["error"])
            self.assertEqual(project.read_text(encoding="utf-8"), original)

            escaped_result, escaped = self.run_capture_operation(
                root,
                "project.configure",
                {
                    "mode": "preview",
                    "project_path": "../outside.md",
                    "profile_markdown": profile,
                },
            )
            self.assertNotEqual(escaped_result.returncode, 0)
            self.assertEqual(escaped["status"], "failed")
            self.assertFalse((root.parent / "outside.md").exists())

    def test_project_checkpoint_preserves_partial_state_and_advances_only_when_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            project = root / "Context/Projects/Research.md"
            configure: dict[str, object] = {
                "mode": "preview",
                "project_path": "Context/Projects/Research.md",
                "title": "Research",
                "summary": "Synthetic checkpoint fixture.",
                "outcome": "Reach an evidence-backed conclusion.",
                "profile_markdown": (
                    "## Context Intake Profile\n\n"
                    "- Sources: web, notes\n"
                    "- Baseline: baseline_pending\n"
                ),
            }
            _, preview = self.run_capture_operation(root, "project.configure", configure)
            configure.update(mode="apply", expected_hash=preview["before_hash"])
            configured_result, configured = self.run_capture_operation(root, "project.configure", configure)
            self.assertEqual(configured_result.returncode, 0, configured_result.stderr)

            partial_payload: dict[str, object] = {
                "mode": "preview",
                "project_path": "Context/Projects/Research.md",
                "run_id": "2026-08-10-baseline",
                "range": "historical baseline",
                "sources": [
                    {"name": "web", "status": "scanned", "scope": "saved reading list", "required": True},
                    {"name": "notes", "status": "failed", "scope": "research folder", "required": True},
                ],
                "candidates": 3,
                "full_reads": 2,
                "changes": [],
                "conflicts": ["notes unavailable"],
                "next_review": "after connector recovery",
            }
            partial_preview_result, partial_preview = self.run_capture_operation(
                root, "project.checkpoint", partial_payload
            )
            self.assertEqual(partial_preview_result.returncode, 0, partial_preview_result.stderr)
            self.assertEqual(partial_preview["status"], "partial")
            self.assertFalse(partial_preview["complete_checkpoint_advanced"])
            self.assertNotIn("2026-08-10-baseline", project.read_text(encoding="utf-8"))

            partial_payload.update(mode="apply", expected_hash=partial_preview["before_hash"])
            partial_apply_result, partial = self.run_capture_operation(root, "project.checkpoint", partial_payload)
            self.assertEqual(partial_apply_result.returncode, 0, partial_apply_result.stderr)
            self.assertEqual(partial["status"], "partial")
            self.assertFalse(partial["complete_checkpoint_advanced"])
            self.assertIn("Status: partial", project.read_text(encoding="utf-8"))

            partial_payload["expected_hash"] = partial["after_hash"]
            repeat_result, repeated = self.run_capture_operation(root, "project.checkpoint", partial_payload)
            self.assertEqual(repeat_result.returncode, 0, repeat_result.stderr)
            self.assertEqual(repeated["status"], "noop")

            complete_payload: dict[str, object] = {
                **partial_payload,
                "mode": "preview",
                "run_id": "2026-08-11-baseline",
                "sources": [
                    {"name": "web", "status": "scanned", "scope": "saved reading list", "required": True},
                    {"name": "notes", "status": "no_durable_change", "scope": "research folder", "required": True},
                ],
                "conflicts": [],
            }
            complete_preview_result, complete_preview = self.run_capture_operation(
                root, "project.checkpoint", complete_payload
            )
            self.assertEqual(complete_preview_result.returncode, 0, complete_preview_result.stderr)
            self.assertEqual(complete_preview["status"], "applied")
            self.assertFalse(complete_preview["complete_checkpoint_advanced"])

            complete_payload.update(mode="apply", expected_hash=complete_preview["before_hash"])
            complete_result, complete = self.run_capture_operation(root, "project.checkpoint", complete_payload)
            self.assertEqual(complete_result.returncode, 0, complete_result.stderr)
            self.assertEqual(complete["status"], "applied")
            self.assertTrue(complete["complete_checkpoint_advanced"])
            project_text = project.read_text(encoding="utf-8")
            self.assertIn("Status: complete", project_text)
            self.assertEqual(project_text.count("2026-08-10-baseline"), 2)
            self.assertEqual(project_text.count("2026-08-11-baseline"), 2)

            cursor_payload = {**complete_payload, "run_id": "cursor-leak", "raw_cursor": "secret-runtime-state"}
            cursor_result, cursor = self.run_capture_operation(root, "project.checkpoint", cursor_payload)
            self.assertNotEqual(cursor_result.returncode, 0)
            self.assertEqual(cursor["status"], "failed")
            self.assertNotIn("secret-runtime-state", project.read_text(encoding="utf-8"))

    def test_capture_create_saves_one_source_and_deduplicates_retries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            payload: dict[str, object] = {
                "destination": "source",
                "title": "Synthetic Writing Guide",
                "summary": "A source about concrete writing behavior.",
                "origin": "https://example.invalid/writing-guide",
                "capture": "full",
                "content": "Prefer concrete verbs and test the revised opening.",
                "note": "Consider this for my writing Skill.",
                "extraction_status": "complete",
            }

            result, captured = self.run_capture_operation(root, "capture.create", payload)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(captured["status"], "applied")
            self.assertEqual(len(captured["affected_paths"]), 1)
            relative = str(captured["affected_paths"][0])
            self.assertTrue(relative.startswith("Knowledge/Sources/"))
            source = root / relative
            source_text = source.read_text(encoding="utf-8")
            self.assertIn("type: source", source_text)
            self.assertIn("weaving: pending", source_text)
            self.assertIn("https://example.invalid/writing-guide", source_text)
            self.assertIn("Prefer concrete verbs", source_text)
            self.assertIn("Consider this for my writing Skill.", source_text)

            repeat_result, repeated = self.run_capture_operation(root, "capture.create", payload)
            self.assertEqual(repeat_result.returncode, 0, repeat_result.stderr)
            self.assertEqual(repeated["status"], "noop")
            self.assertEqual(repeated["target"], relative)
            matching = list((root / "Knowledge/Sources").glob("*Synthetic-Writing-Guide*.md"))
            self.assertEqual(matching, [source])

    def test_capture_create_preserves_failed_extraction_and_rejects_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            failed_result, failed = self.run_capture_operation(
                root,
                "capture.create",
                {
                    "destination": "source",
                    "title": "Unavailable Article",
                    "summary": "A reference retained after extraction failure.",
                    "origin": "https://example.invalid/unavailable",
                    "capture": "full",
                    "content": "",
                    "note": "Retry this source later.",
                    "extraction_status": "failed",
                },
            )
            self.assertEqual(failed_result.returncode, 0, failed_result.stderr)
            self.assertEqual(failed["status"], "partial")
            source = root / str(failed["target"])
            source_text = source.read_text(encoding="utf-8")
            self.assertIn("capture: reference", source_text)
            self.assertIn("extraction_status: failed", source_text)
            self.assertIn("Original content was not available", source_text)
            self.assertIn("Retry this source later.", source_text)

            sensitive = "fixture-secret-value-12345"
            secret_result, secret = self.run_capture_operation(
                root,
                "capture.create",
                {
                    "destination": "inbox",
                    "title": "Unsafe Capture",
                    "summary": "Must be rejected.",
                    "content": f"api_key={sensitive}",
                },
            )
            self.assertNotEqual(secret_result.returncode, 0)
            self.assertEqual(secret["status"], "failed")
            self.assertNotIn(sensitive, secret_result.stdout + secret_result.stderr)
            self.assertFalse(list((root / "Inbox").glob("*Unsafe-Capture*.md")))

    def test_proposal_create_targets_enabled_personal_skill_and_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            self.add_enabled_personal_skill(root)
            evidence = root / "Knowledge/Sources/Synthetic-Writing-Evidence.md"
            evidence.write_text(
                "---\ntype: source\nsummary: writing evidence\nstatus: active\nvisibility: private\n"
                "origin: synthetic://writing-evidence\ncapture: full\nweaving: woven\n"
                "created: 2026-08-10\nupdated: 2026-08-10\n---\n"
                "# Writing Evidence\n\nSpecific openings outperform abstract ones.\n",
                encoding="utf-8",
            )
            wiki = root / "Knowledge/Wiki/Concepts/Synthetic-Writing.md"
            wiki.write_text(
                "---\ntype: knowledge\nkind: concept\nsummary: synthetic writing concept\n"
                "status: active\nvisibility: private\nsources:\n"
                '  - "[[Knowledge/Sources/Synthetic-Writing-Evidence]]"\n'
                "created: 2026-08-10\nupdated: 2026-08-10\n---\n"
                "# Synthetic Writing\n\nUse a specific opening.\n",
                encoding="utf-8",
            )
            payload: dict[str, object] = {
                "title": "Improve synthetic writing openings",
                "summary": "Make openings specific and testable.",
                "skill_name": "synthetic-writing",
                "evidence": [
                    "Knowledge/Sources/Synthetic-Writing-Evidence.md",
                    "Knowledge/Wiki/Concepts/Synthetic-Writing.md",
                ],
                "rationale": "The woven evidence adds a concrete decision rule.",
                "behavior_delta": "Require a specific claim in the opening before drafting the body.",
                "expected_diff": "Update instructions and the opening behavior case.",
                "test_changes": ["Add a case rejecting an abstract opening."],
            }

            result, created = self.run_weave_operation(root, "proposal.create", payload)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(created["status"], "applied")
            proposal = root / str(created["target"])
            proposal_text = proposal.read_text(encoding="utf-8")
            self.assertIn("status: pending", proposal_text)
            self.assertIn("Skills/Personal/synthetic-writing/SKILL.md", proposal_text)
            self.assertIn("## Behavior delta", proposal_text)
            self.assertIn("## Test changes", proposal_text)
            self.assertIn("Synthetic-Writing-Evidence", proposal_text)

            repeat_result, repeated = self.run_weave_operation(root, "proposal.create", payload)
            self.assertEqual(repeat_result.returncode, 0, repeat_result.stderr)
            self.assertEqual(repeated["status"], "noop")
            self.assertEqual(repeated["target"], created["target"])
            self.assertEqual(len(list((root / "System/Proposals").glob("*synthetic-writing-openings*.md"))), 1)

    def test_proposal_create_rejects_ineligible_or_untestable_skill_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            self.add_enabled_personal_skill(root, "disabled-writing", enabled=False)
            evidence = root / "Knowledge/Sources/Proposal-Evidence.md"
            evidence.write_text(
                "---\ntype: source\nsummary: proposal evidence\nstatus: active\nvisibility: private\n"
                "origin: synthetic://proposal-evidence\ncapture: full\nweaving: pending\n"
                "created: 2026-08-10\nupdated: 2026-08-10\n---\n# Evidence\n",
                encoding="utf-8",
            )
            base: dict[str, object] = {
                "title": "Do not create this proposal",
                "summary": "Rejected fixture.",
                "skill_name": "disabled-writing",
                "evidence": ["Knowledge/Sources/Proposal-Evidence.md"],
                "rationale": "The evidence appears related.",
                "behavior_delta": "Change an instruction.",
                "expected_diff": "Update the Skill.",
                "test_changes": ["Add a case."],
            }

            disabled_result, disabled = self.run_weave_operation(root, "proposal.create", base)
            self.assertNotEqual(disabled_result.returncode, 0)
            self.assertEqual(disabled["status"], "failed")
            self.assertIn("must be enabled", disabled["error"])

            core_result, core = self.run_weave_operation(
                root, "proposal.create", {**base, "skill_name": "lbrain-weave"}
            )
            self.assertNotEqual(core_result.returncode, 0)
            self.assertEqual(core["status"], "failed")
            self.assertIn("Personal Skill", core["error"])

            self.add_enabled_personal_skill(root, "enabled-writing")
            untestable_result, untestable = self.run_weave_operation(
                root,
                "proposal.create",
                {**base, "skill_name": "enabled-writing", "test_changes": []},
            )
            self.assertNotEqual(untestable_result.returncode, 0)
            self.assertEqual(untestable["status"], "failed")
            self.assertFalse(list((root / "System/Proposals").glob("*do-not-create*.md")))


if __name__ == "__main__":
    unittest.main()
