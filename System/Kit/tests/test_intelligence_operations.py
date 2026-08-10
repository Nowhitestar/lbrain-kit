from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "System/Kit"))

from disclosure import (  # noqa: E402
    contains_code_runtime_state,
    contains_code_secret,
    contains_document_runtime_state,
    contains_document_secret,
    contains_key,
    contains_runtime_state,
    contains_secret,
)
from transaction import mutation_locks  # noqa: E402


CAPTURE_OPERATIONS = ROOT / "Skills/Kit/lbrain-capture/scripts/operations.py"
WEAVE_OPERATIONS = ROOT / "Skills/Kit/lbrain-weave/scripts/operations.py"
SKILL_OPERATIONS = ROOT / "Skills/Kit/lbrain-skill-manager/scripts/operations.py"


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

    def run_skill_operation(
        self,
        root: Path,
        operation: str,
        payload: dict[str, object],
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        result = subprocess.run(
            [sys.executable, str(SKILL_OPERATIONS), operation, "--root", str(root)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )
        output = json.loads(result.stdout) if result.stdout else {}
        return result, output

    def assert_failed_operation(self, output: dict[str, object], operation: str, target: str) -> None:
        self.assertEqual(output["operation"], operation)
        self.assertEqual(output["status"], "failed")
        self.assertIn(output["target"], ("", target))
        self.assertRegex(str(output["operation_id"]), r"^[0-9a-f]{20}$")
        self.assertEqual(output["affected_paths"], [])
        self.assertFalse(dict(output["validation"])["ok"])

    def accept_project_preview(self, root: Path, preview: dict[str, object]) -> None:
        proposal = dict(preview["proposal"])
        path = root / str(proposal["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(proposal["accepted_markdown"]), encoding="utf-8")

    def accept_skill_preview(self, root: Path, proposal_path: object, preview_hash: object) -> None:
        path = root / str(proposal_path)
        content = path.read_text(encoding="utf-8")
        content = content.replace("status: pending", "status: accepted", 1)
        content = content.replace(
            "## Decision\n\nPending user review.",
            f"## Decision\n\nApproved exact Change Preview `{preview_hash}` after explicit user confirmation.",
            1,
        )
        path.write_text(content, encoding="utf-8")

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
            unapproved_result, unapproved = self.run_capture_operation(
                root, "project.configure", payload
            )
            self.assertNotEqual(unapproved_result.returncode, 0)
            self.assertIn("explicitly accepted Proposal", unapproved["error"])
            self.assertFalse(project.exists())
            self.accept_project_preview(root, preview)
            apply_result, applied = self.run_capture_operation(root, "project.configure", payload)
            self.assertEqual(apply_result.returncode, 0, apply_result.stderr)
            self.assertEqual(applied["status"], "applied")
            self.assertIn("Context/Projects/Synthetic-Research.md", applied["affected_paths"])
            proposal_paths = [
                path for path in applied["affected_paths"] if str(path).startswith("System/Proposals/")
            ]
            self.assertEqual(len(proposal_paths), 1)
            proposal_text = (root / str(proposal_paths[0])).read_text(encoding="utf-8")
            self.assertIn("status: applied", proposal_text)
            self.assertIn("Accepted exact Project configuration", proposal_text)
            self.assertIn("Applied exact Project configuration", proposal_text)
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

    def test_project_configure_retries_an_accepted_proposal_after_validation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            project = root / "Context/Projects/Retryable.md"
            payload: dict[str, object] = {
                "mode": "preview",
                "project_path": "Context/Projects/Retryable.md",
                "title": "Retryable",
                "summary": "Exercise retry after validation failure.",
                "outcome": "Apply one validated Intake Profile.",
                "profile_markdown": (
                    "## Context Intake Profile\n\n"
                    "### Sources and anchors\n\n- notes: research notebook\n\n"
                    "### Schedule\n\n- Baseline: baseline_pending\n"
                ),
            }
            _, preview = self.run_capture_operation(root, "project.configure", payload)
            self.accept_project_preview(root, preview)
            payload.update(mode="apply", expected_hash=preview["before_hash"])
            invalid = root / "Inbox/Invalid-During-Apply.md"
            invalid.write_text(
                "---\ntype: note\nsummary: invalid fixture\nstatus: active\nvisibility: private\n"
                "created: 2026-08-10\nupdated: 2026-08-10\n---\n# Invalid\n\n[[Missing-Retry-Fixture]]\n",
                encoding="utf-8",
            )

            failed_result, failed = self.run_capture_operation(root, "project.configure", payload)

            self.assertNotEqual(failed_result.returncode, 0)
            self.assertEqual(failed["status"], "failed")
            self.assertFalse(project.exists())
            proposal_path = root / str(dict(preview["proposal"])["path"])
            self.assertIn("status: accepted", proposal_path.read_text(encoding="utf-8"))
            self.assertIn("remains retryable", proposal_path.read_text(encoding="utf-8"))

            invalid.unlink()
            retry_result, retried = self.run_capture_operation(root, "project.configure", payload)
            self.assertEqual(retry_result.returncode, 0, retry_result.stderr)
            self.assertEqual(retried["status"], "applied")
            self.assertTrue(project.is_file())
            self.assertIn("status: applied", proposal_path.read_text(encoding="utf-8"))

    def test_project_configure_rolls_back_if_the_proposal_changes_during_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            project = root / "Context/Projects/Concurrent.md"
            payload: dict[str, object] = {
                "mode": "preview",
                "project_path": "Context/Projects/Concurrent.md",
                "title": "Concurrent",
                "summary": "Exercise a Proposal conflict during apply.",
                "outcome": "Preserve both Project and Proposal consistency.",
                "profile_markdown": (
                    "## Context Intake Profile\n\n"
                    "### Sources and anchors\n\n- notes: research notebook\n\n"
                    "### Schedule\n\n- Baseline: baseline_pending\n"
                ),
            }
            _, preview = self.run_capture_operation(root, "project.configure", payload)
            self.accept_project_preview(root, preview)
            payload.update(mode="apply", expected_hash=preview["before_hash"])
            proposal_path = root / str(dict(preview["proposal"])["path"])
            accepted_proposal = proposal_path.read_text(encoding="utf-8")

            spec = importlib.util.spec_from_file_location("capture_operations_conflict", CAPTURE_OPERATIONS)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            operations = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(operations)

            def conflicting_validation(_: Path) -> tuple[bool, str]:
                proposal_path.write_text(
                    proposal_path.read_text(encoding="utf-8") + "\nConcurrent reviewer note.\n",
                    encoding="utf-8",
                )
                return True, ""

            operations.validate = conflicting_validation
            failed = operations.project_configure(root, payload)

            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["rollback"], {"performed": True, "ok": True})
            self.assertFalse(project.exists())
            proposal_text = proposal_path.read_text(encoding="utf-8")
            self.assertIn("status: accepted", proposal_text)
            self.assertIn("Concurrent reviewer note.", proposal_text)
            self.assertNotIn("status: applied", proposal_text)

            proposal_path.write_text(accepted_proposal, encoding="utf-8")
            validation_calls = 0

            def conflicting_second_validation(_: Path) -> tuple[bool, str]:
                nonlocal validation_calls
                validation_calls += 1
                if validation_calls == 2:
                    proposal_path.write_text(
                        proposal_path.read_text(encoding="utf-8") + "\nSecond validation edit.\n",
                        encoding="utf-8",
                    )
                    return False, "concurrent Proposal edit"
                return True, ""

            operations.validate = conflicting_second_validation
            second_failed = operations.project_configure(root, payload)

            self.assertEqual(second_failed["status"], "failed")
            self.assertEqual(second_failed["rollback"], {"performed": True, "ok": False})
            self.assertFalse(project.exists())
            second_proposal = proposal_path.read_text(encoding="utf-8")
            self.assertIn("Second validation edit.", second_proposal)
            self.assertNotIn("status: accepted", second_proposal)

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
                "mode": "preview",
                "project_path": "Context/Projects/Legacy.md",
                "profile_markdown": legacy_profile,
            }

            preview_result, preview = self.run_capture_operation(root, "project.configure", payload)
            self.assertEqual(preview_result.returncode, 0, preview_result.stderr)
            self.assertEqual(preview["before_hash"], before_hash)
            self.accept_project_preview(root, preview)
            payload.update(mode="apply", expected_hash=before_hash)

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
            profile = (
                "## Context Intake Profile\n\n"
                "### Sources and anchors\n\n- Web: saved reading list\n\n"
                "### Schedule\n\n"
                "- Baseline: baseline_pending\n"
            )

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
            self.assert_failed_operation(stale, "project.configure", "Context/Projects/Existing.md")
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
            self.assert_failed_operation(escaped, "project.configure", "../outside.md")
            self.assertFalse((root.parent / "outside.md").exists())

            sensitive_path = "Context/Projects/api_" + "key=fixture-path-value-12345.md"
            path_result, path_failure = self.run_capture_operation(
                root,
                "project.configure",
                {
                    "mode": "preview",
                    "project_path": sensitive_path,
                    "profile_markdown": profile,
                },
            )
            self.assertNotEqual(path_result.returncode, 0)
            self.assertEqual(path_failure["target"], "")
            self.assertNotIn(sensitive_path, path_result.stdout + path_result.stderr)

            sensitive_mode = "api_" + "key=fixture-mode-value-12345"
            mode_result, mode_failure = self.run_capture_operation(
                root,
                "project.configure",
                {
                    "mode": sensitive_mode,
                    "project_path": "Context/Projects/Mode.md",
                    "profile_markdown": profile,
                },
            )
            self.assertNotEqual(mode_result.returncode, 0)
            self.assertEqual(mode_failure["mode"], "apply")
            self.assertNotIn(sensitive_mode, mode_result.stdout + mode_result.stderr)

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
                    "### Sources and anchors\n\n"
                    "- web: saved reading list\n"
                    "- notes: research folder\n\n"
                    "### Schedule\n\n"
                    "- Baseline: baseline_pending\n"
                ),
            }
            _, preview = self.run_capture_operation(root, "project.configure", configure)
            self.accept_project_preview(root, preview)
            configure.update(mode="apply", expected_hash=preview["before_hash"])
            configured_result, configured = self.run_capture_operation(root, "project.configure", configure)
            self.assertEqual(configured_result.returncode, 0, configured_result.stderr)
            project.write_text(
                project.read_text(encoding="utf-8")
                + "\n## Context Intake Checkpoints\n\n## Decisions\n\nPreserve later content.\n",
                encoding="utf-8",
            )

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
            missing_result, missing = self.run_capture_operation(
                root,
                "project.checkpoint",
                {**partial_payload, "sources": [partial_payload["sources"][0]]},
            )
            self.assertNotEqual(missing_result.returncode, 0)
            self.assert_failed_operation(missing, "project.checkpoint", "Context/Projects/Research.md")
            self.assertIn("does not account for", missing["error"])

            no_match_result, no_match = self.run_capture_operation(
                root,
                "project.checkpoint",
                {
                    **partial_payload,
                    "sources": [
                        partial_payload["sources"][0],
                        {
                            "name": "notes",
                            "status": "no_match",
                            "scope": "research folder",
                            "required": True,
                        },
                    ],
                },
            )
            self.assertEqual(no_match_result.returncode, 0, no_match_result.stderr)
            self.assertEqual(no_match["status"], "partial")

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
            self.assertLess(project_text.index("2026-08-11-baseline"), project_text.index("## Decisions"))
            self.assertIn("Preserve later content.", project_text)

            cursor_payload = {
                **complete_payload,
                "run_id": "cursor-leak",
                "connector": {"raw_cursor": "secret-runtime-state"},
            }
            cursor_result, cursor = self.run_capture_operation(root, "project.checkpoint", cursor_payload)
            self.assertNotEqual(cursor_result.returncode, 0)
            self.assertEqual(cursor["status"], "failed")
            self.assertNotIn("secret-runtime-state", project.read_text(encoding="utf-8"))

            cursor_text = "raw_" + "cursor=opaque-runtime-state-12345"
            text_result, text_cursor = self.run_capture_operation(
                root,
                "project.checkpoint",
                {
                    **complete_payload,
                    "mode": "preview",
                    "run_id": "cursor-text-leak",
                    "range": cursor_text,
                },
            )
            self.assertNotEqual(text_result.returncode, 0)
            self.assertEqual(text_cursor["status"], "failed")
            self.assertNotIn(cursor_text, project.read_text(encoding="utf-8"))
            code = (
                "```python\n"
                "cursor = response.next_cursor_v2\n"
                "page_token: pagination.page2_token\n"
                "cursor = cursors[index]\n"
                'cursor = response["next_cursor"]\n'
                "cursor = response?.nextCursor\n"
                "cursor = response.get_cursor(page)\n"
                "```\n"
            )
            self.assertFalse(contains_document_runtime_state(code))
            self.assertFalse(contains_code_runtime_state("cursor = response.get_cursor(page)"))
            self.assertFalse(contains_code_runtime_state('{"next_cursor": response.next_cursor}'))
            self.assertFalse(contains_code_runtime_state('request(next_cursor=response.next_cursor)'))
            self.assertFalse(
                contains_code_runtime_state(
                    'cursor = response.next_cursor  # loaded from connector', python=True
                )
            )
            self.assertFalse(contains_code_runtime_state('cursor = (\n response.get_cursor(page)\n)'))
            self.assertFalse(contains_code_runtime_state("cursor: str = response.get_cursor(page)"))
            self.assertFalse(contains_code_runtime_state("const nextCursor: Record<string, string> = state.nextCursor"))
            self.assertFalse(contains_code_runtime_state("cursor=nextCursor"))
            self.assertFalse(contains_code_runtime_state("cursor=next_cursor_v2"))
            self.assertFalse(contains_code_runtime_state("set_cursor(state.cursor)"))
            self.assertFalse(
                contains_code_runtime_state("def set_cursor(value: str) -> None:\n    pass", python=True)
            )
            self.assertFalse(
                contains_code_runtime_state(
                    "def set_cursor(value: str = state.cursor) -> None:\n    pass",
                    python=True,
                )
            )
            self.assertFalse(contains_code_runtime_state("setCursor(value: string): void {}"))
            self.assertFalse(contains_code_runtime_state("setCursor(value) {}"))
            self.assertFalse(contains_code_runtime_state("client.setCursor(value)"))
            self.assertFalse(contains_code_runtime_state("const setCursor = handler"))
            self.assertFalse(
                contains_code_runtime_state("const setCursor = (value) => handler(value)")
            )
            self.assertFalse(
                contains_code_runtime_state("const setCursor = (value) => { handler(value); }")
            )
            self.assertFalse(
                contains_code_runtime_state(
                    "const setCursor = (value) => {\n handler(value)\n return state.cursor\n}"
                )
            )
            self.assertFalse(
                contains_code_runtime_state(
                    "const setCursor = (value) => {\n if (value) return state.cursor\n return backup.cursor\n}"
                )
            )
            self.assertFalse(
                contains_code_runtime_state(
                    'const setCursor = (value) => { if (!value) throw new Error("missing"); state.cursor = value; }'
                )
            )
            self.assertFalse(
                contains_code_runtime_state("client.set_cursor(value=state.cursor)", python=True)
            )
            self.assertFalse(
                contains_code_runtime_state(
                    "cursor = response.get_cursor(page) or state.cursor", python=True
                )
            )
            self.assertFalse(
                contains_code_runtime_state(
                    "cursor = response.get_cursor(page, state.cursor)", python=True
                )
            )
            self.assertFalse(
                contains_code_runtime_state(
                    "const nextCursor = response.nextCursor ?? state.nextCursor"
                )
            )
            self.assertFalse(
                contains_code_runtime_state(
                    "const nextCursor = ready ?\n state.nextCursor\n : backup.nextCursor"
                )
            )
            self.assertFalse(
                contains_code_runtime_state(
                    "cursor = state.cursor if more else response.cursor", python=True
                )
            )
            self.assertFalse(
                contains_code_runtime_state(
                    "const [nextCursor, page] = [state.nextCursor, page]"
                )
            )
            self.assertFalse(contains_code_runtime_state("state.nextCursor = value"))
            self.assertFalse(
                contains_code_runtime_state(
                    "function setCursor({value = state.cursor}: {value?: string}) {}"
                )
            )
            self.assertFalse(
                contains_code_runtime_state(
                    "const cursor = ready ? nested ? state.cursor : backup.cursor : response.cursor"
                )
            )
            self.assertFalse(
                contains_code_runtime_state(
                    "const setCursor = <T extends (...args: any[]) => any>(value = state.cursor) => state.cursor"
                )
            )
            self.assertFalse(contains_runtime_state('"next_cursor": "${cursor}"'))
            self.assertFalse(contains_runtime_state('"next_cursor": ""'))
            self.assertFalse(contains_runtime_state("next_cursor: ''"))
            self.assertFalse(contains_code_runtime_state("cursor = 0", python=True))
            self.assertFalse(contains_code_runtime_state('cursor = ""', python=True))
            self.assertFalse(
                contains_code_runtime_state(
                    'next_cursor = _dig(raw, "data", "cursor", default="")',
                    python=True,
                )
            )
            self.assertFalse(
                contains_code_runtime_state(
                    'cursor = _pick(inner, "cursor", "lastCursor") or ""',
                    python=True,
                )
            )
            self.assertFalse(
                contains_code_runtime_state(
                    "cursor = int(next_cursor) if str(next_cursor).isdigit() else 0",
                    python=True,
                )
            )
            self.assertFalse(
                contains_code_runtime_state(
                    '"""Args:\n    cursor: 分页游标\n\nReturns:\n    {cursor, notes: [...]}\n"""',
                    python=True,
                )
            )
            self.assertFalse(
                contains_code_runtime_state(
                    '"""Args:\n    cursor: 下一页位置\n    next_cursor: 用于继续分页的标记\n"""',
                    python=True,
                )
            )
            self.assertFalse(contains_code_runtime_state("cursor==response.next_cursor"))
            self.assertFalse(contains_code_runtime_state("cursor:=response.next_cursor"))
            self.assertTrue(contains_code_runtime_state('cursor := "opaque-real-cursor-12345"'))
            self.assertTrue(contains_code_runtime_state("cursor = 1234567"))
            self.assertTrue(contains_code_runtime_state('cursor = "opaque-real-cursor-12345"'))
            self.assertTrue(contains_code_runtime_state('setCursor("next_cursor")'))
            self.assertTrue(
                contains_code_runtime_state('cursor = _dig("opaque-runtime-state-12345")')
            )
            self.assertTrue(contains_code_runtime_state('state["next_cursor"] = "opaque-real-cursor-12345"'))
            self.assertTrue(contains_code_runtime_state('state["page"].next_cursor = "opaque-real-cursor-12345"'))
            self.assertTrue(contains_code_runtime_state('cursor: str = "opaque-real-cursor-12345"'))
            self.assertTrue(contains_code_runtime_state('cursor = r"""\nopaque-real-cursor-12345\n"""'))
            self.assertTrue(contains_code_runtime_state('cursor = str("opaque-real-cursor-12345")'))
            self.assertTrue(contains_code_runtime_state('cursor = response.next_cursor or "opaque-real-cursor-12345"'))
            self.assertTrue(
                contains_code_runtime_state(
                    'const nextCursor = this.#cursor || "opaque-real-cursor-12345"'
                )
            )
            self.assertTrue(contains_code_runtime_state('set_cursor("opaque-real-cursor-12345")'))
            self.assertTrue(
                contains_code_runtime_state(
                    'result = set_cursor("opaque-real-cursor-12345")'
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    'const value = "opaque-real-cursor-12345"; state.cursor = value'
                )
            )
            self.assertTrue(
                contains_code_runtime_state('const value = "opaque"; setCursor(value)')
            )
            self.assertTrue(
                contains_code_runtime_state('const value = "next_cursor"; setCursor(value)')
            )
            self.assertTrue(
                contains_code_runtime_state(
                    'const value = make("opaque-cursor-value"); setCursor(value)'
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    'const value = response.cursor || "opaque-real-cursor-12345"; setCursor(value)'
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    'const value = "opaque"; if (ready) { setCursor(value); }'
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    'client.cursor. /* x */ update("opaque-real-cursor-12345")'
                )
            )
            self.assertTrue(
                contains_code_runtime_state('client["setCursor"]("opaque-real-cursor-12345")')
            )
            self.assertTrue(
                contains_code_runtime_state('client.setCursor?.("opaque-real-cursor-12345")')
            )
            self.assertTrue(
                contains_code_runtime_state('update_cursor("opaque-real-cursor-12345")')
            )
            self.assertTrue(
                contains_code_runtime_state('client.cursor.set("opaque-real-cursor-12345")')
            )
            self.assertTrue(
                contains_code_runtime_state(
                    'client.nextCursor?.update("opaque-real-cursor-12345")'
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    'def set_cursor(value="opaque-real-cursor-12345"):\n    pass',
                    python=True,
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    'enabled ? client.setCursor("opaque-real-cursor-12345") : noop()'
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    'function setCursor({nested: {value = "opaque-real-cursor-12345"}} = state.cursor) {}'
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    'function setCursor({value = "opaque-real-cursor-12345"}: Options) {}'
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    'enabled ?\n client.setCursor("opaque-real-cursor-12345")\n : noop;'
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    'client["nextCursor"]["update"]("opaque-real-cursor-12345")'
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    'client["nextCursor"]?.["update"]?.("opaque-real-cursor-12345")'
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    'client?.nextCursor?.["update"]?.("opaque-real-cursor-12345")'
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    'client["update"]["nextCursor"]("opaque-real-cursor-12345")'
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    'class Pager { set\n nextCursor(value = "opaque-real-cursor-12345") {} }'
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    "cursor = state.cursor if more else 1234567890123456", python=True
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    "cursor = state.cursor, 1234567890123456", python=True
                )
            )
            self.assertTrue(
                contains_code_runtime_state("cursor = int(1234567890123456)", python=True)
            )
            self.assertTrue(
                contains_code_runtime_state(
                    'const [\n nextCursor,\n page\n] = [\n "opaque-real-cursor-12345", page\n]'
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    'const nextCursor // assigned below\n = "opaque-real-cursor-12345";'
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    "blob = 'config = \"next_cursor=opaque-real-cursor-12345\"'",
                    python=True,
                )
            )
            self.assertTrue(
                contains_document_runtime_state(
                    'The connector returned "next_cursor=opaque-real-cursor-12345".'
                )
            )
            self.assertTrue(contains_code_runtime_state('cursor = str("opaque-real-cursor-12345")'))
            self.assertTrue(contains_code_runtime_state('blob = "next_cursor=opaque-real-cursor-12345"'))
            self.assertTrue(
                contains_code_runtime_state(
                    "# don't retain cursors\ncursor = \"opaque-real-cursor-12345\"",
                    python=True,
                )
            )
            self.assertTrue(contains_code_runtime_state("nextCursor = `\nopaque-runtime-state-12345\n`"))
            self.assertTrue(contains_code_runtime_state("cursor=opaque-runtime-state-12345"))
            self.assertTrue(contains_code_runtime_state("cursor=1234567890123456"))
            self.assertFalse(contains_code_runtime_state('cursor = "${NEXT_CURSOR}"', shell=True))
            self.assertFalse(contains_code_runtime_state("cursor=${NEXT_CURSOR}", shell=True))
            self.assertFalse(contains_code_runtime_state("cursor=${NEXT_CURSOR:?required}", shell=True))
            self.assertFalse(contains_code_runtime_state("cursor=${NEXT_CURSOR:?cursor is required}", shell=True))
            self.assertFalse(contains_code_runtime_state("cursor=$(get_cursor)", shell=True))
            self.assertFalse(contains_code_runtime_state("cursor=$NEXT_CURSOR # loaded from connector", shell=True))
            self.assertFalse(contains_code_runtime_state("cursor=$NEXT_CURSOR command", shell=True))
            self.assertFalse(contains_code_runtime_state('cursor="${NEXT_CURSOR}" command', shell=True))
            self.assertFalse(
                contains_code_runtime_state("cursor=$NEXT_CURSOR other=value command", shell=True)
            )
            self.assertTrue(contains_code_runtime_state("cursor=$(printf opaque-runtime-state-12345)", shell=True))
            self.assertTrue(contains_code_runtime_state("cursor=${NEXT_CURSOR}opaque-runtime-state-12345", shell=True))
            self.assertTrue(contains_code_runtime_state("cursor=$NEXT_CURSOR#opaque-runtime-state-12345", shell=True))
            self.assertTrue(contains_code_runtime_state("cursor=$NEXT_CURSOR//opaque-runtime-state-12345", shell=True))
            self.assertTrue(contains_code_runtime_state("cursor=${NEXT_CURSOR:-opaque-runtime-state-12345}", shell=True))
            self.assertTrue(contains_code_runtime_state("cursor=${NEXT_CURSOR:=opaque-runtime-state-12345}", shell=True))
            self.assertTrue(contains_code_runtime_state("nextCursor = `opaque-runtime-state-12345`"))
            self.assertTrue(contains_runtime_state("next_cursor: opaque_cursor_value"))
            self.assertTrue(contains_runtime_state("next_cursor=eyJhbGci.payload.signature"))
            self.assertTrue(contains_runtime_state("next_cursor: 密钥游标值"))
            self.assertTrue(contains_runtime_state("next_cursor: 密钥游标"))
            self.assertTrue(contains_runtime_state("next_cursor: 秘密分页游标"))
            self.assertTrue(
                contains_code_runtime_state(
                    '"""Config:\nnext_cursor: opaque-real-cursor-12345\n"""',
                    python=True,
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    '"""Config:\nnext_cursor: 密钥游标\n"""',
                    python=True,
                )
            )
            self.assertTrue(
                contains_code_runtime_state(
                    '"""Config:\nnext_cursor: 秘密分页游标\n"""',
                    python=True,
                )
            )
            self.assertTrue(contains_key({"connector": {"next_cursor": "opaque"}}, {"cursor"}))
            self.assertTrue(contains_key({"connector": {"endCursor": "opaque"}}, {"cursor"}))
            self.assertTrue(contains_key({"oauth": {"refresh_token": "opaque"}}, {"cursor"}))
            self.assertTrue(contains_key({"session_token": "opaque"}, {"cursor"}))

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

    def test_capture_create_reuses_a_matching_source_in_a_category(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            payload: dict[str, object] = {
                "destination": "source",
                "title": "Categorized Writing Guide",
                "summary": "A previously categorized source.",
                "origin": "https://example.invalid/categorized-writing-guide",
                "capture": "full",
                "content": "Write to discover new ideas.",
                "extraction_status": "complete",
            }
            first_result, first = self.run_capture_operation(root, "capture.create", payload)
            self.assertEqual(first_result.returncode, 0, first_result.stderr)
            existing = root / "Knowledge/Sources/Methodology/Categorized-Writing-Guide.md"
            existing.parent.mkdir(parents=True, exist_ok=True)
            created = root / str(first["target"])
            created.write_text(
                "\n".join(
                    line for line in created.read_text(encoding="utf-8").splitlines()
                    if not line.startswith("capture_id:")
                ) + "\n",
                encoding="utf-8",
            )
            created.rename(existing)

            result, captured = self.run_capture_operation(root, "capture.create", payload)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(captured["status"], "noop")
            self.assertEqual(
                captured["target"],
                "Knowledge/Sources/Methodology/Categorized-Writing-Guide.md",
            )
            self.assertFalse(list((root / "Knowledge/Sources").glob("*Categorized-Writing-Guide*.md")))

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

            recovered_payload = {
                "destination": "source",
                "title": "Unavailable Article",
                "summary": "The recovered article.",
                "origin": "https://example.invalid/unavailable",
                "capture": "full",
                "content": "Recovered source body.",
                "note": "Extraction succeeded on retry.",
                "extraction_status": "complete",
                "expected_hash": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
            source.write_text(
                source.read_text(encoding="utf-8").replace(
                    "status: active\n",
                    "status: active\ntags:\n  - preserve-me\n",
                    1,
                )
                + "\n## Research notes\n\nPreserve this user-authored section.\n",
                encoding="utf-8",
            )
            recovered_payload["expected_hash"] = hashlib.sha256(source.read_bytes()).hexdigest()
            recovered_result, recovered = self.run_capture_operation(
                root, "capture.create", recovered_payload
            )
            self.assertEqual(recovered_result.returncode, 0, recovered_result.stderr)
            self.assertEqual(recovered["status"], "applied")
            self.assertEqual(recovered["target"], failed["target"])
            recovered_text = source.read_text(encoding="utf-8")
            self.assertIn("extraction_status: complete", recovered_text)
            self.assertIn("Recovered source body.", recovered_text)
            self.assertIn("tags:\n  - preserve-me", recovered_text)
            self.assertIn("Preserve this user-authored section.", recovered_text)

            repeat_result, repeated = self.run_capture_operation(
                root, "capture.create", recovered_payload
            )
            self.assertEqual(repeat_result.returncode, 0, repeat_result.stderr)
            self.assertEqual(repeated["status"], "noop")

            bearer = "Authorization: Bearer " + (
                "fixture-token-"
                "value-12345"
            )
            basic = "Authorization: Basic " + (
                "Zml4dHVyZS11c2Vy"
                "OmZpeHR1cmUtcGFzcw=="
            )
            spaced_api_key = "api_key = " + '"fixture-secret-value-12345"'
            secrets = (
                "secret" + "=fixture-secret-value-12345",
                "-----BEGIN " + "PRIVATE KEY-----",
                bearer,
                "ghp_" + "abcdefghijklmnopqrstuvwxyz123456",
                "github_" + "pat_abcdefghijklmnopqrstuvwxyz_1234567890",
                "sk-" + "abcdefghijklmnopqrstuvwxyz123456",
                "AI" + "zaSyABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890",
                basic,
                "refresh_" + "token=fixture-refresh-value-12345",
                "session_" + "token=fixture-session-value-12345",
                "next_" + "cursor=opaque-runtime-state-12345",
                "end" + "Cursor=opaque-runtime-state-12345",
                '"next_' + 'cursor": "opaque-runtime-state-12345"',
                "end" + "Cursor: 'opaque-runtime-state-12345'",
                "next_" + "cursor=abcdefghijklmnop",
                spaced_api_key,
                '```python\nconfig["api_key"] = "fixture-secret-value-12345"\n```',
                "refresh_token = fixture-refresh-value-12345",
                "session_token : fixture-session-value-12345",
            )
            for index, sensitive in enumerate(secrets):
                title = f"Unsafe Capture {index}"
                secret_result, secret = self.run_capture_operation(
                    root,
                    "capture.create",
                    {
                        "destination": "inbox",
                        "title": title,
                        "summary": "Must be rejected.",
                        "content": sensitive,
                    },
                )
                self.assertNotEqual(secret_result.returncode, 0)
                self.assert_failed_operation(secret, "capture.create", title)
                self.assertNotIn(sensitive, secret_result.stdout + secret_result.stderr)
            self.assertFalse(list((root / "Inbox").glob("*Unsafe-Capture*.md")))
            code = (
                "```python\n"
                'api_key = os.getenv("API_KEY")\n'
                'api_key = os.environ.get("API_KEY")\n'
                'api_key = config.get("api_key")\n'
                "session_token = config.sessionToken\n"
                "cursor = response.get_cursor(page)\n"
                "```\n"
            )
            self.assertFalse(contains_document_secret(code))
            self.assertFalse(contains_document_runtime_state(code))
            indented_code = "   " + code.replace("\n```\n", "\n   ```\n")
            self.assertFalse(contains_document_secret(indented_code))
            self.assertFalse(contains_document_runtime_state(indented_code))
            self.assertFalse(contains_code_secret('api_key = config.get("api_key")'))
            self.assertFalse(contains_code_secret('{"api_key": config.api_key}'))
            self.assertFalse(contains_code_secret('payload = {"api_key": config.get("api_key")}'))
            self.assertFalse(contains_code_secret('request(api_key=config.api_key)'))
            self.assertFalse(
                contains_code_secret('api_key = config.api_key  # loaded from env', python=True)
            )
            self.assertFalse(contains_code_secret('const apiKey = process.env.API_KEY // loaded from env'))
            self.assertFalse(contains_code_secret('api_key = (\n config.get("api_key")\n)'))
            self.assertFalse(contains_code_secret('config["api_key"] = settings.api_key'))
            self.assertFalse(contains_code_secret('OPENAI_API_KEY: str = config.get("api_key")'))
            self.assertFalse(contains_code_secret('const openaiApiKey: string = config.apiKey'))
            self.assertFalse(contains_code_secret('const apiKey: Record<string, string> = config.apiKey'))
            self.assertFalse(contains_code_secret('api_key: Annotated[str, "credential"] = config.api_key'))
            self.assertFalse(contains_code_secret("api_key=settingsApiKey"))
            self.assertFalse(contains_code_secret("client.setApiKey(config.apiKey)"))
            self.assertFalse(
                contains_code_secret("def set_api_key(value: str) -> None:\n    pass", python=True)
            )
            self.assertFalse(
                contains_code_secret(
                    "def set_api_key(value: str = config.api_key) -> None:\n    pass",
                    python=True,
                )
            )
            self.assertFalse(contains_code_secret("setApiKey(value: string): void {}"))
            self.assertFalse(contains_code_secret("setApiKey(value) {}"))
            self.assertFalse(contains_code_secret("client.setApiKey(value)"))
            self.assertFalse(contains_code_secret("const setApiKey = handler"))
            self.assertFalse(
                contains_code_secret("const setApiKey = (value) => handler(value)")
            )
            self.assertFalse(
                contains_code_secret("const setApiKey = (value) => { handler(value); }")
            )
            self.assertFalse(
                contains_code_secret(
                    "const setApiKey = (value) => {\n handler(value)\n return config.apiKey\n}"
                )
            )
            self.assertFalse(
                contains_code_secret(
                    "const setApiKey = (value) => {\n if (value) return config.apiKey\n return settings.apiKey\n}"
                )
            )
            self.assertFalse(
                contains_code_secret(
                    "const setApiKey = (value) => { if (value) { return config.apiKey; } return settings.apiKey; }"
                )
            )
            self.assertFalse(
                contains_code_secret(
                    "const setApiKey = (value) => { if (value) return config.apiKey; else return settings.apiKey; }"
                )
            )
            self.assertFalse(
                contains_code_secret(
                    'const setApiKey = (value) => { if (!value) throw new Error("missing"); state.apiKey = value; }'
                )
            )
            self.assertFalse(
                contains_code_secret(
                    'const setApiKey = (value) => { if (!value) throw new Error("API key is required"); state.apiKey = value; }'
                )
            )
            self.assertFalse(
                contains_code_secret(
                    'const setApiKey = (value) => { audit("credential updated"); state.apiKey = value; }'
                )
            )
            self.assertFalse(
                contains_code_secret(
                    'function a(){ const value = "environment"; } function b(value){ setApiKey(value); }'
                )
            )
            self.assertFalse(
                contains_code_secret("client.setApiKey.apply(client, [config.apiKey])")
            )
            self.assertFalse(contains_code_secret('api_key = config.get?.("api_key")'))
            self.assertFalse(
                contains_code_secret(
                    "const apiKey = ready ? config.apiKey : settings.apiKey"
                )
            )
            self.assertFalse(
                contains_code_secret(
                    "const apiKey = ready ?\n config.apiKey\n : settings.apiKey"
                )
            )
            self.assertFalse(
                contains_code_secret(
                    "const apiKey = ready ? (enabled ? config.apiKey : other.apiKey) : settings.apiKey"
                )
            )
            self.assertFalse(
                contains_code_secret("function setApiKey({value = config.apiKey}) {}")
            )
            self.assertFalse(
                contains_code_secret("client.set_api_key(value=config.api_key)", python=True)
            )
            self.assertFalse(
                contains_code_secret(
                    'api_key = os.getenv("API_KEY") or config.api_key', python=True
                )
            )
            self.assertFalse(
                contains_code_secret(
                    'api_key = os.getenv("API_KEY", config.api_key)', python=True
                )
            )
            self.assertFalse(
                contains_code_secret(
                    'api_key = config.get("api_key", settings.api_key)', python=True
                )
            )
            self.assertFalse(
                contains_code_secret("const apiKey = process.env.API_KEY ?? config.apiKey")
            )
            self.assertFalse(
                contains_code_secret(
                    "api_key = config.api_key if configured else settings.api_key", python=True
                )
            )
            self.assertFalse(
                contains_code_secret("const [apiKey, user] = [config.apiKey, user]")
            )
            self.assertFalse(contains_code_secret("state.apiKey = value"))
            self.assertFalse(
                contains_code_secret(
                    "function setApiKey({value = config.apiKey}: {value?: string}) {}"
                )
            )
            self.assertFalse(
                contains_code_secret(
                    "function setApiKey([value = config.apiKey]: [string]) {}"
                )
            )
            self.assertFalse(
                contains_code_secret(
                    "const apiKey = ready ? nested ? config.apiKey : settings.apiKey : fallback.apiKey"
                )
            )
            self.assertFalse(
                contains_code_secret(
                    "const setApiKey = async <T extends Promise<Record<string,string>>>(value = config.apiKey) => config.apiKey"
                )
            )
            self.assertFalse(
                contains_code_secret(
                    "const setApiKey = <T extends (...args: any[]) => any>(value = config.apiKey) => config.apiKey"
                )
            )
            self.assertFalse(
                contains_code_secret(
                    "const setApiKey = <T /* > */ extends string>(value = config.apiKey) => config.apiKey"
                )
            )
            self.assertFalse(
                contains_code_secret(
                    "const setApiKey = <T>(value = config.apiKey) => value < limit ? config.apiKey : settings.apiKey"
                )
            )
            self.assertFalse(contains_code_secret("if(api_key==config.api_key)"))
            self.assertFalse(contains_code_secret("if(apiKey===config.apiKey){}"))
            self.assertFalse(contains_code_secret("api_key:=config.api_key"))
            self.assertTrue(contains_code_secret("api_key = 0"))
            self.assertTrue(contains_code_secret('api_key := "fixture-secret-value-12345"'))
            self.assertTrue(contains_code_secret('api_key = "fixture-generic-secret-12345"'))
            self.assertTrue(contains_code_secret("api_key: token_abcdefghijklmnop"))
            self.assertTrue(contains_code_secret('config["api_key"] = "fixture-secret-value-12345"'))
            self.assertTrue(contains_code_secret('config["auth"].api_key = "fixture-secret-value-12345"'))
            self.assertTrue(contains_code_secret('OPENAI_API_KEY: str = "fixture-secret-value-12345"'))
            self.assertTrue(contains_code_secret('api_key: Literal["token"] = "fixture-secret-value-12345"'))
            self.assertTrue(contains_code_secret('const apiKey?: string = "fixture-secret-value-12345"'))
            self.assertTrue(contains_code_secret('api_key = """\nfixture-secret-value-12345\n"""'))
            self.assertTrue(contains_code_secret('api_key = rf"""\nfixture-secret-value-12345\n"""'))
            self.assertTrue(contains_code_secret('api_key = SecretStr("fixture-secret-value-12345")'))
            self.assertTrue(contains_code_secret('api_key = re.compile("fixture-secret-value-12345")'))
            self.assertTrue(contains_code_secret('api_key = load_kit_helper("fixture-secret-value-12345")'))
            self.assertTrue(contains_code_secret('api_key = os.getenv("API_KEY") or "fixture-secret-value-12345"'))
            self.assertTrue(
                contains_code_secret(
                    'const apiKey = this.#secret || "fixture-secret-value-12345"'
                )
            )
            self.assertTrue(contains_code_secret('set_api_key("fixture-secret-value-12345")'))
            self.assertTrue(
                contains_code_secret('result = set_api_key("fixture-secret-value-12345")')
            )
            self.assertTrue(
                contains_code_secret('config = api_key = "fixture-secret-value-12345"')
            )
            self.assertTrue(
                contains_code_secret('result = api_key += "fixture-secret-value-12345"')
            )
            self.assertTrue(
                contains_code_secret('result = api_key ??= "fixture-secret-value-12345"')
            )
            self.assertTrue(
                contains_code_secret("result = apiKey <<= 1234567890123456")
            )
            self.assertTrue(contains_code_secret('client.setApiKey("fixture-secret-value-12345")'))
            self.assertTrue(
                contains_code_secret('client["setApiKey"]("fixture-secret-value-12345")')
            )
            self.assertTrue(
                contains_code_secret('client.setApiKey?.("fixture-secret-value-12345")')
            )
            self.assertTrue(contains_code_secret('update_api_key("fixture-secret-value-12345")'))
            self.assertTrue(contains_code_secret('configure_api_key("fixture-secret-value-12345")'))
            self.assertTrue(
                contains_code_secret('client.apiKey.set("fixture-secret-value-12345")')
            )
            self.assertTrue(
                contains_code_secret('client.apiKey?.set("fixture-secret-value-12345")')
            )
            self.assertTrue(
                contains_code_secret(
                    'def set_api_key(value: str = "fixture-secret-value-12345"):\n    pass',
                    python=True,
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'function setApiKey(value = "fixture-secret-value-12345") {}'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'function setApiKey({value = "fixture-secret-value-12345"}) {}'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'function setApiKey({nested: {value = "fixture-secret-value-12345"}} = config.apiKey) {}'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'enabled ? client.setApiKey("fixture-secret-value-12345") : noop()'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'enabled ? client.setApiKey("fixture-secret-value-12345") : noop;'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'enabled ?\n client.setApiKey("fixture-secret-value-12345")\n : noop;'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'function setApiKey({value = "fixture-secret-value-12345"}: Options) {}'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'const setApiKey = async (value = "fixture-secret-value-12345") => config.apiKey'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'const setApiKey = (value = "fixture-secret-value-12345"): string => config.apiKey'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'const setApiKey = <T>(value = "fixture-secret-value-12345") => config.apiKey'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'const setApiKey = async <T extends Promise<string>>(value = "fixture-secret-value-12345") => config.apiKey'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'function setApiKey<T>(value = "fixture-secret-value-12345") {}'
                )
            )
            self.assertTrue(
                contains_code_secret('client["apiKey"]["set"]("fixture-secret-value-12345")')
            )
            self.assertTrue(
                contains_code_secret(
                    'client["apiKey"]?.["set"]?.("fixture-secret-value-12345")'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'client?.apiKey?.["set"]?.("fixture-secret-value-12345")'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'client.apiKey /* x */ .set("fixture-secret-value-12345")'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'client.apiKey. /* x */ set("fixture-secret-value-12345")'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'client.apiKey[/* x */ "set"]("fixture-secret-value-12345")'
                )
            )
            self.assertTrue(
                contains_code_secret('client.apiKey\n.set("fixture-secret-value-12345")')
            )
            self.assertTrue(
                contains_code_secret(
                    'client["apiKey"] /* x */ ["set"]("fixture-secret-value-12345")'
                )
            )
            self.assertTrue(
                contains_code_secret('client["set"].apiKey("fixture-secret-value-12345")')
            )
            self.assertTrue(
                contains_code_secret('client.set?.apiKey("fixture-secret-value-12345")')
            )
            self.assertTrue(
                contains_code_secret(
                    'client.setApiKey.call(client, "fixture-secret-value-12345")'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'client.setApiKey.bind(client, "fixture-secret-value-12345")'
                )
            )
            self.assertTrue(
                contains_code_secret('client["set"]["apiKey"]("fixture-secret-value-12345")')
            )
            self.assertTrue(
                contains_code_secret(
                    'class Vault { set apiKey(value = "fixture-secret-value-12345") {} }'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'class Vault { set\n apiKey(value = "fixture-secret-value-12345") {} }'
                )
            )
            self.assertTrue(
                contains_code_secret('set ["apiKey"](value = "fixture-secret-value-12345") {}')
            )
            self.assertTrue(
                contains_code_secret('set #apiKey(value = "fixture-secret-value-12345") {}')
            )
            self.assertTrue(
                contains_code_secret(
                    'class Vault { set /* accessor */ apiKey(value = "fixture-secret-value-12345") {} }'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'class Vault { set "apiKey"(value = "fixture-secret-value-12345") {} }'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'function setApiKey<T extends (...args: any[]) => any>(value = "fixture-secret-value-12345") {}'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'function setApiKey<T extends ">" | string>(value = "fixture-secret-value-12345") {}'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'const value = "fixture-secret-value-12345"; setApiKey(value)'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'const value = "fixture-secret-value-12345"; state.apiKey = value'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'const value: string = "fixture-secret-value-12345"; setApiKey(value)'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'const value = "fixture-secret-value-12345"; if (ready) { setApiKey(value); }'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'const value = String("fixture-secret-value-12345"); state.apiKey = value'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'const setApiKey = (value) => { if (value === "fixture-secret-value-12345") return config.apiKey; return settings.apiKey; }'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'class Vault { set // accessor\n apiKey(value = "fixture-secret-value-12345") {} }'
                )
            )
            self.assertFalse(
                contains_code_secret(
                    "function setApiKey({value = config.apiKey} = {}) {}"
                )
            )
            self.assertTrue(
                contains_code_secret(
                    "api_key = config.api_key or 1234567890123456", python=True
                )
            )
            self.assertTrue(
                contains_code_secret(
                    "api_key = config.api_key, 1234567890123456", python=True
                )
            )
            self.assertTrue(
                contains_code_secret("api_key = SecretInt(1234567890123456)", python=True)
            )
            self.assertTrue(
                contains_code_secret(
                    'const [\n apiKey,\n user\n] = [\n "fixture-secret-value-12345", user\n]'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    'const apiKey // assigned below\n = "fixture-secret-value-12345";'
                )
            )
            self.assertTrue(
                contains_code_secret(
                    "blob = 'config = \"api_key=fixture-secret-value-12345\"'",
                    python=True,
                )
            )
            self.assertTrue(
                contains_document_secret(
                    'The config is "api_key=fixture-secret-value-12345".'
                )
            )
            self.assertTrue(
                contains_document_secret(
                    "The config is `api_key=fixture-secret-value-12345`."
                )
            )
            deeply_nested = "api_key=fixture-secret-value-12345"
            for _ in range(9):
                deeply_nested = f"blob={deeply_nested!r}"
            self.assertTrue(contains_code_secret(deeply_nested, python=True))
            self.assertTrue(contains_code_secret('api_key = config.api_key, "fixture-secret-value-12345"'))
            self.assertTrue(contains_code_secret('const apiKey = process.env.API_KEY || "fixture-secret-value-12345"'))
            self.assertTrue(contains_code_secret('const apiKey = // assigned below\n "fixture-secret-value-12345"'))
            self.assertTrue(contains_code_secret('blob = "api_key = fixture-secret-value-12345"'))
            self.assertTrue(contains_code_secret('blob = """api_key: fixture-secret-value-12345"""'))
            self.assertTrue(contains_code_secret('blob = `apiKey=fixture-secret-value-12345`'))
            self.assertTrue(
                contains_code_secret(
                    "# don't hardcode credentials\napi_key = \"fixture-secret-value-12345\"",
                    python=True,
                )
            )
            self.assertFalse(contains_code_secret('use(api_key, fallback=config.api_key)'))
            self.assertTrue(contains_code_secret('OPENAI_API_KEY = r"fixture-secret-value-12345"'))
            self.assertTrue(contains_code_secret("const api_key = `fixture-secret-value-12345`"))
            self.assertTrue(contains_code_secret("const openaiApiKey = `fixture-secret-value-12345`"))
            self.assertTrue(contains_code_secret('api_key = b"fixture-secret-value-12345"'))
            self.assertTrue(contains_code_secret("api_key=1234567890123456"))
            self.assertFalse(contains_code_secret('api_key = "${API_KEY}"', shell=True))
            self.assertFalse(contains_code_secret("api_key=${API_KEY}", shell=True))
            self.assertFalse(contains_code_secret("api_key=${API_KEY:?required}", shell=True))
            self.assertFalse(contains_code_secret("api_key=${API_KEY:?API key is required}", shell=True))
            self.assertFalse(contains_code_secret("api_key=$(get_api_key)", shell=True))
            self.assertFalse(contains_code_secret("api_key=$API_KEY # loaded from env", shell=True))
            self.assertFalse(contains_code_secret("api_key=$API_KEY command", shell=True))
            self.assertFalse(contains_code_secret('api_key="${API_KEY}" command', shell=True))
            self.assertFalse(contains_code_secret("api_key=$API_KEY other=value command", shell=True))
            self.assertTrue(contains_code_secret("api_key=$(printf fixture-secret-value-12345)", shell=True))
            self.assertTrue(contains_code_secret("api_key=${API_KEY}fixture-secret-value-12345", shell=True))
            self.assertTrue(contains_code_secret("api_key=$API_KEY#fixture-secret-value-12345", shell=True))
            self.assertTrue(contains_code_secret("api_key=$API_KEY//fixture-secret-value-12345", shell=True))
            self.assertTrue(contains_code_secret("api_key=${API_KEY:-fixture-secret-value-12345}", shell=True))
            self.assertTrue(contains_code_secret("api_key=${API_KEY:=fixture-secret-value-12345}", shell=True))
            self.assertFalse(contains_document_secret("```{.bash}\napi_key=${API_KEY}\n```\n"))
            self.assertFalse(contains_document_secret("````python\napi_key = config.api_key\n`````\n"))
            self.assertTrue(contains_document_secret("```\nopenai_api_key: fixture-secret-value-12345\n```\n"))
            self.assertTrue(contains_document_secret("```console\nAPI_KEY=fixture-secret-value-12345\n```\n"))
            self.assertTrue(contains_code_secret("api_key=fixture-generic-secret-12345", shell=True))
            code_result, code_capture = self.run_capture_operation(
                root,
                "capture.create",
                {
                    "destination": "inbox",
                    "title": "Fenced code reference",
                    "summary": "Legitimate credential and cursor references in code.",
                    "content": code,
                },
            )
            self.assertEqual(code_result.returncode, 0, code_result.stderr)
            self.assertEqual(code_capture["status"], "applied")
            fenced_token = "```text\n" + "ghp_" + "abcdefghijklmnopqrstuvwxyz123456\n```\n"
            self.assertTrue(contains_document_secret(fenced_token))
            fenced_result, fenced_failure = self.run_capture_operation(
                root,
                "capture.create",
                {
                    "destination": "inbox",
                    "title": "Unsafe fenced token",
                    "summary": "Concrete credentials remain unsafe inside code fences.",
                    "content": fenced_token,
                },
            )
            self.assertNotEqual(fenced_result.returncode, 0)
            self.assertEqual(fenced_failure["target"], "")
            self.assertNotIn(fenced_token, fenced_result.stdout + fenced_result.stderr)
            disguised_secret = "api_key=response.real-" + "secret-token-12345"
            self.assertTrue(contains_secret(disguised_secret))

            sensitive_title = "api_" + "key=fixture-title-value-12345"
            title_result, title_failure = self.run_capture_operation(
                root,
                "capture.create",
                {
                    "destination": "inbox",
                    "title": sensitive_title,
                    "summary": "Must not echo the title.",
                    "content": "Safe body.",
                },
            )
            self.assertNotEqual(title_result.returncode, 0)
            self.assertEqual(title_failure["target"], "")
            self.assertNotIn(sensitive_title, title_result.stdout + title_result.stderr)

            sensitive_origin = "https://example.invalid/?session_" + "token=fixture-origin-value-12345"
            origin_result, origin_failure = self.run_capture_operation(
                root,
                "capture.create",
                {
                    "destination": "source",
                    "title": "Unsafe origin",
                    "summary": "Must not echo the origin.",
                    "origin": sensitive_origin,
                    "capture": "reference",
                },
            )
            self.assertNotEqual(origin_result.returncode, 0)
            self.assertEqual(origin_failure["target"], "")
            self.assertNotIn(sensitive_origin, origin_result.stdout + origin_result.stderr)

    def test_mutation_lock_rejects_a_concurrent_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            with mutation_locks([root]):
                result, output = self.run_capture_operation(
                    root,
                    "capture.create",
                    {
                        "destination": "inbox",
                        "title": "Locked Capture",
                        "summary": "Must not write while another mutation holds the lock.",
                        "content": "Synthetic non-secret content.",
                    },
                )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("another LBrain mutation", output["error"])
            self.assertFalse(list((root / "Inbox").glob("*Locked-Capture*.md")))

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
            self.assert_failed_operation(disabled, "proposal.create", "disabled-writing")
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

    def test_skill_preview_is_validated_immutable_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            skill = self.add_enabled_personal_skill(root)
            source = root / "Knowledge/Sources/Preview-Evidence.md"
            source.write_text(
                "---\ntype: source\nsummary: preview evidence\nstatus: active\nvisibility: private\n"
                "origin: synthetic://preview-evidence\ncapture: full\nweaving: pending\n"
                "created: 2026-08-10\nupdated: 2026-08-10\n---\n# Preview Evidence\n",
                encoding="utf-8",
            )
            proposal_result, proposal = self.run_weave_operation(
                root,
                "proposal.create",
                {
                    "title": "Improve preview writing",
                    "summary": "Add a specific-opening rule.",
                    "skill_name": "synthetic-writing",
                    "evidence": ["Knowledge/Sources/Preview-Evidence.md"],
                    "rationale": "The evidence supplies a testable rule.",
                    "behavior_delta": "Require one concrete claim in the opening.",
                    "expected_diff": "Update instructions and behavior cases.",
                    "test_changes": ["Reject an abstract opening."],
                },
            )
            self.assertEqual(proposal_result.returncode, 0, proposal_result.stderr)
            before_skill = (skill / "SKILL.md").read_text(encoding="utf-8")
            before_cases = (skill / "tests/cases.md").read_text(encoding="utf-8")
            before_manifest = (skill / "lbrain.json").read_text(encoding="utf-8")
            payload: dict[str, object] = {
                "proposal_path": proposal["target"],
                "change_level": "minor",
                "rationale": "Adds a compatible opening check.",
                "changes": {
                    "SKILL.md": before_skill.replace(
                        "Use concrete verbs.",
                        "Use concrete verbs. Require one concrete claim in the opening.",
                    ),
                    "tests/cases.md": before_cases + "- Reject an abstract opening.\n",
                    "scripts/reference.py": (
                        'api_key = config.get("api_key")\n'
                        "cursor = response.get_cursor(page)\n"
                    ),
                },
            }

            unsafe_result, unsafe = self.run_skill_operation(
                root,
                "skill.preview",
                {
                    **payload,
                    "changes": {
                        **payload["changes"],
                        "scripts/leak.py": 'config["api_key"] = """\nfixture-secret-value-12345\n"""\n',
                    },
                },
            )
            self.assertNotEqual(unsafe_result.returncode, 0)
            self.assertIn("possible credentials", unsafe["error"])

            unsafe_typescript_result, unsafe_typescript = self.run_skill_operation(
                root,
                "skill.preview",
                {
                    **payload,
                    "changes": {
                        **payload["changes"],
                        "scripts/leak.ts": (
                            'const apiKey = this.#secret || "fixture-secret-value-12345";\n'
                        ),
                    },
                },
            )
            self.assertNotEqual(unsafe_typescript_result.returncode, 0)
            self.assertIn("possible credentials", unsafe_typescript["error"])

            preview_result, previewed = self.run_skill_operation(root, "skill.preview", payload)
            self.assertEqual(preview_result.returncode, 0, preview_result.stderr)
            self.assertEqual(previewed["status"], "applied")
            preview = previewed["preview"]
            self.assertEqual(preview["base_version"], "1.0.0")
            self.assertEqual(preview["proposed_version"], "1.1.0")
            self.assertTrue(preview["preview_hash"])
            self.assertIn("lbrain.json", preview["files"])
            self.assertIn("scripts/reference.py", preview["files"])
            self.assertEqual((skill / "SKILL.md").read_text(encoding="utf-8"), before_skill)
            self.assertEqual((skill / "tests/cases.md").read_text(encoding="utf-8"), before_cases)
            self.assertEqual((skill / "lbrain.json").read_text(encoding="utf-8"), before_manifest)
            proposal_text = (root / str(proposal["target"])).read_text(encoding="utf-8")
            self.assertIn("## Change Preview", proposal_text)
            self.assertIn(str(preview["preview_hash"]), proposal_text)
            self.assertIn("Proposed version: 1.1.0", proposal_text)
            with (root / str(proposal["target"])).open("a", encoding="utf-8") as file:
                file.write("\n## Reviewer notes\n\nPreserve this note.\n")

            repeat_result, repeated = self.run_skill_operation(root, "skill.preview", payload)
            self.assertEqual(repeat_result.returncode, 0, repeat_result.stderr)
            self.assertEqual(repeated["status"], "noop")
            self.assertEqual(repeated["preview"]["preview_hash"], preview["preview_hash"])
            self.assertIn(
                "Preserve this note.",
                (root / str(proposal["target"])).read_text(encoding="utf-8"),
            )

            patch_result, patch_preview = self.run_skill_operation(
                root, "skill.preview", {**payload, "change_level": "patch"}
            )
            self.assertEqual(patch_result.returncode, 0, patch_result.stderr)
            self.assertEqual(patch_preview["preview"]["proposed_version"], "1.0.1")

            major_result, major_preview = self.run_skill_operation(
                root, "skill.preview", {**payload, "change_level": "major"}
            )
            self.assertEqual(major_result.returncode, 0, major_result.stderr)
            self.assertEqual(major_preview["preview"]["proposed_version"], "2.0.0")

    def test_skill_preview_rejects_an_invalid_proposed_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            skill = self.add_enabled_personal_skill(root)
            source = root / "Knowledge/Sources/Invalid-Preview-Evidence.md"
            source.write_text(
                "---\ntype: source\nsummary: invalid preview evidence\nstatus: active\nvisibility: private\n"
                "origin: synthetic://invalid-preview\ncapture: full\nweaving: pending\n"
                "created: 2026-08-10\nupdated: 2026-08-10\n---\n# Invalid Preview Evidence\n",
                encoding="utf-8",
            )
            _, proposal = self.run_weave_operation(
                root,
                "proposal.create",
                {
                    "title": "Reject invalid preview",
                    "summary": "Validation fixture.",
                    "skill_name": "synthetic-writing",
                    "evidence": ["Knowledge/Sources/Invalid-Preview-Evidence.md"],
                    "rationale": "Exercise preview validation.",
                    "behavior_delta": "Add a validated instruction.",
                    "expected_diff": "Update instructions and cases.",
                    "test_changes": ["Add one validated case."],
                },
            )
            original = (skill / "SKILL.md").read_text(encoding="utf-8")
            result, rejected = self.run_skill_operation(
                root,
                "skill.preview",
                {
                    "proposal_path": proposal["target"],
                    "change_level": "patch",
                    "rationale": "Must fail before preview is recorded.",
                    "changes": {
                        "SKILL.md": original.replace(
                            "description:", "version: 1.0.1\ndescription:", 1
                        ),
                        "tests/cases.md": "# Cases\n\n- A changed case.\n",
                    },
                },
            )
            self.assertNotEqual(result.returncode, 0)
            self.assert_failed_operation(rejected, "skill.preview", str(proposal["target"]))
            self.assertIn("does not validate", rejected["error"])
            self.assertEqual((skill / "SKILL.md").read_text(encoding="utf-8"), original)
            proposal_text = (root / str(proposal["target"])).read_text(encoding="utf-8")
            self.assertNotIn("## Change Preview", proposal_text)

    def test_skill_apply_uses_exact_approval_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.copy_repo(base)
            skill = self.add_enabled_personal_skill(root)
            source = root / "Knowledge/Sources/Apply-Evidence.md"
            source.write_text(
                "---\ntype: source\nsummary: apply evidence\nstatus: active\nvisibility: private\n"
                "origin: synthetic://apply-evidence\ncapture: full\nweaving: pending\n"
                "created: 2026-08-10\nupdated: 2026-08-10\n---\n# Apply Evidence\n",
                encoding="utf-8",
            )
            _, proposal = self.run_weave_operation(
                root,
                "proposal.create",
                {
                    "title": "Apply writing improvement",
                    "summary": "Apply a concrete-opening rule.",
                    "skill_name": "synthetic-writing",
                    "evidence": ["Knowledge/Sources/Apply-Evidence.md"],
                    "rationale": "The rule is evidence-backed.",
                    "behavior_delta": "Require a concrete opening claim.",
                    "expected_diff": "Update instructions and cases.",
                    "test_changes": ["Add a concrete-opening case."],
                },
            )
            before_skill = (skill / "SKILL.md").read_text(encoding="utf-8")
            before_cases = (skill / "tests/cases.md").read_text(encoding="utf-8")
            codex_root = base / "codex"
            openclaw_root = base / "openclaw"
            shutil.copytree(skill, openclaw_root / skill.name)
            preview_payload: dict[str, object] = {
                "proposal_path": proposal["target"],
                "change_level": "minor",
                "rationale": "Adds compatible opening behavior.",
                "changes": {
                    "SKILL.md": before_skill.replace(
                        "Use concrete verbs.",
                        "Use concrete verbs. Require a concrete opening claim.",
                    ),
                    "tests/cases.md": before_cases + "- Require a concrete opening claim.\n",
                },
            }
            internal_result, internal = self.run_skill_operation(
                root,
                "skill.preview",
                {
                    **preview_payload,
                    "runtime_targets": [
                        {"runtime": "codex", "target": str(root / "Skills/Personal")},
                    ],
                },
            )
            self.assertNotEqual(internal_result.returncode, 0)
            self.assertIn("outside the canonical LBrain", internal["error"])

            escaped_openclaw = base / "openclaw-symlink"
            escaped_openclaw.mkdir()
            (escaped_openclaw / skill.name).symlink_to(skill, target_is_directory=True)
            escaped_result, escaped = self.run_skill_operation(
                root,
                "skill.preview",
                {
                    **preview_payload,
                    "runtime_targets": [
                        {"runtime": "openclaw", "target": str(escaped_openclaw)},
                    ],
                },
            )
            self.assertNotEqual(escaped_result.returncode, 0)
            self.assertIn("OpenClaw requires a copied Skill package", escaped["error"])

            duplicate_result, duplicate = self.run_skill_operation(
                root,
                "skill.preview",
                {
                    **preview_payload,
                    "runtime_targets": [
                        {"runtime": "codex", "target": str(codex_root)},
                        {"runtime": "claude", "target": str(codex_root)},
                    ],
                },
            )
            self.assertNotEqual(duplicate_result.returncode, 0)
            self.assertIn("duplicate package destination", duplicate["error"])

            drift_root = base / "drift"
            preview_payload["runtime_targets"] = [
                {"runtime": "codex", "target": str(codex_root)},
                {"runtime": "openclaw", "target": str(openclaw_root)},
                {"runtime": "codex", "target": str(drift_root)},
            ]
            _, previewed = self.run_skill_operation(
                root,
                "skill.preview",
                preview_payload,
            )
            preview = previewed["preview"]
            pending_result, pending = self.run_skill_operation(
                root,
                "skill.apply",
                {
                    "proposal_path": proposal["target"],
                    "approved_preview_hash": preview["preview_hash"],
                    "preview": preview,
                },
            )
            self.assertNotEqual(pending_result.returncode, 0)
            self.assertIn("explicitly accepted Proposal", pending["error"])
            self.accept_skill_preview(root, proposal["target"], preview["preview_hash"])
            rejected_result, rejected = self.run_skill_operation(
                root,
                "skill.apply",
                {
                    "proposal_path": proposal["target"],
                    "approved_preview_hash": preview["preview_hash"],
                    "preview": preview,
                    "runtime_targets": [
                        {"runtime": "openclaw", "target": str(escaped_openclaw)},
                    ],
                },
            )
            self.assertNotEqual(rejected_result.returncode, 0)
            self.assertEqual(rejected["status"], "failed")
            self.assertIn("declared and approved during skill.preview", rejected["error"])
            self.assertEqual((skill / "SKILL.md").read_text(encoding="utf-8"), before_skill)

            payload: dict[str, object] = {
                "proposal_path": proposal["target"],
                "approved_preview_hash": preview["preview_hash"],
                "preview": preview,
            }

            shutil.copytree(skill, drift_root / skill.name)
            drift_result, drifted = self.run_skill_operation(root, "skill.apply", payload)
            self.assertNotEqual(drift_result.returncode, 0)
            self.assertEqual(drifted["status"], "failed")
            self.assertIn("runtime target state changed after preview", drifted["validation"]["message"])
            self.assertEqual((skill / "SKILL.md").read_text(encoding="utf-8"), before_skill)
            shutil.rmtree(drift_root / skill.name)

            result, applied = self.run_skill_operation(root, "skill.apply", payload)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(applied["status"], "applied")
            self.assertIn("Require a concrete opening claim", (skill / "SKILL.md").read_text(encoding="utf-8"))
            self.assertIn("Require a concrete opening claim", (skill / "tests/cases.md").read_text(encoding="utf-8"))
            manifest = json.loads((skill / "lbrain.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["version"], "1.1.0")
            self.assertTrue((codex_root / skill.name).is_symlink())
            self.assertEqual((codex_root / skill.name).resolve(), skill.resolve())
            self.assertFalse((openclaw_root / skill.name).is_symlink())
            self.assertIn(
                "Require a concrete opening claim",
                (openclaw_root / skill.name / "SKILL.md").read_text(encoding="utf-8"),
            )
            proposal_text = (root / str(proposal["target"])).read_text(encoding="utf-8")
            self.assertIn("status: applied", proposal_text)
            self.assertIn(str(preview["preview_hash"]), proposal_text)
            self.assertIn("Accepted exact Change Preview", proposal_text)
            self.assertIn("Applied exact Change Preview", proposal_text)

            repeat_result, repeated = self.run_skill_operation(root, "skill.apply", payload)
            self.assertEqual(repeat_result.returncode, 0, repeat_result.stderr)
            self.assertEqual(repeated["status"], "noop")

    def test_skill_apply_rolls_back_and_records_accepted_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.copy_repo(base)
            skill = self.add_enabled_personal_skill(root)
            source = root / "Knowledge/Sources/Rollback-Evidence.md"
            source.write_text(
                "---\ntype: source\nsummary: rollback evidence\nstatus: active\nvisibility: private\n"
                "origin: synthetic://rollback-evidence\ncapture: full\nweaving: pending\n"
                "created: 2026-08-10\nupdated: 2026-08-10\n---\n# Rollback Evidence\n",
                encoding="utf-8",
            )
            _, proposal = self.run_weave_operation(
                root,
                "proposal.create",
                {
                    "title": "Rollback writing improvement",
                    "summary": "Exercise atomic rollback.",
                    "skill_name": "synthetic-writing",
                    "evidence": ["Knowledge/Sources/Rollback-Evidence.md"],
                    "rationale": "Runtime failure must not split state.",
                    "behavior_delta": "Add a rollback-tested instruction.",
                    "expected_diff": "Update instructions and cases.",
                    "test_changes": ["Add a rollback behavior case."],
                },
            )
            before_skill = (skill / "SKILL.md").read_text(encoding="utf-8")
            before_cases = (skill / "tests/cases.md").read_text(encoding="utf-8")
            before_manifest = (skill / "lbrain.json").read_text(encoding="utf-8")
            openclaw_root = base / "openclaw"
            runtime_skill = openclaw_root / skill.name
            shutil.copytree(skill, runtime_skill)
            before_runtime = (runtime_skill / "SKILL.md").read_text(encoding="utf-8")
            blocked_runtime_root = base / "not-a-directory"
            blocked_runtime_root.write_text("block runtime installation", encoding="utf-8")
            _, previewed = self.run_skill_operation(
                root,
                "skill.preview",
                {
                    "proposal_path": proposal["target"],
                    "change_level": "patch",
                    "rationale": "Compatible instruction fix.",
                    "changes": {
                        "SKILL.md": before_skill + "\nRollback-tested instruction.\n",
                        "tests/cases.md": before_cases + "- Roll back a failed runtime refresh.\n",
                    },
                    "runtime_targets": [
                        {"runtime": "openclaw", "target": str(openclaw_root)},
                        {"runtime": "openclaw", "target": str(blocked_runtime_root)},
                    ],
                },
            )
            preview = previewed["preview"]
            self.accept_skill_preview(root, proposal["target"], preview["preview_hash"])

            result, failed = self.run_skill_operation(
                root,
                "skill.apply",
                {
                    "proposal_path": proposal["target"],
                    "approved_preview_hash": preview["preview_hash"],
                    "preview": preview,
                },
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["rollback"], {"performed": True, "ok": True})
            self.assertEqual((skill / "SKILL.md").read_text(encoding="utf-8"), before_skill)
            self.assertEqual((skill / "tests/cases.md").read_text(encoding="utf-8"), before_cases)
            self.assertEqual((skill / "lbrain.json").read_text(encoding="utf-8"), before_manifest)
            self.assertEqual((runtime_skill / "SKILL.md").read_text(encoding="utf-8"), before_runtime)
            proposal_text = (root / str(proposal["target"])).read_text(encoding="utf-8")
            self.assertIn("status: accepted", proposal_text)
            self.assertNotIn("status: applied", proposal_text)
            self.assertIn("failed and rolled back", proposal_text)

            spec = importlib.util.spec_from_file_location("skill_operations_rollback", SKILL_OPERATIONS)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            good_package = base / "good-runtime"
            good_backup = base / "good-backup"
            bad_package = base / "bad-runtime"
            bad_backup = base / "bad-backup"
            for package, marker in (
                (good_package, "new"), (good_backup, "old"),
                (bad_package, "new"), (bad_backup, "old"),
            ):
                package.mkdir()
                (package / "marker").write_text(marker, encoding="utf-8")
            original_remove = module.remove_runtime_package

            def fail_one_runtime(path: Path) -> None:
                if path == bad_package:
                    raise OSError("synthetic rollback failure")
                original_remove(path)

            module.remove_runtime_package = fail_one_runtime
            rollback_ok, recovery_paths = module.rollback_runtimes(
                [(good_package, good_backup), (bad_package, bad_backup)]
            )
            self.assertFalse(rollback_ok)
            self.assertEqual(recovery_paths, [bad_backup])
            self.assertEqual((good_package / "marker").read_text(encoding="utf-8"), "old")
            self.assertEqual((bad_backup / "marker").read_text(encoding="utf-8"), "old")

            partial_runtime = base / "partial-runtime"
            partial_backups = base / "partial-backups"
            shutil.copytree(skill, partial_runtime)
            partial_entries: list[tuple[Path, Path | None]] = []

            def fail_during_remove(path: Path) -> None:
                if path == partial_runtime:
                    (path / "SKILL.md").unlink()
                    raise OSError("synthetic partial removal")
                original_remove(path)

            module.remove_runtime_package = fail_during_remove
            with self.assertRaises(OSError):
                module.refresh_runtimes(
                    skill,
                    [("openclaw", partial_runtime, "replace")],
                    partial_backups,
                    partial_entries,
                    [],
                )
            self.assertEqual(partial_entries, [(partial_runtime, partial_backups / "0")])
            partial_ok, partial_recovery = module.rollback_runtimes(partial_entries)
            self.assertFalse(partial_ok)
            self.assertEqual(partial_recovery, [partial_backups / "0"])

    def test_skill_apply_invalidates_stale_preview_before_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            skill = self.add_enabled_personal_skill(root)
            source = root / "Knowledge/Sources/Stale-Evidence.md"
            source.write_text(
                "---\ntype: source\nsummary: stale evidence\nstatus: active\nvisibility: private\n"
                "origin: synthetic://stale-evidence\ncapture: full\nweaving: pending\n"
                "created: 2026-08-10\nupdated: 2026-08-10\n---\n# Stale Evidence\n",
                encoding="utf-8",
            )
            _, proposal = self.run_weave_operation(
                root,
                "proposal.create",
                {
                    "title": "Stale writing improvement",
                    "summary": "Reject stale approval.",
                    "skill_name": "synthetic-writing",
                    "evidence": ["Knowledge/Sources/Stale-Evidence.md"],
                    "rationale": "Baseline changes invalidate approval.",
                    "behavior_delta": "Add a stale-tested instruction.",
                    "expected_diff": "Update instructions and cases.",
                    "test_changes": ["Add a stale-preview case."],
                },
            )
            before_skill = (skill / "SKILL.md").read_text(encoding="utf-8")
            before_cases = (skill / "tests/cases.md").read_text(encoding="utf-8")
            _, previewed = self.run_skill_operation(
                root,
                "skill.preview",
                {
                    "proposal_path": proposal["target"],
                    "change_level": "patch",
                    "rationale": "Compatible instruction fix.",
                    "changes": {
                        "SKILL.md": before_skill + "\nStale-tested instruction.\n",
                        "tests/cases.md": before_cases + "- Reject stale preview.\n",
                    },
                },
            )
            preview = previewed["preview"]
            self.accept_skill_preview(root, proposal["target"], preview["preview_hash"])
            with (skill / "SKILL.md").open("a", encoding="utf-8") as file:
                file.write("\nConcurrent canonical edit.\n")

            result, stale = self.run_skill_operation(
                root,
                "skill.apply",
                {
                    "proposal_path": proposal["target"],
                    "approved_preview_hash": preview["preview_hash"],
                    "preview": preview,
                },
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(stale["status"], "failed")
            self.assertIn("changed after preview", stale["error"])
            proposal_text = (root / str(proposal["target"])).read_text(encoding="utf-8")
            self.assertIn("status: accepted", proposal_text)


if __name__ == "__main__":
    unittest.main()
