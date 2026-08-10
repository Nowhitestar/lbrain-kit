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


if __name__ == "__main__":
    unittest.main()
