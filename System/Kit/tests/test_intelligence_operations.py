from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest import mock


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
CAPTURE_NATIVE_HOST = ROOT / "Skills/Kit/lbrain-capture/scripts/native_host.py"
CAPTURE_NATIVE_INSTALLER = ROOT / "Skills/Kit/lbrain-capture/scripts/install_native_host.py"
CAPTURE_EXTENSION = ROOT / "Skills/Kit/lbrain-capture/browser-extension"
WEAVE_OPERATIONS = ROOT / "Skills/Kit/lbrain-weave/scripts/operations.py"
SKILL_OPERATIONS = ROOT / "Skills/Kit/lbrain-skill-manager/scripts/operations.py"


class IntelligenceOperationTest(unittest.TestCase):
    def copy_repo(self, destination: Path) -> Path:
        copy = destination / "lbrain"
        untracked: set[str] = set()
        if (ROOT / ".git").exists():
            untracked = set(
                subprocess.run(
                    [
                        "git", "-C", str(ROOT), "ls-files", "--others", "--directory",
                        "--exclude-standard", "-z",
                    ],
                    check=True,
                    capture_output=True,
                ).stdout.decode().rstrip("\0").split("\0")
            )

        def ignored(source: str, names: list[str]) -> set[str]:
            relative = Path(source).resolve().relative_to(ROOT).as_posix()
            prefix = "" if relative == "." else f"{relative}/"
            return {
                name for name in names
                if name in {".git", "__pycache__"}
                or (relative == "Inbox/Captures" and name != "README.md")
                or f"{prefix}{name}" in untracked
                or f"{prefix}{name}/" in untracked
            }

        shutil.copytree(ROOT, copy, ignore=ignored)
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

    def run_capture_native_host(
        self,
        root: Path,
        payload: dict[str, object],
        staging_root: Path | None = None,
    ) -> tuple[subprocess.CompletedProcess[bytes], dict[str, object]]:
        message = json.dumps(payload).encode("utf-8")
        command = [sys.executable, str(CAPTURE_NATIVE_HOST), "--root", str(root)]
        if staging_root is not None:
            command.extend(("--staging-root", str(staging_root)))
        result = subprocess.run(
            command,
            input=struct.pack("=I", len(message)) + message,
            capture_output=True,
            check=False,
        )
        if len(result.stdout) < 4:
            return result, {}
        offset = 0
        output: dict[str, object] = {}
        while offset + 4 <= len(result.stdout):
            length = struct.unpack("=I", result.stdout[offset : offset + 4])[0]
            offset += 4
            output = json.loads(result.stdout[offset : offset + length])
            offset += length
        return result, output

    def run_capture_native_stream(
        self,
        root: Path,
        payload: dict[str, object],
        snapshot: bytes,
        snapshot_kind: str,
        staging_root: Path,
        attachments: dict[str, bytes] | None = None,
        snapshot_media_type: str | None = None,
        attachment_media_types: dict[str, str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[bytes], dict[str, object]]:
        payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        attachments = attachments or {}
        attachment_media_types = attachment_media_types or {}
        stream_id = "test-stream"
        messages: list[dict[str, object]] = [{
            "protocol": "lbrain.capture.stream.v1",
            "type": "begin",
            "acknowledgements": True,
            "integrity": "sha256-chunks",
            "stream_id": stream_id,
            "payload_size": len(payload_bytes),
            "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
            "snapshot_kind": snapshot_kind,
            "snapshot_size": len(snapshot),
            "snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
            "snapshot_media_type": snapshot_media_type
            or ("multipart/related" if snapshot_kind == "mhtml" else "application/octet-stream"),
            "attachments": [
                {
                    "id": asset_id,
                    "size": len(value),
                    "sha256": hashlib.sha256(value).hexdigest(),
                    "media_type": attachment_media_types.get(asset_id, ""),
                }
                for asset_id, value in attachments.items()
            ],
        }]
        for channel, value in (
            ("payload", payload_bytes),
            ("snapshot", snapshot),
            *((f"asset:{asset_id}", value) for asset_id, value in attachments.items()),
        ):
            for sequence, offset in enumerate(range(0, len(value), 127)):
                chunk = value[offset : offset + 127]
                messages.append({
                    "protocol": "lbrain.capture.stream.v1",
                    "type": "chunk",
                    "stream_id": stream_id,
                    "channel": channel,
                    "sequence": sequence,
                    "data": base64.b64encode(chunk).decode("ascii"),
                    "sha256": hashlib.sha256(chunk).hexdigest(),
                })
        messages.append({"protocol": "lbrain.capture.stream.v1", "type": "end", "stream_id": stream_id})
        framed = b"".join(
            struct.pack("=I", len(value)) + value
            for value in (json.dumps(message).encode("utf-8") for message in messages)
        )
        result = subprocess.run(
            [
                sys.executable,
                str(CAPTURE_NATIVE_HOST),
                "--root",
                str(root),
                "--staging-root",
                str(staging_root),
            ],
            input=framed,
            capture_output=True,
            check=False,
        )
        if len(result.stdout) < 4:
            return result, {}
        offset = 0
        output: dict[str, object] = {}
        while offset + 4 <= len(result.stdout):
            length = struct.unpack("=I", result.stdout[offset : offset + 4])[0]
            offset += 4
            output = json.loads(result.stdout[offset : offset + length])
            offset += length
        return result, output

    def run_browser_fixtures(self, chrome: Path, fixtures: list[Path]) -> list[dict[str, object]]:
        node_path = os.environ.get("LBRAIN_NODE_PATH")
        if not node_path:
            self.skipTest("LBRAIN_NODE_PATH is not configured for the optional real-browser fixture")
        script = (
            "const fs = require('fs');const { chromium } = require('playwright');"
            "(async () => {"
            "const browser = await chromium.launch({ headless: true, executablePath: process.argv[1] });"
            "const results = [];"
            "for (const uri of process.argv.slice(3)) {"
            "const page = await browser.newPage();"
            "let target=uri;if(uri.includes('youtube-fixture')){const body=fs.readFileSync(new URL(uri));"
            "await page.route('https://www.youtube.com/**',route=>route.fulfill({contentType:'text/html',body}));"
            "target='https://www.youtube.com/watch?v=abc'}"
            "if(uri.includes('x-single')){const body=fs.readFileSync(new URL(uri));"
            "await page.route('https://x.com/**',route=>route.fulfill({contentType:'text/html',body}));"
            "target='https://x.com/alice/status/900/photo/1'}"
            "if(uri.includes('x-missing')){const body=fs.readFileSync(new URL(uri));"
            "await page.route('https://x.com/**',route=>route.fulfill({contentType:'text/html',body}));"
            "target='https://x.com/alice/status/999'}"
            "if(uri.includes('x-marked-thread')){const body=fs.readFileSync(new URL(uri));"
            "await page.route('https://x.com/**',route=>route.fulfill({contentType:'text/html',body}));"
            "target='https://x.com/alice/status/100'}"
            "await page.goto(target, { waitUntil: 'domcontentloaded', timeout: 10000 });"
            "await page.addScriptTag({ path: process.argv[2] });"
            "const selection=uri.includes('selection-responsive');"
            "if(selection){await page.evaluate(()=>{const range=document.createRange();range.selectNodeContents(document.querySelector('article'));"
            "const selected=window.getSelection();selected.removeAllRanges();selected.addRange(range)})}"
            "results.push(await page.evaluate(scope => LBrainCapture.extract(scope), selection?'selection':'page'));"
            "await page.close();"
            "}"
            "console.log(JSON.stringify(results));"
            "await browser.close();"
            "})().catch(error => { console.error(error); process.exit(1); });"
        )
        result = subprocess.run(
            [
                "node",
                "-e",
                script,
                str(chrome),
                str(CAPTURE_EXTENSION / "extractor.js"),
                *(fixture.as_uri() for fixture in fixtures),
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
            env={**os.environ, "NODE_PATH": node_path},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

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
            self.assertTrue(contains_runtime_state('"next_cursor": "opaque-real-cursor-12345"'))
            self.assertFalse(
                contains_document_runtime_state(
                    "# The rise of Cursor: The $300M ARR AI tool that engineers cannot stop using"
                )
            )
            self.assertFalse(
                contains_document_runtime_state(
                    "### Referenced:\n\n"
                    "• The rise of Cursor: The $300M ARR AI tool that engineers can’t stop using "
                    "\\| Michael Truell (co-founder and CEO): "
                    "[https://www.lennysnewsletter.com/p/the-rise-of-cursor-michael-truell]"
                    "(https://www.lennysnewsletter.com/p/the-rise-of-cursor-michael-truell)"
                )
            )
            for heading, title, byline, url in (
                (
                    "References",
                    "Cursor: A practical guide for engineering teams",
                    "Jane Doe",
                    "https://example.com/guides/cursor",
                ),
                (
                    "See also",
                    "Working with Cursor: A field guide",
                    "Alex Rivera (editor)",
                    "https://docs.example.org/cursor/field-guide",
                ),
                (
                    "Further reading",
                    "Why Cursor: Lessons from an AI editor",
                    "LBrain Editorial Team",
                    "https://research.example.net/articles/cursor",
                ),
                (
                    "References",
                    "Cursor: A normal article slug",
                    "Jane Doe",
                    "https://example.com/the-rise-of-cursor-michael-truell",
                ),
            ):
                self.assertFalse(
                    contains_document_runtime_state(
                        f"### {heading}:\n\n"
                        f"- {title} \\| {byline}: [{url}]({url})"
                    )
                )
            self.assertTrue(
                contains_document_runtime_state(
                    "### References:\n\n"
                    "- The rise of Cursor: The $300M ARR AI tool that engineers cannot stop using "
                    "\\| opaque-real-cursor-12345: "
                    "[https://www.lennysnewsletter.com/p/the-rise-of-cursor-michael-truell]"
                    "(https://www.lennysnewsletter.com/p/the-rise-of-cursor-michael-truell)"
                )
            )
            self.assertTrue(
                contains_document_runtime_state(
                    "### References:\n\n"
                    "- The rise of Cursor: The $300M ARR AI tool that engineers cannot stop using "
                    "\\| Michael Truell (co-founder and CEO): "
                    "[https://www.lennysnewsletter.com/p/the-rise-of-cursor-michael-truell?%63ursor=opaque-real-cursor-12345]"
                    "(https://www.lennysnewsletter.com/p/the-rise-of-cursor-michael-truell?%63ursor=opaque-real-cursor-12345)"
                )
            )
            self.assertTrue(
                contains_document_runtime_state(
                    "### References:\n\n"
                    "- The rise of Cursor: "
                    "<span title=\"opaque-real-cursor-12345\">"
                    "The $300M ARR AI tool that engineers cannot stop using</span> "
                    "\\| Michael Truell (co-founder and CEO): "
                    "[https://www.lennysnewsletter.com/p/the-rise-of-cursor-michael-truell]"
                    "(https://www.lennysnewsletter.com/p/the-rise-of-cursor-michael-truell)"
                )
            )
            self.assertTrue(
                contains_document_runtime_state(
                    "### References:\n\n"
                    "- The rise of Cursor: The $300M ARR AI tool that engineers cannot stop using "
                    "\\| Michael Truell (co-founder and CEO): "
                    "[https://opaque-real-cursor-12345.invalid/state]"
                    "(https://opaque-real-cursor-12345.invalid/state)"
                )
            )
            for unsafe_url in (
                "https://example.com/%63ursor-guide",
                "https://example.com/cursor-guide?source=references",
                "https://example.com/cursor-guide#cursor",
                "https://xn--cursor-qza.example/reference",
                "https://foo.xn--cursor-qza.example/reference",
                "https://abcdefghijklmnop12345.example.com/guide",
                "https://example.com/abcdefghijklmnop12345",
                "https://123e4567-e89b-12d3-a456-426614174000.example.com/reference",
                "https://example.com/123e4567-e89b-12d3-a456-426614174000",
            ):
                self.assertTrue(
                    contains_document_runtime_state(
                        "### References:\n\n"
                        "- Cursor: A practical guide for engineering teams "
                        f"\\| Jane Doe: [{unsafe_url}]({unsafe_url})"
                    )
                )
            self.assertTrue(
                contains_document_runtime_state(
                    "### References:\n\n"
                    "- Cursor: A practical guide for engineering teams "
                    "\\| Jane Doe: [https://example.com/guides/cursor]"
                    "(https://example.com/guides/different)"
                )
            )
            for altered_citation in (
                "HTTPS://WWW.LENNYSNEWSLETTER.COM/P/THE-RISE-OF-CURSOR-MICHAEL-TRUELL",
                "https://www.lenny\u017fnewsletter.com/p/the-rise-of-cursor-michael-truell",
                "https://www.lennysnewsletter.com/p/the-r\u0131se-of-cursor-michael-truell",
            ):
                self.assertTrue(
                    contains_document_runtime_state(
                        "### References:\n\n"
                        "- The rise of Cursor: The $300M ARR AI tool that engineers cannot stop using "
                        "\\| Michael Truell (co-founder and CEO): "
                        f"[{altered_citation}]({altered_citation})"
                    )
                )
            self.assertTrue(
                contains_document_runtime_state(
                    "### References:\n\n"
                    "- The rise of Cursor: The $300M ARR AI tool that engineers cannot stop using "
                    "\\| private checkpoint opaque-real-cursor-12345 "
                    "\\| Michael Truell (co-founder and CEO): "
                    "[https://www.lennysnewsletter.com/p/the-rise-of-cursor-michael-truell]"
                    "(https://www.lennysnewsletter.com/p/the-rise-of-cursor-michael-truell)"
                )
            )
            self.assertTrue(
                contains_document_runtime_state(
                    "### References:\n\n"
                    "- <!--opaque-real-cursor-12345-->The rise of Cursor: "
                    "The $300M ARR AI tool that engineers cannot stop using "
                    "\\| Michael Truell (co-founder and CEO): "
                    "[https://www.lennysnewsletter.com/p/the-rise-of-cursor-michael-truell]"
                    "(https://www.lennysnewsletter.com/p/the-rise-of-cursor-michael-truell)"
                )
            )
            self.assertTrue(
                contains_document_runtime_state(
                    "The rise of Cursor: A field guide \\| Jane Doe: "
                    "[https://example.com/guides/cursor]"
                    "(https://example.com/guides/cursor)"
                )
            )
            self.assertTrue(
                contains_document_runtime_state(
                    "### References:\n\n"
                    "- Cursor: A field guide \\| current value is alpha beta gamma: "
                    "[https://example.com/guides/cursor]"
                    "(https://example.com/guides/cursor)"
                )
            )
            self.assertTrue(contains_document_runtime_state("Continue with Cursor: opaque"))
            self.assertTrue(contains_document_runtime_state("Resume using Cursor: next"))
            self.assertTrue(
                contains_document_runtime_state(
                    "- Continue with Cursor: opaque token value abc"
                )
            )
            self.assertTrue(
                contains_document_runtime_state(
                    "### References:\n\n"
                    "- Continue with Cursor: opaque token value abc "
                    "\\| Worker: [state](https://example.invalid/state)"
                )
            )
            for runtime_value in (
                "opaque",
                "opaque-real-cursor-12345",
                "alpha beta gamma delta",
            ):
                self.assertTrue(
                    contains_document_runtime_state(
                        "### References:\n\n"
                        f"- Runtime state of Cursor: {runtime_value} "
                        "\\| Michael Truell: [article](https://example.invalid/cursor)"
                    )
                )
            self.assertTrue(
                contains_document_runtime_state(
                    "### References:\n\n"
                    "- The stored value of Cursor: alpha beta gamma delta epsilon "
                    "\\| Michael Truell: "
                    "[https://example.invalid/cursor](https://example.invalid/cursor)"
                )
            )
            for runtime_context in ("current value", "active state", "checkpoint value"):
                self.assertTrue(
                    contains_document_runtime_state(
                        "### References:\n\n"
                        f"- The {runtime_context} of Cursor: alpha beta gamma delta epsilon "
                        "\\| Michael Truell: "
                        "[https://example.invalid/cursor](https://example.invalid/cursor)"
                    )
                )
            for runtime_value in (
                "current value is alpha beta gamma",
                "active value is alpha beta gamma",
                "saved token is alpha beta gamma",
                "continuation value is alpha beta gamma",
                "last checkpoint is alpha beta gamma",
            ):
                self.assertTrue(
                    contains_document_runtime_state(
                        "### References:\n\n"
                        f"- The rise of Cursor: {runtime_value} "
                        "\\| Michael Truell: "
                        "[https://example.invalid/cursor](https://example.invalid/cursor)"
                    )
                )
            self.assertTrue(
                contains_document_runtime_state(
                    "### References:\n\n"
                    "- The rise of Cursor: opaque\\| Michael Truell: "
                    "[https://example.invalid/cursor](https://example.invalid/cursor)"
                )
            )
            self.assertFalse(
                contains_document_runtime_state(
                    "# Page 2 about Cursor: How an AI editor changed software"
                )
            )
            self.assertFalse(
                contains_document_runtime_state(
                    '<h2><span>The rise of </span><a href="https://example.invalid/cursor">Cursor</a>: '
                    "The $300M ARR AI tool that engineers cannot stop using</h2>"
                )
            )
            self.assertFalse(
                contains_document_runtime_state(
                    "<h2>The rise of Cursor: The $300M ARR AI tool that engineers cannot stop using</h2>\n"
                    "<div>Article body.</div>"
                )
            )
            self.assertFalse(
                contains_document_runtime_state(
                    "<h2>The rise of\nCursor: The $300M ARR AI tool that engineers cannot stop using</h2>"
                )
            )
            self.assertFalse(
                contains_document_runtime_state("# Cursor: How an AI editor changed software")
            )
            self.assertFalse(
                contains_document_runtime_state("<h2>Cursor: The future of coding</h2>")
            )
            self.assertFalse(
                contains_document_runtime_state("# cursor: Token economics for AI products")
            )
            self.assertTrue(
                contains_document_runtime_state("# Cursor: opaque-real-cursor-12345")
            )
            self.assertTrue(
                contains_document_runtime_state("<h2>Cursor: opaque-real-cursor-12345</h2>")
            )
            self.assertTrue(
                contains_document_runtime_state("# Cursor: 1234567890123456")
            )
            self.assertTrue(
                contains_document_runtime_state("# Cursor: abcDEF1234567890")
            )
            self.assertTrue(
                contains_document_runtime_state("# Cursor: eyJwYWdlIjoyfQ")
            )
            self.assertTrue(
                contains_document_runtime_state(
                    "<h2>Cursor: <span>eyJw</span><span>YWdlIjoyfQ</span></h2>"
                )
            )
            self.assertTrue(
                contains_document_runtime_state("# Cursor: eyJw<!-- split -->YWdlIjoyfQ")
            )
            self.assertTrue(
                contains_document_runtime_state("<h2>Cursor: eyJw<wbr>YWdlIjoyfQ</h2>")
            )
            self.assertTrue(
                contains_document_runtime_state("<h2>Cursor: <bdi>eyJw</bdi>YWdlIjoyfQ</h2>")
            )
            self.assertTrue(
                contains_document_runtime_state("<h2>Cur<span>sor</span>: eyJwYWdlIjoyfQ</h2>")
            )
            self.assertTrue(
                contains_document_runtime_state("<h2>Cur<!-- split -->sor: opaque-real-cursor-12345</h2>")
            )
            self.assertFalse(
                contains_document_runtime_state("<h2>Cur<span>sor</span>: How an AI editor changed software</h2>")
            )
            self.assertTrue(
                contains_document_runtime_state("# Cursor: resume from shard seven after item forty two")
            )
            self.assertTrue(contains_document_runtime_state("# Cursor: page 2"))
            self.assertTrue(contains_document_runtime_state("# Cursor: page: 2"))
            self.assertTrue(contains_document_runtime_state("# Cursor: page=2"))
            self.assertTrue(
                contains_document_runtime_state("# Cursor: start after item forty two")
            )
            self.assertTrue(
                contains_document_runtime_state("Cursor: opaque-real-cursor-12345")
            )
            self.assertTrue(
                contains_document_runtime_state(
                    "Current pagination Cursor: opaque-real-cursor-12345"
                )
            )
            self.assertTrue(
                contains_document_runtime_state(
                    "Current pagination state Cursor: opaque-real-cursor-12345"
                )
            )
            self.assertTrue(
                contains_document_runtime_state(
                    "Current pagination state Cursor: resume from shard seven after item forty two"
                )
            )
            self.assertTrue(
                contains_document_runtime_state(
                    "The stored pagination Cursor: token value is opaque-real-cursor-12345 for next request"
                )
            )
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

    def test_capture_create_saves_one_inbox_original_and_deduplicates_retries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            payload: dict[str, object] = {
                "destination": "inbox",
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
            self.assertEqual(captured["status"], "saved")
            self.assertEqual(len(captured["affected_paths"]), 2)
            relative = str(captured["target"])
            self.assertTrue(relative.startswith("Inbox/Captures/"))
            capture = root / relative
            capture_text = capture.read_text(encoding="utf-8")
            self.assertIn("type: note", capture_text)
            self.assertIn("capture_version: 1", capture_text)
            self.assertIn("weaving: pending", capture_text)
            self.assertIn("media_manifest:", capture_text)
            self.assertIn("https://example.invalid/writing-guide", capture_text)
            self.assertIn("Prefer concrete verbs", capture_text)
            self.assertIn("Consider this for my writing Skill.", capture_text)

            repeat_result, repeated = self.run_capture_operation(root, "capture.create", payload)
            self.assertEqual(repeat_result.returncode, 0, repeat_result.stderr)
            self.assertEqual(repeated["status"], "already_saved")
            self.assertEqual(repeated["target"], relative)
            matching = list((root / "Inbox/Captures").glob("*Synthetic-Writing-Guide*.md"))
            self.assertEqual(matching, [capture])

            changed_result, changed = self.run_capture_operation(
                root,
                "capture.create",
                {**payload, "content": "A changed original becomes an immutable second version."},
            )
            self.assertEqual(changed_result.returncode, 0, changed_result.stderr)
            self.assertEqual(changed["status"], "new_version")
            self.assertEqual(changed["version"], 2)
            self.assertNotEqual(changed["target"], relative)

            rejected_result, rejected = self.run_capture_operation(
                root, "capture.create", {**payload, "destination": "source"}
            )
            self.assertNotEqual(rejected_result.returncode, 0)
            self.assertEqual(rejected["status"], "failed")
            reference_result, reference = self.run_capture_operation(
                root,
                "capture.create",
                {
                    "destination": "inbox",
                    "title": "URL-only Reference <!-- lbrain:capture:end -->",
                    "summary": "A source retained before full extraction.",
                    "origin": "https://example.invalid/url-only-reference",
                },
            )
            self.assertEqual(reference_result.returncode, 0, reference_result.stderr)
            self.assertEqual(reference["status"], "saved")
            reference_text = (root / str(reference["target"])).read_text(encoding="utf-8")
            self.assertIn(
                "[https://example.invalid/url-only-reference](https://example.invalid/url-only-reference)",
                reference_text,
            )
            self.assertEqual(reference_text.count("<!-- lbrain:capture:end -->"), 1)

    def test_native_host_saves_idempotent_and_versioned_inbox_bundles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Capture Test"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "capture@example.invalid"],
                check=True,
            )
            payload: dict[str, object] = {
                "schema": "lbrain.capture.v1",
                "title": "Cursor: How an AI editor changed software",
                "summary": "A rendered article saved from the authenticated browser tab. --- Example Author",
                "origin": "https://example.invalid/rendered-article",
                "scope": "page",
                "author": "Example Author",
                "published_at": "2026-08-11T09:00:00+08:00",
                "content_markdown": "# Cursor: How an AI editor changed software\n\nThe first saved body.",
                "extraction_status": "complete",
                "assets": [],
            }
            result, saved = self.run_capture_native_host(root, payload)

            self.assertEqual(result.returncode, 0, (result.stderr.decode(), saved))
            self.assertEqual(saved["status"], "saved")
            self.assertRegex(str(saved["operation_id"]), r"^[0-9a-f]{20}$")
            self.assertEqual(saved["version"], 1)
            target = str(saved["target"])
            self.assertTrue(target.startswith("Inbox/Captures/"))
            note = root / target
            text = note.read_text(encoding="utf-8")
            self.assertIn("capture_version: 1", text)
            self.assertIn("weaving: pending", text)
            self.assertIn("- Author: Example Author", text)
            self.assertIn("- Published: 2026-08-11T09:00:00+08:00", text)
            self.assertIn("The first saved body.", text)
            self.assertTrue(str(saved["open_uri"]).startswith("obsidian://open?path="))
            capture_id = str(saved["capture_id"])
            manifest = root / f"Inbox/Captures/_assets/{capture_id}/v1/manifest.json"
            self.assertTrue(manifest.is_file())
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["assets"], [])
            self.assertTrue(dict(saved["git"])["committed"])
            self.assertIn(
                "capture: Cursor: How an AI editor changed software",
                subprocess.run(
                    ["git", "-C", str(root), "log", "-1", "--format=%s"],
                    text=True,
                    capture_output=True,
                    check=True,
                ).stdout,
            )

            repeat_result, repeated = self.run_capture_native_host(root, payload)
            self.assertEqual(repeat_result.returncode, 0, repeat_result.stderr.decode())
            self.assertEqual(repeated["status"], "already_saved")
            self.assertEqual(repeated["target"], target)
            self.assertEqual(
                subprocess.run(
                    ["git", "-C", str(root), "rev-list", "--count", "HEAD"],
                    text=True,
                    capture_output=True,
                    check=True,
                ).stdout.strip(),
                "1",
            )

            changed = {**payload, "content_markdown": "# Cursor: How an AI editor changed software\n\nA changed second body."}
            version_result, versioned = self.run_capture_native_host(root, changed)
            self.assertEqual(version_result.returncode, 0, (version_result.stderr.decode(), versioned))
            self.assertEqual(versioned["status"], "new_version")
            self.assertEqual(versioned["version"], 2)
            self.assertNotEqual(versioned["target"], target)
            self.assertIn(f"previous_version: {json.dumps(target)}", (root / str(versioned["target"])).read_text())
            self.assertIn("The first saved body.", note.read_text(encoding="utf-8"))

    def test_native_host_rolls_back_a_bundle_that_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            result, failed = self.run_capture_native_host(
                root,
                {
                    "schema": "lbrain.capture.v1",
                    "title": "Invalid Rendered Article",
                    "summary": "A synthetic capture that must roll back.",
                    "origin": "https://example.invalid/invalid-rendered-article",
                    "scope": "page",
                    "content_markdown": "A missing internal link: [[Does-Not-Exist]].",
                    "extraction_status": "complete",
                    "assets": [],
                },
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["affected_paths"], [])
            self.assertEqual(list((root / "Inbox/Captures").glob("*.md")), [root / "Inbox/Captures/README.md"])
            self.assertFalse(list((root / "Inbox/Captures/_assets").glob("*")))

    def test_native_host_preserves_only_manifest_verified_staged_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.copy_repo(base)
            staging = base / "staging"
            staging.mkdir()
            media = b"synthetic-image-bytes"
            (staging / "cover.png").write_bytes(media)
            payload: dict[str, object] = {
                "schema": "lbrain.capture.v1",
                "title": "Article With Media",
                "summary": "A rendered article with one staged image.",
                "origin": "https://example.invalid/article-with-media",
                "scope": "page",
                "content_markdown": "An article with ![Cover](lbrain-asset://cover).",
                "extraction_status": "complete",
                "assets": [
                    {
                        "name": "images/cover.png",
                        "staged_name": "cover.png",
                        "placeholder": "lbrain-asset://cover",
                        "media_type": "image/png",
                    }
                ],
            }

            saved_result, saved = self.run_capture_native_host(root, payload, staging)

            self.assertEqual(saved_result.returncode, 0, (saved_result.stderr.decode(), saved))
            self.assertFalse(dict(saved["git"])["committed"])
            self.assertIn("Git repository is unavailable", str(dict(saved["git"])["warning"]))
            capture_id = str(saved["capture_id"])
            preserved = root / f"Inbox/Captures/_assets/{capture_id}/v1/files/images/cover.png"
            self.assertEqual(preserved.read_bytes(), media)
            manifest = json.loads(
                (root / f"Inbox/Captures/_assets/{capture_id}/v1/manifest.json").read_text()
            )
            self.assertEqual(manifest["assets"][0]["sha256"], hashlib.sha256(media).hexdigest())
            note = (root / str(saved["target"])).read_text(encoding="utf-8")
            self.assertIn(
                f"![Cover](_assets/{capture_id}/v1/files/images/cover.png)",
                note,
            )
            self.assertNotIn("lbrain-asset://", note)

            corrupt = {
                **payload,
                "origin": "https://example.invalid/corrupt-media",
                "assets": [
                    {
                        **dict(payload["assets"][0]),
                        "sha256": "0" * 64,
                        "size": len(media),
                    }
                ],
            }
            failed_result, failed = self.run_capture_native_host(root, corrupt, staging)
            self.assertNotEqual(failed_result.returncode, 0)
            self.assertEqual(failed["status"], "failed")
            self.assertFalse(list((root / "Inbox/Captures").glob("*corrupt-media*.md")))

            injected_result, injected = self.run_capture_native_host(
                root,
                {
                    **payload,
                    "origin": "https://example.invalid/injected-asset-name",
                    "assets": [{
                        **dict(payload["assets"][0]),
                        "name": "images/<!-- lbrain:capture:end -->.png",
                    }],
                },
                staging,
            )
            self.assertNotEqual(injected_result.returncode, 0)
            self.assertEqual(injected["status"], "failed")

            readable_result, readable = self.run_capture_native_host(
                root,
                {
                    **payload,
                    "origin": "https://example.invalid/readable-asset-name",
                    "assets": [{
                        **dict(payload["assets"][0]),
                        "name": "documents/2026 年度报告 #1).pdf",
                    }],
                },
                staging,
            )
            self.assertEqual(readable_result.returncode, 0, (readable_result.stderr.decode(), readable))
            self.assertTrue(
                (root / f"Inbox/Captures/_assets/{readable['capture_id']}/v1/files/documents/2026 年度报告 #1).pdf").is_file()
            )
            readable_note = (root / str(readable["target"])).read_text(encoding="utf-8")
            self.assertIn("documents/2026%20%E5%B9%B4%E5%BA%A6%E6%8A%A5%E5%91%8A%20%231%29.pdf", readable_note)

            long_title_result, long_title = self.run_capture_native_host(
                root,
                {**payload, "origin": "https://example.invalid/long-title", "title": "长标题" * 120},
                staging,
            )
            self.assertEqual(long_title_result.returncode, 0, (long_title_result.stderr.decode(), long_title))
            self.assertLessEqual(max(len(part.encode()) for part in Path(str(long_title["target"])).parts), 200)

            overlong_result, overlong = self.run_capture_native_host(
                root,
                {
                    **payload,
                    "origin": "https://example.invalid/overlong-asset",
                    "assets": [{**dict(payload["assets"][0]), "name": f"images/{'a' * 220}.png"}],
                },
                staging,
            )
            self.assertNotEqual(overlong_result.returncode, 0)
            self.assertEqual(overlong["status"], "failed")

    def test_capture_bundle_localizes_prefix_sharing_asset_placeholders(self) -> None:
        spec = importlib.util.spec_from_file_location("capture_operations_placeholders", CAPTURE_OPERATIONS)
        assert spec and spec.loader
        operations = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(operations)
        capture_id = "a" * 64
        rendered = operations.render_bundle(
            "Prefix assets",
            "Distinct placeholders must remain distinct.",
            "https://example.invalid/prefix-assets",
            "page",
            (
                "![One](lbrain-asset://asset-1)\n\n"
                "![Ten](lbrain-asset://asset-10)\n\n"
                "Literal lbrain-asset://asset-100\n\n"
                "[Crafted](lbrain-asset://asset-1/../../other.md)"
            ),
            "",
            "",
            "complete",
            capture_id,
            "b" * 64,
            "c" * 64,
            1,
            f"Inbox/Captures/_assets/{capture_id}/v1/manifest.json",
            [
                {
                    "name": "images/one.png",
                    "placeholder": "lbrain-asset://asset-1",
                },
                {
                    "name": "images/ten.png",
                    "placeholder": "lbrain-asset://asset-10",
                },
            ],
            "",
            "",
        )
        self.assertIn(f"![One](_assets/{capture_id}/v1/files/images/one.png)", rendered)
        self.assertIn(f"![Ten](_assets/{capture_id}/v1/files/images/ten.png)", rendered)
        self.assertNotIn("one.png0", rendered)
        self.assertIn("Literal lbrain-asset://asset-100", rendered)
        self.assertIn("[Crafted](lbrain-asset://asset-1/../../other.md)", rendered)

    def test_capture_frontmatter_accepts_a_closing_delimiter_at_eof(self) -> None:
        spec = importlib.util.spec_from_file_location("capture_operations_frontmatter", CAPTURE_OPERATIONS)
        assert spec and spec.loader
        operations = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(operations)
        with tempfile.TemporaryDirectory() as temporary:
            note = Path(temporary) / "legacy.md"
            note.write_text("---\ncapture_id: " + "a" * 64 + "\n---", encoding="utf-8")
            self.assertEqual(operations.capture_frontmatter(note), ["capture_id: " + "a" * 64])

    def test_native_stream_saves_a_generic_page_as_html_without_download_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.copy_repo(base)
            staging = base / "staging"
            staging.mkdir()
            image = b"\x89PNG\r\n\x1a\nsynthetic PNG bytes"
            larger_image = b"\x89PNG\r\n\x1a\nsecond synthetic PNG bytes"
            late_image = b"\x89PNG\r\n\x1a\nlate PNG bytes"
            report = b"PK synthetic document bytes"
            disguised_video = b"FLV\x01 disguised video bytes"
            boundary = "lbrain-boundary"
            archive = (
                "MIME-Version: 1.0\r\n"
                f'Content-Type: multipart/related; boundary="{boundary}"\r\n\r\n'
                f"--{boundary}\r\nContent-Type: text/html; charset=utf-8\r\n"
                "Content-Location: https://alpha.example.invalid/\r\n\r\n"
                "<html><body><main><h1>Alpha School</h1></main></body></html>\r\n"
                f"--{boundary}\r\nContent-Type: image/png\r\nContent-Transfer-Encoding: base64\r\n"
                "Content-Location: https://alpha.example.invalid/hero.png\r\n\r\n"
                f"{base64.b64encode(image).decode('ascii')}\r\n"
                f"--{boundary}\r\nContent-Type: image/png\r\nContent-Transfer-Encoding: base64\r\n"
                "Content-Location: https://alpha.example.invalid/hero.png?size=2\r\n\r\n"
                f"{base64.b64encode(larger_image).decode('ascii')}\r\n"
                f"--{boundary}\r\nContent-Type: video/mp4\r\nContent-Transfer-Encoding: base64\r\n"
                "Content-Location: https://alpha.example.invalid/hero.mp4\r\n\r\n"
                f"{base64.b64encode(b'video must not persist').decode('ascii')}\r\n"
                f"--{boundary}--\r\n"
            ).encode("ascii")
            payload: dict[str, object] = {
                "schema": "lbrain.capture.v1",
                "title": "Alpha School",
                "summary": "The rendered homepage.",
                "origin": "https://alpha.example.invalid/",
                "scope": "page",
                "author": "",
                "published_at": "",
                "capture_kind": "html",
                "content_markdown": (
                    "[打开保存的 HTML 快照](lbrain-asset://html-snapshot)\n\n"
                    "- 原页面：[https://alpha.example.invalid/](https://alpha.example.invalid/)"
                ),
                "snapshot_html": (
                    "<!doctype html><html><head><meta charset=\"utf-8\"></head><body>"
                    "<main><h1>Alpha School</h1><img src=\"https://alpha.example.invalid/hero.png\"></main>"
                    "<img src=\"https://alpha.example.invalid/hero.png?size=2\">"
                    "<a href=\"https://alpha.example.invalid/report.docx?download=1&amp;source=home\">Report</a>"
                    "<audio src=\"https://alpha.example.invalid/lesson.mp3\"></audio>"
                    "<svg><image href=\"https://alpha.example.invalid/chart.svg?signature=fixture\"></image></svg>"
                    "</body></html>"
                ),
                "extraction_status": "complete",
                "remote_assets": [{
                    "id": "hero",
                    "url": "https://alpha.example.invalid/hero.png",
                    "name": "images/001-hero",
                    "media_type": "image/png",
                }, {
                    "id": "hero-large",
                    "url": "https://alpha.example.invalid/hero.png?size=2",
                    "name": "images/002-hero-large.png",
                    "media_type": "image/png",
                }, {
                    "id": "report",
                    "url": "https://alpha.example.invalid/report.docx?download=1&source=home",
                    "name": "documents/report.docx",
                    "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                }, {
                    "id": "disguised-video",
                    "url": "https://alpha.example.invalid/hero.mp4",
                    "name": "documents/hero.bin",
                    "media_type": "application/octet-stream",
                }, {
                    "id": "disguised-flv",
                    "url": "https://alpha.example.invalid/lesson.bin",
                    "name": "documents/lesson.bin",
                    "media_type": "application/octet-stream",
                }, {
                    "id": "missing-audio",
                    "url": "https://alpha.example.invalid/lesson.mp3",
                    "name": "audio/lesson.mp3",
                    "media_type": "audio/mpeg",
                }, {
                    "id": "missing-svg",
                    "url": "https://alpha.example.invalid/chart.svg?signature=fixture",
                    "name": "images/chart.svg",
                    "media_type": "image/svg+xml",
                }],
                "assets": [],
            }
            original_source_content = f'{payload["content_markdown"]}\0{payload["snapshot_html"]}'
            source_identity = "\0".join((
                str(payload["title"]), "", "", original_source_content
            ))
            payload["source_content_markdown"] = original_source_content
            payload["source_content_hash"] = hashlib.sha256(source_identity.encode()).hexdigest()

            result, saved = self.run_capture_native_stream(
                root,
                payload,
                archive,
                "mhtml",
                staging,
                {"report": report, "disguised-flv": disguised_video},
            )

            self.assertEqual(result.returncode, 0, (result.stderr.decode(), saved))
            self.assertEqual(saved["status"], "partial")
            capture_id = str(saved["capture_id"])
            files = root / f"Inbox/Captures/_assets/{capture_id}/v1/files"
            self.assertEqual((files / "images/001-hero.png").read_bytes(), image)
            self.assertEqual((files / "images/002-hero-large.png").read_bytes(), larger_image)
            self.assertEqual((files / "documents/report.docx").read_bytes(), report)
            html = (files / "snapshot/page.html").read_text(encoding="utf-8")
            self.assertIn("../images/001-hero.png", html)
            self.assertIn("../images/002-hero-large.png", html)
            self.assertNotIn("../images/001-hero.png?size=2", html)
            self.assertIn("../documents/report.docx", html)
            self.assertNotIn("https://alpha.example.invalid/hero.png", html)
            self.assertNotIn("report.docx?download=1", html)
            self.assertNotIn("https://alpha.example.invalid/lesson.mp3", html)
            self.assertNotIn("https://alpha.example.invalid/chart.svg", html)
            self.assertFalse(list(files.rglob("*.mp4")))
            self.assertFalse((files / "documents/lesson.bin").exists())
            note = (root / str(saved["target"])).read_text(encoding="utf-8")
            self.assertIn("snapshot/page.html", note)
            self.assertNotIn("signature=fixture", note)
            self.assertIn("Media could not be preserved: missing-svg", note)
            self.assertEqual(list(staging.iterdir()), [])

            overlap_payload = {
                **payload,
                "origin": "https://alpha.example.invalid/overlap",
                "content_markdown": (
                    "![Small](https://alpha.example.invalid/hero.png)\n\n"
                    "![Large](https://alpha.example.invalid/hero.png?size=missing)\n\n"
                    "[Download variant](https://alpha.example.invalid/hero.png?download=1)"
                ),
                "snapshot_html": (
                    '<img src="https://alpha.example.invalid/hero.png">'
                    '<img src="https://alpha.example.invalid/hero.png?size=missing">'
                    '<a href="https://redirect.example.invalid/?next=https://alpha.example.invalid/hero.png">Redirect</a>'
                    '<a href="https://alpha.example.invalid/hero.png?download=1">Download</a>'
                ),
                "remote_assets": [{
                    "id": "small",
                    "url": "https://alpha.example.invalid/hero.png",
                    "name": "images/small.png",
                    "media_type": "image/png",
                }, {
                    "id": "large",
                    "url": "https://alpha.example.invalid/hero.png?size=missing",
                    "name": "images/large.png",
                    "media_type": "image/png",
                }],
            }
            overlap_payload.pop("source_content_hash", None)
            overlap_payload.pop("source_content_markdown", None)
            overlap_result, overlap = self.run_capture_native_stream(
                root, overlap_payload, archive, "mhtml", staging
            )
            self.assertEqual(overlap_result.returncode, 0, (overlap_result.stderr.decode(), overlap))
            self.assertEqual(overlap["status"], "partial")
            overlap_files = root / f"Inbox/Captures/_assets/{overlap['capture_id']}/v1/files"
            overlap_html = (overlap_files / "snapshot/page.html").read_text(encoding="utf-8")
            self.assertIn("../images/small.png", overlap_html)
            self.assertIn("about:blank#lbrain-missing-", overlap_html)
            self.assertNotIn("../images/small.png?size=missing", overlap_html)
            self.assertIn("?next=https://alpha.example.invalid/hero.png", overlap_html)
            self.assertIn("https://alpha.example.invalid/hero.png?download=1", overlap_html)
            overlap_note = (root / str(overlap["target"])).read_text(encoding="utf-8")
            self.assertNotIn("lbrain-asset://small?size=missing", overlap_note)
            self.assertIn("https://alpha.example.invalid/hero.png?download=1", overlap_note)

            late_source = "https://alpha.example.invalid/late.png"
            payload["origin"] = "https://alpha.example.invalid/recovery"
            payload["content_markdown"] = (
                "[打开保存的 HTML 快照](lbrain-asset://html-snapshot)\n\n"
                "- 原页面：[https://alpha.example.invalid/recovery](https://alpha.example.invalid/recovery)"
            )
            payload["snapshot_html"] = str(payload["snapshot_html"]).replace(
                "</main>", f'<img src="{late_source}"></main>'
            )
            cast_assets = list(payload["remote_assets"])
            cast_assets.append({
                "id": "late",
                "url": late_source,
                "name": "images/002-late.png",
                "media_type": "image/png",
            })
            payload["remote_assets"] = cast_assets
            source_content = f'{payload["content_markdown"]}\0{payload["snapshot_html"]}'
            payload["source_content_markdown"] = source_content
            payload["source_content_hash"] = hashlib.sha256(
                "\0".join((str(payload["title"]), "", "", source_content)).encode()
            ).hexdigest()
            first_missing, first_receipt = self.run_capture_native_stream(
                root, payload, archive, "mhtml", staging, {"report": report, "disguised-flv": disguised_video}
            )
            self.assertEqual(first_missing.returncode, 0, (first_missing.stderr.decode(), first_receipt))
            self.assertEqual(first_receipt["status"], "partial")
            self.assertEqual(first_receipt["version"], 1)
            payload["recovery_target"] = first_receipt["target"]
            payload["expected_hash"] = first_receipt["expected_hash"]
            recovered_archive = archive.replace(
                f"--{boundary}--\r\n".encode(),
                (
                    f"--{boundary}\r\nContent-Type: image/png\r\nContent-Transfer-Encoding: base64\r\n"
                    f"Content-Location: {late_source}\r\n\r\n"
                    f"{base64.b64encode(late_image).decode('ascii')}\r\n--{boundary}--\r\n"
                ).encode("ascii"),
            )
            first_files = root / f"Inbox/Captures/_assets/{first_receipt['capture_id']}/v1/files"
            first_snapshot = first_files / "snapshot/page.html"
            original_snapshot = first_snapshot.read_bytes()
            first_snapshot.write_bytes(original_snapshot + b"\n<!-- user edit -->\n")
            conflict_result, conflict = self.run_capture_native_stream(
                root, payload, recovered_archive, "mhtml", staging, {"report": report, "disguised-flv": disguised_video}
            )
            self.assertNotEqual(conflict_result.returncode, 0)
            self.assertEqual(conflict["status"], "failed")
            self.assertTrue(first_snapshot.read_bytes().endswith(b"<!-- user edit -->\n"))
            first_snapshot.write_bytes(original_snapshot)
            recovered_result, recovered = self.run_capture_native_stream(
                root, payload, recovered_archive, "mhtml", staging, {"report": report, "disguised-flv": disguised_video}
            )
            self.assertEqual(recovered_result.returncode, 0, (recovered_result.stderr.decode(), recovered))
            self.assertEqual(recovered["target"], first_receipt["target"])
            self.assertEqual(recovered["version"], first_receipt["version"])
            recovered_files = root / f"Inbox/Captures/_assets/{recovered['capture_id']}/v{recovered['version']}/files"
            self.assertTrue((recovered_files / "images/002-late.png").is_file())
            self.assertIn("../images/002-late.png", (recovered_files / "snapshot/page.html").read_text(encoding="utf-8"))

            rotating_origin = "https://alpha.example.invalid/rotating-recovery"
            first_url, second_url = (
                "https://alpha.example.invalid/first.png",
                "https://alpha.example.invalid/second.png",
            )
            rotating_payload = {
                "schema": "lbrain.capture.v1",
                "title": "Rotating recovery",
                "summary": "Assets that succeed on different attempts remain linked.",
                "origin": rotating_origin,
                "scope": "page",
                "capture_kind": "html",
                "content_markdown": (
                    "[HTML](lbrain-asset://html-snapshot)\n\n"
                    f"[Redirect](https://redirect.example.invalid/?next={first_url})"
                ),
                "snapshot_html": f'<img src="{first_url}"><img src="{second_url}">',
                "extraction_status": "complete",
                "remote_assets": [
                    {"id": "first", "url": first_url, "name": "images/first.png", "media_type": "image/png"},
                    {"id": "second", "url": second_url, "name": "images/second.png", "media_type": "image/png"},
                ],
                "assets": [],
            }
            rotating_source = (
                f'{rotating_payload["content_markdown"]}\0{rotating_payload["snapshot_html"]}'
            )
            rotating_payload["source_content_markdown"] = rotating_source
            rotating_payload["source_content_hash"] = hashlib.sha256(
                "\0".join((
                    str(rotating_payload["title"]), "", "", rotating_source
                )).encode()
            ).hexdigest()

            def image_archive(source: str, body: bytes) -> bytes:
                return (
                    "MIME-Version: 1.0\r\n"
                    f'Content-Type: multipart/related; boundary="{boundary}"\r\n\r\n'
                    f"--{boundary}\r\nContent-Type: image/png\r\nContent-Transfer-Encoding: base64\r\n"
                    f"Content-Location: {source}\r\n\r\n"
                    f"{base64.b64encode(body).decode('ascii')}\r\n--{boundary}--\r\n"
                ).encode("ascii")

            rotating_first_result, rotating_first = self.run_capture_native_stream(
                root, rotating_payload, image_archive(first_url, image), "mhtml", staging
            )
            self.assertEqual(rotating_first_result.returncode, 0, rotating_first)
            self.assertEqual(rotating_first["status"], "partial")
            rotating_payload.update({
                "recovery_target": rotating_first["target"],
                "expected_hash": rotating_first["expected_hash"],
            })
            rotating_retry_result, rotating_retry = self.run_capture_native_stream(
                root, rotating_payload, image_archive(second_url, late_image), "mhtml", staging
            )
            self.assertEqual(rotating_retry_result.returncode, 0, rotating_retry)
            self.assertEqual(rotating_retry["status"], "saved")
            rotating_files = root / (
                f"Inbox/Captures/_assets/{rotating_retry['capture_id']}/v1/files"
            )
            rotating_html = (rotating_files / "snapshot/page.html").read_text(encoding="utf-8")
            self.assertIn("../images/first.png", rotating_html)
            self.assertIn("../images/second.png", rotating_html)
            self.assertNotIn("lbrain-missing", rotating_html)
            rotating_note = (root / str(rotating_retry["target"])).read_text(encoding="utf-8")
            self.assertIn(f"https://redirect.example.invalid/?next={first_url}", rotating_note)
            self.assertNotIn("Media could not be preserved", rotating_note)

            encoded_source = "https://alpha.example.invalid/a%2Fb.png"
            slash_archive = (
                "MIME-Version: 1.0\r\n"
                f'Content-Type: multipart/related; boundary="{boundary}"\r\n\r\n'
                f"--{boundary}\r\nContent-Type: image/png\r\nContent-Transfer-Encoding: base64\r\n"
                "Content-Location: https://alpha.example.invalid/a/b.png\r\n\r\n"
                f"{base64.b64encode(image).decode('ascii')}\r\n--{boundary}--\r\n"
            ).encode("ascii")
            collision_result, collision = self.run_capture_native_stream(
                root,
                {
                    "schema": "lbrain.capture.v1",
                    "title": "Distinct encoded asset",
                    "summary": "Reserved URL escapes remain distinct.",
                    "origin": "https://alpha.example.invalid/encoded-asset",
                    "scope": "page",
                    "content_markdown": f"![Asset]({encoded_source})",
                    "capture_kind": "article",
                    "extraction_status": "complete",
                    "remote_assets": [{
                        "id": "encoded",
                        "url": encoded_source,
                        "name": "images/encoded.png",
                        "media_type": "image/png",
                    }],
                    "assets": [],
                },
                slash_archive,
                "mhtml",
                staging,
            )
            self.assertEqual(collision_result.returncode, 0, (collision_result.stderr.decode(), collision))
            self.assertEqual(collision["status"], "partial")
            collision_files = root / f"Inbox/Captures/_assets/{collision['capture_id']}/v1/files"
            self.assertFalse((collision_files / "images/encoded.png").exists())

    def test_native_stream_rejects_disclosure_inside_html_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.copy_repo(base)
            staging = base / "staging"
            staging.mkdir()
            payload = {
                "schema": "lbrain.capture.v1",
                "title": "Unsafe snapshot",
                "summary": "A generic page.",
                "origin": "https://example.invalid/unsafe",
                "scope": "page",
                "content_markdown": "[HTML](lbrain-asset://html-snapshot)",
                "snapshot_html": '<main>api_key="fixture-hardcoded-secret-12345"</main>',
                "capture_kind": "html",
                "extraction_status": "complete",
                "remote_assets": [],
                "assets": [],
            }
            result, rejected = self.run_capture_native_stream(
                root, payload, b"", "none", staging
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(rejected["status"], "failed")
            self.assertFalse(list((root / "Inbox/Captures").glob("*Unsafe*")))

            payload["origin"] = "https://example.invalid/unsafe-svg"
            payload["snapshot_html"] = ""
            payload["content_markdown"] = "![SVG](lbrain-asset://unsafe-svg)"
            payload["remote_assets"] = [{
                "id": "unsafe-svg",
                "url": "https://example.invalid/unsafe.svg",
                "name": "images/unsafe.svg",
                "media_type": "image/svg+xml",
            }]
            svg_result, svg_rejected = self.run_capture_native_stream(
                root,
                payload,
                b"",
                "none",
                staging,
                {"unsafe-svg": b'<svg xmlns="http://www.w3.org/2000/svg"><text api_key="fixture-hardcoded-secret-12345">x</text></svg>'},
            )
            self.assertNotEqual(svg_result.returncode, 0)
            self.assertEqual(svg_rejected["status"], "failed")

            payload["origin"] = "https://example.invalid/active-svg"
            active_svg = (
                b"<!--" + b"x" * 5000 + b"-->"
                b'<?xml-stylesheet href="https://attacker.invalid/style.css"?>'
                b'<svg xmlns="http://www.w3.org/2000/svg"><rect fill="url(\'https://attacker.invalid/pattern.svg#x\')"/></svg>'
            )
            active_result, active = self.run_capture_native_stream(
                root,
                payload,
                b"",
                "none",
                staging,
                {"unsafe-svg": active_svg},
                attachment_media_types={"unsafe-svg": "text/plain"},
            )
            self.assertEqual(active_result.returncode, 0, (active_result.stderr.decode(), active))
            self.assertEqual(active["status"], "partial")
            self.assertFalse(list((root / "Inbox/Captures/_assets").rglob("unsafe.svg")))

            escaped_result, escaped = self.run_capture_native_stream(
                root,
                {**payload, "origin": "https://example.invalid/escaped-active-svg"},
                b"",
                "none",
                staging,
                {"unsafe-svg": b'<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:\\75 rl(https://attacker.invalid/pixel)"/></svg>'},
                attachment_media_types={"unsafe-svg": "image/svg+xml"},
            )
            self.assertEqual(escaped_result.returncode, 0, (escaped_result.stderr.decode(), escaped))
            self.assertEqual(escaped["status"], "partial")
            self.assertFalse(list((root / "Inbox/Captures/_assets").rglob("unsafe.svg")))

    def test_native_stream_saves_direct_pdf_and_rejects_disguised_video(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.copy_repo(base)
            staging = base / "staging"
            staging.mkdir()
            payload = {
                "schema": "lbrain.capture.v1",
                "title": "Direct report",
                "summary": "The original PDF.",
                "origin": "https://example.invalid/report.pdf",
                "scope": "page",
                "content_markdown": "[Original PDF](lbrain-asset://direct-document)",
                "capture_kind": "document",
                "extraction_status": "complete",
                "remote_assets": [{
                    "id": "direct-document",
                    "url": "https://example.invalid/report.pdf",
                    "name": "documents/report.pdf",
                    "media_type": "application/pdf",
                }],
                "assets": [],
            }
            saved_result, saved = self.run_capture_native_stream(
                root,
                payload,
                b"%PDF-1.7\nsynthetic report",
                "binary",
                staging,
                snapshot_media_type="text/plain",
            )
            self.assertEqual(saved_result.returncode, 0, (saved_result.stderr.decode(), saved))
            files = root / f"Inbox/Captures/_assets/{saved['capture_id']}/v1/files"
            self.assertTrue((files / "documents/report.pdf").is_file())
            manifest = json.loads((files.parent / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["assets"][0]["media_type"], "application/pdf")
            note = (root / str(saved["target"])).read_text(encoding="utf-8")
            self.assertIn("Extracted PDF text", note)

            payload["origin"] = "https://example.invalid/secret.pdf"
            secret_result, secret = self.run_capture_native_stream(
                root,
                payload,
                b'%PDF-1.7\napi_key = "fixture-hardcoded-secret-12345"',
                "binary",
                staging,
                snapshot_media_type="application/pdf",
            )
            self.assertNotEqual(secret_result.returncode, 0)
            self.assertEqual(secret["status"], "failed")

            if shutil.which("pdftotext"):
                stream = zlib.compress(b'BT /F1 12 Tf 72 720 Td (api_key = "fixture-compressed-secret-12345") Tj ET')
                objects = [
                    b"<< /Type /Catalog /Pages 2 0 R >>",
                    b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
                    f"<< /Length {len(stream)} /Filter /FlateDecode >>\nstream\n".encode() + stream + b"\nendstream",
                    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
                ]
                compressed_pdf = bytearray(b"%PDF-1.4\n")
                offsets = [0]
                for index, body in enumerate(objects, 1):
                    offsets.append(len(compressed_pdf))
                    compressed_pdf.extend(f"{index} 0 obj\n".encode() + body + b"\nendobj\n")
                xref = len(compressed_pdf)
                compressed_pdf.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
                compressed_pdf.extend(b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:]))
                compressed_pdf.extend(
                    f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
                )
                compressed_result, compressed = self.run_capture_native_stream(
                    root,
                    {**payload, "origin": "https://example.invalid/compressed-secret.pdf"},
                    bytes(compressed_pdf),
                    "binary",
                    staging,
                    snapshot_media_type="application/pdf",
                )
                self.assertNotEqual(compressed_result.returncode, 0)
                self.assertEqual(compressed["status"], "failed")

            office = io.BytesIO()
            with zipfile.ZipFile(office, "w") as archive:
                archive.writestr("word/document.xml", '<w:t>api_key = "fixture-office-secret-12345"</w:t>')
            office_payload = {
                **payload,
                "origin": "https://example.invalid/secret.docx",
                "content_markdown": "[Original document](lbrain-asset://direct-document)",
                "remote_assets": [{
                    **payload["remote_assets"][0],
                    "url": "https://example.invalid/secret.docx",
                    "name": "documents/secret.docx",
                    "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                }],
            }
            office_result, office_rejected = self.run_capture_native_stream(
                root, office_payload, office.getvalue(), "binary", staging,
                snapshot_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            self.assertNotEqual(office_result.returncode, 0)
            self.assertEqual(office_rejected["status"], "failed")

            legacy_payload = {
                **office_payload,
                "origin": "https://example.invalid/secret.doc",
                "remote_assets": [{
                    **office_payload["remote_assets"][0],
                    "url": "https://example.invalid/secret.doc",
                    "name": "documents/secret.doc",
                    "media_type": "application/msword",
                }],
            }
            legacy_body = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1x" + 'api_key = "fixture-legacy-secret-12345"'.encode("utf-16le")
            legacy_result, legacy = self.run_capture_native_stream(
                root, legacy_payload, legacy_body, "binary", staging,
                snapshot_media_type="application/msword",
            )
            self.assertNotEqual(legacy_result.returncode, 0)
            self.assertEqual(legacy["status"], "failed")

            image_payload = {
                **payload,
                "origin": "https://example.invalid/secret.jpg",
                "content_markdown": "![Original image](lbrain-asset://direct-document)",
                "remote_assets": [{
                    **payload["remote_assets"][0],
                    "url": "https://example.invalid/secret.jpg",
                    "name": "images/secret.jpg",
                    "media_type": "image/jpeg",
                }],
            }
            image_result, image_rejected = self.run_capture_native_stream(
                root,
                image_payload,
                b'\xff\xd8\xff\xe1api_key = "fixture-image-secret-12345"',
                "binary",
                staging,
                snapshot_media_type="image/jpeg",
            )
            self.assertNotEqual(image_result.returncode, 0)
            self.assertEqual(image_rejected["status"], "failed")

            payload["origin"] = "https://example.invalid/disguised.pdf"
            rejected_result, rejected = self.run_capture_native_stream(
                root, payload, b"FLV\x01 disguised video", "binary", staging
            )
            self.assertNotEqual(rejected_result.returncode, 0)
            self.assertEqual(rejected["status"], "failed")
            html_result, html_rejected = self.run_capture_native_stream(
                root,
                payload,
                b"<!doctype html><title>Sign in</title>",
                "binary",
                staging,
                snapshot_media_type="text/html",
            )
            self.assertNotEqual(html_result.returncode, 0)
            self.assertEqual(html_rejected["status"], "failed")

    def test_chrome_extension_extracts_rendered_article_with_minimal_permissions(self) -> None:
        manifest = json.loads((CAPTURE_EXTENSION / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], 3)
        self.assertEqual(manifest["action"]["default_popup"], "confirm.html")
        self.assertEqual(
            set(manifest["permissions"]),
            {"activeTab", "alarms", "contextMenus", "nativeMessaging", "notifications", "pageCapture", "scripting", "storage"},
        )
        self.assertNotIn("history", manifest["permissions"])
        self.assertNotIn("tabs", manifest["permissions"])
        self.assertNotIn("downloads", manifest["permissions"])
        self.assertEqual(manifest.get("host_permissions", []), [])
        self.assertEqual(set(manifest.get("optional_host_permissions", [])), {"http://*/*", "https://*/*"})
        self.assertNotIn("<all_urls>", json.dumps(manifest))
        worker = (CAPTURE_EXTENSION / "service_worker.js").read_text(encoding="utf-8")
        self.assertNotIn("chrome.downloads", worker)
        self.assertIn('iconUrl: "icon.png"', worker)
        self.assertTrue((CAPTURE_EXTENSION / "icon.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))

        chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if not chrome.is_file():
            candidate = shutil.which("google-chrome") or shutil.which("chromium")
            if not candidate:
                self.skipTest("Chrome or Chromium is not installed")
            chrome = Path(candidate)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            fixture = directory / "rendered.html"
            fixture.write_text(
                "<!doctype html><html><head>"
                '<title>Fallback title</title><meta name="author" content="Example Author">'
                '<link rel="canonical" href="https://example.invalid/authenticated-article">'
                "</head><body><nav>Navigation noise</nav><article>\n    "
                "<h1>\n    Authenticated Article\n</h1><p>Opening <strong>claim</strong>.</p><p>"
                + ("Long authenticated article paragraph. " * 20) + "</p>"
                "\n    <blockquote>Quoted evidence.</blockquote>\n    "
                "<ul><li>First item</li><li>Second item</li></ul>"
                '<p>Reference <a href="https://example.invalid/source">[1]</a>.</p>'
                '<p>Literal &lt;img src="https://tracker.invalid/pixel"&gt; and '
                '![beacon](https://tracker.invalid/markdown).</p>'
                '<p>Inline <code>safe&#96; ![inline](https://tracker.invalid/inline.png)</code>.</p>'
                '<p>Price ~~100~~ and <del>real deletion</del>. Literal #AI tag.</p>'
                '<div>Literal controls:\n---\n-\n=\n==\n~~~js\n===\n    indented code\nAfter.</div>'
                '<figure><img data-src="https://cdn.example.invalid/figure.png" alt="Figure"><figcaption>Figure caption</figcaption></figure>'
                '<picture><source srcset="https://cdn.example.invalid/responsive-article.png 2x">'
                '<img src="https://cdn.example.invalid/responsive-article.png" alt="Responsive article"></picture>'
                '<p><img src="https://cdn.example.invalid/injection.png" alt="x](https://tracker.invalid/alt) ![y"> '
                '<a href="https://example.invalid/foo)![x](https://tracker.invalid/href">Safe destination</a></p>'
                "\n    <table><tr><th>Metric</th><th>Value</th></tr><tr><td>A|B</td><td>Yes</td></tr>"
                '<tr><td><a href="https://example.invalid/a|b">Pipe link</a></td><td>No</td></tr></table>'
                '<pre><code>print("saved")</code></pre></article><aside>Recommendation noise</aside>'
                '<aside class="recommendations"><video src="https://ads.example/promo.mp4"><track kind="subtitles" '
                'src="https://ads.example/promo.vtt"></video></aside>'
                "</body></html>",
                encoding="utf-8",
            )
            wechat_fixture = directory / "wechat.html"
            wechat_fixture.write_text(
                "<!doctype html><html><head><title>WeChat</title>"
                '<link rel="canonical" href="https://example.invalid/wechat-article"></head><body>'
                '<div aria-hidden="true"><div id="activity-name">旧标题</div><div id="js_name">旧作者</div>'
                '<div id="publish_time">2020-01-01</div><div id="js_content">旧正文</div></div>'
                '<div id="activity-name">微信文章标题</div>'
                '<div id="js_name">示例作者</div><div id="publish_time">2026-08-11</div>'
                '<div id="js_content"><p>第一段<strong>重点</strong>。</p>'
                '<p><img data-src="https://mmbiz.example.invalid/example.jpg" alt="配图"></p>'
                '<blockquote>原文引用。</blockquote></div><div class="recommendations">推荐噪声</div>'
                "</body></html>",
                encoding="utf-8",
            )
            x_article_fixture = directory / "x-article.html"
            x_article_fixture.write_text(
                "<!doctype html><html><head><title>X</title></head><body>"
                '<article data-testid="twitterArticleReadView"><div data-testid="User-Name" aria-hidden="true">'
                '<span>Hidden Author</span><a href="https://x.com/hidden">@hidden</a></div>'
                '<div data-testid="User-Name">'
                '<span>Article Author</span><a href="https://x.com/articleauthor">@articleauthor</a></div>'
                '<div data-testid="twitter-article-title" aria-hidden="true">Aria-hidden X Article title</div>'
                '<div data-testid="twitter-article-title" style="display:none">Hidden X Article title</div>'
                '<div data-testid="twitter-article-title">Long-form X Article</div>'
                '<div data-testid="twitterArticleRichTextView" aria-hidden="true">Hidden stale X Article body.</div>'
                '<div data-testid="tweetPhoto"><img data-src="https://pbs.example.invalid/cover.png" alt="Cover"></div>'
                '<div data-testid="twitterArticleRichTextView">'
                '<div class="public-DraftStyleDefault-block">Article opening.</div>'
                '<div class="public-DraftStyleDefault-block">Second paragraph.</div>'
                '<h2>Article section</h2><figure><a href="https://x.com/article/media/1">'
                '<img data-src="https://pbs.example.invalid/article.png" alt="Article figure"></a>'
                '<figcaption>Article caption</figcaption></figure><div class="public-DraftStyleDefault-block">After image.</div></div>'
                '<div data-testid="UserCell">Author footer noise</div></article><div>Timeline noise</div>'
                "</body></html>",
                encoding="utf-8",
            )
            x_thread_fixture = directory / "x-thread.html"
            x_thread_fixture.write_text(
                "<!doctype html><html><head><title>X Thread</title></head><body><main>"
                '<article data-testid="tweet" style="display:none"><div data-testid="User-Name"><span>Alice</span>'
                '<a href="https://x.com/alice/status/100"><time datetime="2026-08-11T00:59:00Z">hidden</time></a></div>'
                '<div data-testid="tweetText">Hidden duplicate.</div></article>'
                '<article data-testid="tweet" aria-hidden="true"><div data-testid="User-Name"><span>Alice</span>'
                '<a href="https://x.com/alice/status/100"><time datetime="2026-08-11T00:58:00Z">hidden</time></a></div>'
                '<div data-testid="tweetText">Aria-hidden duplicate.</div></article>'
                '<article data-testid="tweet" style="visibility:collapse"><div data-testid="User-Name"><span>Alice</span>'
                '<a href="https://x.com/alice/status/100"><time datetime="2026-08-11T00:57:00Z">hidden</time></a></div>'
                '<div data-testid="tweetText">Collapsed duplicate.</div></article>'
                '<article data-testid="tweet"><div data-testid="User-Name"><span>Alice</span>'
                '<a href="https://x.com/alice/status/100"><time datetime="2026-08-11T01:00:00Z">Aug 11</time></a></div>'
                '<div data-testid="tweetText">First author post.</div>'
                '<div data-testid="quoteTweet">Quoted Bob: useful evidence.</div><div role="group">Action noise</div></article>'
                '<article data-testid="tweet"><div data-testid="User-Name"><span>Alice</span>'
                '<a href="https://x.com/alice/status/101"><time datetime="2026-08-11T01:05:00Z">Aug 11</time></a></div>'
                '<div>回复 <a href="https://x.com/alice">@alice</a></div>'
                '<div data-testid="tweetText">Second author post.</div><div data-testid="tweetPhoto">'
                '<picture><source srcset="https://pbs.example.invalid/thread-responsive.png 2x"><img alt="Thread responsive"></picture>'
                '</div></article>'
                '<article data-testid="tweet"><div data-testid="User-Name"><span>Alice</span>'
                '<a href="https://x.com/alice/status/102"><time datetime="2026-08-11T01:06:00Z">Aug 11</time></a></div>'
                '<div>回复 <a href="https://x.com/alice">@alice</a></div>'
                '<div data-testid="tweetPhoto"><img src="https://pbs.example.invalid/thread-photo.png" alt="Media-only reply"></div></article>'
                '<article data-testid="tweet"><div data-testid="User-Name"><span>Alice</span>'
                '<a href="https://x.com/alice/status/103"><time datetime="2026-08-11T01:07:00Z">Aug 11</time></a></div>'
                '<div data-testid="tweetText">Recommended same-author post.</div>'
                '<div data-testid="quoteTweet">Quoted <a href="https://x.com/alice/status/102">previous post</a>.</div></article>'
                '<article data-testid="tweet"><div data-testid="User-Name"><span>Reply User</span>'
                '<a href="https://x.com/replier/status/200"><time datetime="2026-08-11T01:06:00Z">Aug 11</time></a></div>'
                '<div data-testid="tweetText">Unrelated reply.</div></article>'
                '<article data-testid="tweet" data-in-reply-to-status-id="999"><div data-testid="User-Name"><span>Alice</span>'
                '<a href="https://x.com/alice/status/104"><time datetime="2026-08-11T01:08:00Z">Aug 11</time></a></div>'
                '<div>Replying to <a href="https://x.com/bob">@bob</a> and <a href="https://x.com/alice">@alice</a></div>'
                '<div data-testid="tweetText">Reply to another chain.</div></article></main></body></html>',
                encoding="utf-8",
            )
            media_fixture = directory / "media.html"
            media_fixture.write_text(
                "<!doctype html><html><head><title>Media article</title>"
                '<link rel="canonical" href="https://video.example.invalid/watch/123"></head><body><article>'
                "<h1>Media article</h1><p>Body with "
                '<a href="https://cdn.example.invalid/report.pdf">a PDF</a> and '
                '<a href="https://cdn.example.invalid/download?id=signed" type="application/pdf">a signed PDF</a> and '
                '<a href="https://cdn.example.invalid/brief.docx">a document</a>, '
                '<a href="https://cdn.example.invalid/notes.rtf">RTF</a>, and '
                '<a href="https://cdn.example.invalid/notes.odt">ODT</a>. '
                '<a href="https://github.com/example/project/blob/main/README.md">source Markdown</a> and '
                '<a href="https://github.com/example/project/graphs/contributors-data.txt">contributors</a>, plus '
                '<a href="https://cdn.example.invalid/export.txt" download>an exported text file</a>.</p>'
                '<video src="blob:https://video.example.invalid/runtime-stream">'
                '<track kind="subtitles" src="https://video.example.invalid/captions.vtt" label="English">'
                '</video><audio src="https://video.example.invalid/soundtrack.mp3"></audio>'
                '<ytd-transcript-renderer><div class="segment"><p>Page transcript sentence.</p></div></ytd-transcript-renderer>'
                "</article></body></html>",
                encoding="utf-8",
            )
            substack_fixture = directory / "substack.html"
            substack_fixture.write_text(
                '<!doctype html><html><head><title>Alexander - by Example Author - Newsletter</title><style>.concealed{display:none}</style>'
                '<meta property="og:type" content="article"><meta property="og:title" content="Alexander">'
                '<link rel="canonical" href="https://newsletter.example.invalid/p/paid-post">'
                '</head><body><div class="concealed"><article><h2>Why humans are AI&#39;s biggest bottleneck</h2>'
                '<p>Hidden account-state copy.</p><p>'
                + ('Hidden account-state body must not be captured. ' * 30)
                + '</p></article></div><article class="sponsor"><h2>Alexander</h2><div class="body markup"><p>Sponsored introduction.</p><p>'
                + ('Sponsored course details. ' * 16)
                + '</p></div></article><main><h1>Alexander</h1>'
                '<section><time datetime="2026-08-11">Aug 11</time><p>Private account panel.</p><p>'
                + ('Account and podcast player context. ' * 100)
                + '</p></section>'
                '<article class="post"><div class="shows-post-audio-player-wrapper-outer">'
                '<div data-testid="audio-player-preview-label">Preview</div><span>0:00–1:25:12</span></div>'
                '<h2 class="concealed">Hidden stale title</h2><h2>Why humans are AI&#39;s biggest bottleneck</h2>'
                '<div class="byline-wrapper"><a rel="author">Example Author</a> · <time datetime="2025-12-14">Dec 14</time></div>'
                '<button class="post-ufi-button">Share</button>'
                '<figure class="post-header"><img src="https://cdn.example.invalid/paid-cover.png" alt="Paid cover">'
                '<figcaption>Paid cover caption</figcaption></figure>'
                '<img class="hero" width="699" src="https://cdn.example.invalid/paid-hero.png" alt="Paid hero">'
                '<div class="available-content">'
                '<div class="body markup concealed"><p>' + ('Hidden mobile article body. ' * 30) + '</p></div>'
                '<div class="body markup">'
                '<p>Opening context for the authenticated article. '
                '<span class="concealed">Hidden child state.</span></p><p>'
                + ('Detailed paid article body with evidence and analysis. ' * 18)
                + '</p><p>Final takeaways for readers.</p>'
                '<p><a href="https://youtu.be/example-video">Watch the original video</a></p>'
                '<video src="https://cdn.example.invalid/opaque-signed-path/private-stream.mp4"></video>'
                '<img src="https://cdn.example.invalid/paid-figure.png" alt="Paid figure">'
                '<audio src="https://cdn.example.invalid/private-podcast.mp3?signature=fixture"></audio>'
                '</div></div></article></main></body></html>',
                encoding="utf-8",
            )
            generic_fixture = directory / "generic.html"
            generic_fixture.write_text(
                "<!doctype html><html><head><title>Alpha School</title>"
                '<meta property="og:type" content="article"><base href="https://remote.invalid/leak/">'
                '<link rel="canonical" href="https://alpha.example.invalid/"></head><body>'
                '<main aria-hidden="true"><h1>Hidden responsive shell</h1></main>'
                "<header><h1>Alpha School</h1></header><nav>Course navigation</nav><main><p>Choose a course.</p>"
                '<article class="course-card"><h1>Course card</h1><p>' + ("Course features and pricing. " * 24)
                + "</p><p>Choose this course.</p></article>"
                '<img src="https://alpha.example.invalid/hero.png" onerror="leak()" '
                'title="The rise of Cursor: A related article">'
                '<picture><source srcset="https://alpha.example.invalid/responsive-generic.png 2x"><img alt="Responsive generic"></picture>'
                '<svg><image href="https://alpha.example.invalid/chart.svg"></image></svg>'
                '<svg xmlns:xlink="http://www.w3.org/1999/xlink"><image xlink:href="https://alpha.example.invalid/xlink-chart.svg"></image></svg>'
                '<svg><symbol id="local-symbol"><path d="M0 0"></path></symbol>'
                '<use href="#local-symbol"></use><use href="https://alpha.example.invalid/icons.svg#home"></use></svg>'
                '<audio src="https://alpha.example.invalid/lesson.mp3"></audio>'
                '<a href="javascript:alert(1)">unsafe link</a>'
                '<form><input value="private form value"></form><script>privateRuntimeState()</script>'
                '</main><aside class="recommendations"><ytd-transcript-renderer>Unrelated promo transcript.</ytd-transcript-renderer>'
                '<img src="https://ads.example/tracker.png"></aside>'
                "</body></html>",
                encoding="utf-8",
            )
            main_article_fixture = directory / "main-article.html"
            main_article_fixture.write_text(
                "<!doctype html><html><head><title>AI agents — what changes now | Newsletter</title>"
                '<meta property="og:type" content="article"></head><body><article><h2>AI agents — what changes now</h2>'
                "<p>Opening paragraph.</p><p>" + ("Long story body. " * 30)
                + '</p><p>Closing paragraph.</p><iframe src="https://www.youtube-nocookie.com/embed/abc123"></iframe>'
                '</article></body></html>',
                encoding="utf-8",
            )
            product_fixture = directory / "product.html"
            product_fixture.write_text(
                "<!doctype html><html><head><title>Plans</title><meta property=\"og:type\" content=\"article\"></head>"
                '<body><header><h1>Plans</h1></header><main><h1>Choose your plan</h1><video src="decorative.mp4"></video>'
                + "".join(
                    '<div class="pricing-plan" itemscope itemtype="https://schema.org/Product">'
                    f'<h2>{name} Plan</h2><p>' + ("Pricing and subscription details. " * 12)
                    + "</p><p>Annual billing.</p><p>Choose this plan.</p></div>"
                    for name in ("Pro", "Team", "Enterprise")
                )
                + "</main></body></html>",
                encoding="utf-8",
            )
            product_article_fixture = directory / "product-article.html"
            product_article_fixture.write_text(
                '<!doctype html><html><head><title>Subscription</title><meta property="og:type" content="article"></head>'
                '<body><article><h1>Pro subscription</h1><section itemscope itemtype="https://schema.org/Product"><h2>Pro</h2><p>'
                + ('Pricing and feature catalog. ' * 30)
                + '</p><p>Annual billing.</p></section></article></body></html>', encoding="utf-8",
            )
            unknown_video_fixture = directory / "unknown-video.html"
            unknown_video_fixture.write_text(
                '<!doctype html><html><head><title>Watch lesson</title></head><body><main><h1>Watch lesson</h1>'
                '<p>Short lesson introduction.</p><p>Watch the lesson below.</p>'
                '</main><div id="player"><video src="https://training.example/lesson.mp4"><track kind="subtitles" '
                'src="https://training.example/lesson.vtt"></video>'
                '<audio src="https://training.example/lesson-audio.mp3"></audio></div></body></html>', encoding="utf-8",
            )
            youtube_fixture = directory / "youtube-fixture.html"
            youtube_fixture.write_text(
                '<!doctype html><html><head><title>Restricted video</title></head><body><main>'
                '<h1>Restricted video</h1><p>Sign in to confirm your age.</p><p>This content is restricted.</p>'
                '<img src="" alt="Empty image"><audio src="https://ads.example/audio-only.m4a"></audio><ytd-wrapper>'
                '<ytd-transcript-segment-list-renderer><div class="segment">First transcript cue.</div>'
                '<div class="segment">Second transcript cue.</div></ytd-transcript-segment-list-renderer></ytd-wrapper>'
                '</main></body></html>', encoding="utf-8",
            )
            transcript_fixture = directory / "transcript-only.html"
            transcript_fixture.write_text(
                '<!doctype html><html><head><title>Training replay</title>'
                '<link rel="canonical" href="https://training.example/replay/7"></head><body><main>'
                '<h1>Training replay</h1><div data-lbrain-transcript><div class="segment">Replay cue.</div></div>'
                '</main></body></html>', encoding="utf-8",
            )
            interview_fixture = directory / "interview.html"
            interview_fixture.write_text(
                '<!doctype html><html><head><title>Interview transcript</title></head><body><main>'
                '<h1>Interview transcript</h1><p>' + ('Editorial introduction and context. ' * 25) + '</p>'
                '<section itemprop="transcript"><p>Alice: First answer.</p><p>Bob: Follow-up question.</p></section>'
                '<p>' + ('Editorial conclusion and analysis. ' * 20) + '</p></main></body></html>', encoding="utf-8",
            )
            selection_fixture = directory / "selection-responsive.html"
            selection_fixture.write_text(
                '<!doctype html><html><head><title>Selection</title></head><body><article><h1>Selected passage</h1>'
                '<p>Selected text.</p><picture><source srcset="https://cdn.example/selected.png 2x">'
                '<img alt="Selected responsive"></picture></article></body></html>', encoding="utf-8",
            )
            plain_article_fixture = directory / "plain-article.html"
            plain_article_fixture.write_text(
                "<!doctype html><html><head><title>Research Note</title></head><body><main><h1>Research Note</h1>"
                "<p>Opening.</p><p>" + ("Detailed research argument. " * 45)
                + "</p><p>Conclusion.</p></main></body></html>",
                encoding="utf-8",
            )
            interposed_thread_fixture = directory / "interposed-thread.html"
            interposed_thread_fixture.write_text(
                '<!doctype html><html><body><main><article data-testid="tweet"><div data-testid="User-Name">'
                '<span>Alice</span><a href="https://x.com/alice/status/300"><time datetime="2026-08-11T01:00:00Z">1</time></a></div>'
                '<div data-testid="tweetText">First chain post.</div></article>'
                '<article data-testid="tweet"><div data-testid="User-Name"><span>Bob</span>'
                '<a href="https://x.com/bob/status/400"><time datetime="2026-08-11T01:01:00Z">2</time></a></div>'
                '<div data-testid="tweetText">Interposed reply.</div></article>'
                '<article data-testid="tweet"><div data-testid="User-Name"><span>Alice</span>'
                '<a href="https://x.com/alice/status/399"><time datetime="2026-08-11T01:01:30Z">2.5</time></a></div>'
                '<div data-testid="tweetText">Interposed standalone post.</div></article>'
                '<article data-testid="tweet" data-in-reply-to-status-id="300"><div data-testid="User-Name"><span>Alice</span>'
                '<a href="https://x.com/alice/status/301"><time datetime="2026-08-11T01:02:00Z">3</time></a></div>'
                '<div data-testid="tweetText">Second chain post.</div></article>'
                '<article data-testid="tweet" data-in-reply-to-status-id="300"><div data-testid="User-Name"><span>Alice</span>'
                '<a href="https://x.com/alice/status/302"><time datetime="2026-08-11T01:03:00Z">4</time></a></div>'
                '<div data-testid="tweetText">Third root reply.</div></article></main></body></html>',
                encoding="utf-8",
            )
            timeline_fixture = directory / "x-timeline.html"
            timeline_fixture.write_text(
                '<!doctype html><html><head><title>Alice timeline</title>'
                '<link rel="canonical" href="https://x.com/alice"></head><body><main>'
                '<a style="display:none" href="https://x.com/alice/thread/500">Hidden thread marker</a>'
                '<article data-testid="tweet"><div data-testid="User-Name"><span>Alice</span>'
                '<a href="https://x.com/alice/status/500"></a></div><div data-testid="tweetText">Standalone one.</div></article>'
                '<article data-testid="tweet"><div data-testid="User-Name"><span>Alice</span>'
                '<a href="https://x.com/alice/status/501"></a></div><div data-testid="tweetText">Standalone two.</div></article>'
                '</main></body></html>', encoding="utf-8",
            )
            chinese_article_fixture = directory / "chinese-article.html"
            chinese_article_fixture.write_text(
                '<!doctype html><html><head><title>人工智能未来 | 人工智能周刊</title>'
                '<meta property="og:title" content="人工智能未来 | 人工智能周刊">'
                '</head><body><article><h2>人工智能周刊</h2><figure></figure><p>课程介绍。</p><p>'
                + ('这是更长的赞助课程介绍，不应被识别为页面正文。' * 30)
                + '</p></article><article><h2>人工智能未来</h2>'
                '<p><span itemprop="author">张三</span><time datetime="2026-08-11">2026-08-11</time></p>'
                '<p>' + ('这是一个完整的中文论证段落，包含背景、证据、判断以及可复核的结论。' * 8) + '</p>'
                '<p>' + ('第二段继续解释取舍、限制与后续行动，形成清晰完整的文章结构。' * 8) + '</p>'
                '</article></body></html>', encoding="utf-8",
            )
            editorial_product_fixture = directory / "editorial-product.html"
            editorial_product_fixture.write_text(
                '<!doctype html><html><head><title>Main Story</title>'
                '<meta property="og:type" content="article"><meta property="article:published_time" content="2026-08-11">'
                '</head><body><main><h1>Main Story</h1><p>'
                + ('Independent editorial evidence and analysis. ' * 20)
                + '</p><section class="content-item"><p>' + ('First editorial section. ' * 20)
                + '</p></section><section class="content-item"><p>' + ('Second editorial section. ' * 20)
                + '</p></section><figure><figcaption>Evidence</figcaption></figure>'
                '<aside itemscope itemtype="https://schema.org/Product"><h2>Related product</h2><p>Small recommendation.</p></aside>'
                '<article><h2>Embedded unrelated note</h2><time datetime="2026-08-10">Aug 10</time>'
                '<p>Embedded note one.</p><p>' + ('Unrelated embedded note. ' * 15)
                + '</p><p>Embedded note three.</p></article><p>Final editorial conclusion.</p></main></body></html>', encoding="utf-8",
            )
            (
                captured, wechat, x_article, x_thread, media_capture, generic, main_article,
                product, plain_article, interposed_thread, timeline, chinese_article, editorial_product,
                product_article,
                substack_article,
                unknown_video,
                youtube_video,
                transcript_video,
                interview,
                selection_capture,
            ) = self.run_browser_fixtures(
                chrome,
                [
                    fixture, wechat_fixture, x_article_fixture, x_thread_fixture, media_fixture,
                    generic_fixture, main_article_fixture, product_fixture, plain_article_fixture,
                    interposed_thread_fixture, timeline_fixture, chinese_article_fixture, editorial_product_fixture,
                    product_article_fixture,
                    substack_fixture,
                    unknown_video_fixture,
                    youtube_fixture,
                    transcript_fixture,
                    interview_fixture,
                    selection_fixture,
                ],
            )
            self.assertEqual(captured["capture_kind"], "article")
            self.assertEqual(captured["title"], "Authenticated Article")
            self.assertEqual(captured["author"], "Example Author")
            self.assertEqual(captured["origin"], "https://example.invalid/authenticated-article")
            markdown = captured["content_markdown"]
            lines = markdown.splitlines()
            self.assertIn("# Authenticated Article", lines)
            self.assertIn("- First item", lines)
            self.assertIn("| Metric | Value |", lines)
            self.assertEqual(markdown.count("&#32;"), 1)
            self.assertIn("Opening **claim**.", captured["content_markdown"])
            self.assertIn("> Quoted evidence.", captured["content_markdown"])
            self.assertIn("- First item", captured["content_markdown"])
            self.assertIn(r"[\[1\]](https://example.invalid/source)", captured["content_markdown"])
            self.assertNotIn("[[1]]", captured["content_markdown"])
            self.assertIn(r"\<img src=", captured["content_markdown"])
            self.assertIn(r"\!\[beacon\]", captured["content_markdown"])
            self.assertIn("``safe` ![inline](https://tracker.invalid/inline.png)``", captured["content_markdown"])
            self.assertIn(r"Price \~\~100\~\~ and ~~real deletion~~.", captured["content_markdown"])
            self.assertIn(r"Literal \#AI tag.", captured["content_markdown"])
            self.assertIn(r"\---", captured["content_markdown"])
            self.assertIn("\n\\-\n", captured["content_markdown"])
            self.assertIn(r"\=", captured["content_markdown"])
            self.assertIn(r"\==", captured["content_markdown"])
            self.assertIn(r"\~\~\~js", captured["content_markdown"])
            self.assertIn(r"\===", captured["content_markdown"])
            self.assertIn("&#32;   indented code", captured["content_markdown"])
            self.assertNotIn("https://tracker.invalid/pixel", {asset["url"] for asset in captured["remote_assets"]})
            self.assertIn(r"x\](https://tracker.invalid/alt) \!\[y", captured["content_markdown"])
            self.assertIn("(<https://example.invalid/foo)![x](https://tracker.invalid/href>)", captured["content_markdown"])
            self.assertIn("![Figure](https://cdn.example.invalid/figure.png)", captured["content_markdown"])
            self.assertIn("![Responsive article](https://cdn.example.invalid/responsive-article.png)", captured["content_markdown"])
            self.assertIn("Figure caption", captured["content_markdown"])
            self.assertIn("| Metric | Value |", captured["content_markdown"])
            self.assertIn(r"| A\|B | Yes |", captured["content_markdown"])
            self.assertIn("[Pipe link](https://example.invalid/a%7Cb)", captured["content_markdown"])
            self.assertNotIn("Navigation noise", captured["content_markdown"])
            self.assertNotIn("Recommendation noise", captured["content_markdown"])
            self.assertNotIn("ads.example", captured["content_markdown"])
            self.assertFalse(captured["has_video"])
            self.assertEqual(substack_article["capture_kind"], "article")
            self.assertEqual(substack_article["title"], "Why humans are AI's biggest bottleneck")
            self.assertEqual(substack_article["author"], "Example Author")
            self.assertEqual(substack_article["published_at"], "2025-12-14")
            self.assertTrue(substack_article["has_video"])
            self.assertIn("Detailed paid article body", substack_article["content_markdown"])
            self.assertIn("![Paid cover](https://cdn.example.invalid/paid-cover.png)", substack_article["content_markdown"])
            self.assertIn("![Paid hero](https://cdn.example.invalid/paid-hero.png)", substack_article["content_markdown"])
            self.assertIn("Paid cover caption", substack_article["content_markdown"])
            self.assertNotIn("Hidden account-state", substack_article["content_markdown"])
            self.assertNotIn("Hidden child state", substack_article["content_markdown"])
            self.assertNotIn("Hidden mobile article body", substack_article["content_markdown"])
            self.assertNotIn("Private account panel", substack_article["content_markdown"])
            self.assertNotIn("Preview", substack_article["content_markdown"])
            self.assertNotIn("0:00", substack_article["content_markdown"])
            self.assertNotIn("Share", substack_article["content_markdown"])
            self.assertNotIn("Example Author · Dec 14", substack_article["content_markdown"])
            self.assertIn("https://youtu.be/example-video", substack_article["content_markdown"])
            self.assertFalse(any(asset["media_type"].startswith("audio/") for asset in substack_article["remote_assets"]))
            self.assertNotIn("private-podcast", substack_article["content_markdown"])
            self.assertNotIn("private-stream", substack_article["content_markdown"])
            self.assertEqual(wechat["title"], "微信文章标题")
            self.assertEqual(wechat["author"], "示例作者")
            self.assertEqual(wechat["published_at"], "2026-08-11")
            self.assertEqual(wechat["origin"], "https://example.invalid/wechat-article")
            self.assertIn("第一段**重点**。", wechat["content_markdown"])
            self.assertIn("![配图](https://mmbiz.example.invalid/example.jpg)", wechat["content_markdown"])
            self.assertEqual(wechat["remote_assets"][0]["url"], "https://mmbiz.example.invalid/example.jpg")
            self.assertNotIn("推荐噪声", wechat["content_markdown"])
            self.assertEqual(x_article["title"], "Long-form X Article")
            self.assertEqual(x_article["author"], "Article Author")
            self.assertIn("Article opening.\n\nSecond paragraph.", x_article["content_markdown"])
            self.assertIn("## Article section", x_article["content_markdown"])
            self.assertIn("![Cover](https://pbs.example.invalid/cover.png)", x_article["content_markdown"])
            self.assertIn(
                "[![Article figure](https://pbs.example.invalid/article.png)](https://x.com/article/media/1)",
                x_article["content_markdown"],
            )
            self.assertIn("Article caption", x_article["content_markdown"])
            self.assertIn("*Article caption*\n\nAfter image.", x_article["content_markdown"])
            self.assertNotIn("Author footer noise", x_article["content_markdown"])
            self.assertNotIn("Timeline noise", x_article["content_markdown"])
            self.assertEqual(x_thread["title"], "Alice — Thread")
            self.assertEqual(x_thread["author"], "Alice")
            self.assertEqual(x_thread["origin"], "https://x.com/alice/status/100")
            self.assertIn("First author post.", x_thread["content_markdown"])
            self.assertIn("Quoted Bob: useful evidence.", x_thread["content_markdown"])
            self.assertIn("Second author post.", x_thread["content_markdown"])
            self.assertNotIn("**Alice", x_thread["content_markdown"])
            self.assertIn("![Thread responsive](https://pbs.example.invalid/thread-responsive.png)", x_thread["content_markdown"])
            self.assertNotIn("[![Thread responsive]", x_thread["content_markdown"])
            self.assertIn("## Thread sources", x_thread["content_markdown"])
            self.assertIn("1. [Post 1](https://x.com/alice/status/100)", x_thread["content_markdown"])
            self.assertIn("https://pbs.example.invalid/thread-responsive.png", x_thread["content_markdown"])
            self.assertIn("Media-only reply", x_thread["content_markdown"])
            self.assertNotIn("Unrelated reply.", x_thread["content_markdown"])
            self.assertNotIn("Aria-hidden duplicate.", x_thread["content_markdown"])
            self.assertNotIn("Collapsed duplicate.", x_thread["content_markdown"])
            self.assertNotIn("Reply to another chain.", x_thread["content_markdown"])
            self.assertNotIn("Recommended same-author post.", x_thread["content_markdown"])
            self.assertNotIn("Action noise", x_thread["content_markdown"])
            remote = {asset["url"] for asset in media_capture["remote_assets"]}
            self.assertIn("https://cdn.example.invalid/report.pdf", remote)
            self.assertIn("https://cdn.example.invalid/download?id=signed", remote)
            self.assertIn("https://cdn.example.invalid/brief.docx", remote)
            self.assertIn("https://cdn.example.invalid/notes.rtf", remote)
            self.assertIn("https://cdn.example.invalid/notes.odt", remote)
            self.assertNotIn("https://github.com/example/project/blob/main/README.md", remote)
            self.assertNotIn("https://github.com/example/project/graphs/contributors-data.txt", remote)
            self.assertIn("https://cdn.example.invalid/export.txt", remote)
            self.assertIn("https://video.example.invalid/captions.vtt", remote)
            self.assertNotIn("https://video.example.invalid/soundtrack.mp3", remote)
            self.assertFalse(any(value.endswith((".mp4", ".mov", ".webm")) for value in remote))
            self.assertIn("Body with", media_capture["content_markdown"])
            self.assertIn("Page transcript sentence.", media_capture["content_markdown"])
            self.assertEqual(media_capture["content_markdown"].count("Page transcript sentence."), 1)
            self.assertIn("https://video.example.invalid/watch/123", media_capture["content_markdown"])
            self.assertNotIn("blob:https://", media_capture["content_markdown"])
            self.assertEqual(media_capture["capture_kind"], "article")
            self.assertTrue(media_capture["has_video"])
            self.assertEqual(generic["capture_kind"], "html")
            self.assertEqual(generic["title"], "Alpha School")
            self.assertIn("lbrain-asset://html-snapshot", generic["content_markdown"])
            self.assertIn("<main>", generic["snapshot_html"])
            self.assertNotIn("<script", generic["snapshot_html"])
            self.assertNotIn("private form value", generic["snapshot_html"])
            self.assertNotIn("onerror", generic["snapshot_html"])
            self.assertNotIn("The rise of Cursor", generic["snapshot_html"])
            self.assertNotIn("javascript:", generic["snapshot_html"])
            self.assertNotIn("<base", generic["snapshot_html"])
            self.assertNotIn("icons.svg", generic["snapshot_html"])
            self.assertNotIn("Unrelated promo transcript.", generic["content_markdown"])
            self.assertIn("https://ads.example/tracker.png", generic["snapshot_html"])
            self.assertIn('href="#local-symbol"', generic["snapshot_html"])
            generic_media = {asset["url"] for asset in generic["remote_assets"]}
            self.assertIn("https://alpha.example.invalid/chart.svg", generic_media)
            self.assertIn("https://alpha.example.invalid/xlink-chart.svg", generic_media)
            self.assertIn("xlink-chart.svg", generic["snapshot_html"])
            self.assertIn("https://alpha.example.invalid/lesson.mp3", generic_media)
            self.assertIn("https://ads.example/tracker.png", generic_media)
            self.assertIn("https://alpha.example.invalid/responsive-generic.png", generic_media)
            self.assertIn("https://alpha.example.invalid/responsive-generic.png", generic["snapshot_html"])
            self.assertEqual(main_article["capture_kind"], "article")
            self.assertEqual(main_article["title"], "AI agents — what changes now")
            self.assertIn("Long story body.", main_article["content_markdown"])
            self.assertTrue(main_article["has_video"])
            self.assertIn("https://www.youtube-nocookie.com/embed/abc123", main_article["content_markdown"])
            self.assertEqual(product["capture_kind"], "html")
            self.assertEqual(product["title"], "Plans")
            self.assertEqual(plain_article["capture_kind"], "article")
            self.assertEqual(plain_article["title"], "Research Note")
            self.assertIn("First chain post.", interposed_thread["content_markdown"])
            self.assertIn("Second chain post.", interposed_thread["content_markdown"])
            self.assertIn("Third root reply.", interposed_thread["content_markdown"])
            self.assertNotIn("Interposed reply.", interposed_thread["content_markdown"])
            self.assertNotIn("Interposed standalone post.", interposed_thread["content_markdown"])
            self.assertEqual(timeline["capture_kind"], "html")
            self.assertEqual(timeline["origin"], "https://x.com/alice")
            self.assertIn("https://x.com/alice", timeline["content_markdown"])
            self.assertNotIn("/status/500", timeline["content_markdown"])
            self.assertEqual(chinese_article["capture_kind"], "article")
            self.assertEqual(chinese_article["title"], "人工智能未来")
            self.assertEqual(editorial_product["capture_kind"], "article")
            self.assertEqual(editorial_product["title"], "Main Story")
            self.assertIn("Independent editorial evidence", editorial_product["content_markdown"])
            self.assertEqual(product_article["capture_kind"], "html")
            self.assertEqual(unknown_video["capture_kind"], "html")
            self.assertTrue(unknown_video["has_video"])
            self.assertIn("https://training.example/lesson.mp4", unknown_video["content_markdown"])
            self.assertNotIn("lesson-audio.mp3", unknown_video["snapshot_html"])
            self.assertFalse(any(asset["media_type"].startswith(("audio/", "video/")) for asset in unknown_video["remote_assets"]))
            self.assertIn("https://training.example/lesson.vtt", {asset["url"] for asset in unknown_video["remote_assets"]})
            self.assertEqual(youtube_video["capture_kind"], "video")
            self.assertTrue(youtube_video["has_video"])
            self.assertIn("https://www.youtube.com/watch?v=abc", youtube_video["content_markdown"])
            self.assertEqual(youtube_video["content_markdown"].count("First transcript cue."), 1)
            self.assertEqual(youtube_video["content_markdown"].count("Second transcript cue."), 1)
            self.assertIn("First transcript cue.\nSecond transcript cue.", youtube_video["content_markdown"])
            self.assertNotIn("Sign in to confirm your age.", youtube_video["content_markdown"])
            self.assertNotIn("https://www.youtube.com/watch?v=abc", {
                asset["url"] for asset in youtube_video["remote_assets"]
            })
            self.assertFalse(any(asset["media_type"].startswith(("audio/", "video/")) for asset in youtube_video["remote_assets"]))
            self.assertEqual(transcript_video["capture_kind"], "video")
            self.assertIn("https://training.example/replay/7", transcript_video["content_markdown"])
            self.assertEqual(transcript_video["content_markdown"].count("Replay cue."), 1)
            self.assertEqual(interview["capture_kind"], "article")
            self.assertFalse(interview["has_video"])
            self.assertIn("Alice: First answer.", interview["content_markdown"])
            self.assertEqual(selection_capture["capture_kind"], "selection")
            self.assertIn("https://cdn.example/selected.png", selection_capture["content_markdown"])

    def test_chrome_extension_extracts_single_x_post_as_markdown(self) -> None:
        chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if not chrome.is_file():
            candidate = shutil.which("google-chrome") or shutil.which("chromium")
            if not candidate:
                self.skipTest("Chrome or Chromium is not installed")
            chrome = Path(candidate)
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "x-single.html"
            fixture.write_text(
                '<!doctype html><html><head><title>X</title></head><body><main>'
                '<article data-testid="tweet"><div data-testid="User-Name"><span>Alice</span>'
                '<a href="https://x.com/alice">@alice</a><a href="https://x.com/alice/status/900">'
                '<time datetime="2026-08-11T01:00:00Z">Aug 11</time></a></div>'
                '<div>Translated from English <button aria-label="Show original">Show original</button>'
                '<button aria-label="About translation">About translation</button></div>'
                '<div data-testid="tweetText">Single post with <a href="https://example.invalid/source">a source</a>.</div>'
                '<div data-testid="quoteTweet">Quoted evidence.</div><div data-testid="tweetPhoto">'
                '<img src="https://pbs.example.invalid/single.png" alt="Chart"></div>'
                '<div role="group">Action noise</div></article>'
                '<article data-testid="tweet"><div data-testid="User-Name"><span>Reply User</span>'
                '<a href="https://x.com/replier/status/901"></a></div>'
                '<div data-testid="tweetText">Unrelated reply.</div></article></main></body></html>',
                encoding="utf-8",
            )
            missing_fixture = Path(temporary) / "x-missing.html"
            missing_fixture.write_text(
                '<!doctype html><html><head><title>X recommendations</title></head><body><main>'
                '<article data-testid="tweet"><div data-testid="User-Name"><span>Alice</span>'
                '<a href="https://x.com/alice/status/101"></a></div>'
                '<div data-testid="tweetText">Recommended one.</div></article>'
                '<article data-testid="tweet"><div data-testid="User-Name"><span>Alice</span>'
                '<a href="https://x.com/alice/status/102"></a></div><div>Replying to '
                '<a href="https://x.com/alice">@alice</a></div>'
                '<div data-testid="tweetText">Recommended two.</div></article></main></body></html>',
                encoding="utf-8",
            )
            capture, missing = self.run_browser_fixtures(chrome, [fixture, missing_fixture])
            self.assertEqual(capture["capture_kind"], "tweet")
            self.assertEqual(capture["title"], "Alice — X Post")
            self.assertEqual(capture["author"], "Alice")
            self.assertEqual(capture["published_at"], "2026-08-11T01:00:00Z")
            self.assertEqual(capture["origin"], "https://x.com/alice/status/900")
            self.assertEqual(capture["summary"], "Single post with a source.")
            self.assertIn("Single post with [a source](https://example.invalid/source).", capture["content_markdown"])
            self.assertIn("Quoted evidence.", capture["content_markdown"])
            self.assertIn("https://pbs.example.invalid/single.png", capture["content_markdown"])
            self.assertTrue(capture["rendered_translation"])
            self.assertIn("浏览器中的可见译文", capture["content_markdown"])
            self.assertNotIn("Show original", capture["content_markdown"])
            self.assertNotIn("Translated from English", capture["content_markdown"])
            self.assertNotIn("Unrelated reply.", capture["content_markdown"])
            self.assertNotIn("Action noise", capture["content_markdown"])
            self.assertEqual(missing["capture_kind"], "html")
            self.assertEqual(missing["origin"], "https://x.com/alice/status/999")
            self.assertEqual(missing["author"], "")
            self.assertEqual(missing["published_at"], "")

    def test_chrome_extension_uses_x_thread_marker_for_contiguous_author_posts(self) -> None:
        chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if not chrome.is_file():
            candidate = shutil.which("google-chrome") or shutil.which("chromium")
            if not candidate:
                self.skipTest("Chrome or Chromium is not installed")
            chrome = Path(candidate)
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "x-marked-thread.html"
            fixture.write_text(
                '<!doctype html><html><head><title>X</title></head><body><main>'
                '<a href="https://x.com/alice/thread/100">Thread</a>'
                '<article data-testid="tweet"><div data-testid="User-Name"><span>Alice</span>'
                '<a href="https://x.com/alice/status/100"><time datetime="2026-08-11T01:00:00Z">1</time></a></div>'
                '<div data-testid="tweetText">First author post.</div></article>'
                '<article data-testid="tweet"><div data-testid="User-Name"><span>Alice</span>'
                '<a href="https://x.com/alice/status/101"><time datetime="2026-08-11T01:01:00Z">2</time></a></div>'
                '<div data-testid="tweetText">Second author post.</div></article>'
                '<article data-testid="tweet"><div data-testid="User-Name"><span>Reply User</span>'
                '<a href="https://x.com/replier/status/901"></a></div>'
                '<div data-testid="tweetText">Unrelated reply.</div></article></main></body></html>',
                encoding="utf-8",
            )
            [capture] = self.run_browser_fixtures(chrome, [fixture])
            self.assertEqual(capture["capture_kind"], "thread")
            self.assertEqual(capture["title"], "Alice — Thread")
            self.assertEqual(capture["origin"], "https://x.com/alice/status/100")
            self.assertEqual(capture["summary"], "First author post.")
            self.assertIn("First author post.", capture["content_markdown"])
            self.assertIn("Second author post.", capture["content_markdown"])
            self.assertNotIn("Unrelated reply.", capture["content_markdown"])

    def test_extension_builds_direct_pdf_capture_without_saving_video_binary(self) -> None:
        script = (
            "const fs=require('fs');"
            "global.chrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(){}},onMessage:{addListener(){}},onConnect:{addListener(){}},lastError:null},"
            "contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(){}}},"
            "action:{onClicked:{addListener(){}}},windows:{onRemoved:{addListener(){}}},"
            "notifications:{onButtonClicked:{addListener(){}}}};"
            "eval(fs.readFileSync(process.argv[1],'utf8'));"
            "(async()=>{const pdf=LBrainCaptureWorker.directCapture({url:'https://example.invalid/report.pdf',title:'Annual Report'});"
            "const video=LBrainCaptureWorker.directCapture({url:'https://example.invalid/movie.mp4',title:'Recorded talk'});"
            "const signedUrl='https://example.invalid/report.pdf?Policy=private&Signature=fixture&Key-Pair-Id=key';"
            "const signed=LBrainCaptureWorker.directCapture({url:signedUrl,title:signedUrl,mimeType:'application/pdf'});"
            "const edgeSigned=LBrainCaptureWorker.directCapture({url:'https://example.invalid/report.pdf?hdnea=fixture~hmac=private&auth_key=secret&jwt=token',title:'Edge signed report',mimeType:'application/pdf'});"
            "const readable=LBrainCaptureWorker.directCapture({url:'https://example.invalid/2026%20%E5%B9%B4%E6%8A%A5.pdf',title:'Readable report'});"
            "const malformed=LBrainCaptureWorker.directCapture({url:'https://example.invalid/%E0%A4%A',title:'Malformed',mimeType:'application/pdf'});"
            "const longName=LBrainCaptureWorker.directCapture({url:'https://example.invalid/" + ("a" * 260) + ".pdf',title:'Long',mimeType:'application/pdf'});"
            "const prepared=await LBrainCaptureWorker.preparePayload(pdf);"
            "const preparedWhitespace=await LBrainCaptureWorker.preparePayload({...pdf,title:' Annual Report ',author:' Example Author ',published_at:' 2026-08-11 ',content_markdown:' Body '});"
            "const rotating=(signature)=>({schema:'lbrain.capture.v1',title:'Signed image',summary:'Image',origin:'https://example.invalid/post',scope:'page',author:'',published_at:'',capture_kind:'article',content_markdown:'![Image](https://cdn.invalid/a%7Cb.png?Policy=private&Signature='+signature+')',remote_assets:[{id:'image-1',url:'https://cdn.invalid/a|b.png?Policy=private&Signature='+signature,name:'images/a.png',media_type:'image/png'}]});"
            "const preparedRotating=[await LBrainCaptureWorker.preparePayload(rotating('one')),await LBrainCaptureWorker.preparePayload(rotating('two'))];"
            "const overlap=(signature)=>({schema:'lbrain.capture.v1',title:'Overlapping images',summary:'Images',origin:'https://example.invalid/post',scope:'page',author:'',published_at:'',capture_kind:'article',content_markdown:'![Base](https://cdn.invalid/hero.png) ![Signed](https://cdn.invalid/hero.png?Policy=private&Signature='+signature+')',remote_assets:[{id:'image-1',url:'https://cdn.invalid/hero.png',name:'images/base.png',media_type:'image/png'},{id:'image-2',url:'https://cdn.invalid/hero.png?Policy=private&Signature='+signature,name:'images/signed.png',media_type:'image/png'}]});"
            "const preparedOverlap=[await LBrainCaptureWorker.preparePayload(overlap('one')),await LBrainCaptureWorker.preparePayload(overlap('two'))];"
            "const routed=[await LBrainCaptureWorker.preparePayload({...pdf,origin:'https://app.invalid/#/doc/1'}),await LBrainCaptureWorker.preparePayload({...pdf,origin:'https://app.invalid/#/doc/2'})];"
            "const raw='https://example.invalid/post?podcast_rss_token=fixture&part=1';"
            "const privateLink='https://cdn.invalid/private.html?Policy=private&Signature=fixture&Key-Pair-Id=key';"
            "const preparedSigned=await LBrainCaptureWorker.preparePayload({title:'Saved '+raw,summary:'Summary '+raw,author:'Author '+raw,published_at:'Date '+raw,origin:raw,content_markdown:'[Original]('+raw+') [Private]('+privateLink+') [OAuth](https://app.invalid/callback#id_token=fixture-secret) [Callback](https://app.invalid/#callback?code=fixture-secret) [Route](https://app.invalid/#/doc/1) [Normal](https://cdn.invalid/public.html?id=signed) [Install](https://docs.invalid/guide#install) [Video](https://www.youtube.com/watch?v=abc#t=120)',snapshot_html:'<a href=\"https://example.invalid/post?podcast_rss_token=fixture&amp;part=1\">Original</a><a href=\"https://cdn.invalid/private.html?Policy=private&amp;Signature=fixture&amp;Key-Pair-Id=key\">Private</a>',capture_kind:'html'});"
            "const translated=LBrainCaptureWorker.previewFor({title:'Translated X',origin:'https://x.com/a/status/1',capture_kind:'tweet',"
            "rendered_translation:true,preview_characters:3,remote_assets:[]});"
            "console.log(JSON.stringify([pdf,video,signed,edgeSigned,readable,malformed,longName,prepared,preparedWhitespace,preparedSigned,preparedRotating,preparedOverlap,routed,LBrainCaptureWorker.previewFor(pdf),translated]));})().catch(error=>{console.error(error);process.exit(1)});"
        )
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        pdf, video, signed, edge_signed, readable, malformed, long_name, prepared, prepared_whitespace, prepared_signed, prepared_rotating, prepared_overlap, routed, preview, translated = json.loads(result.stdout)
        self.assertEqual(pdf["remote_assets"][0]["media_type"], "application/pdf")
        self.assertIn("lbrain-asset://direct-document", pdf["content_markdown"])
        self.assertEqual(video["remote_assets"], [])
        self.assertIn("https://example.invalid/movie.mp4", video["content_markdown"])
        self.assertEqual(signed["remote_assets"][0]["media_type"], "application/pdf")
        self.assertTrue(str(signed["remote_assets"][0]["name"]).endswith(".pdf"))
        self.assertEqual(signed["origin"], "https://example.invalid/report.pdf")
        self.assertEqual(signed["title"], "https://example.invalid/report.pdf")
        self.assertIn("?Policy=private&Signature=fixture", signed["remote_assets"][0]["url"])
        self.assertEqual(edge_signed["origin"], "https://example.invalid/report.pdf")
        self.assertIn("?hdnea=fixture", edge_signed["remote_assets"][0]["url"])
        self.assertEqual(readable["remote_assets"][0]["name"], "documents/2026 年报.pdf")
        self.assertTrue(malformed["remote_assets"][0]["name"].endswith(".pdf"))
        self.assertLessEqual(len(long_name["remote_assets"][0]["name"].split("/", 1)[1].encode()), 160)
        source_identity = "\0".join((pdf["title"], pdf["author"], pdf["published_at"], pdf["content_markdown"]))
        self.assertEqual(prepared["source_content_hash"], hashlib.sha256(source_identity.encode()).hexdigest())
        self.assertEqual(prepared["source_content_markdown"], pdf["content_markdown"])
        whitespace_identity = "\0".join(("Annual Report", "Example Author", "2026-08-11", "Body"))
        self.assertEqual(prepared_whitespace["source_content_hash"], hashlib.sha256(whitespace_identity.encode()).hexdigest())
        self.assertEqual(prepared_whitespace["title"], "Annual Report")
        self.assertEqual(prepared_whitespace["content_markdown"], "Body")
        self.assertEqual(prepared_signed["origin"], "https://example.invalid/post")
        self.assertNotIn("podcast_rss_token", prepared_signed["content_markdown"])
        self.assertNotIn("podcast_rss_token", prepared_signed["snapshot_html"])
        self.assertNotIn("podcast_rss_token", prepared_signed["source_content_markdown"])
        self.assertNotIn("Policy=private", prepared_signed["content_markdown"])
        self.assertNotIn("Policy=private", prepared_signed["snapshot_html"])
        self.assertIn("https://cdn.invalid/public.html?id=signed", prepared_signed["content_markdown"])
        self.assertIn("https://docs.invalid/guide#install", prepared_signed["content_markdown"])
        self.assertIn("https://www.youtube.com/watch?v=abc#t=120", prepared_signed["content_markdown"])
        self.assertNotIn("id_token", prepared_signed["content_markdown"])
        self.assertNotIn("#callback?code", prepared_signed["content_markdown"])
        self.assertIn("https://app.invalid/#/doc/1", prepared_signed["content_markdown"])
        self.assertEqual(prepared_rotating[0]["source_content_hash"], prepared_rotating[1]["source_content_hash"])
        self.assertIn("lbrain-asset://image-1", prepared_rotating[0]["source_content_markdown"])
        self.assertIn("Signature=one", prepared_rotating[0]["content_markdown"])
        self.assertEqual(prepared_overlap[0]["source_content_hash"], prepared_overlap[1]["source_content_hash"])
        self.assertIn("lbrain-asset://image-1", prepared_overlap[0]["source_content_markdown"])
        self.assertIn("lbrain-asset://image-2", prepared_overlap[0]["source_content_markdown"])
        self.assertNotIn("Policy=", prepared_overlap[0]["source_content_markdown"])
        self.assertEqual([item["origin"] for item in routed], ["https://app.invalid/#/doc/1", "https://app.invalid/#/doc/2"])
        for field in ("title", "summary", "author", "published_at"):
            self.assertNotIn("podcast_rss_token", prepared_signed[field])
        self.assertEqual(preview["details"][0], ["保存内容", "原始文档"])
        self.assertIn("自动译文", translated["summary"])
        self.assertIn("显示原文", translated["summary"])

    def test_extension_requests_temporary_access_for_cross_origin_images(self) -> None:
        script = (
            "const fs=require('fs');"
            "global.chrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(){}},onMessage:{addListener(){}},onConnect:{addListener(){}},lastError:null},"
            "contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(){}}},action:{onClicked:{addListener(){}}},"
            "windows:{onRemoved:{addListener(){}}},notifications:{onButtonClicked:{addListener(){}}}};"
            "eval(fs.readFileSync(process.argv[1],'utf8'));"
            "const preview=LBrainCaptureWorker.previewFor({title:'Article',origin:'https://canonical.invalid/post',capture_kind:'article',preview_characters:10,remote_assets:["
            "{url:'https://cdn.invalid/image.png',name:'images/image.png',media_type:'image/png'},"
            "{url:'https://files.invalid/report.pdf',name:'documents/report.pdf',media_type:'application/pdf'},"
            "{url:'https://canonical.invalid/figure.png',name:'images/figure.png',media_type:'image/png'},"
            "{url:'https://media.invalid/video.mp4',name:'video.mp4',media_type:'video/mp4'},"
            "{url:'https://*/wildcard.png',name:'images/wildcard.png',media_type:'image/png'},"
            "{url:'https://*.example.com/wildcard.png',name:'images/subdomain-wildcard.png',media_type:'image/png'},"
            "{url:'https://article.invalid/local.png',name:'images/local.png',media_type:'image/png'}]},'https://article.invalid/current');"
            "console.log(JSON.stringify(preview.permission_origins));"
        )
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            ["https://cdn.invalid/*", "https://files.invalid/*", "https://canonical.invalid/*"],
        )

    def test_native_receiver_rewrites_markdown_safe_pipe_urls(self) -> None:
        spec = importlib.util.spec_from_file_location("capture_host_pipe_url", CAPTURE_NATIVE_HOST)
        assert spec and spec.loader
        host = importlib.util.module_from_spec(spec)
        with mock.patch.object(sys, "path", [str(CAPTURE_NATIVE_HOST.parent), *sys.path]):
            spec.loader.exec_module(host)
        self.assertEqual(
            host.replace_exact_url(
                "[Pipe link](https://example.invalid/a%7Cb)",
                "https://example.invalid/a|b",
                "lbrain-asset://asset-1",
            ),
            "[Pipe link](lbrain-asset://asset-1)",
        )
        webp = b"RIFF\x04\x00\x00\x00WEBP"
        png = b"\x89PNG\r\n\x1a\n"
        vtt = b"WEBVTT\n\n00:00.000 --> 00:01.000\nCaption\n"
        self.assertEqual(host.permitted_media_type(webp, "image/webp", "image/jpeg"), "image/webp")
        self.assertEqual(host.permitted_media_type(png, "image/png", "image/jpeg"), "image/png")
        self.assertEqual(host.permitted_media_type(vtt, "text/plain", "text/vtt"), "text/vtt")
        self.assertEqual(host.permitted_media_type(b"plain text", "text/plain", "text/markdown"), "text/markdown")
        self.assertEqual(host.permitted_media_type(b"plain text", "text/plain", "text/plain"), "text/plain")
        self.assertEqual(host.permitted_media_type(b"<html>", "text/html", "text/plain"), "")
        self.assertEqual(host.permitted_media_type(b'{"error":"denied"}', "application/json", "image/jpeg"), "")
        self.assertEqual(host.permitted_media_type(b'{"error":"denied"}', "application/json", "application/pdf"), "")
        for declared in ("text/plain", "text/csv", "text/markdown", "text/vtt", "application/x-subrip"):
            self.assertEqual(host.permitted_media_type(b'{"error":"denied"}', "application/json", declared), "")
        self.assertEqual(
            host.stored_asset_name({"name": "images/photo.jpg"}, "image/webp"),
            "images/photo.webp",
        )
        self.assertEqual(
            host.stored_asset_name({"name": "documents/report.docx"}, "application/pdf"),
            "documents/report.pdf",
        )

    def test_extension_cancelled_confirmation_has_no_native_write(self) -> None:
        script = r'''
const fs=require("fs"),{webcrypto}=require("crypto");
let messageHandler,connectHandler,nativeWrites=0,calls=0;const cached={},shared={};
const session={async get(key){return{[key]:shared[key]}},async set(values){Object.assign(shared,values)},
  async remove(key){delete shared[key]}};
global.caches={async open(){return{async put(key,response){cached[key]=await response.text()},
  async match(key){return cached[key]===undefined?undefined:new Response(cached[key])},
  async delete(key){delete cached[key]}}},async delete(){}};
global.chrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(){}},
  onMessage:{addListener(fn){messageHandler=fn}},onConnect:{addListener(fn){connectHandler=fn}},getURL(value){return"chrome-extension://test/"+value},
  lastError:null,connectNative(){nativeWrites++}},contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(){}}},
  action:{onClicked:{addListener(){}}},storage:{session,local:{async get(){return{}},async remove(){},async set(){}}},
  scripting:{async executeScript(){calls++;if(calls===1)return[{result:"text/html"}];if(calls===2)return[{}];
    return[{result:{schema:"lbrain.capture.v1",title:"Alpha School",summary:"Home",
      origin:"https://alpha.example.invalid/",scope:"page",author:"",published_at:"",
      content_markdown:"[Signed](https://cdn.invalid/report?X-Amz-Signature=fixture-secret)",capture_kind:"html",
      snapshot_html:"<a href='https://cdn.invalid/report?X-Amz-Signature=fixture-secret'>Alpha</a>",
      preview_characters:5,extraction_status:"complete",remote_assets:[{id:"signed",name:"documents/report.pdf",
        media_type:"application/pdf",url:"https://cdn.invalid/report?X-Amz-Signature=fixture-secret"}],assets:[]}}]}},
  windows:{onRemoved:{addListener(){}}},permissions:{async remove(){return true}},
  notifications:{async create(){throw new Error("unexpected notification")},onButtonClicked:{addListener(){}}}};
global.crypto=webcrypto;eval(fs.readFileSync(process.argv[1],"utf8"));
function send(message){return new Promise(resolve=>messageHandler(message,{},resolve))}
async function waitFor(predicate){for(let i=0;i<50;i++){if(predicate())return;await Promise.resolve()}throw new Error("not ready")}
(async()=>{const tab={id:7,url:"https://alpha.example.invalid/",title:"Alpha School"};
  const preparing=await send({type:"confirmation.prepare",tab,scope:"page"});
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.phase==="ready");
  const kind=shared["lbrain-popup-job-v1"].preview.details[0][1];
  const beforeClose={cached:Object.keys(cached).length,signed:Object.values(cached).join("").includes("fixture-secret")};
  let listener,disconnect;connectHandler({name:"lbrain-popup",onMessage:{addListener(fn){listener=fn}},
    onDisconnect:{addListener(fn){disconnect=fn}},postMessage(){}});listener({type:"watch",id:preparing.id});
  disconnect();await waitFor(()=>!shared["lbrain-popup-job-v1"]);
  console.log(JSON.stringify({nativeWrites,calls,beforeClose,cached:Object.keys(cached).length,kind,
    job:Boolean(shared["lbrain-popup-job-v1"])}))})()
  .catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "nativeWrites": 0,
                "calls": 3,
                "beforeClose": {"cached": 0, "signed": False},
                "cached": 0,
                "kind": "HTML 快照",
                "job": False,
            },
        )

    def test_extension_stream_waits_for_each_native_ack(self) -> None:
        script = (
            "const fs=require('fs');const nativeSetTimeout=setTimeout;global.setTimeout=(fn,ms)=>nativeSetTimeout(fn,ms===120000?50:ms);"
            "let messageHandler;let disconnectHandler;let inFlight=false;let overlap=false;let chunks=0;let hashes=true;"
            "const port={onMessage:{addListener(fn){messageHandler=fn}},onDisconnect:{addListener(fn){disconnectHandler=fn}},"
            "postMessage(message){if(message.type==='chunk'){if(inFlight)overlap=true;inFlight=true;chunks++;hashes=hashes&&/^[0-9a-f]{64}$/.test(message.sha256);"
            "setTimeout(()=>{inFlight=false;messageHandler({type:'ack',channel:message.channel,sequence:message.sequence})},1)}"
            "if(message.type==='end')setTimeout(()=>messageHandler({status:'saved',target:'Inbox/Captures/example.md',capture_id:'id',version:1}),80)}};"
            "global.chrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(){}},onMessage:{addListener(){}},onConnect:{addListener(){}},lastError:null,connectNative(){return port}},"
            "contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(){}}},action:{onClicked:{addListener(){}}},"
            "windows:{onRemoved:{addListener(){}}},notifications:{onButtonClicked:{addListener(){}}}};"
            "eval(fs.readFileSync(process.argv[1],'utf8'));"
            "const blob=new Blob([new Uint8Array(900000)]);const bytes={size:blob.size,reader:blob.stream().getReader()};"
            "LBrainCaptureWorker.streamCapture({schema:'lbrain.capture.v1'},{kind:'binary',mediaType:'application/pdf',bytes,attachments:[]})"
            ".then(result=>console.log(JSON.stringify({status:result.status,chunks,overlap,hashes})))"
            ".catch(error=>{console.error(error);process.exit(1)});"
        )
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["status"], "saved")
        self.assertGreaterEqual(output["chunks"], 4)
        self.assertFalse(output["overlap"])
        self.assertTrue(output["hashes"])

    def test_extension_reuses_partial_receipt_after_chrome_storage_round_trip(self) -> None:
        script = r'''
const fs=require("fs"),{webcrypto}=require("crypto");
const local={},payloads=[];
const persistedKey=value=>String(value).split("\0",1)[0];
const storage={
  async get(request){if(request===null)return{...local};const key=persistedKey(request);return local[key]===undefined?{}:{[key]:local[key]}},
  async set(values){for(const [key,value] of Object.entries(values))local[persistedKey(key)]=value},
  async remove(request){if(local[request]!==undefined)delete local[request];else delete local[persistedKey(request)]}
};
function connectNative(){let onMessage;const chunks=[];return{
  onMessage:{addListener(fn){onMessage=fn}},onDisconnect:{addListener(){}},disconnect(){},
  postMessage(message){
    if(message.type==="chunk"){
      if(message.channel==="payload")chunks.push(Buffer.from(message.data,"base64"));
      queueMicrotask(()=>onMessage({type:"ack",channel:message.channel,sequence:message.sequence}));
    }
    if(message.type==="end"){
      const payload=JSON.parse(Buffer.concat(chunks).toString());payloads.push(payload);
      const recovered=Boolean(payload.recovery_target&&payload.expected_hash);
      queueMicrotask(()=>onMessage({
        status:payloads.length===1?"partial":recovered?"saved":"new_version",
        target:payloads.length===1?"Inbox/Captures/recovery.md":recovered?payload.recovery_target:"Inbox/Captures/recovery-v2.md",
        capture_id:"recovery",version:payloads.length===1||recovered?1:2,
        expected_hash:"a".repeat(64),source_content_hash:payload.source_content_hash
      }));
    }
  }
}};
global.chrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(){}},onMessage:{addListener(){}},
  onConnect:{addListener(){}},lastError:null,connectNative},contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(){}}},
  action:{onClicked:{addListener(){}}},windows:{onRemoved:{addListener(){}}},
  storage:{local:storage,session:{async set(){}}},notifications:{async create(){},onButtonClicked:{addListener(){}}}};
global.crypto=webcrypto;
eval(fs.readFileSync(process.argv[1],"utf8"));
const capture={schema:"lbrain.capture.v1",title:"Recovery",summary:"Recovery",origin:"https://example.invalid/recovery/",
  scope:"page",author:"",published_at:"",content_markdown:"Recovery body",capture_kind:"video",
  extraction_status:"complete",remote_assets:[]};
(async()=>{
  const first=await LBrainCaptureWorker.savePrepared({id:7,url:capture.origin,title:capture.title},capture);
  const retryCapture={...capture,origin:"https://example.invalid/recovery"};
  const second=await LBrainCaptureWorker.savePrepared(
    {id:7,url:retryCapture.origin,title:retryCapture.title},retryCapture);
  const legacyCapture={...capture,title:"Legacy recovery",summary:"Legacy recovery",
    origin:"https://example.invalid/legacy-recovery",content_markdown:"Legacy recovery body"};
  const legacyPayload=await LBrainCaptureWorker.preparePayload(legacyCapture);
  const legacyIdentity=`${legacyCapture.origin}\0${legacyCapture.scope}`;
  const legacyId=Buffer.from(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(legacyIdentity))).toString("hex");
  const legacyKey=`capture-recovery:${legacyCapture.origin}///`;
  local[legacyKey]={recovery_target:`Inbox/Captures/legacy-recovery-${legacyId.slice(0,8)}.md`,expected_hash:"b".repeat(64),
    source_content_hash:legacyPayload.source_content_hash};
  const legacy=await LBrainCaptureWorker.savePrepared(
    {id:8,url:legacyCapture.origin,title:legacyCapture.title},legacyCapture);
  const jsonCapture={...capture,title:"JSON recovery",summary:"JSON recovery",
    origin:"https://example.invalid/json-recovery/",content_markdown:"JSON recovery body"};
  const jsonRetry={...jsonCapture,origin:"https://example.invalid/json-recovery"};
  const jsonPayload=await LBrainCaptureWorker.preparePayload(jsonRetry);
  const jsonIdentity=`${jsonRetry.origin}\0${jsonRetry.scope}`;
  const jsonId=Buffer.from(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(jsonIdentity))).toString("hex");
  const jsonKey=`capture-recovery:${JSON.stringify([jsonCapture.origin,jsonCapture.scope])}`;
  local[jsonKey]={recovery_target:`Inbox/Captures/json-recovery-${jsonId.slice(0,8)}.md`,
    expected_hash:"f".repeat(64),source_content_hash:jsonPayload.source_content_hash};
  const jsonRecovery=await LBrainCaptureWorker.savePrepared(
    {id:9,url:jsonRetry.origin,title:jsonRetry.title},jsonRetry);
  const nulCapture={...capture,title:"NUL recovery",summary:"NUL recovery",
    origin:"https://example.invalid/nul-recovery",content_markdown:"NUL recovery body"};
  const nulPayload=await LBrainCaptureWorker.preparePayload(nulCapture);
  const nulIdentity=`${nulCapture.origin}\0${nulCapture.scope}`;
  const nulId=Buffer.from(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(nulIdentity))).toString("hex");
  const nulKey=`capture-recovery:${nulIdentity}`;
  local[nulKey]={recovery_target:`Inbox/Captures/nul-recovery-${nulId.slice(0,8)}.md`,
    expected_hash:"1".repeat(64),source_content_hash:nulPayload.source_content_hash};
  const nulRecovery=await LBrainCaptureWorker.savePrepared(
    {id:10,url:nulCapture.origin,title:nulCapture.title},nulCapture);
  const wrongScopeCapture={...capture,title:"Wrong scope",summary:"Wrong scope",
    origin:"https://example.invalid/wrong-scope",content_markdown:"Wrong scope body"};
  const wrongScopePayload=await LBrainCaptureWorker.preparePayload(wrongScopeCapture);
  const selectionIdentity=`${wrongScopeCapture.origin}\0selection`;
  const selectionId=Buffer.from(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(selectionIdentity))).toString("hex");
  const wrongScopeKey=`capture-recovery:${wrongScopeCapture.origin}`;
  local[wrongScopeKey]={recovery_target:`Inbox/Captures/wrong-scope-${selectionId.slice(0,8)}.md`,
    expected_hash:"c".repeat(64),source_content_hash:wrongScopePayload.source_content_hash};
  const wrongScope=await LBrainCaptureWorker.savePrepared(
    {id:11,url:wrongScopeCapture.origin,title:wrongScopeCapture.title},wrongScopeCapture);
  const staleCapture={...capture,title:"Stale recovery",summary:"Stale recovery",
    origin:"https://example.invalid/stale-recovery",content_markdown:"Changed body"};
  const staleIdentity=`${staleCapture.origin}\0${staleCapture.scope}`;
  const staleId=Buffer.from(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(staleIdentity))).toString("hex");
  const staleKey=`capture-recovery:${staleCapture.origin}`;
  local[staleKey]={recovery_target:`Inbox/Captures/stale-recovery-${staleId.slice(0,8)}.md`,
    expected_hash:"d".repeat(64),source_content_hash:"e".repeat(64)};
  const stale=await LBrainCaptureWorker.savePrepared(
    {id:12,url:staleCapture.origin,title:staleCapture.title},staleCapture);
  console.log(JSON.stringify({first:first.status,second:second.status,version:second.version,
    recovery_target:payloads[1].recovery_target,expected_hash:payloads[1].expected_hash,
    legacy:legacy.status,legacy_version:legacy.version,legacy_recovery_target:payloads[2].recovery_target,
    legacy_expected_hash:payloads[2].expected_hash,legacy_removed:local[legacyKey]===undefined,
    json:jsonRecovery.status,json_recovery_target:payloads[3].recovery_target,
    json_removed:local[jsonKey]===undefined,nul:nulRecovery.status,
    nul_recovery_target:payloads[4].recovery_target,nul_removed:local[nulKey]===undefined,
    wrong_scope:wrongScope.status,wrong_scope_recovery_target:payloads[5].recovery_target||null,
    wrong_scope_preserved:local[wrongScopeKey]!==undefined,stale:stale.status,
    stale_recovery_target:payloads[6].recovery_target||null,stale_removed:local[staleKey]===undefined}));
})().catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "first": "partial",
                "second": "saved",
                "version": 1,
                "recovery_target": "Inbox/Captures/recovery.md",
                "expected_hash": "a" * 64,
                "legacy": "saved",
                "legacy_version": 1,
                "legacy_recovery_target": "Inbox/Captures/legacy-recovery-"
                + hashlib.sha256(b"https://example.invalid/legacy-recovery\0page").hexdigest()[:8]
                + ".md",
                "legacy_expected_hash": "b" * 64,
                "legacy_removed": True,
                "json": "saved",
                "json_recovery_target": "Inbox/Captures/json-recovery-"
                + hashlib.sha256(b"https://example.invalid/json-recovery\0page").hexdigest()[:8]
                + ".md",
                "json_removed": True,
                "nul": "saved",
                "nul_recovery_target": "Inbox/Captures/nul-recovery-"
                + hashlib.sha256(b"https://example.invalid/nul-recovery\0page").hexdigest()[:8]
                + ".md",
                "nul_removed": True,
                "wrong_scope": "new_version",
                "wrong_scope_recovery_target": None,
                "wrong_scope_preserved": True,
                "stale": "new_version",
                "stale_recovery_target": None,
                "stale_removed": True,
            },
        )

    def test_extension_retries_without_mhtml_when_its_stream_cannot_be_read(self) -> None:
        script = (
            "const fs=require('fs');let listeners=[];let attempts=0;let ended=[],channels=[[],[]];"
            "function port(){const index=attempts++;let onMessage;return{onMessage:{addListener(fn){onMessage=fn}},"
            "onDisconnect:{addListener(){}},disconnect(){},postMessage(message){"
            "if(message.type==='chunk'){channels[index].push(message.channel);queueMicrotask(()=>onMessage({type:'ack',channel:message.channel,sequence:message.sequence}))};"
            "if(message.type==='end'){ended.push(index);queueMicrotask(()=>onMessage({status:'saved',target:'Inbox/Captures/example.md',capture_id:'id',version:1}))}}}};"
            "global.chrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(){}},onMessage:{addListener(){}},onConnect:{addListener(){}},lastError:null,connectNative:port},"
            "contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(){}}},action:{onClicked:{addListener(){}}},"
            "windows:{onRemoved:{addListener(){}}},notifications:{onButtonClicked:{addListener(){}}}};"
            "eval(fs.readFileSync(process.argv[1],'utf8'));"
            "const broken={size:8,reader:{async read(){throw new Error('network error')},releaseLock(){}}};"
            "LBrainCaptureWorker.streamCaptureWithFallback({schema:'lbrain.capture.v1'},{kind:'mhtml',mediaType:'multipart/related',bytes:broken,attachments:[{id:'image',mediaType:'image/png',bytes:new Blob(['image'])}]})"
            ".then(result=>console.log(JSON.stringify({status:result.status,attempts,ended,secondAsset:channels[1].includes('asset:image')})))"
            ".catch(error=>{console.error(error);process.exit(1)});"
        )
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {"status": "saved", "attempts": 2, "ended": [1], "secondAsset": True},
        )

    def test_extension_creates_mhtml_after_fetching_attachments(self) -> None:
        script = (
            "const fs=require('fs');let fetched=false,snapshotAfterFetch=false,credentials='';"
            "global.fetch=async(_url,options)=>{fetched=true;credentials=options.credentials;return{ok:true,headers:{get(){return'image/png'}},async blob(){return new Blob(['image'])}}};"
            "global.chrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(){}},onMessage:{addListener(){}},onConnect:{addListener(){}},lastError:null},"
            "contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(){}}},action:{onClicked:{addListener(){}}},"
            "scripting:{async executeScript(){}},pageCapture:{saveAsMHTML(_options,done){snapshotAfterFetch=fetched;done(new Blob(['snapshot']))}},"
            "windows:{onRemoved:{addListener(){}}},notifications:{onButtonClicked:{addListener(){}}}};"
            "eval(fs.readFileSync(process.argv[1],'utf8'));"
            "LBrainCaptureWorker.snapshotFor({id:7,url:'https://evil.invalid/current'},{capture_kind:'article',origin:'https://example.invalid/canonical',remote_assets:[{id:'image',url:'https://example.invalid/image.png',name:'images/image.png',media_type:'image/png'}]})"
            ".then(snapshot=>console.log(JSON.stringify({snapshotAfterFetch,attachments:snapshot.attachments.length,streamed:Boolean(snapshot.bytes.reader),credentials})))"
            ".catch(error=>{console.error(error);process.exit(1)});"
        )
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout), {"snapshotAfterFetch": True, "attachments": 1, "streamed": True, "credentials": "omit"}
        )

    def test_extension_does_not_follow_a_credentialed_cross_origin_redirect(self) -> None:
        script = (
            "const fs=require('fs');const calls=[];"
            "global.fetch=async(_url,options)=>{calls.push({credentials:options.credentials,redirect:options.redirect||'follow'});"
            "if(options.credentials==='include')throw new TypeError('redirect blocked');"
            "return{ok:true,headers:{get(){return'image/png'}},async blob(){return new Blob(['image'])}}};"
            "global.chrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(){}},onMessage:{addListener(){}},onConnect:{addListener(){}},lastError:null},"
            "contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(){}}},action:{onClicked:{addListener(){}}},"
            "scripting:{async executeScript(){}},pageCapture:{saveAsMHTML(_options,done){done(new Blob(['snapshot']))}},"
            "windows:{onRemoved:{addListener(){}}},notifications:{onButtonClicked:{addListener(){}}}};"
            "eval(fs.readFileSync(process.argv[1],'utf8'));"
            "LBrainCaptureWorker.snapshotFor({id:7,url:'https://article.invalid/post'},{capture_kind:'article',origin:'https://article.invalid/post',remote_assets:[{id:'image',url:'https://article.invalid/redirect',name:'images/image.png',media_type:'image/png'}]})"
            ".then(snapshot=>console.log(JSON.stringify({calls,attachments:snapshot.attachments.length})))"
            ".catch(error=>{console.error(error);process.exit(1)});"
        )
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "calls": [
                {"credentials": "include", "redirect": "error"},
                {"credentials": "omit", "redirect": "follow"},
            ],
            "attachments": 1,
        })

    def test_extension_keeps_fetched_assets_when_mhtml_is_unavailable(self) -> None:
        script = (
            "const fs=require('fs');let credentials='';"
            "global.fetch=async(_url,options)=>{credentials=options.credentials;return{ok:true,headers:{get(){return'image/png'}},async blob(){return new Blob(['image'])}}};"
            "let mhtmlCalls=0;"
            "global.chrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(){}},onMessage:{addListener(){}},onConnect:{addListener(){}},lastError:{message:'network error'}},"
            "contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(){}}},action:{onClicked:{addListener(){}}},"
            "scripting:{async executeScript(){}},pageCapture:{saveAsMHTML(){mhtmlCalls+=1;throw new Error('network error')}},"
            "windows:{onRemoved:{addListener(){}}},notifications:{onButtonClicked:{addListener(){}}}};"
            "eval(fs.readFileSync(process.argv[1],'utf8'));"
            "LBrainCaptureWorker.snapshotFor({id:7,url:'https://article.invalid/post'},{capture_kind:'html',origin:'https://article.invalid/post',remote_assets:[{id:'image',url:'https://article.invalid/image.png',name:'images/image.png',media_type:'image/png'}]})"
            ".then(snapshot=>console.log(JSON.stringify({kind:snapshot.kind,attachments:snapshot.attachments.length,bytes:snapshot.bytes.length,mhtmlCalls,credentials})))"
            ".catch(error=>{console.error(error);process.exit(1)});"
        )
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {"kind": "none", "attachments": 1, "bytes": 0, "mhtmlCalls": 0, "credentials": "include"},
        )

    def test_extension_bounds_attachment_fetch_time(self) -> None:
        script = (
            "const fs=require('fs');const timeouts=[];let bounded=0,active=0,maxActive=0;"
            "global.AbortSignal={timeout(value){timeouts.push(value);return{aborted:false}}};"
            "global.fetch=async(_url,options)=>{bounded+=Number(Boolean(options.signal));active++;maxActive=Math.max(maxActive,active);"
            "await new Promise(resolve=>setTimeout(resolve,5));active--;throw new Error('offline')};"
            "global.chrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(){}},onMessage:{addListener(){}},onConnect:{addListener(){}},lastError:null},"
            "contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(){}}},action:{onClicked:{addListener(){}}},"
            "scripting:{async executeScript(){}},windows:{onRemoved:{addListener(){}}},notifications:{onButtonClicked:{addListener(){}}}};"
            "eval(fs.readFileSync(process.argv[1],'utf8'));"
            "Promise.allSettled([LBrainCaptureWorker.snapshotFor({id:7,url:'https://article.invalid/post'},{capture_kind:'html',origin:'https://article.invalid/post',remote_assets:[{id:'image',url:'https://cdn.invalid/image.png',name:'images/image.png',media_type:'image/png'},{id:'document',url:'https://files.invalid/report.pdf',name:'documents/report.pdf',media_type:'application/pdf'}]}),"
            "LBrainCaptureWorker.snapshotFor({id:8,url:'https://files.invalid/report.pdf'},{capture_kind:'document',origin:'https://files.invalid/report.pdf',remote_assets:[{id:'direct-document',url:'https://files.invalid/report.pdf',name:'documents/report.pdf',media_type:'application/pdf'}]})])"
            ".then(results=>console.log(JSON.stringify({timeouts,bounded,maxActive,attachments:results[0].value.attachments.length,direct:results[1].status})))"
            ".catch(error=>{console.error(error);process.exit(1)});"
        )
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout), {"timeouts": [30000, 30000], "bounded": 4, "maxActive": 2, "attachments": 0, "direct": "rejected"}
        )

    def test_extension_bounds_media_before_materializing_or_connecting(self) -> None:
        script = r'''
const fs=require("fs");let headerReads=0,headerCancelled=false,cancelled=false,released=false,nativeConnections=0;
global.fetch=async()=>({ok:true,headers:{get(name){
  if(name==="content-type")return"application/pdf";
  if(name==="content-length")return"268435457";
  return null}},body:{async cancel(){headerCancelled=true},getReader(){headerReads++;throw new Error("oversized body was read")}}});
global.chrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(){}},onMessage:{addListener(){}},
  onConnect:{addListener(){}},lastError:null,connectNative(){nativeConnections++;throw new Error("unexpected native connection")}},
  contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(){}}},action:{onClicked:{addListener(){}}},
  windows:{onRemoved:{addListener(){}}},notifications:{onButtonClicked:{addListener(){}}}};
eval(fs.readFileSync(process.argv[1],"utf8"));
async function error(promise){try{await promise;return""}catch(reason){return String(reason.message||reason)}}
const chunks=[new Uint8Array([1,2,3]),new Uint8Array([4,5])];let index=0;
const streamed={headers:{get(name){return name==="content-type"?"application/octet-stream":null}},body:{getReader(){return{
  async read(){return index<chunks.length?{done:false,value:chunks[index++]}:{done:true}},
  async cancel(){cancelled=true},releaseLock(){released=true}}}}};
(async()=>{const direct=await error(LBrainCaptureWorker.snapshotFor(
  {id:7,url:"https://files.invalid/report.pdf"},
  {capture_kind:"document",origin:"https://files.invalid/report.pdf",remote_assets:[]}
));
const bounded=await error(LBrainCaptureWorker.responseBlobWithin(streamed,4));
const oversized={size:268435457,reader:{async read(){return{done:true}},releaseLock(){}}};
const preflight=await error(LBrainCaptureWorker.streamCapture(
  {schema:"lbrain.capture.v1"},
  {kind:"binary",mediaType:"application/pdf",bytes:oversized,attachments:[]}
));
console.log(JSON.stringify({direct,bounded,headerReads,headerCancelled,cancelled,released,nativeConnections,preflight}))})()
  .catch(reason=>{console.error(reason);process.exit(1)});
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertIn("256 MiB", output["direct"])
        self.assertIn("256 MiB", output["bounded"])
        self.assertIn("256 MiB", output["preflight"])
        self.assertEqual(
            {key: output[key] for key in ("headerReads", "headerCancelled", "cancelled", "released", "nativeConnections")},
            {"headerReads": 0, "headerCancelled": True, "cancelled": True, "released": True, "nativeConnections": 0},
        )

    def test_native_receiver_enforces_stream_limits_and_disk_reserve(self) -> None:
        spec = importlib.util.spec_from_file_location("capture_host_limits", CAPTURE_NATIVE_HOST)
        assert spec and spec.loader
        host = importlib.util.module_from_spec(spec)
        with mock.patch.object(sys, "path", [str(CAPTURE_NATIVE_HOST.parent), *sys.path]):
            spec.loader.exec_module(host)
        payload = b"{}"
        base = {
            "protocol": host.STREAM_PROTOCOL,
            "type": "begin",
            "acknowledgements": True,
            "integrity": "sha256-chunks",
            "stream_id": "limits",
            "payload_size": len(payload),
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "snapshot_size": 0,
            "snapshot_sha256": "",
            "snapshot_kind": "none",
            "snapshot_media_type": "application/octet-stream",
            "attachments": [],
        }
        attachment = {"id": "asset", "size": 0, "sha256": "", "media_type": "image/png"}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with self.assertRaisesRegex(host.OperationError, "size limit"):
                host.receive_stream(
                    {**base, "snapshot_size": host.MAX_CAPTURE_ASSET_BYTES + 1},
                    io.BytesIO(), io.BytesIO(), directory,
                )
            with self.assertRaisesRegex(host.OperationError, "metadata"):
                host.receive_stream(
                    {**base, "attachments": [{**attachment, "size": host.MAX_CAPTURE_ASSET_BYTES + 1}]},
                    io.BytesIO(), io.BytesIO(), directory,
                )
            with self.assertRaisesRegex(host.OperationError, "aggregate size"):
                host.receive_stream(
                    {
                        **base,
                        "snapshot_size": host.MAX_CAPTURE_ASSET_BYTES,
                        "attachments": [
                            {**attachment, "size": host.MAX_CAPTURE_ASSET_BYTES},
                        ],
                    },
                    io.BytesIO(), io.BytesIO(), directory,
                )
            with mock.patch.object(
                host.shutil,
                "disk_usage",
                return_value=mock.Mock(free=len(payload) + host.CAPTURE_DISK_RESERVE_BYTES - 1),
            ), self.assertRaisesRegex(host.OperationError, "disk space"):
                host.receive_stream(base, io.BytesIO(), io.BytesIO(), directory)

    def test_capture_bundle_preserves_disk_reserve_before_finalizing(self) -> None:
        spec = importlib.util.spec_from_file_location("capture_operations_disk_reserve", CAPTURE_OPERATIONS)
        assert spec and spec.loader
        operations = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(operations)
        payload = {
            "schema": "lbrain.capture.v1",
            "title": "Disk reserve",
            "summary": "The Bundle must leave a safe disk reserve.",
            "origin": "https://example.invalid/disk-reserve",
            "scope": "page",
            "content_markdown": "Synthetic body.",
            "extraction_status": "complete",
            "assets": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            with mock.patch.object(
                operations.shutil,
                "disk_usage",
                return_value=mock.Mock(free=operations.CAPTURE_DISK_RESERVE_BYTES),
            ), self.assertRaisesRegex(operations.OperationError, "disk space"):
                operations.capture_bundle(root, payload, None)
            self.assertEqual(list((root / "Inbox/Captures").glob("*Disk-reserve*.md")), [])

    def test_native_receiver_does_not_hold_every_attachment_open(self) -> None:
        script = r'''
import hashlib, importlib.util, io, json, resource, struct, sys, tempfile
from pathlib import Path
host = Path(sys.argv[1])
sys.path.insert(0, str(host.parent))
spec = importlib.util.spec_from_file_location("capture_host_fd", host)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
resource.setrlimit(resource.RLIMIT_NOFILE, (64, resource.getrlimit(resource.RLIMIT_NOFILE)[1]))
payload = b"{}"
empty = hashlib.sha256(b"").hexdigest()
attachments = [{"id": f"a{i}", "size": 0, "sha256": empty, "media_type": "image/png"} for i in range(130)]
first = {"protocol": module.STREAM_PROTOCOL, "type": "begin", "acknowledgements": True,
    "integrity": "sha256-chunks", "stream_id": "fd", "payload_size": len(payload),
    "payload_sha256": hashlib.sha256(payload).hexdigest(), "snapshot_size": 0, "snapshot_sha256": empty,
    "snapshot_kind": "none", "snapshot_media_type": "application/octet-stream",
    "attachments": attachments}
chunk = json.dumps({"protocol": module.STREAM_PROTOCOL, "type": "chunk", "stream_id": "fd",
    "channel": "payload", "sequence": 0, "data": "e30=", "sha256": hashlib.sha256(payload).hexdigest()}).encode()
end = json.dumps({"protocol": module.STREAM_PROTOCOL, "type": "end", "stream_id": "fd"}).encode()
framed = io.BytesIO(struct.pack("=I", len(chunk)) + chunk + struct.pack("=I", len(end)) + end)
with tempfile.TemporaryDirectory() as temporary:
    result = module.receive_stream(first, framed, io.BytesIO(), Path(temporary))
    print(len(result[-1]))
'''
        result = subprocess.run(
            [sys.executable, "-c", script, str(CAPTURE_NATIVE_HOST)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "130")

    def test_bundle_escapes_untrusted_metadata_and_extracted_text(self) -> None:
        spec = importlib.util.spec_from_file_location("capture_operations_markdown_text", CAPTURE_OPERATIONS)
        assert spec and spec.loader
        operations = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(operations)
        beacon = "![beacon](https://tracker.invalid/pixel.png)"
        rendered = operations.render_bundle(
            beacon, "summary", f"https://example.invalid/{beacon}", "page", "Safe body.",
            beacon, beacon, "complete", "capture-id", "a" * 64, "b" * 64, 1,
            "Inbox/Captures/_assets/capture-id/v1/manifest.json", [], "", beacon,
        )
        markdown = rendered.split("---\n", 2)[2]
        self.assertNotIn(beacon, markdown)
        self.assertIn(r"\!\[beacon\]", markdown)
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "captions.vtt"
            source.write_text(
                f"WEBVTT\n\n00:00 --> 00:01\n{beacon}\n<img src=https://tracker.invalid/html>\n",
                encoding="utf-8",
            )
            enriched, _ = operations.enriched_bundle_content("Safe body.", [{
                "name": "captions.vtt", "media_type": "text/vtt", "_source": source
            }])
        self.assertNotIn(beacon, enriched)
        self.assertNotIn("<img", enriched)
        self.assertIn(r"\!\[beacon\]", enriched)

    def test_binary_disclosure_uses_full_parser_only_for_sensitive_chunks(self) -> None:
        spec = importlib.util.spec_from_file_location("capture_operations_binary_scan", CAPTURE_OPERATIONS)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        operations = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(operations)
        with tempfile.TemporaryDirectory() as temporary:
            asset = Path(temporary) / "document.bin"
            asset.write_bytes(b"%PDF-1.7\n" + b"ordinary document bytes\n" * 1000)
            with mock.patch.object(operations, "reject_secrets") as reject, mock.patch.object(
                operations.shutil, "which", return_value=None
            ):
                operations.reject_binary_secret_file(ROOT, asset, "application/octet-stream")
            reject.assert_not_called()

            asset.write_bytes(b'prefix api_key = "fixture-secret-value-12345" suffix')
            with mock.patch.object(operations, "reject_secrets") as reject:
                operations.reject_binary_secret_file(ROOT, asset, "application/octet-stream")
            reject.assert_called()

    def test_extension_popup_renders_immediately_and_maps_save_states(self) -> None:
        html = (CAPTURE_EXTENSION / "confirm.html").read_text(encoding="utf-8")
        self.assertIn('data-phase="preparing"', html)
        self.assertNotIn("aria-busy", html)
        script = r'''
const fs=require("fs"),vm=require("vm");
const source=fs.readFileSync(process.argv[1],"utf8");
const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done});return{promise,resolve}};
const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve()};
async function scenario(status){
  const listeners={},nodes={},sent=[];
  const element=id=>nodes[id]||(nodes[id]={id,textContent:"",disabled:false,hidden:false,dataset:{},attributes:{},
    addEventListener(type,fn){listeners[`${id}:${type}`]=fn},append(){},replaceChildren(){this.textContent=""},
    setAttribute(name,value){this.attributes[name]=String(value)},removeAttribute(name){delete this.attributes[name]},
    classList:{add(){},remove(){},toggle(){}}});
  const body=element("body");body.dataset.phase="preparing";
  const document={body,querySelector(selector){return selector==="body"?body:element(selector.replace(/^#/,""))},
    createElement(tag){return element(`created-${tag}-${Object.keys(nodes).length}`)}};
  let prepare,decide,portListener,prepareCount=0;
  const tab={id:7,title:"Rendered article",url:"https://example.invalid/article"};
  const ready={id:"job-1",phase:"ready",tab,preview:{title:"Rendered article",summary:"Readable body",
    permission_origins:[],details:[["保存内容","文章正文"]]}};
  const chrome={tabs:{async query(){return[tab]}},runtime:{
    connect(options){if(options.name!=="lbrain-popup")throw new Error("wrong port");return{
      onMessage:{addListener(fn){portListener=fn}},postMessage(message){sent.push(message)},disconnect(){}}},
    sendMessage(message){sent.push(message);
      if(message.type==="confirmation.prepare"){
        if(++prepareCount===1){prepare=deferred();return prepare.promise}
        return Promise.resolve({id:"job-2",phase:"preparing",tab})}
      if(message.type==="confirmation.preflight")return Promise.resolve({reserved:true,missing:[]});
      if(message.type==="confirmation.permissions")return Promise.resolve({recorded:true});
      if(message.type==="confirmation.decide"){decide=deferred();return decide.promise}
      if(message.type==="confirmation.cancel")return Promise.resolve({cancelled:true});
      throw new Error(`unexpected ${message.type}`)}},
    permissions:{async contains(){return true},async request(){return true},async remove(){return true}}};
  const context={chrome,document,location:{search:""},window:{close(){}},URLSearchParams,URL,Response,console,
    setTimeout,clearTimeout,queueMicrotask};
  vm.createContext(context);vm.runInContext(source,context);
  const initial={phase:body.dataset.phase,saveDisabled:element("save").disabled};
  await settle();
  const prepareBeforeExtraction={phase:body.dataset.phase,saveDisabled:element("save").disabled,
    requested:sent.find(message=>message.type==="confirmation.prepare")};
  const prepared=status==="preparation_failed"
    ? {id:"job-1",phase:"failed",tab,error:"extraction unavailable"}
    : ready;
  prepare.resolve(prepared);await settle();
  if(portListener)portListener(prepared);await settle();
  if(status==="preparation_failed")return{initial,prepareBeforeExtraction,preparationFailure:{
    phase:body.dataset.phase,title:element("status-title").textContent,message:element("status-message").textContent}};
  const readyState={phase:body.dataset.phase,saveDisabled:element("save").disabled};
  const click=listeners["save:click"]();
  const saving={phase:body.dataset.phase,saveDisabled:element("save").disabled,detailsHidden:element("details").hidden,
    message:element("status-message").textContent};
  if(portListener)portListener({type:"job",job:{...ready,phase:"saving"}});await settle();
  const backgroundSaving={phase:body.dataset.phase,message:element("status-message").textContent};
  await settle();
  const terminal=status==="failed"
    ? {id:"job-1",phase:"failed",tab,error:"disk unavailable"}
    : {id:"job-1",phase:"complete",tab,receipt:{status,target:"Inbox/Captures/article.md",capture_id:"article",version:1}};
  decide.resolve(terminal);await click;await settle();
  if(portListener)portListener(terminal);await settle();
  const final={phase:body.dataset.phase,text:Object.values(nodes).map(node=>node.textContent).join(" "),
    saveDisabled:element("save").disabled,actionsHidden:element("actions").hidden,saveText:element("save").textContent};
  let repeat=null;
  if(status!=="failed"){
    const offset=sent.length;await listeners["save:click"]();await settle();
    const afterPrepare=body.dataset.phase;const repeated=sent.slice(offset);
    const readyAgain={...ready,id:"job-2"};
    if(portListener)portListener({type:"job",job:readyAgain});await settle();
    repeat={afterPrepare,watched:repeated.some(message=>message.type==="watch"&&message.id==="job-2"),
      messages:repeated.filter(message=>message.type?.startsWith("confirmation.")),
      readyPhase:body.dataset.phase,saveDisabled:element("save").disabled};
  }
  return{initial,prepareBeforeExtraction,readyState,saving,backgroundSaving,final,repeat,
    watched:sent.some(message=>message.type==="watch"&&message.id==="job-1")};
}
(async()=>console.log(JSON.stringify({saved:await scenario("saved"),already:await scenario("already_saved"),
  partial:await scenario("partial"),failed:await scenario("failed"),prepareFailed:await scenario("preparation_failed")})))()
  .catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "confirm.js")],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        for scenario in (output["saved"], output["already"], output["failed"]):
            self.assertEqual(scenario["initial"], {"phase": "preparing", "saveDisabled": True})
            self.assertEqual(scenario["prepareBeforeExtraction"]["phase"], "preparing")
            self.assertTrue(scenario["prepareBeforeExtraction"]["saveDisabled"])
            self.assertEqual(scenario["prepareBeforeExtraction"]["requested"], {
                "type": "confirmation.prepare",
                "tab": {"id": 7, "title": "Rendered article", "url": "https://example.invalid/article"},
                "scope": "page",
            })
            self.assertEqual(scenario["readyState"], {"phase": "ready", "saveDisabled": False})
            self.assertEqual(scenario["saving"]["phase"], "saving")
            self.assertTrue(scenario["saving"]["saveDisabled"])
            self.assertTrue(scenario["saving"]["detailsHidden"])
            self.assertIn("正在交给 LBrain 保存", scenario["saving"]["message"])
            self.assertNotIn("关闭弹窗也会继续", scenario["saving"]["message"])
            self.assertEqual(scenario["backgroundSaving"]["phase"], "saving")
            self.assertIn("关闭弹窗也会继续", scenario["backgroundSaving"]["message"])
            self.assertTrue(scenario["watched"])
        self.assertEqual(output["saved"]["final"]["phase"], "complete")
        self.assertIn("保存成功", output["saved"]["final"]["text"])
        self.assertFalse(output["saved"]["final"]["saveDisabled"])
        self.assertFalse(output["saved"]["final"]["actionsHidden"])
        self.assertIn("再次保存", output["saved"]["final"]["saveText"])
        self.assertEqual(output["already"]["final"]["phase"], "complete")
        self.assertIn("已保存", output["already"]["final"]["text"])
        self.assertIn("Inbox/Captures/article.md", output["already"]["final"]["text"])
        self.assertEqual(output["partial"]["final"]["phase"], "complete")
        self.assertIn("部分媒体缺失", output["partial"]["final"]["text"])
        self.assertIn("Inbox/Captures/article.md", output["partial"]["final"]["text"])
        for status in ("saved", "already"):
            self.assertEqual(output[status]["repeat"]["afterPrepare"], "preparing")
            self.assertTrue(output[status]["repeat"]["watched"])
            self.assertEqual(output[status]["repeat"]["readyPhase"], "ready")
            self.assertFalse(output[status]["repeat"]["saveDisabled"])
            self.assertEqual(output[status]["repeat"]["messages"], [
                {"type": "confirmation.cancel", "id": "job-1"},
                {
                    "type": "confirmation.prepare",
                    "tab": {"id": 7, "title": "Rendered article", "url": "https://example.invalid/article"},
                    "scope": "page",
                },
            ])
        self.assertEqual(output["failed"]["final"]["phase"], "failed")
        self.assertIn("disk unavailable", output["failed"]["final"]["text"])
        self.assertEqual(output["prepareFailed"]["preparationFailure"]["phase"], "failed")
        self.assertEqual(output["prepareFailed"]["preparationFailure"]["title"], "读取失败")
        self.assertIn("extraction unavailable", output["prepareFailed"]["preparationFailure"]["message"])

    def test_extension_popup_native_failure_repreflights_without_releasing_retry_lease(self) -> None:
        script = r'''
const fs=require("fs"),vm=require("vm");const source=fs.readFileSync(process.argv[1],"utf8");
const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done});return{promise,resolve}};
const settle=async()=>{for(let i=0;i<16;i++)await Promise.resolve()};
async function scenario(popup){
  const listeners={},nodes={},messages=[];let popupListener,preflights=0,decides=0,closes=0;
  const decideFailure=deferred(),secondPreflight=deferred();
  const element=id=>nodes[id]||(nodes[id]={textContent:"",disabled:false,hidden:false,dataset:{},
    addEventListener(type,fn){listeners[`${id}:${type}`]=fn},append(){},replaceChildren(){},setAttribute(){},removeAttribute(){},
    classList:{add(){},remove(){},toggle(){}}});
  const body=element("body");body.dataset.phase="preparing";
  const document={body,querySelector(selector){return selector==="body"?body:element(selector.replace(/^#/,""))},
    createElement(tag){return element(`created-${tag}-${Object.keys(nodes).length}`)}};
  const tab={id:7,title:"Saved",url:"https://example.invalid/article"};
  const preview={title:"Saved",summary:"",permission_origins:[],details:[]};
  const ready={id:popup?"popup":"legacy",phase:"ready",tab,preview};
  const chrome={tabs:{async query(){return[tab]}},runtime:{
    connect({name}){if(name==="lbrain-popup")return{onMessage:{addListener(fn){popupListener=fn}},postMessage(){},disconnect(){}};
      let listener;return{onMessage:{addListener(fn){listener=fn}},postMessage(){queueMicrotask(()=>listener({type:"preview",preview,
        capture:{schema:"lbrain.capture.v1"},tab}))},disconnect(){}}},
    async sendMessage(message){messages.push(message);
      if(message.type==="confirmation.prepare")return ready;
      if(message.type==="confirmation.preflight"){
        preflights++;if(popup&&preflights===2)return secondPreflight.promise;return{reserved:true,missing:[]}}
      if(message.type==="confirmation.reserve")return{reserved:true};
      if(message.type==="confirmation.decide"){
        decides++;if(decides===1){if(popup){
            queueMicrotask(()=>popupListener({type:"job",job:{...ready,phase:"failed",error:"native failed"}}));
            return decideFailure.promise}
          return{error:"native failed"}}
        return{id:"popup",phase:"complete",tab,receipt:{status:"saved",target:"Inbox/Captures/saved.md",capture_id:"saved",version:1}}}
      if(message.type==="confirmation.release")return{released:true};
      throw new Error(`unexpected ${message.type}`)}},windows:{async getCurrent(){return{id:19}}},
    permissions:{async contains(){return true},async request(){return true},async remove(){return true}}};
  const caches={async open(){return{async put(){},async delete(){}}}};
  const context={chrome,caches,document,location:{search:popup?"":"?id=legacy"},window:{close(){closes++}},URLSearchParams,URL,
    Response,console,setTimeout,clearTimeout,queueMicrotask};vm.createContext(context);vm.runInContext(source,context);await settle();
  const firstClick=listeners["save:click"]();let productionTiming=null;
  if(popup){
    await settle();const whilePreflight={phase:body.dataset.phase,preflights,saveDisabled:element("save").disabled};
    secondPreflight.resolve({reserved:true,missing:[]});await settle();
    const preflightFinished={phase:body.dataset.phase,preflights,saveDisabled:element("save").disabled};
    decideFailure.resolve({error:"native failed"});await firstClick;await settle();
    productionTiming={whilePreflight,preflightFinished,afterDecideError:preflights};
  }else{await firstClick;await settle()}
  const afterFailure={phase:body.dataset.phase,preflights,releases:messages.filter(value=>value.type==="confirmation.release").length,
    enabled:!element("save").disabled};
  await listeners["save:click"]();await settle();
  return{afterFailure,productionTiming,final:body.dataset.phase,decides,closes,
    releases:messages.filter(value=>value.type==="confirmation.release").length};
}
(async()=>console.log(JSON.stringify({popup:await scenario(true),legacy:await scenario(false)})))()
  .catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "confirm.js")],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["popup"]["afterFailure"], {
            "phase": "failed", "preflights": 2, "releases": 0, "enabled": True,
        })
        self.assertEqual(output["popup"]["productionTiming"], {
            "whilePreflight": {"phase": "failed", "preflights": 2, "saveDisabled": True},
            "preflightFinished": {"phase": "failed", "preflights": 2, "saveDisabled": False},
            "afterDecideError": 2,
        })
        self.assertEqual(output["popup"]["final"], "complete")
        self.assertEqual(output["popup"]["decides"], 2)
        self.assertEqual(output["popup"]["releases"], 0)
        self.assertEqual(output["legacy"]["afterFailure"], {
            "phase": "failed", "preflights": 2, "releases": 1, "enabled": True,
        })
        self.assertEqual(output["legacy"]["decides"], 2)
        self.assertEqual(output["legacy"]["closes"], 1)

    def test_extension_confirmation_releases_only_new_permissions(self) -> None:
        script = r'''
const fs=require("fs");const listeners={},nodes={},messages=[],events=[];
let requested,preflightResolve,permissionResolve,containsCalls=0;
const element=id=>nodes[id]||(nodes[id]={textContent:"",disabled:false,hidden:false,dataset:{},
  addEventListener(type,fn){listeners[`${id}:${type}`]=fn},append(){},replaceChildren(){},
  setAttribute(){},removeAttribute(){},classList:{add(){},remove(){},toggle(){}}});
const body=element("body");body.dataset.phase="preparing";
global.document={body,querySelector(selector){return selector==="body"?body:element(selector.replace(/^#/,""))},
  createElement(tag){return element(`created-${tag}-${Object.keys(nodes).length}`)}};
global.location={search:""};global.window={close(){}};
const tab={id:7,title:"Saved",url:"https://example.invalid/article"};
const ready={id:"stored",phase:"ready",tab,preview:{title:"Saved",summary:"",
  permission_origins:["https://existing.invalid/*","https://new.invalid/*"],details:[]}};
global.chrome={tabs:{async query(){return[tab]}},runtime:{connect(){return{onMessage:{addListener(){}},postMessage(){},disconnect(){}}},
  async sendMessage(message){messages.push(message);
    events.push(`runtime:${message.type}`);
    if(message.type==="confirmation.prepare")return ready;
    if(message.type==="confirmation.preflight")return new Promise(resolve=>{preflightResolve=resolve});
    if(message.type==="confirmation.arm")return{armed:true,started:false};
    if(message.type==="confirmation.permission_result")return{id:"stored",phase:"complete",tab,
      receipt:{status:"saved",target:"Inbox/Captures/saved.md",capture_id:"saved",version:1}};
    throw new Error(`unexpected ${message.type}`)}},
  permissions:{async contains(){containsCalls++;return false},request({origins}){events.push("permission.request");requested=origins;
      return new Promise(resolve=>{permissionResolve=resolve})},
    async remove(){throw new Error("worker owns permission cleanup")}}};
eval(fs.readFileSync(process.argv[1],"utf8"));
(async()=>{while(!preflightResolve)await Promise.resolve();const disabledBeforePreflight=nodes.save.disabled;
  const preflight=messages.find(value=>value.type==="confirmation.preflight");
  preflightResolve({reserved:true,missing:["https://new.invalid/*"]});for(let i=0;i<8;i++)await Promise.resolve();
  const enabledAfterPreflight=!nodes.save.disabled;const offset=events.length;const click=listeners["save:click"]();
  const immediate={events:events.slice(offset),phase:body.dataset.phase};permissionResolve(true);await click;
  const permissionResult=messages.find(value=>value.type==="confirmation.permission_result");
  console.log(JSON.stringify({requested,disabledBeforePreflight,enabledAfterPreflight,preflight,immediate,
    permissionResult,releases:messages.filter(value=>value.type==="confirmation.release").length,containsCalls}))})()
  .catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "confirm.js")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["requested"], ["https://new.invalid/*"])
        self.assertTrue(output["disabledBeforePreflight"])
        self.assertTrue(output["enabledAfterPreflight"])
        self.assertEqual(output["preflight"], {
            "type": "confirmation.preflight",
            "id": "stored",
            "window_id": None,
            "permission_origins": ["https://existing.invalid/*", "https://new.invalid/*"],
        })
        self.assertEqual(output["immediate"], {
            "events": ["runtime:confirmation.arm", "permission.request"],
            "phase": "saving",
        })
        self.assertEqual(output["permissionResult"], {
            "type": "confirmation.permission_result", "id": "stored", "granted": True,
        })
        self.assertEqual(output["releases"], 0)
        self.assertEqual(output["containsCalls"], 0)

    def test_extension_popup_reconnect_repreflights_after_worker_cleanup(self) -> None:
        script = r'''
const fs=require("fs"),vm=require("vm");const source=fs.readFileSync(process.argv[1],"utf8");
const settle=async()=>{for(let i=0;i<20;i++)await Promise.resolve()};
const listeners={},nodes={},disconnects=[],watches=[];let connects=0,preflights=0,decides=0,lease=false;
const element=id=>nodes[id]||(nodes[id]={textContent:"",disabled:false,hidden:false,dataset:{},
  addEventListener(type,fn){listeners[`${id}:${type}`]=fn},append(){},replaceChildren(){},setAttribute(){},removeAttribute(){},
  classList:{add(){},remove(){},toggle(){}}});const body=element("body");body.dataset.phase="preparing";
const document={body,querySelector(selector){return selector==="body"?body:element(selector.replace(/^#/,""))},
  createElement(tag){return element(`created-${tag}-${Object.keys(nodes).length}`)}};
const tab={id:7,title:"Reconnect",url:"https://example.invalid/reconnect.mp4"};
const ready={id:"job-reconnect",phase:"ready",tab,preview:{title:"Reconnect",summary:"",permission_origins:[],details:[]}};
const chrome={tabs:{async query(){return[tab]}},runtime:{connect({name}){if(name!=="lbrain-popup")throw new Error("wrong port");
    connects++;let messageListener;const index=disconnects.length;return{onMessage:{addListener(fn){messageListener=fn}},
      onDisconnect:{addListener(fn){disconnects[index]=fn}},postMessage(message){watches.push(message);
        queueMicrotask(()=>messageListener({type:"job",job:ready}))},disconnect(){}}},
  async sendMessage(message){
    if(message.type==="confirmation.prepare")return ready;
    if(message.type==="confirmation.preflight"){preflights++;lease=true;return{reserved:true,missing:[]}}
    if(message.type==="confirmation.decide"){decides++;if(!lease)return{error:"This capture no longer owns the save slot."};
      lease=false;return{...ready,phase:"complete",receipt:{status:"saved",target:"Inbox/Captures/reconnect.md",
        capture_id:"reconnect",version:1}}}
    throw new Error(`unexpected ${message.type}`)}},permissions:{async request(){throw new Error("unexpected permission request")},
    async contains(){throw new Error("UI must not query permission state")},async remove(){return true}}};
const context={chrome,document,location:{search:""},window:{close(){}},URLSearchParams,URL,Response,console,
  setTimeout,clearTimeout,queueMicrotask};vm.createContext(context);vm.runInContext(source,context);
(async()=>{await settle();const initial={connects,preflights,lease,phase:body.dataset.phase};
  lease=false;disconnects[0]();await settle();
  const reconnected={connects,preflights,lease,phase:body.dataset.phase,saveDisabled:element("save").disabled,
    watches:watches.map(value=>value.id)};
  await listeners["save:click"]();await settle();
  console.log(JSON.stringify({initial,reconnected,final:{phase:body.dataset.phase,decides,lease}}));
})().catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "confirm.js")],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["initial"], {
            "connects": 1, "preflights": 1, "lease": True, "phase": "ready",
        })
        self.assertEqual(output["reconnected"], {
            "connects": 2,
            "preflights": 2,
            "lease": True,
            "phase": "ready",
            "saveDisabled": False,
            "watches": ["job-reconnect", "job-reconnect"],
        })
        self.assertEqual(output["final"], {"phase": "complete", "decides": 1, "lease": False})

    def test_extension_does_not_request_an_unjournaled_permission(self) -> None:
        script = r'''
const fs=require("fs");const listeners={},nodes={};let requested=0,decided=false,preflight=false;
const element=id=>nodes[id]||(nodes[id]={textContent:"",disabled:false,hidden:false,dataset:{},
  addEventListener(type,fn){listeners[`${id}:${type}`]=fn},append(){},replaceChildren(){},
  setAttribute(){},removeAttribute(){},classList:{add(){},remove(){},toggle(){}}});
const body=element("body");body.dataset.phase="preparing";
global.document={body,querySelector(selector){return selector==="body"?body:element(selector.replace(/^#/,""))},
  createElement(tag){return element(`created-${tag}-${Object.keys(nodes).length}`)}};
global.location={search:""};global.window={close(){}};
const tab={id:7,title:"Saved",url:"https://example.invalid/article"};
global.chrome={tabs:{async query(){return[tab]}},runtime:{connect(){return{onMessage:{addListener(){}},postMessage(){},disconnect(){}}},
  async sendMessage(message){
    if(message.type==="confirmation.prepare")return{id:"stored",phase:"ready",tab,
      preview:{title:"Saved",summary:"",permission_origins:["https://new.invalid/*"],details:[]}};
    if(message.type==="confirmation.preflight"){preflight=true;return{reserved:true,missing:[],warning:"journal failed"}};
    if(message.type==="confirmation.decide"){decided=true;return{id:"stored",phase:"complete",tab,
      receipt:{status:"partial",target:"Inbox/Captures/saved.md",capture_id:"saved",version:1}}}
    throw new Error(`unexpected ${message.type}`)}},
  permissions:{async contains(){return false},async request(){requested++;return true},async remove(){}}};
eval(fs.readFileSync(process.argv[1],"utf8"));
setTimeout(async()=>{await listeners["save:click"]();console.log(JSON.stringify({requested,decided,preflight}))},0);
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "confirm.js")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"requested": 0, "decided": True, "preflight": True})

    def test_extension_legacy_busy_preflight_requires_recovery_click_before_save(self) -> None:
        script = r'''
const fs=require("fs"),vm=require("vm");const source=fs.readFileSync(process.argv[1],"utf8");
const settle=async()=>{for(let i=0;i<20;i++)await Promise.resolve()};
const listeners={},nodes={},messages=[];let ownerBusy=true,preflights=0,decides=0,puts=0,closes=0,requests=0;
const element=id=>nodes[id]||(nodes[id]={textContent:"",disabled:false,hidden:false,dataset:{},
  addEventListener(type,fn){listeners[`${id}:${type}`]=fn},append(){},replaceChildren(){},setAttribute(){},removeAttribute(){},
  classList:{add(){},remove(){},toggle(){}}});const body=element("body");body.dataset.phase="preparing";
const document={body,querySelector(selector){return selector==="body"?body:element(selector.replace(/^#/,""))},
  createElement(tag){return element(`created-${tag}-${Object.keys(nodes).length}`)}};
const tab={id:7,title:"Legacy busy",url:"https://example.invalid/legacy.mp4"};
const preview={title:"Legacy busy",summary:"",permission_origins:[],details:[]};
const chrome={runtime:{connect({name}){if(name!=="lbrain-confirm")throw new Error("wrong port");let listener;return{
      onMessage:{addListener(fn){listener=fn}},postMessage(){queueMicrotask(()=>listener({type:"preview",preview,
        capture:{schema:"lbrain.capture.v1"},tab}))},disconnect(){}}},
    async sendMessage(message){messages.push(message);
      if(message.type==="confirmation.preflight"){
        preflights++;return ownerBusy?{error:"Another LBrain capture is already being saved."}:{reserved:true,missing:[]}}
      if(message.type==="confirmation.decide"){decides++;return{status:"saved",target:"Inbox/Captures/legacy.md",
        capture_id:"legacy",version:1}}
      if(message.type==="confirmation.release")return{released:true};
      throw new Error(`unexpected ${message.type}`)}},windows:{async getCurrent(){return{id:19}}},permissions:{
    async request(){requests++;return true},async contains(){throw new Error("UI must not query permission state")},
    async remove(){return true}}};
const caches={async open(){return{async put(){puts++},async delete(){}}}};
const context={chrome,caches,document,location:{search:"?id=legacy-busy"},window:{close(){closes++}},
  URLSearchParams,URL,Response,console,setTimeout,clearTimeout,queueMicrotask};vm.createContext(context);vm.runInContext(source,context);
(async()=>{await settle();const initial={phase:body.dataset.phase,title:element("status-title").textContent,
    previewHidden:element("preview").hidden,saveText:element("save").textContent,enabled:!element("save").disabled,
    preflights,decides,puts};
  ownerBusy=false;await listeners["save:click"]();await settle();
  const recovered={phase:body.dataset.phase,saveText:element("save").textContent,enabled:!element("save").disabled,
    preflights,decides,puts,closes};
  await listeners["save:click"]();await settle();
  console.log(JSON.stringify({initial,recovered,final:{preflights,decides,puts,closes,requests},
    preflightWindows:messages.filter(value=>value.type==="confirmation.preflight").map(value=>value.window_id)}));
})().catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "confirm.js")],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["initial"], {
            "phase": "failed",
            "title": "准备失败",
            "previewHidden": True,
            "saveText": "重新读取",
            "enabled": True,
            "preflights": 1,
            "decides": 0,
            "puts": 0,
        })
        self.assertEqual(output["recovered"], {
            "phase": "ready",
            "saveText": "确认保存",
            "enabled": True,
            "preflights": 2,
            "decides": 0,
            "puts": 0,
            "closes": 0,
        })
        self.assertEqual(output["final"], {
            "preflights": 2, "decides": 1, "puts": 1, "closes": 1, "requests": 0,
        })
        self.assertEqual(output["preflightWindows"], [19, 19])

    def test_extension_legacy_initial_read_failure_reconnects_before_save(self) -> None:
        script = r'''
const fs=require("fs"),vm=require("vm");const source=fs.readFileSync(process.argv[1],"utf8");
const settle=async()=>{for(let i=0;i<10;i++)await Promise.resolve()};
const listeners={},nodes={},posts=[],messages=[];let connections=0,disconnects=0;
const element=id=>nodes[id]||(nodes[id]={textContent:"",disabled:false,hidden:false,dataset:{},
  addEventListener(type,fn){listeners[`${id}:${type}`]=fn},append(){},replaceChildren(){}});
const body=element("body");body.dataset.phase="preparing";
const document={body,querySelector(selector){return selector==="body"?body:element(selector.replace(/^#/,""))},
  createElement(tag){return element(`created-${tag}`)}};
const chrome={runtime:{connect({name}){if(name!=="lbrain-confirm")throw new Error("wrong port");connections++;
      let listener;const attempt=connections;return{onMessage:{addListener(fn){listener=fn}},
        postMessage(message){posts.push(message);if(attempt===1)queueMicrotask(()=>listener({type:"error",error:"read failed"}))},
        disconnect(){disconnects++}}},async sendMessage(message){messages.push(message);throw new Error("must not save")}}};
const context={chrome,caches:{},document,location:{search:"?id=legacy-read"},window:{close(){}},
  URLSearchParams,URL,console,queueMicrotask};vm.createContext(context);vm.runInContext(source,context);
(async()=>{await settle();const failed={phase:body.dataset.phase,saveText:element("save").textContent,
    connections,disconnects};await listeners["save:click"]();await settle();
  console.log(JSON.stringify({failed,retry:{phase:body.dataset.phase,title:element("status-title").textContent,
    connections,disconnects,posts,messages}}))})().catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "confirm.js")],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["failed"], {
            "phase": "failed", "saveText": "重新读取", "connections": 1, "disconnects": 1,
        })
        self.assertEqual(output["retry"], {
            "phase": "preparing", "title": "正在读取当前页面…", "connections": 2,
            "disconnects": 1,
            "posts": [
                {"type": "ready", "id": "legacy-read"},
                {"type": "ready", "id": "legacy-read"},
            ],
            "messages": [],
        })

    def test_extension_legacy_worker_restart_closes_instead_of_retrying_lost_confirmation(self) -> None:
        script = r'''
const fs=require("fs"),vm=require("vm");const source=fs.readFileSync(process.argv[1],"utf8");
const settle=async()=>{for(let i=0;i<10;i++)await Promise.resolve()};
const listeners={},nodes={},posts=[],messages=[];let connections=0,disconnects=0,closes=0;
const element=id=>nodes[id]||(nodes[id]={textContent:"",disabled:false,hidden:false,dataset:{},
  addEventListener(type,fn){listeners[`${id}:${type}`]=fn},append(){},replaceChildren(){}});
const body=element("body");body.dataset.phase="preparing";
const document={body,querySelector(selector){return selector==="body"?body:element(selector.replace(/^#/,""))},
  createElement(tag){return element(`created-${tag}`)}};
const chrome={runtime:{connect({name}){if(name!=="lbrain-confirm")throw new Error("wrong port");connections++;
      let listener;return{onMessage:{addListener(fn){listener=fn}},postMessage(message){posts.push(message);
        queueMicrotask(()=>listener({type:"error",error:"This capture confirmation is no longer available."}))},
        disconnect(){disconnects++}}},async sendMessage(message){messages.push(message);throw new Error("must not save")}}};
const context={chrome,caches:{},document,location:{search:"?id=legacy-lost"},window:{close(){closes++}},
  URLSearchParams,URL,console,queueMicrotask};vm.createContext(context);vm.runInContext(source,context);
(async()=>{await settle();const failed={phase:body.dataset.phase,title:element("status-title").textContent,
    saveText:element("save").textContent,connections,disconnects};await listeners["save:click"]();await settle();
  console.log(JSON.stringify({failed,afterClick:{connections,disconnects,closes,posts,messages}}))})()
  .catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "confirm.js")],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["failed"], {
            "phase": "failed", "title": "读取已中断", "saveText": "关闭后重新发起",
            "connections": 1, "disconnects": 1,
        })
        self.assertEqual(output["afterClick"], {
            "connections": 1, "disconnects": 1, "closes": 1,
            "posts": [{"type": "ready", "id": "legacy-lost"}], "messages": [],
        })

    def test_extension_stale_confirmation_removes_late_grant_and_repreflights(self) -> None:
        script = r'''
const fs=require("fs"),vm=require("vm");const source=fs.readFileSync(process.argv[1],"utf8");
const settle=async()=>{for(let i=0;i<20;i++)await Promise.resolve()};
async function scenario(popup){
  const listeners={},nodes={},messages=[],events=[],removed=[];let popupListener,preflights=0,decides=0,closed=0,
    directRemovals=0;
  const element=id=>nodes[id]||(nodes[id]={textContent:"",disabled:false,hidden:false,dataset:{},
    addEventListener(type,fn){listeners[`${id}:${type}`]=fn},append(){},replaceChildren(){},setAttribute(){},removeAttribute(){},
    classList:{add(){},remove(){},toggle(){}}});const body=element("body");body.dataset.phase="preparing";
  const document={body,querySelector(selector){return selector==="body"?body:element(selector.replace(/^#/,""))},
    createElement(tag){return element(`created-${tag}-${Object.keys(nodes).length}`)}};
  const tab={id:7,title:"Stale",url:"https://example.invalid/article"},origin="https://late.invalid/*";
  const preview={title:"Stale",summary:"",permission_origins:[origin],details:[]};
  const ready={id:popup?"popup-a":"legacy-a",phase:"ready",tab,preview};
  const chrome={tabs:{async query(){return[tab]}},runtime:{connect({name}){
      if(name==="lbrain-popup")return{onMessage:{addListener(fn){popupListener=fn}},postMessage(){},disconnect(){}};
      let listener;return{onMessage:{addListener(fn){listener=fn}},postMessage(){queueMicrotask(()=>listener({
        type:"preview",preview,capture:{schema:"lbrain.capture.v1"},tab}))},disconnect(){}}},
    async sendMessage(message){messages.push(message);events.push(`runtime:${message.type}`);
      if(message.type==="confirmation.prepare")return ready;
      if(message.type==="confirmation.preflight"){preflights++;return{reserved:true,missing:[origin]}}
      if(message.type==="confirmation.arm")return{error:"This capture no longer owns the save slot."};
      if(message.type==="confirmation.decide"){decides++;return{error:"This capture no longer owns the save slot."}}
      if(message.type==="confirmation.permissions"&&message.cleanup){removed.push(...message.origins);
        return{recorded:true,released:true}}
      if(message.type==="confirmation.release")return{released:true};
      throw new Error(`unexpected ${message.type}`)}},windows:{async getCurrent(){return{id:19}}},permissions:{
      request({origins}){events.push("permission.request");return Promise.resolve(origins.includes(origin))},
      async remove(){directRemovals++;throw new Error("UI must delegate cleanup to the worker")},
      async contains(){throw new Error("UI must not query permission state")}}};
  const caches={async open(){return{async put(){events.push("cache.put")},async delete(){events.push("cache.delete")}}}};
  const context={chrome,caches,document,location:{search:popup?"":"?id=legacy-a"},window:{close(){closed++}},
    URLSearchParams,URL,Response,console,setTimeout,clearTimeout,queueMicrotask};
  vm.createContext(context);vm.runInContext(source,context);await settle();
  const offset=events.length,click=listeners["save:click"]();const immediate=events.slice(offset);await click;await settle();
  return{immediate,events:events.slice(offset),phase:body.dataset.phase,preflights,decides,removed,
    enabled:!element("save").disabled,closed,directRemovals,
    cleanup:messages.filter(value=>value.type==="confirmation.permissions"&&value.cleanup),
    releases:messages.filter(value=>value.type==="confirmation.release").length,
    permissionResults:messages.filter(value=>value.type==="confirmation.permission_result").length};
}
(async()=>console.log(JSON.stringify({popup:await scenario(true),legacy:await scenario(false)})))()
  .catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "confirm.js")],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["popup"]["immediate"], ["runtime:confirmation.arm", "permission.request"])
        self.assertEqual(output["popup"]["phase"], "failed")
        self.assertEqual(output["popup"]["preflights"], 2)
        self.assertEqual(output["popup"]["removed"], ["https://late.invalid/*"])
        self.assertEqual(output["popup"]["directRemovals"], 0)
        self.assertEqual(output["popup"]["cleanup"], [{
            "type": "confirmation.permissions", "id": "popup-a",
            "origins": ["https://late.invalid/*"], "cleanup": True,
        }])
        self.assertLess(
            output["popup"]["events"].index("runtime:confirmation.permissions"),
            output["popup"]["events"].index("runtime:confirmation.preflight"),
        )
        self.assertTrue(output["popup"]["enabled"])
        self.assertEqual(output["popup"]["decides"], 0)
        self.assertEqual(output["popup"]["permissionResults"], 0)
        self.assertEqual(output["popup"]["releases"], 0)
        self.assertEqual(output["legacy"]["immediate"], ["permission.request"])
        self.assertEqual(output["legacy"]["phase"], "failed")
        self.assertEqual(output["legacy"]["preflights"], 2)
        self.assertEqual(output["legacy"]["removed"], ["https://late.invalid/*"])
        self.assertEqual(output["legacy"]["directRemovals"], 0)
        self.assertEqual(output["legacy"]["cleanup"], [{
            "type": "confirmation.permissions", "id": "legacy-a",
            "origins": ["https://late.invalid/*"], "cleanup": True,
        }])
        self.assertLess(
            output["legacy"]["events"].index("runtime:confirmation.permissions"),
            output["legacy"]["events"].index("runtime:confirmation.preflight"),
        )
        self.assertTrue(output["legacy"]["enabled"])
        self.assertEqual(output["legacy"]["decides"], 1)
        self.assertEqual(output["legacy"]["releases"], 1)
        self.assertEqual(output["legacy"]["closed"], 0)

    def test_extension_stale_confirmation_journals_failed_late_grant_cleanup(self) -> None:
        script = r'''
const fs=require("fs"),vm=require("vm"),{webcrypto}=require("crypto");
const confirmSource=fs.readFileSync(process.argv[1],"utf8");
const workerSource=fs.readFileSync(process.argv[2],"utf8");
const shared={},local={},granted=new Set(),workerRemovals=[];let workerHandler,startup,permissionAdded,
  workerFailure="",directRemovals=0;
const storage=values=>({async get(key){if(key===null)return{...values};return{[key]:values[key]}},
  async set(entries){Object.assign(values,entries)},async remove(key){delete values[key]}});
const workerChrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(fn){startup=fn}},
    onMessage:{addListener(fn){workerHandler=fn}},onConnect:{addListener(){}},lastError:null,
    getURL(value){return`chrome-extension://test/${value}`}},
  contextMenus:{removeAll(){},create(){},onClicked:{addListener(){}}},action:{onClicked:{addListener(){}}},
  windows:{onRemoved:{addListener(){}}},permissions:{onAdded:{addListener(fn){permissionAdded=fn}},
    async contains({origins}){return origins.every(origin=>granted.has(origin))},
    async remove({origins}){workerRemovals.push({failure:workerFailure,origins:[...origins]});
      if(workerFailure==="throw")throw new Error("temporary remove failure");
      if(workerFailure==="false")return false;
      for(const origin of origins)granted.delete(origin);return true}},
  storage:{session:storage(shared),local:storage(local),onChanged:{addListener(){}}},
  notifications:{async create(){},onButtonClicked:{addListener(){}}},tabs:{async create(){}}};
const workerContext={chrome:workerChrome,caches:{async open(){return{async match(){},async delete(){}}},async delete(){}},
  crypto:webcrypto,URL,URLSearchParams,TextEncoder,Blob,Response,setTimeout,clearTimeout,queueMicrotask,console};
vm.createContext(workerContext);vm.runInContext(workerSource,workerContext);
const workerSend=message=>new Promise(resolve=>workerHandler(message,{},resolve));
const settle=async()=>{for(let i=0;i<30;i++)await Promise.resolve()};
const waitFor=async predicate=>{for(let i=0;i<100;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,0))}
  throw new Error("condition did not settle")};
async function scenario(failure){
  const listeners={},nodes={},messages=[];
  const origin=`https://${failure}.late.invalid/*`,id=`stale-${failure}`;
  const element=key=>nodes[key]||(nodes[key]={textContent:"",disabled:false,hidden:false,dataset:{},
    addEventListener(type,fn){listeners[`${key}:${type}`]=fn},append(){},replaceChildren(){},setAttribute(){},
    removeAttribute(){},classList:{add(){},remove(){},toggle(){}}});
  const body=element("body");body.dataset.phase="preparing";
  const document={body,querySelector(selector){return selector==="body"?body:element(selector.replace(/^#/,""))},
    createElement(tag){return element(`created-${tag}-${Object.keys(nodes).length}`)}};
  const tab={id:7,title:"Stale",url:"https://example.invalid/article"};
  const preview={title:"Stale",summary:"",permission_origins:[origin],details:[]};
  const chrome={tabs:{async query(){return[tab]}},runtime:{connect(){return{onMessage:{addListener(){}},
        onDisconnect:{addListener(){}},postMessage(){},disconnect(){}}},
      async sendMessage(message){messages.push(message);
        if(message.type==="confirmation.prepare")return{id,phase:"ready",tab,preview};
        if(message.type==="confirmation.preflight")return{reserved:true,missing:[origin]};
        if(message.type==="confirmation.arm")return{error:"This capture no longer owns the save slot."};
        if(message.type==="confirmation.permissions"&&message.cleanup)return workerSend(message);
        throw new Error(`unexpected ${message.type}`)}},permissions:{
      async request(){granted.add(origin);return true},
      async remove(){directRemovals++;throw new Error("UI must delegate cleanup to the worker")},
      async contains(){throw new Error("UI must not query permission state")}}};
  const context={chrome,caches:{async open(){return{async delete(){}}}},document,location:{search:""},window:{close(){}},
    URLSearchParams,URL,Response,console,setTimeout,clearTimeout,queueMicrotask};
  vm.createContext(context);vm.runInContext(confirmSource,context);await settle();
  workerFailure=failure;await listeners["save:click"]();await settle();
  const cleanupMessages=messages.filter(message=>message.type==="confirmation.permissions"&&message.cleanup);
  const retained={journal:[...(local["lbrain-temporary-origins-v1"]||[])],granted:granted.has(origin)};
  workerFailure="";
  if(failure==="false")await workerSend(cleanupMessages[0]);
  else await startup();
  await settle();
  return{cleanupMessages,retained,afterRecovery:{journal:local["lbrain-temporary-origins-v1"]||[],
    granted:granted.has(origin)}};
}
(async()=>{
  const returnedFalse=await scenario("false"),threw=await scenario("throw");
  const transferOrigin="https://shared.late.invalid/*";granted.add(transferOrigin);
  await workerSend({type:"confirmation.reserve",id:"active-b",permission_origins:[transferOrigin]});
  const beforeTransferRemovals=workerRemovals.length;
  const transferResponse=await workerSend({type:"confirmation.permissions",id:"stale-a",origins:[transferOrigin],cleanup:true});
  const transfer={response:transferResponse,removalDelta:workerRemovals.length-beforeTransferRemovals,
    granted:granted.has(transferOrigin),journal:[...(local["lbrain-temporary-origins-v1"]||[])],
    reservation:shared["lbrain-save-reservation-v1"]?.id||null,
    releaseOrigins:shared["lbrain-save-reservation-v1"]?.release_origins||[]};
  await workerSend({type:"confirmation.release",id:"active-b"});
  transfer.afterRelease={granted:granted.has(transferOrigin),journal:local["lbrain-temporary-origins-v1"]||[],
    reservation:shared["lbrain-save-reservation-v1"]?.id||null};

  const orphanOrigin="https://orphan-added.invalid/*";workerFailure="throw";granted.add(orphanOrigin);
  permissionAdded({origins:[orphanOrigin]});
  await waitFor(()=>(local["lbrain-temporary-origins-v1"]||[]).includes(orphanOrigin));
  const orphanAdded={journal:[...local["lbrain-temporary-origins-v1"]],granted:granted.has(orphanOrigin)};
  workerFailure="";await startup();await settle();
  orphanAdded.afterStartup={journal:local["lbrain-temporary-origins-v1"]||[],granted:granted.has(orphanOrigin)};
  console.log(JSON.stringify({returnedFalse,threw,transfer,orphanAdded,directRemovals,workerRemovals}));
})()
  .catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            [
                "node", "-e", script,
                str(CAPTURE_EXTENSION / "confirm.js"),
                str(CAPTURE_EXTENSION / "service_worker.js"),
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        for name, failure, origin in (
            ("returnedFalse", "false", "https://false.late.invalid/*"),
            ("threw", "throw", "https://throw.late.invalid/*"),
        ):
            self.assertEqual(output[name]["cleanupMessages"], [{
                "type": "confirmation.permissions",
                "id": f"stale-{failure}",
                "origins": [origin],
                "cleanup": True,
            }])
            self.assertEqual(output[name]["retained"], {"journal": [origin], "granted": True})
            self.assertEqual(output[name]["afterRecovery"], {"journal": [], "granted": False})
        self.assertEqual(output["directRemovals"], 0)
        self.assertEqual(output["transfer"], {
            "response": {"recorded": True, "released": False},
            "removalDelta": 0,
            "granted": True,
            "journal": ["https://shared.late.invalid/*"],
            "reservation": "active-b",
            "releaseOrigins": ["https://shared.late.invalid/*"],
            "afterRelease": {"granted": False, "journal": [], "reservation": None},
        })
        self.assertEqual(output["orphanAdded"], {
            "journal": ["https://orphan-added.invalid/*"],
            "granted": True,
            "afterStartup": {"journal": [], "granted": False},
        })
        self.assertEqual(output["workerRemovals"], [
            {"failure": "false", "origins": ["https://false.late.invalid/*"]},
            {"failure": "", "origins": ["https://false.late.invalid/*"]},
            {"failure": "throw", "origins": ["https://throw.late.invalid/*"]},
            {"failure": "", "origins": ["https://throw.late.invalid/*"]},
            {"failure": "", "origins": ["https://shared.late.invalid/*"]},
            {"failure": "throw", "origins": ["https://orphan-added.invalid/*"]},
            {"failure": "", "origins": ["https://orphan-added.invalid/*"]},
        ])

    def test_extension_popup_permission_intent_survives_ui_loss_and_runs_once(self) -> None:
        script = r'''
const fs=require("fs"),{webcrypto}=require("crypto");
let messageHandler,permissionAdded,nativeConnections=0;const shared={},local={},cached={},nativeReplies=[];
const granted=new Set(),removed=[];
const storage=values=>({async get(key){if(key===null)return{...values};return{[key]:values[key]}},
  async set(entries){Object.assign(values,entries)},async remove(key){delete values[key]}});
global.caches={async open(){return{async put(key,response){cached[key]=await response.text()},
  async match(key){return cached[key]===undefined?undefined:new Response(cached[key])},
  async delete(key){delete cached[key]}}},async delete(){for(const key of Object.keys(cached))delete cached[key]}};
function connectNative(){nativeConnections++;let listener;return{onMessage:{addListener(fn){listener=fn}},
  onDisconnect:{addListener(){}},disconnect(){},postMessage(message){
    if(message.type==="chunk")queueMicrotask(()=>listener({type:"ack",channel:message.channel,sequence:message.sequence}));
    if(message.type==="end")nativeReplies.push(value=>listener(value))}}}
global.chrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(){}},onMessage:{addListener(fn){messageHandler=fn}},
  onConnect:{addListener(){}},getURL(value){return"chrome-extension://test/"+value},connectNative,lastError:null},
  contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(){}}},action:{onClicked:{addListener(){}}},
  windows:{onRemoved:{addListener(){}}},permissions:{onAdded:{addListener(fn){permissionAdded=fn}},
    async contains({origins}){return origins.every(origin=>granted.has(origin))},
    async remove({origins}){let changed=false;for(const origin of origins){
      if(granted.delete(origin)){removed.push(origin);changed=true}}return changed}},
  storage:{session:storage(shared),local:storage(local),onChanged:{addListener(){}}},
  notifications:{async create(){},onButtonClicked:{addListener(){}}},tabs:{async create(){}}};
global.crypto=webcrypto;eval(fs.readFileSync(process.argv[1],"utf8"));
function send(message){return new Promise(resolve=>messageHandler(message,{},resolve))}
async function waitFor(predicate){for(let i=0;i<200;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,0))}
  throw new Error("condition did not settle")}
async function ready(number){const tab={id:number,url:`https://example.invalid/${number}.mp4`,title:`Movie ${number}`};
  const job=await send({type:"confirmation.prepare",tab,scope:"page"});
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.id===job.id&&shared["lbrain-popup-job-v1"].phase==="ready");return job}
async function finish(status,label){await waitFor(()=>nativeReplies.length===1);nativeReplies.shift()({status,
  target:`Inbox/Captures/${label}.md`,capture_id:label,version:1});
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.phase==="complete");
  await waitFor(()=>!shared["lbrain-save-reservation-v1"]);return shared["lbrain-popup-job-v1"]}
async function clear(id){await send({type:"confirmation.cancel",id})}
(async()=>{
  const lostOrigin="https://lost.invalid/*";let job=await ready(1);
  const lostPreflight=await send({type:"confirmation.preflight",id:job.id,permission_origins:[lostOrigin]});
  const lostArm=await send({type:"confirmation.arm",id:job.id});
  granted.add(lostOrigin);permissionAdded({origins:[lostOrigin]});
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.phase==="saving"&&nativeConnections===1);
  const lostSaving={phase:shared["lbrain-popup-job-v1"].phase,nativeConnections};
  const lostComplete=await finish("saved","lost");const afterLost={phase:lostComplete.phase,
    removed:[...removed],granted:[...granted],journal:local["lbrain-temporary-origins-v1"]||[]};
  await clear(job.id);

  const earlyOrigin="https://early.invalid/*";job=await ready(2);
  await send({type:"confirmation.preflight",id:job.id,permission_origins:[earlyOrigin]});
  granted.add(earlyOrigin);permissionAdded({origins:[earlyOrigin]});
  await new Promise(resolve=>setTimeout(resolve,0));const beforeArm=nativeConnections;
  const earlyArm=await send({type:"confirmation.arm",id:job.id});
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.phase==="saving");
  const earlyComplete=await finish("saved","early");const afterEarly={phase:earlyComplete.phase,nativeConnections};
  await clear(job.id);

  const deniedOrigin="https://denied.invalid/*";job=await ready(3);
  await send({type:"confirmation.preflight",id:job.id,permission_origins:[deniedOrigin]});
  const deniedArm=await send({type:"confirmation.arm",id:job.id});
  const denied=send({type:"confirmation.permission_result",id:job.id,granted:false});
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.phase==="saving"&&nativeReplies.length===1);
  const duplicateResult=send({type:"confirmation.permission_result",id:job.id,granted:false});
  permissionAdded({origins:[deniedOrigin]});await new Promise(resolve=>setTimeout(resolve,0));
  const deniedDuring={phase:shared["lbrain-popup-job-v1"].phase,nativeConnections};
  nativeReplies.shift()({status:"partial",target:"Inbox/Captures/denied.md",capture_id:"denied",version:1});
  const [deniedComplete,duplicateComplete]=await Promise.all([denied,duplicateResult]);
  await waitFor(()=>!shared["lbrain-save-reservation-v1"]);const afterDenied={
    phases:[deniedComplete.phase,duplicateComplete.phase],statuses:[deniedComplete.receipt.status,duplicateComplete.receipt.status],
    nativeConnections,journal:local["lbrain-temporary-origins-v1"]||[]};
  await clear(job.id);

  const expiredOrigin="https://expired.invalid/*";job=await ready(4);
  await send({type:"confirmation.preflight",id:job.id,permission_origins:[expiredOrigin]});
  granted.add(expiredOrigin);shared["lbrain-save-reservation-v1"].save_intent=true;
  shared["lbrain-save-reservation-v1"].created=Date.now()-11*60*1000;
  const beforeExpired=nativeConnections;permissionAdded({origins:[expiredOrigin]});
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.phase==="failed");
  await waitFor(()=>!shared["lbrain-save-reservation-v1"]);const expired={phase:shared["lbrain-popup-job-v1"].phase,
    preview:Boolean(shared["lbrain-popup-job-v1"].preview),nativeDelta:nativeConnections-beforeExpired,
    granted:[...granted],journal:local["lbrain-temporary-origins-v1"]||[]};
  console.log(JSON.stringify({lostPreflight,lostArm,lostSaving,afterLost,beforeArm,earlyArm,afterEarly,
    deniedArm,deniedDuring,afterDenied,expired,nativeConnections,removed}));
})().catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["lostPreflight"], {"reserved": True, "missing": ["https://lost.invalid/*"]})
        self.assertEqual(output["lostArm"], {"armed": True, "started": False})
        self.assertEqual(output["lostSaving"], {"phase": "saving", "nativeConnections": 1})
        self.assertEqual(output["afterLost"], {
            "phase": "complete", "removed": ["https://lost.invalid/*"], "granted": [], "journal": [],
        })
        self.assertEqual(output["beforeArm"], 1)
        self.assertEqual(output["earlyArm"], {"armed": True, "started": True})
        self.assertEqual(output["afterEarly"], {"phase": "complete", "nativeConnections": 2})
        self.assertEqual(output["deniedArm"], {"armed": True, "started": False})
        self.assertEqual(output["deniedDuring"], {"phase": "saving", "nativeConnections": 3})
        self.assertEqual(output["afterDenied"], {
            "phases": ["complete", "complete"], "statuses": ["partial", "partial"],
            "nativeConnections": 3, "journal": [],
        })
        self.assertEqual(output["expired"], {
            "phase": "failed", "preview": True, "nativeDelta": 0, "granted": [], "journal": [],
        })
        self.assertEqual(output["nativeConnections"], 3)
        self.assertEqual(output["removed"], ["https://lost.invalid/*", "https://early.invalid/*", "https://expired.invalid/*"])

    def test_extension_popup_port_arm_marker_waits_for_runtime_arm_and_keeps_terminal(self) -> None:
        script = r'''
const fs=require("fs"),{webcrypto}=require("crypto");
let messageHandler,connectHandler,nativeConnections=0;
const shared={},local={},cached={},granted=new Set(),removed=[],nativeReplies=[];
const storage=values=>({async get(key){if(key===null)return{...values};return{[key]:values[key]}},
  async set(entries){Object.assign(values,entries)},async remove(key){delete values[key]}});
global.caches={async open(){return{async put(key,response){cached[key]=await response.text()},
  async match(key){return cached[key]===undefined?undefined:new Response(cached[key])},
  async delete(key){delete cached[key]}}},async delete(){for(const key of Object.keys(cached))delete cached[key]}};
function connectNative(){nativeConnections++;let listener;return{onMessage:{addListener(fn){listener=fn}},
  onDisconnect:{addListener(){}},disconnect(){},postMessage(message){
    if(message.type==="chunk")queueMicrotask(()=>listener({type:"ack",channel:message.channel,sequence:message.sequence}));
    if(message.type==="end")nativeReplies.push(value=>listener(value))}}}
global.chrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(){}},onMessage:{addListener(fn){messageHandler=fn}},
  onConnect:{addListener(fn){connectHandler=fn}},getURL(value){return`chrome-extension://test/${value}`},
  connectNative,lastError:null},contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(){}}},
  action:{onClicked:{addListener(){}}},windows:{onRemoved:{addListener(){}}},permissions:{onAdded:{addListener(){}},
    async contains({origins}){return origins.every(origin=>granted.has(origin))},
    async remove({origins}){for(const origin of origins)if(granted.delete(origin))removed.push(origin);return true}},
  storage:{session:storage(shared),local:storage(local),onChanged:{addListener(){}}},
  notifications:{async create(){},onButtonClicked:{addListener(){}}},tabs:{async create(){}}};
global.crypto=webcrypto;eval(fs.readFileSync(process.argv[1],"utf8"));
const send=message=>new Promise(resolve=>messageHandler(message,{},resolve));
const waitFor=async predicate=>{for(let i=0;i<100;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,0))}
  throw new Error("condition did not settle")};
function watch(id){let listener,disconnect;const port={name:"lbrain-popup",onMessage:{addListener(fn){listener=fn}},
  onDisconnect:{addListener(fn){disconnect=fn}},postMessage(){}};connectHandler(port);listener({type:"watch",id});
  return{arm(){listener({type:"arm",id})},close(){disconnect()}}}
async function scenario(number,status){
  const tab={id:number,url:`https://example.invalid/${status}.mp4`,title:`Fast ${status}`};
  const preparing=await send({type:"confirmation.prepare",tab,scope:"page"});
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.id===preparing.id&&shared["lbrain-popup-job-v1"].phase==="ready");
  const id=preparing.id,origin=`https://${status}.fast.invalid/*`;
  const preflight=await send({type:"confirmation.preflight",id,permission_origins:[origin]});
  const popup=watch(id);granted.add(origin);
  const beforeNative=nativeConnections;popup.arm();popup.close();
  await waitFor(()=>shared["lbrain-save-reservation-v1"]?.id===id&&shared["lbrain-save-reservation-v1"].awaiting_arm===true);
  const marker={phase:shared["lbrain-popup-job-v1"].phase,saveIntent:shared["lbrain-save-reservation-v1"].save_intent,
    awaitingArm:shared["lbrain-save-reservation-v1"].awaiting_arm,nativeDelta:nativeConnections-beforeNative,
    journal:[...(local["lbrain-temporary-origins-v1"]||[])]};
  const runtimeArm=await send({type:"confirmation.arm",id});
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.phase==="saving"&&nativeReplies.length===1);
  const duringSaving={phase:shared["lbrain-popup-job-v1"].phase,
    awaitingArm:Boolean(shared["lbrain-save-reservation-v1"]?.awaiting_arm),nativeDelta:nativeConnections-beforeNative};
  const duplicateArm=await send({type:"confirmation.arm",id});
  nativeReplies.shift()(status==="failed"?{status:"failed",error:"disk unavailable"}
    :{status:"saved",target:"Inbox/Captures/fast.md",capture_id:"fast",version:1});
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.id===id&&shared["lbrain-popup-job-v1"].phase===(status==="failed"?"failed":"complete"));
  const terminal={phase:shared["lbrain-popup-job-v1"].phase,error:shared["lbrain-popup-job-v1"].error||null,
    receipt:shared["lbrain-popup-job-v1"].receipt?.status||null};
  const lateArm=await send({type:"confirmation.arm",id});
  const permissionResult=await send({type:"confirmation.permission_result",id,granted:true});
  const afterLate={phase:shared["lbrain-popup-job-v1"].phase,error:shared["lbrain-popup-job-v1"].error||null,
    receipt:shared["lbrain-popup-job-v1"].receipt?.status||null,nativeDelta:nativeConnections-beforeNative,
    reservation:shared["lbrain-save-reservation-v1"]?.id||null,journal:local["lbrain-temporary-origins-v1"]||[]};
  await send({type:"confirmation.cancel",id});
  return{preflight,marker,runtimeArm,duringSaving,duplicateArm,terminal,lateArm,
    permissionPhase:permissionResult.phase,permissionError:permissionResult.error||null,
    permissionReceipt:permissionResult.receipt?.status||null,afterLate};
}
(async()=>console.log(JSON.stringify({complete:await scenario(1,"saved"),failed:await scenario(2,"failed"),
  nativeConnections,removed})))().catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["complete"], {
            "preflight": {"reserved": True, "missing": ["https://saved.fast.invalid/*"]},
            "marker": {
                "phase": "ready", "saveIntent": True, "awaitingArm": True, "nativeDelta": 0,
                "journal": ["https://saved.fast.invalid/*"],
            },
            "runtimeArm": {"armed": True, "started": True},
            "duringSaving": {"phase": "saving", "awaitingArm": False, "nativeDelta": 1},
            "duplicateArm": {"armed": True, "started": True},
            "terminal": {"phase": "complete", "error": None, "receipt": "saved"},
            "lateArm": {"armed": True, "started": True},
            "permissionPhase": "complete",
            "permissionError": None,
            "permissionReceipt": "saved",
            "afterLate": {
                "phase": "complete", "error": None, "receipt": "saved", "nativeDelta": 1,
                "reservation": None, "journal": [],
            },
        })
        self.assertEqual(output["failed"], {
            "preflight": {"reserved": True, "missing": ["https://failed.fast.invalid/*"]},
            "marker": {
                "phase": "ready", "saveIntent": True, "awaitingArm": True, "nativeDelta": 0,
                "journal": ["https://failed.fast.invalid/*"],
            },
            "runtimeArm": {"armed": True, "started": True},
            "duringSaving": {"phase": "saving", "awaitingArm": False, "nativeDelta": 1},
            "duplicateArm": {"armed": True, "started": True},
            "terminal": {"phase": "failed", "error": "disk unavailable", "receipt": None},
            "lateArm": {"armed": True, "started": True},
            "permissionPhase": "failed",
            "permissionError": "disk unavailable",
            "permissionReceipt": None,
            "afterLate": {
                "phase": "failed", "error": "disk unavailable", "receipt": None, "nativeDelta": 1,
                "reservation": None, "journal": [],
            },
        })
        self.assertEqual(output["nativeConnections"], 2)
        self.assertEqual(output["removed"], ["https://saved.fast.invalid/*", "https://failed.fast.invalid/*"])

    def test_extension_save_reservation_survives_worker_restart(self) -> None:
        script = (
            "const fs=require('fs'),vm=require('vm'),{webcrypto}=require('crypto');const shared={},persistent={},removed=[];let failRemove=false;"
            "function worker(){let handler,startup;const session={async get(key){return{[key]:shared[key]}},"
            "async set(value){Object.assign(shared,value)},async remove(key){delete shared[key]}};"
            "const chrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(fn){startup=fn}},"
            "onMessage:{addListener(fn){handler=fn}},onConnect:{addListener(){}},lastError:null,"
            "getURL(value){return 'chrome-extension://test/'+value}},contextMenus:{removeAll(){},create(){},"
            "onClicked:{addListener(){}}},action:{onClicked:{addListener(){}}},windows:{onRemoved:{addListener(){}}},"
            "permissions:{async remove({origins}){if(failRemove)return false;removed.push(...origins);return true},async contains(){return failRemove}},"
            "notifications:{onButtonClicked:{addListener(){}}},storage:{session,local:{async get(key){return{[key]:persistent[key]}},async set(value){Object.assign(persistent,value)},async remove(key){delete persistent[key]}}}};"
            "const caches={async open(){return{async match(){return undefined},async delete(){}}},async delete(){}};"
            "const context={chrome,caches,crypto:webcrypto,URL,TextEncoder,Blob,Response,setTimeout,clearTimeout,console};"
            "vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);return{handler,startup}}"
            "function send(handler,message){return new Promise(resolve=>handler(message,{},resolve))}"
            "(async()=>{const first=worker();const reserved=await send(first.handler,{type:'confirmation.reserve',id:'capture-1',"
            "permission_origins:['https://new.invalid/*','https://second.invalid/*','https://*/*','https://*.example.com/*']});"
            "const allowed=[...shared['lbrain-save-reservation-v1'].allowed_origins];"
            "await send(first.handler,{type:'confirmation.permissions',id:'capture-1',origins:['https://new.invalid/*']});"
            "await send(first.handler,{type:'confirmation.permissions',id:'capture-1',origins:['https://second.invalid/*']});"
            "const restarted=worker();await restarted.startup();"
            "const second=worker();await send(second.handler,{type:'confirmation.reserve',id:'capture-2'});"
            "const decided=await send(worker().handler,{type:'confirmation.decide',id:'capture-2'});"
            "shared['lbrain-save-reservation-v1']={id:'busy',created:Date.now(),state:'saving'};"
            "const concurrent=await send(worker().handler,{type:'confirmation.reserve',id:'concurrent'});"
            "delete shared['lbrain-save-reservation-v1'];"
            "shared['lbrain-save-reservation-v1']={id:'stale',created:Date.now()-660000,release_origins:['https://crash.invalid/*']};"
            "const third=worker();await send(third.handler,{type:'confirmation.reserve',id:'capture-3'});await third.startup();"
            "shared['lbrain-save-reservation-v1']={id:'retry',created:Date.now(),release_origins:['https://retry.invalid/*']};"
            "persistent['lbrain-temporary-origins-v1']=['https://retry.invalid/*'];"
            "failRemove=true;await worker().startup();const retainedOnFailure=Boolean(shared['lbrain-save-reservation-v1']);"
            "const journalRetainedOnFailure=Boolean(persistent['lbrain-temporary-origins-v1']);"
            "failRemove=false;await worker().startup();"
            "persistent['lbrain-temporary-origins-v1']=['https://browser-restart.invalid/*'];await worker().startup();"
            "console.log(JSON.stringify({reserved:reserved.reserved,allowed,error:decided.error,concurrent:concurrent.reserved,removed,retainedOnFailure,journalRetainedOnFailure,stale:Boolean(shared['lbrain-save-reservation-v1']),journal:Boolean(persistent['lbrain-temporary-origins-v1'])}))})()"
            ".catch(error=>{console.error(error);process.exit(1)});"
        )
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertTrue(output["reserved"])
        self.assertEqual(output["allowed"], ["https://new.invalid/*", "https://second.invalid/*"])
        self.assertIn("confirmation is no longer available", output["error"])
        self.assertNotIn("owns the save slot", output["error"])
        self.assertTrue(output["concurrent"])
        self.assertEqual(output["removed"], [
            "https://new.invalid/*", "https://second.invalid/*", "https://crash.invalid/*", "https://retry.invalid/*",
            "https://browser-restart.invalid/*",
        ])
        self.assertTrue(output["retainedOnFailure"])
        self.assertTrue(output["journalRetainedOnFailure"])
        self.assertFalse(output["stale"])
        self.assertFalse(output["journal"])

    def test_extension_popup_capture_ownership_survives_only_after_arm_and_reconciles_restart(self) -> None:
        script = r'''
const fs=require("fs"),vm=require("vm"),{webcrypto}=require("crypto");
const source=fs.readFileSync(process.argv[1],"utf8");
const shared={},local={},cached={},granted=new Set(),removed=[],nativeReplies=[];let nativeConnections=0;
const storage=values=>({async get(key){if(key===null)return{...values};return{[key]:values[key]}},
  async set(entries){Object.assign(values,entries)},async remove(key){delete values[key]}});
const caches={async match(key){return cached[key]===undefined?undefined:new Response(cached[key])},async open(){return{
  async put(key,response){cached[key]=await response.text()},
  async match(key){return cached[key]===undefined?undefined:new Response(cached[key])},
  async delete(key){delete cached[key]}}},async delete(){for(const key of Object.keys(cached))delete cached[key]}};
function video(tab){return{schema:"lbrain.capture.v1",title:tab.title,
  summary:"Original video link captured without the video binary.",origin:tab.url,scope:"page",author:"",published_at:"",
  content_markdown:"Video",capture_kind:"video",has_video:true,preview_characters:0,extraction_status:"complete",
  remote_assets:[],assets:[]}}
function worker(){let handler,connectHandler,permissionAdded;const chrome={runtime:{onInstalled:{addListener(){}},
  onStartup:{addListener(){}},onMessage:{addListener(fn){handler=fn}},onConnect:{addListener(fn){connectHandler=fn}},
  getURL(value){return"chrome-extension://test/"+value},lastError:null,connectNative(){nativeConnections++;let listener;return{
    onMessage:{addListener(fn){listener=fn}},onDisconnect:{addListener(){}},disconnect(){},postMessage(message){
      if(message.type==="chunk")queueMicrotask(()=>listener({type:"ack",channel:message.channel,sequence:message.sequence}));
      if(message.type==="end")nativeReplies.push(value=>listener(value))}}}},
  contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(){}}},action:{onClicked:{addListener(){}}},
  windows:{onRemoved:{addListener(){}}},permissions:{onAdded:{addListener(fn){permissionAdded=fn}},
    async contains({origins}){return origins.every(origin=>granted.has(origin))},
    async remove({origins}){let changed=false;for(const origin of origins)if(granted.delete(origin)){
      removed.push(origin);changed=true}return changed}},storage:{session:storage(shared),local:storage(local),
      onChanged:{addListener(){}}},notifications:{async create(){},onButtonClicked:{addListener(){}}},tabs:{async create(){}}};
  const context={chrome,caches,crypto:webcrypto,URL,TextEncoder,Blob,Response,AbortSignal,setTimeout,clearTimeout,
    queueMicrotask,console,btoa:value=>Buffer.from(value,"binary").toString("base64")};
  vm.createContext(context);vm.runInContext(source,context);return{handler,connectHandler,permissionAdded}}
function send(worker,message){return new Promise(resolve=>worker.handler(message,{},resolve))}
function watch(worker,id){const messages=[];let receive,disconnect;const port={name:"lbrain-popup",
  onMessage:{addListener(fn){receive=fn}},onDisconnect:{addListener(fn){disconnect=fn}},
  postMessage(message){messages.push(message)}};worker.connectHandler(port);receive({type:"watch",id});
  return{messages,close(){disconnect()}}}
async function waitFor(predicate){for(let i=0;i<200;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,0))}
  throw new Error("condition did not settle")}
(async()=>{
  const tab={id:7,url:"https://example.invalid/restart.mp4",title:"Restart"};const first=worker();
  const prepared=await send(first,{type:"confirmation.prepare",tab,scope:"page"});
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.phase==="ready");
  const preRestart={phase:shared["lbrain-popup-job-v1"].phase,cache:Object.keys(cached).length};

  const restarted=worker(),lostWatch=watch(restarted,prepared.id);
  await waitFor(()=>lostWatch.messages.some(message=>message.job?.phase==="failed"));
  const lostJob=lostWatch.messages.at(-1).job;
  const lost={phase:lostJob.phase,preview:Boolean(lostJob.preview),cache:Object.keys(cached).length};
  await send(restarted,{type:"confirmation.cancel",id:prepared.id});
  const reread=await send(restarted,{type:"confirmation.prepare",tab,scope:"page"});
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.id===reread.id&&shared["lbrain-popup-job-v1"].phase==="ready");
  const rereadResult={phase:reread.phase,fresh:reread.id!==prepared.id,stored:shared["lbrain-popup-job-v1"].phase};

  const origin="https://armed.invalid/*";
  await send(restarted,{type:"confirmation.preflight",id:reread.id,permission_origins:[origin]});
  const armed=await send(restarted,{type:"confirmation.arm",id:reread.id});
  const afterArm={cache:Object.keys(cached).length,saveIntent:Boolean(shared["lbrain-save-reservation-v1"]?.save_intent)};
  const armedRestart=worker(),restoredWatch=watch(armedRestart,reread.id);
  await waitFor(()=>restoredWatch.messages.some(message=>message.job?.phase==="ready"));
  granted.add(origin);armedRestart.permissionAdded({origins:[origin]});
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.phase==="saving"&&nativeReplies.length===1);
  nativeReplies.shift()({status:"saved",target:"Inbox/Captures/restart.md",capture_id:"restart",version:1});
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.phase==="complete"&&!shared["lbrain-save-reservation-v1"]);
  const completed={phase:shared["lbrain-popup-job-v1"].phase,status:shared["lbrain-popup-job-v1"].receipt.status,
    cache:Object.keys(cached).length,permission:granted.has(origin),journal:local["lbrain-temporary-origins-v1"]||[]};

  for(const values of [shared,local,cached])for(const key of Object.keys(values))delete values[key];
  granted.clear();removed.length=0;const beforeOrphanNative=nativeConnections;
  const orphanOrigin="https://orphan-watch.invalid/*",orphanTab={id:8,url:"https://example.invalid/orphan.mp4",title:"Orphan"};
  shared["lbrain-popup-job-v1"]={id:"orphan-watch",phase:"saving",tab:orphanTab,
    preview:{title:"Orphan",summary:"",permission_origins:[orphanOrigin],details:[]}};
  shared["lbrain-save-reservation-v1"]={id:"orphan-watch",created:Date.now(),state:"saving",
    allowed_origins:[orphanOrigin],release_origins:[orphanOrigin]};
  local["lbrain-temporary-origins-v1"]=[orphanOrigin];granted.add(orphanOrigin);
  cached["https://lbrain.invalid/confirmation/orphan-watch"]=JSON.stringify({capture:video(orphanTab),tab:orphanTab});
  const orphanWorker=worker(),orphanWatch=watch(orphanWorker,"orphan-watch");
  await waitFor(()=>orphanWatch.messages.some(message=>message.job?.phase==="failed")
    && !shared["lbrain-save-reservation-v1"]&&!granted.has(orphanOrigin));
  const orphanJob=orphanWatch.messages.at(-1).job;
  const orphan={phase:orphanJob.phase,preview:Boolean(orphanJob.preview),cache:Object.keys(cached).length,
    permission:granted.has(orphanOrigin),journal:local["lbrain-temporary-origins-v1"]||[],
    reservation:Boolean(shared["lbrain-save-reservation-v1"]),removed:[...removed],
    nativeDelta:nativeConnections-beforeOrphanNative};
  console.log(JSON.stringify({preRestart,lost,reread:rereadResult,armed,afterArm,
    restored:restoredWatch.messages.find(message=>message.job?.phase==="ready").job.phase,completed,orphan,nativeConnections}));
})().catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["preRestart"], {"phase": "ready", "cache": 0})
        self.assertEqual(output["lost"], {"phase": "failed", "preview": False, "cache": 0})
        self.assertEqual(output["reread"], {"phase": "preparing", "fresh": True, "stored": "ready"})
        self.assertEqual(output["armed"], {"armed": True, "started": False})
        self.assertEqual(output["afterArm"], {"cache": 1, "saveIntent": True})
        self.assertEqual(output["restored"], "ready")
        self.assertEqual(output["completed"], {
            "phase": "complete", "status": "saved", "cache": 0,
            "permission": False, "journal": [],
        })
        self.assertEqual(output["orphan"], {
            "phase": "failed", "preview": True, "cache": 1,
            "permission": False, "journal": [], "reservation": False,
            "removed": ["https://orphan-watch.invalid/*"], "nativeDelta": 0,
        })
        self.assertEqual(output["nativeConnections"], 1)

    def test_extension_reservation_alarm_reclaims_stale_permission_and_preserves_live_save(self) -> None:
        script = r'''
const fs=require("fs"),vm=require("vm"),{webcrypto}=require("crypto");
const source=fs.readFileSync(process.argv[1],"utf8"),shared={},local={},cached={},granted=new Set(),removed=[],scheduled={};
let failRemove=false;
const storage=values=>({async get(key){if(key===null)return{...values};return{[key]:values[key]}},
  async set(entries){Object.assign(values,entries)},async remove(key){delete values[key]}});
const caches={async match(key){return cached[key]===undefined?undefined:new Response(cached[key])},async open(){return{
  async match(key){return cached[key]===undefined?undefined:new Response(cached[key])},async delete(key){delete cached[key]}}},
  async delete(){for(const key of Object.keys(cached))delete cached[key]}};
function worker(){let alarmHandler,messageHandler;const alarms={onAlarm:{addListener(fn){alarmHandler=fn}},
  async create(name,details){scheduled[name]=details},async clear(name){delete scheduled[name];return true}};
  const chrome={alarms,runtime:{onInstalled:{addListener(){}},onStartup:{addListener(){}},onMessage:{addListener(){}},
    onConnect:{addListener(){}},getURL(value){return"chrome-extension://test/"+value},lastError:null},
    contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(){}}},action:{onClicked:{addListener(){}}},
    windows:{onRemoved:{addListener(){}}},permissions:{onAdded:{addListener(){}},
      async contains({origins}){return origins.every(origin=>granted.has(origin))},async remove({origins}){
        if(failRemove)return false;let changed=false;for(const origin of origins)if(granted.delete(origin)){
          removed.push(origin);changed=true}return changed}},storage:{session:storage(shared),local:storage(local),
        onChanged:{addListener(){}}},notifications:{onButtonClicked:{addListener(){}}},tabs:{async create(){}}};
  const context={chrome,caches,crypto:webcrypto,URL,TextEncoder,Blob,Response,setTimeout,clearTimeout,console};
  chrome.runtime.onMessage={addListener(fn){messageHandler=fn}};
  vm.createContext(context);vm.runInContext(source,context);return{alarmHandler,messageHandler,context}}
function send(worker,message){return new Promise(resolve=>worker.messageHandler(message,{},resolve))}
function seed(id,origin){for(const values of [shared,local,cached,scheduled])for(const key of Object.keys(values))delete values[key];
  granted.clear();removed.length=0;shared["lbrain-popup-job-v1"]={id,phase:"saving",tab:{id:7,url:"https://example.invalid/"},
    preview:{title:"Saved",summary:"",permission_origins:[origin],details:[]}};
  shared["lbrain-save-reservation-v1"]={id,created:Date.now()-11*60*1000,state:"saving",
    allowed_origins:[origin],release_origins:[origin]};local["lbrain-temporary-origins-v1"]=[origin];
  cached[`https://lbrain.invalid/confirmation/${id}`]="confirmed";granted.add(origin)}
function state(id,origin){return{phase:shared["lbrain-popup-job-v1"]?.phase||null,
  preview:Boolean(shared["lbrain-popup-job-v1"]?.preview),reservation:shared["lbrain-save-reservation-v1"]?.id||null,
  permission:granted.has(origin),journal:local["lbrain-temporary-origins-v1"]||[],cache:Object.keys(cached).length,
  retry:Boolean(scheduled["lbrain-save-reservation-expiry-v1"]),removed:[...removed]}}
(async()=>{
  const scheduler=worker();const reserved=await send(scheduler,{type:"confirmation.reserve",id:"scheduled",permission_origins:[]});
  const scheduledLifecycle={reserved:reserved.reserved,scheduled:Boolean(scheduled["lbrain-save-reservation-expiry-v1"])};
  await send(scheduler,{type:"confirmation.release",id:"scheduled"});
  scheduledLifecycle.cleared=!scheduled["lbrain-save-reservation-expiry-v1"]&&!shared["lbrain-save-reservation-v1"];

  const staleOrigin="https://stale-alarm.invalid/*";seed("stale-alarm",staleOrigin);const staleWorker=worker();
  await staleWorker.alarmHandler({name:"lbrain-save-reservation-expiry-v1"});const stale=state("stale-alarm",staleOrigin);

  const failedOrigin="https://retry-alarm.invalid/*";seed("retry-alarm",failedOrigin);failRemove=true;const retryWorker=worker();
  await retryWorker.alarmHandler({name:"lbrain-save-reservation-expiry-v1"});const retained=state("retry-alarm",failedOrigin);
  failRemove=false;await retryWorker.alarmHandler({name:"lbrain-save-reservation-expiry-v1"});
  const retried=state("retry-alarm",failedOrigin);

  const liveOrigin="https://live-alarm.invalid/*";seed("live-alarm",liveOrigin);const liveWorker=worker();
  vm.runInContext("saveReservation = 'live-alarm'",liveWorker.context);
  await liveWorker.alarmHandler({name:"lbrain-save-reservation-expiry-v1"});const live=state("live-alarm",liveOrigin);
  console.log(JSON.stringify({scheduledLifecycle,stale,retained,retried,live}));
})().catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["scheduledLifecycle"], {"reserved": True, "scheduled": True, "cleared": True})
        self.assertEqual(output["stale"], {
            "phase": "failed", "preview": True, "reservation": None,
            "permission": False, "journal": [], "cache": 1, "retry": False,
            "removed": ["https://stale-alarm.invalid/*"],
        })
        self.assertEqual(output["retained"], {
            "phase": "failed", "preview": True, "reservation": "retry-alarm",
            "permission": True, "journal": ["https://retry-alarm.invalid/*"], "cache": 1,
            "retry": True, "removed": [],
        })
        self.assertEqual(output["retried"], {
            "phase": "failed", "preview": True, "reservation": None,
            "permission": False, "journal": [], "cache": 1, "retry": False,
            "removed": ["https://retry-alarm.invalid/*"],
        })
        self.assertEqual(output["live"], {
            "phase": "saving", "preview": True, "reservation": "live-alarm",
            "permission": True, "journal": ["https://live-alarm.invalid/*"], "cache": 1,
            "retry": True, "removed": [],
        })

    def test_extension_legacy_window_repreflights_after_native_failure_and_retries(self) -> None:
        script = r'''
const fs=require("fs"),vm=require("vm"),{webcrypto}=require("crypto");
const confirmSource=fs.readFileSync(process.argv[1],"utf8"),workerSource=fs.readFileSync(process.argv[2],"utf8");
let workerMessage,workerConnect,contextClick,createdUrl="",permissionAdded,nativeConnections=0,closed=0;
const shared={},local={},cached={},nativeReplies=[],events=[],messages=[],permissionResolvers=[],requests=[];
const origin="https://cdn.invalid/*",granted=new Set(),removed=[];
const storage=values=>({async get(key){if(key===null)return{...values};return{[key]:values[key]}},
  async set(entries){Object.assign(values,entries)},async remove(key){delete values[key]}});
const caches={async open(){return{async put(key,response){events.push("cache.put");cached[key]=await response.text()},
  async match(key){return cached[key]===undefined?undefined:new Response(cached[key])},
  async delete(key){events.push("cache.delete");delete cached[key]}}},
  async delete(){for(const key of Object.keys(cached))delete cached[key]}};
function connectNative(){nativeConnections++;let listener;return{onMessage:{addListener(fn){listener=fn}},
  onDisconnect:{addListener(){}},disconnect(){},postMessage(message){
    if(message.type==="chunk")queueMicrotask(()=>listener({type:"ack",channel:message.channel,sequence:message.sequence}));
    if(message.type==="end")nativeReplies.push(value=>listener(value))}}}
global.caches=caches;global.chrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(){}},
  onMessage:{addListener(fn){workerMessage=fn}},onConnect:{addListener(fn){workerConnect=fn}},
  getURL(value){return"chrome-extension://test/"+value},connectNative,lastError:null},
  contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(fn){contextClick=fn}}},
  action:{onClicked:{addListener(){}}},windows:{async create(options){createdUrl=options.url;return{id:19}},
    onRemoved:{addListener(){}}},permissions:{onAdded:{addListener(fn){permissionAdded=fn}},
    async contains({origins}){return origins.every(value=>granted.has(value))},
    async remove({origins}){let changed=false;for(const value of origins){if(granted.delete(value)){
      removed.push(value);changed=true}}return changed}},storage:{session:storage(shared),local:storage(local),onChanged:{addListener(){}}},
  notifications:{async create(){},onButtonClicked:{addListener(){}}},tabs:{async create(){}}};
global.crypto=webcrypto;eval(workerSource);
function sendWorker(message){messages.push(message);events.push(`runtime:${message.type}`);
  const sender={url:createdUrl,tab:{windowId:19}};return new Promise(resolve=>workerMessage(message,sender,resolve))}
async function waitFor(predicate){for(let i=0;i<250;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,0))}
  throw new Error("condition did not settle")}
function legacyPort(){let uiListener,serviceListener;const servicePort={name:"lbrain-confirm",
  onMessage:{addListener(fn){serviceListener=fn}},postMessage(message){const outbound=message?.type==="preview"
      ? {...message,preview:{...message.preview,permission_origins:[origin]}}:message;
    queueMicrotask(()=>uiListener(outbound))}};workerConnect(servicePort);return{
    onMessage:{addListener(fn){uiListener=fn}},postMessage(message){queueMicrotask(()=>serviceListener(message))},disconnect(){}}}
const listeners={},nodes={};const element=id=>nodes[id]||(nodes[id]={textContent:"",disabled:false,hidden:false,dataset:{},
  addEventListener(type,fn){listeners[`${id}:${type}`]=fn},append(){},replaceChildren(){},setAttribute(){},removeAttribute(){},
  classList:{add(){},remove(){},toggle(){}}});const body=element("body");body.dataset.phase="preparing";
const document={body,querySelector(selector){return selector==="body"?body:element(selector.replace(/^#/,""))},
  createElement(tag){return element(`created-${tag}-${Object.keys(nodes).length}`)}};
(async()=>{
  const tab={id:7,url:"https://example.invalid/movie.mp4",title:"Movie"};contextClick({menuItemId:"lbrain-save-page"},tab);
  await waitFor(()=>Boolean(createdUrl));await new Promise(resolve=>setTimeout(resolve,0));
  const uiChrome={runtime:{connect({name}){if(name!=="lbrain-confirm")throw new Error("wrong port");return legacyPort()},
      sendMessage:sendWorker},windows:{async getCurrent(){return{id:19}}},permissions:{request({origins}){
      events.push("permission.request");requests.push(origins);return new Promise(resolve=>permissionResolvers.push(resolve))}},
    tabs:{async query(){return[tab]}}};
  const context={chrome:uiChrome,caches,document,location:{search:new URL(createdUrl).search},window:{close(){closed++}},
    URLSearchParams,URL,Response,console,setTimeout,clearTimeout,queueMicrotask};vm.createContext(context);vm.runInContext(confirmSource,context);
  await waitFor(()=>messages.filter(value=>value.type==="confirmation.preflight").length===1&&!element("save").disabled);
  const firstPreflight=messages.find(value=>value.type==="confirmation.preflight");
  const firstOffset=events.length,firstClick=listeners["save:click"]();
  const firstImmediate={events:events.slice(firstOffset),phase:body.dataset.phase};
  granted.add(origin);permissionAdded({origins:[origin]});permissionResolvers.shift()(true);
  await waitFor(()=>nativeReplies.length===1);const firstBeforeNative=events.slice(firstOffset,firstOffset+3);
  nativeReplies.shift()({status:"failed",error:"disk unavailable"});await firstClick;
  await waitFor(()=>messages.filter(value=>value.type==="confirmation.preflight").length===2&&!element("save").disabled);
  const afterFailure={phase:body.dataset.phase,preflights:messages.filter(value=>value.type==="confirmation.preflight").length,
    releases:messages.filter(value=>value.type==="confirmation.release").length,closed};

  const secondOffset=events.length,secondClick=listeners["save:click"]();
  const secondImmediate={events:events.slice(secondOffset),phase:body.dataset.phase};
  granted.add(origin);permissionAdded({origins:[origin]});permissionResolvers.shift()(true);
  await waitFor(()=>nativeReplies.length===1);const secondBeforeNative=events.slice(secondOffset,secondOffset+3);
  nativeReplies.shift()({status:"saved",target:"Inbox/Captures/movie.md",capture_id:"movie",version:1});await secondClick;
  await waitFor(()=>!shared["lbrain-save-reservation-v1"]);
  console.log(JSON.stringify({firstPreflight,firstImmediate,firstBeforeNative,afterFailure,secondImmediate,secondBeforeNative,
    requests,nativeConnections,closed,removed,granted:[...granted],journal:local["lbrain-temporary-origins-v1"]||[],
    cached:Object.keys(cached).length,arms:messages.filter(value=>value.type==="confirmation.arm").length}));
})().catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            [
                "node", "-e", script,
                str(CAPTURE_EXTENSION / "confirm.js"),
                str(CAPTURE_EXTENSION / "service_worker.js"),
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["firstPreflight"]["type"], "confirmation.preflight")
        self.assertEqual(output["firstPreflight"]["window_id"], 19)
        self.assertEqual(output["firstPreflight"]["permission_origins"], ["https://cdn.invalid/*"])
        self.assertEqual(output["firstImmediate"], {"events": ["permission.request"], "phase": "saving"})
        self.assertEqual(output["firstBeforeNative"], [
            "permission.request", "cache.put", "runtime:confirmation.decide",
        ])
        self.assertEqual(output["afterFailure"], {
            "phase": "failed", "preflights": 2, "releases": 1, "closed": 0,
        })
        self.assertEqual(output["secondImmediate"], {"events": ["permission.request"], "phase": "saving"})
        self.assertEqual(output["secondBeforeNative"], [
            "permission.request", "cache.put", "runtime:confirmation.decide",
        ])
        self.assertEqual(output["requests"], [["https://cdn.invalid/*"], ["https://cdn.invalid/*"]])
        self.assertEqual(output["nativeConnections"], 2)
        self.assertEqual(output["closed"], 1)
        self.assertEqual(output["removed"], ["https://cdn.invalid/*", "https://cdn.invalid/*"])
        self.assertEqual(output["granted"], [])
        self.assertEqual(output["journal"], [])
        self.assertEqual(output["cached"], 0)
        self.assertEqual(output["arms"], 0)

    def test_extension_popup_reopens_from_session_without_duplicate_native_save(self) -> None:
        script = r'''
const fs=require("fs"),{webcrypto}=require("crypto");
let connectHandler,messageHandler,nativeMessage,endSeen=false,nativeConnections=0;
const shared={},local={},cached={},removed=[],granted=new Set();
const area={async get(key){if(key===null)return{...this.values};return{[key]:this.values[key]}},
  async set(values){Object.assign(this.values,values)},async remove(key){delete this.values[key]}};
const session={...area,values:shared};const localStorage={...area,values:local};
global.caches={async open(){return{
  async put(key,response){cached[key]=await response.text()},
  async match(key){return cached[key]===undefined?undefined:new Response(cached[key])},
  async delete(key){delete cached[key]}}},async delete(){for(const key of Object.keys(cached))delete cached[key]}};
function nativePort(){nativeConnections++;return{onMessage:{addListener(fn){nativeMessage=fn}},onDisconnect:{addListener(){}},disconnect(){},
  postMessage(message){if(message.type==="chunk")queueMicrotask(()=>nativeMessage({type:"ack",channel:message.channel,sequence:message.sequence}));
    if(message.type==="end")endSeen=true}}}
global.chrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(){}},onMessage:{addListener(fn){messageHandler=fn}},
  onConnect:{addListener(fn){connectHandler=fn}},getURL(value){return"chrome-extension://test/"+value},
  connectNative:nativePort,lastError:null},contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(){}}},
  action:{onClicked:{addListener(){}}},windows:{onRemoved:{addListener(){}}},
  permissions:{async remove({origins}){for(const origin of origins)if(granted.delete(origin))removed.push(origin);return true},
    async contains({origins}){return origins.every(origin=>granted.has(origin))}},
  storage:{session,local:localStorage,onChanged:{addListener(){}}},
  notifications:{async create(){},onButtonClicked:{addListener(){}}},tabs:{async create(){}}};
global.crypto=webcrypto;
eval(fs.readFileSync(process.argv[1],"utf8"));
function send(message){return new Promise(resolve=>messageHandler(message,{},resolve))}
async function waitFor(predicate){for(let i=0;i<100;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,0))}
  throw new Error("condition did not settle")}
function watch(id){let listener,disconnected;const messages=[];const port={name:"lbrain-popup",onMessage:{addListener(fn){listener=fn}},
  onDisconnect:{addListener(fn){disconnected=fn}},postMessage(message){messages.push(message)}};connectHandler(port);listener({type:"watch",id});
  return{messages,close(){disconnected()}}}
(async()=>{
  let tab={id:7,url:"https://example.invalid/movie.mp4",title:"Movie"};
  const preparing=await send({type:"confirmation.prepare",tab,scope:"page"});
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.phase==="ready");
  let id=preparing.id;const firstPopup=watch(id);await waitFor(()=>firstPopup.messages.length);
  const readyPhase=firstPopup.messages.at(-1).job.phase;firstPopup.close();await new Promise(resolve=>setTimeout(resolve,0));
  const firstId=id;
  const restoredReady=await send({type:"confirmation.prepare",tab,scope:"page"});
  id=restoredReady.id;
  const restoredPopup=watch(id);await waitFor(()=>restoredPopup.messages.length);restoredPopup.close();
  const oldId=id;tab={id:8,url:"https://example.invalid/other.mp4",title:"Other movie"};
  const replacement=await send({type:"confirmation.prepare",tab,scope:"page"});
  const oldCacheRemoved=!Object.keys(cached).some(key=>key.includes(oldId));id=replacement.id;
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.phase==="ready");
  const readyPopup=watch(id);await waitFor(()=>readyPopup.messages.length);
  const preflight=await send({type:"confirmation.preflight",id,permission_origins:["https://new.invalid/*"]});
  const armed=await send({type:"confirmation.arm",id});readyPopup.close();await new Promise(resolve=>setTimeout(resolve,0));
  const afterDisconnect={reservation:shared["lbrain-save-reservation-v1"]?.id||null,
    release:[...(shared["lbrain-save-reservation-v1"]?.release_origins||[])],
    journal:[...(local["lbrain-temporary-origins-v1"]||[])],state:shared["lbrain-save-reservation-v1"]?.state||null,
    saveIntent:Boolean(shared["lbrain-save-reservation-v1"]?.save_intent),
    contains:await chrome.permissions.contains({origins:["https://new.invalid/*"]})};
  const pendingOther=await send({type:"confirmation.prepare",
    tab:{id:10,url:"https://example.invalid/pending-other.mp4",title:"Pending other"},scope:"page"});
  const reentered=await send({type:"confirmation.preflight",id,permission_origins:["https://new.invalid/*"]});
  const merged={allowed:[...(shared["lbrain-save-reservation-v1"]?.allowed_origins||[])],
    release:[...(shared["lbrain-save-reservation-v1"]?.release_origins||[])],
    state:shared["lbrain-save-reservation-v1"]?.state||null,
    saveIntent:Boolean(shared["lbrain-save-reservation-v1"]?.save_intent)};
  granted.add("https://new.invalid/*");
  const savePopup=watch(id);await waitFor(()=>savePopup.messages.length);
  const first=send({type:"confirmation.decide",id,release_origins:["https://new.invalid/*"]});
  await waitFor(()=>endSeen&&shared["lbrain-popup-job-v1"]?.phase==="saving");
  savePopup.close();await new Promise(resolve=>setTimeout(resolve,0));
  const reopened=await send({type:"confirmation.prepare",
    tab:{id:9,url:"https://example.invalid/third.mp4",title:"Third movie"},scope:"page"});
  const savingPopup=watch(id);await waitFor(()=>savingPopup.messages.length);const reopenedWatch=savingPopup.messages.at(-1).job.phase;
  const duplicate=send({type:"confirmation.decide",id,release_origins:[]});
  await new Promise(resolve=>setTimeout(resolve,0));
  const during={phase:shared["lbrain-popup-job-v1"].phase,nativeConnections,
    reservation:shared["lbrain-save-reservation-v1"]?.id};
  nativeMessage({status:"saved",target:"Inbox/Captures/movie.md",capture_id:"movie",version:1});
  const completed=await first;const duplicateResult=await duplicate;
  const terminal=await send({type:"confirmation.prepare",tab,scope:"page"});
  const completeMessages=watch(id);await waitFor(()=>completeMessages.messages.length);
  console.log(JSON.stringify({preparing:preparing.phase,ready:readyPhase,restoredReady:restoredReady.phase,
    restoredFresh:restoredReady.id!==firstId,replacement:replacement.phase,replacedId:replacement.id!==oldId,oldCacheRemoved,
    reopened:reopened.phase,reopenedSameId:reopened.id===id,reopenedWatch,during,
    completed:completed.phase,status:completed.receipt.status,duplicateError:duplicateResult.error,
    terminal:terminal.phase,terminalWatch:completeMessages.messages.at(-1).job.phase,nativeConnections,
    preflightMissing:preflight.missing,armed,afterDisconnect,pendingOther:{id:pendingOther.id,phase:pendingOther.phase},
    reentered:{reserved:reentered.reserved,missing:reentered.missing},merged,removed,
    granted:[...granted],journal:local["lbrain-temporary-origins-v1"]||[]}));
})().catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["preparing"], "preparing")
        self.assertEqual(output["ready"], "ready")
        self.assertEqual(output["restoredReady"], "preparing")
        self.assertTrue(output["restoredFresh"])
        self.assertEqual(output["replacement"], "preparing")
        self.assertTrue(output["replacedId"])
        self.assertTrue(output["oldCacheRemoved"])
        self.assertEqual(output["reopened"], "saving")
        self.assertTrue(output["reopenedSameId"])
        self.assertEqual(output["reopenedWatch"], "saving")
        self.assertEqual(output["during"]["phase"], "saving")
        self.assertEqual(output["during"]["nativeConnections"], 1)
        self.assertTrue(output["during"]["reservation"])
        self.assertEqual(output["completed"], "complete")
        self.assertEqual(output["status"], "saved")
        self.assertIn("save slot", output["duplicateError"])
        self.assertEqual(output["terminal"], "complete")
        self.assertEqual(output["terminalWatch"], "complete")
        self.assertEqual(output["nativeConnections"], 1)
        self.assertTrue(output["afterDisconnect"]["reservation"])
        self.assertEqual(output["preflightMissing"], ["https://new.invalid/*"])
        self.assertEqual(output["armed"], {"armed": True, "started": False})
        self.assertEqual(output["afterDisconnect"]["release"], ["https://new.invalid/*"])
        self.assertEqual(output["afterDisconnect"]["journal"], ["https://new.invalid/*"])
        self.assertEqual(output["afterDisconnect"]["state"], "permission_pending")
        self.assertTrue(output["afterDisconnect"]["saveIntent"])
        self.assertFalse(output["afterDisconnect"]["contains"])
        self.assertEqual(output["pendingOther"]["phase"], "ready")
        self.assertEqual(output["pendingOther"]["id"], output["afterDisconnect"]["reservation"])
        self.assertEqual(output["reentered"], {"reserved": True, "missing": ["https://new.invalid/*"]})
        self.assertEqual(output["merged"]["allowed"], ["https://new.invalid/*"])
        self.assertEqual(output["merged"]["release"], ["https://new.invalid/*"])
        self.assertEqual(output["merged"]["state"], "permission_pending")
        self.assertTrue(output["merged"]["saveIntent"])
        self.assertEqual(output["removed"], ["https://new.invalid/*"])
        self.assertEqual(output["granted"], [])
        self.assertEqual(output["journal"], [])

    def test_extension_popup_watchers_and_preflight_replacement_do_not_leak_leases(self) -> None:
        script = r'''
const fs=require("fs"),{webcrypto}=require("crypto");
let connectHandler,messageHandler,windowRemoved,blockedGet,blockNextReservationGet=false,raceOldId="",nativeConnections=0;
const shared={},local={},cached={},ghostWrites=[],liveWindows=new Set([19,20]);
const session={async get(key){
    if(key==="lbrain-save-reservation-v1"&&blockNextReservationGet){blockNextReservationGet=false;
      return new Promise(resolve=>{blockedGet=()=>resolve({[key]:shared[key]})})}
    return{[key]:shared[key]}},
  async set(values){const reservation=values["lbrain-save-reservation-v1"];
    if(raceOldId&&reservation?.id===raceOldId&&shared["lbrain-popup-job-v1"]?.id!==raceOldId)ghostWrites.push(reservation.id);
    Object.assign(shared,values)},async remove(key){delete shared[key]}};
global.caches={async open(){return{async put(key,response){cached[key]=await response.text()},
  async match(key){return cached[key]===undefined?undefined:new Response(cached[key])},
  async delete(key){delete cached[key]}}},async delete(){}};
global.chrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(){}},onMessage:{addListener(fn){messageHandler=fn}},
  onConnect:{addListener(fn){connectHandler=fn}},getURL(value){return"chrome-extension://test/"+value},
  connectNative(){nativeConnections++;let listener;return{onMessage:{addListener(fn){listener=fn}},onDisconnect:{addListener(){}},
    disconnect(){},postMessage(message){if(message.type==="chunk")queueMicrotask(()=>listener({
      type:"ack",channel:message.channel,sequence:message.sequence}));if(message.type==="end")queueMicrotask(()=>listener({
      status:"saved",target:"Inbox/Captures/reconnect.md",capture_id:"reconnect",version:1}))}}},lastError:null},
  contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(){}}},
  action:{onClicked:{addListener(){}}},windows:{async get(id){if(liveWindows.has(id))return{id};throw new Error("closed")},
    onRemoved:{addListener(fn){windowRemoved=fn}}},permissions:{
    async contains({origins}){return origins.length===0},async remove(){return false}},
  storage:{session,local:{async get(key){return{[key]:local[key]}},async set(values){Object.assign(local,values)},
    async remove(key){delete local[key]}},onChanged:{addListener(){}}},notifications:{async create(){},onButtonClicked:{addListener(){}}},
  tabs:{async create(){}}};
global.crypto=webcrypto;eval(fs.readFileSync(process.argv[1],"utf8"));
function send(message,sender={}){return new Promise(resolve=>messageHandler(message,sender,resolve))}
async function waitFor(predicate){for(let i=0;i<100;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,0))}
  throw new Error("condition did not settle")}
function watch(id){let listener,disconnect;const port={name:"lbrain-popup",onMessage:{addListener(fn){listener=fn}},
  onDisconnect:{addListener(fn){disconnect=fn}},postMessage(){}};connectHandler(port);listener({type:"watch",id});return()=>disconnect()}
async function ready(tab){const job=await send({type:"confirmation.prepare",tab,scope:"page"});
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.phase==="ready");return job}
(async()=>{
  const firstTab={id:1,url:"https://example.invalid/first.mp4",title:"First"};let job=await ready(firstTab);
  const firstId=job.id,previewOrigin="https://preview.invalid/*",close=watch(firstId);
  const previewPreflight=await send({type:"confirmation.preflight",id:firstId,permission_origins:[previewOrigin]});close();
  const toolbar=await send({type:"confirmation.prepare",
    tab:{id:5,url:"https://example.invalid/toolbar.mp4",title:"Toolbar"},scope:"page"});
  const toolbarFlow={previewMissing:previewPreflight.missing,phase:toolbar.phase,fresh:toolbar.id!==firstId,
    oldLease:shared["lbrain-save-reservation-v1"]?.id===firstId,journal:local["lbrain-temporary-origins-v1"]||[]};
  await send({type:"confirmation.cancel",id:toolbar.id});

  const contextTab={id:6,url:"https://example.invalid/context.mp4",title:"Context"};job=await ready(contextTab);
  const contextId=job.id,contextOrigin="https://context-preview.invalid/*",closeContext=watch(contextId);
  const contextPreflight=await send({type:"confirmation.preflight",id:contextId,permission_origins:[contextOrigin]});
  closeContext();const other=await send({type:"confirmation.reserve",id:"context-menu",permission_origins:[]});
  const contextFlow={missing:contextPreflight.missing,reserved:other.reserved,
    reservation:shared["lbrain-save-reservation-v1"]?.id||null,
    journal:local["lbrain-temporary-origins-v1"]||[]};
  await send({type:"confirmation.release",id:"context-menu"});await send({type:"confirmation.cancel",id:contextId});

  const ownerTab={id:7,url:"https://example.invalid/owner.mp4",title:"Owner"};job=await ready(ownerTab);
  const ownerId=job.id,closeOwner=watch(ownerId);
  await send({type:"confirmation.preflight",id:ownerId,permission_origins:["https://owner.invalid/*"]});
  const blockedToolbar=await send({type:"confirmation.prepare",
    tab:{id:8,url:"https://example.invalid/blocked.mp4",title:"Blocked"},scope:"page"});
  const blockedContext=await send({type:"confirmation.reserve",id:"blocked-context",permission_origins:[]});
  const ownerBeforeClose={job:shared["lbrain-popup-job-v1"]?.id||null,
    reservation:shared["lbrain-save-reservation-v1"]?.id||null};
  closeOwner();const ownerReplacement=await send({type:"confirmation.prepare",
    tab:{id:8,url:"https://example.invalid/blocked.mp4",title:"Blocked"},scope:"page"});
  const popupOwner={toolbarError:blockedToolbar.error||null,contextError:blockedContext.error||null,
    before:ownerBeforeClose,replacementPhase:ownerReplacement.phase,replacementFresh:ownerReplacement.id!==ownerId,
    oldLease:shared["lbrain-save-reservation-v1"]?.id===ownerId,
    journal:local["lbrain-temporary-origins-v1"]||[]};
  await send({type:"confirmation.cancel",id:ownerReplacement.id});

  const reconnectTab={id:9,url:"https://example.invalid/reconnect.mp4",title:"Reconnect"};job=await ready(reconnectTab);
  const reconnectId=job.id,closeReconnectOld=watch(reconnectId);
  await send({type:"confirmation.preflight",id:reconnectId,permission_origins:[]});
  blockNextReservationGet=true;
  const heldMutation=send({type:"confirmation.permissions",id:reconnectId,origins:[]});
  await waitFor(()=>Boolean(blockedGet));closeReconnectOld();const closeReconnectNew=watch(reconnectId);
  const releaseHeld=blockedGet;blockedGet=null;releaseHeld();await heldMutation;await new Promise(resolve=>setTimeout(resolve,0));
  const keptBeforeDecide=shared["lbrain-save-reservation-v1"]?.id||null;
  const reconnectDecision=await send({type:"confirmation.decide",id:reconnectId});
  const reconnect={keptBeforeDecide,phase:reconnectDecision.phase,status:reconnectDecision.receipt.status,
    nativeConnections,reservation:shared["lbrain-save-reservation-v1"]?.id||null};
  closeReconnectNew();await send({type:"confirmation.cancel",id:reconnectId});

  const secondTab={id:2,url:"https://example.invalid/second.mp4",title:"Second"};job=await ready(secondTab);
  const closeOld=watch(job.id),closeNew=watch(job.id);
  await send({type:"confirmation.preflight",id:job.id,permission_origins:[]});closeOld();
  await new Promise(resolve=>setTimeout(resolve,0));const afterOld=shared["lbrain-save-reservation-v1"]?.id||null;
  closeNew();await waitFor(()=>!shared["lbrain-save-reservation-v1"]);const afterLast=shared["lbrain-save-reservation-v1"]?.id||null;
  await send({type:"confirmation.cancel",id:job.id});

  const raceTab={id:3,url:"https://example.invalid/race.mp4",title:"Race"};job=await ready(raceTab);raceOldId=job.id;
  blockNextReservationGet=true;const preflight=send({type:"confirmation.preflight",id:job.id,permission_origins:[]});
  await waitFor(()=>Boolean(blockedGet));
  const replacementTab={id:4,url:"https://example.invalid/replacement.mp4",title:"Replacement"};
  const replacement=send({type:"confirmation.prepare",tab:replacementTab,scope:"page"});
  await new Promise(resolve=>setTimeout(resolve,0));blockedGet();const preflightResult=await preflight;const replaced=await replacement;
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.id===replaced.id);
  const race={oldId:job.id,newId:replaced.id,preflightError:preflightResult.error||null,ghostWrites,
    reservation:shared["lbrain-save-reservation-v1"]?.id||null,current:shared["lbrain-popup-job-v1"].id};
  await send({type:"confirmation.cancel",id:replaced.id});

  const legacyOwner="legacy-owner",legacyOther="legacy-other";
  const legacySender=(id,windowId)=>({url:`chrome-extension://test/confirm.html?id=${id}`,tab:{windowId}});
  const legacyPreflight=await send({type:"confirmation.preflight",id:legacyOwner,window_id:19,
    permission_origins:["https://legacy-owner.invalid/*"]},legacySender(legacyOwner,19));
  const legacyBlocked=await send({type:"confirmation.preflight",id:legacyOther,window_id:20,
    permission_origins:[]},legacySender(legacyOther,20));
  const legacyContextBlocked=await send({type:"confirmation.reserve",id:"legacy-context",permission_origins:[]});
  liveWindows.delete(19);windowRemoved(19);
  await waitFor(()=>shared["lbrain-save-reservation-v1"]?.id!==legacyOwner);
  const legacyReplacement=await send({type:"confirmation.preflight",id:legacyOther,window_id:20,
    permission_origins:[]},legacySender(legacyOther,20));
  const legacyOwnerFlow={missing:legacyPreflight.missing,preflightError:legacyBlocked.error||null,
    contextError:legacyContextBlocked.error||null,replacement:legacyReplacement,
    reservation:shared["lbrain-save-reservation-v1"]?.id||null,
    journal:local["lbrain-temporary-origins-v1"]||[]};
  await send({type:"confirmation.release",id:legacyOther});
  console.log(JSON.stringify({toolbarFlow,contextFlow,popupOwner,reconnect,legacyOwnerFlow,watchers:{afterOld,afterLast},race}));
})().catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["toolbarFlow"], {
            "previewMissing": ["https://preview.invalid/*"],
            "phase": "preparing",
            "fresh": True,
            "oldLease": False,
            "journal": [],
        })
        self.assertEqual(output["contextFlow"], {
            "missing": ["https://context-preview.invalid/*"],
            "reserved": True,
            "reservation": "context-menu",
            "journal": [],
        })
        self.assertIn("preview is already open", output["popupOwner"]["toolbarError"])
        self.assertIn("already being saved", output["popupOwner"]["contextError"])
        self.assertTrue(output["popupOwner"]["before"]["job"])
        self.assertEqual(output["popupOwner"]["before"]["job"], output["popupOwner"]["before"]["reservation"])
        self.assertEqual(output["popupOwner"]["replacementPhase"], "preparing")
        self.assertTrue(output["popupOwner"]["replacementFresh"])
        self.assertFalse(output["popupOwner"]["oldLease"])
        self.assertEqual(output["popupOwner"]["journal"], [])
        self.assertTrue(output["reconnect"]["keptBeforeDecide"])
        self.assertEqual(output["reconnect"]["phase"], "complete")
        self.assertEqual(output["reconnect"]["status"], "saved")
        self.assertEqual(output["reconnect"]["nativeConnections"], 1)
        self.assertIsNone(output["reconnect"]["reservation"])
        self.assertEqual(output["legacyOwnerFlow"]["missing"], ["https://legacy-owner.invalid/*"])
        self.assertIn("already being saved", output["legacyOwnerFlow"]["preflightError"])
        self.assertIn("already being saved", output["legacyOwnerFlow"]["contextError"])
        self.assertEqual(output["legacyOwnerFlow"]["replacement"], {"reserved": True, "missing": []})
        self.assertEqual(output["legacyOwnerFlow"]["reservation"], "legacy-other")
        self.assertEqual(output["legacyOwnerFlow"]["journal"], [])
        self.assertTrue(output["watchers"]["afterOld"])
        self.assertIsNone(output["watchers"]["afterLast"])
        self.assertNotEqual(output["race"]["oldId"], output["race"]["newId"])
        self.assertEqual(output["race"]["ghostWrites"], [])
        self.assertNotEqual(output["race"]["reservation"], output["race"]["oldId"])
        self.assertEqual(output["race"]["current"], output["race"]["newId"])

    def test_extension_popup_failure_keeps_prepared_capture_for_retry(self) -> None:
        script = r'''
const fs=require("fs"),{webcrypto}=require("crypto");
let messageHandler,connectHandler,nativeConnections=0;const shared={},cached={},nativeReplies=[],notifications=[];
const session={async get(key){return{[key]:shared[key]}},async set(values){Object.assign(shared,values)},
  async remove(key){delete shared[key]}};
global.caches={async open(){return{async put(key,response){cached[key]=await response.text()},
  async match(key){return cached[key]===undefined?undefined:new Response(cached[key])},
  async delete(key){delete cached[key]}}},async delete(){}};
function connectNative(){nativeConnections++;let listener;return{onMessage:{addListener(fn){listener=fn}},
  onDisconnect:{addListener(){}},disconnect(){},postMessage(message){
    if(message.type==="chunk")queueMicrotask(()=>listener({type:"ack",channel:message.channel,sequence:message.sequence}));
    if(message.type==="end")nativeReplies.push(value=>listener(value))}}}
global.chrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(){}},onMessage:{addListener(fn){messageHandler=fn}},
  onConnect:{addListener(fn){connectHandler=fn}},getURL(value){return"chrome-extension://test/"+value},connectNative,lastError:null},
  contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(){}}},action:{onClicked:{addListener(){}}},
  windows:{onRemoved:{addListener(){}}},permissions:{async remove(){return true},async contains(){return false}},
  storage:{session,local:{async get(key){return key===null?{}:{[key]:undefined}},async set(){},async remove(){}}},
  notifications:{async create(id,options){notifications.push({id,...options})},onButtonClicked:{addListener(){}}},
  tabs:{async create(){}}};
global.crypto=webcrypto;eval(fs.readFileSync(process.argv[1],"utf8"));
function send(message){return new Promise(resolve=>messageHandler(message,{},resolve))}
async function waitFor(predicate){for(let i=0;i<100;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,0))}
  throw new Error("condition did not settle")}
function watch(id){let listener,disconnect;const port={name:"lbrain-popup",onMessage:{addListener(fn){listener=fn}},
  onDisconnect:{addListener(fn){disconnect=fn}},postMessage(){}};connectHandler(port);listener({type:"watch",id});return()=>disconnect()}
(async()=>{const tab={id:7,url:"https://example.invalid/movie.mp4",title:"Movie"};
  const preparing=await send({type:"confirmation.prepare",tab,scope:"page"});
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.phase==="ready");const id=preparing.id;
  const firstPreflight=await send({type:"confirmation.preflight",id,permission_origins:[]});
  const close=watch(id);
  const first=send({type:"confirmation.decide",id,release_origins:[]});await waitFor(()=>nativeReplies.length===1);
  const closedPhase=shared["lbrain-popup-job-v1"].phase;close();await new Promise(resolve=>setTimeout(resolve,0));
  nativeReplies.shift()({status:"failed",error:"disk unavailable"});const failure=await first;
  const afterFailure={phase:shared["lbrain-popup-job-v1"].phase,error:shared["lbrain-popup-job-v1"].error,
    cached:Object.keys(cached).length};
  const retryPreflight=await send({type:"confirmation.preflight",id,permission_origins:[]});
  const retry=send({type:"confirmation.decide",id,release_origins:[]});await waitFor(()=>nativeReplies.length===1);
  nativeReplies.shift()({status:"saved",target:"Inbox/Captures/movie.md",capture_id:"movie",version:1});
  const completed=await retry;
  console.log(JSON.stringify({firstPreflight,retryPreflight,failure:failure.error,afterFailure,completed:completed.phase,
    status:completed.receipt.status,cached:Object.keys(cached).length,nativeConnections,closedPhase,
    failureNotifications:notifications.filter(value=>value.title==="LBrain capture needs attention").map(value=>value.message)}))})()
  .catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["firstPreflight"], {"reserved": True, "missing": []})
        self.assertIn("disk unavailable", output["failure"])
        self.assertEqual(output["afterFailure"], {
            "phase": "failed", "error": "disk unavailable", "cached": 1,
        })
        self.assertEqual(output["retryPreflight"], {"reserved": True, "missing": []})
        self.assertEqual(output["completed"], "complete")
        self.assertEqual(output["status"], "saved")
        self.assertEqual(output["cached"], 0)
        self.assertEqual(output["nativeConnections"], 2)
        self.assertEqual(output["closedPhase"], "saving")
        self.assertIn("disk unavailable", output["failureNotifications"])

    def test_extension_mv3_restart_recovers_orphaned_saving_and_blocks_duplicate_native(self) -> None:
        script = r'''
const fs=require("fs"),vm=require("vm"),{webcrypto}=require("crypto");
const source=fs.readFileSync(process.argv[1],"utf8");
const shared={},local={},cached={},granted=new Set(),removed=[],nativeReplies=[];let nativeConnections=0;
const storage=values=>({async get(key){if(key===null)return{...values};return{[key]:values[key]}},
  async set(entries){Object.assign(values,entries)},async remove(key){delete values[key]}});
const session=storage(shared),localStorage=storage(local);
const caches={async open(){return{async put(key,response){cached[key]=await response.text()},
  async match(key){return cached[key]===undefined?undefined:new Response(cached[key])},
  async delete(key){delete cached[key]}}},async delete(){for(const key of Object.keys(cached))delete cached[key]}};
function worker(){let handler;const chrome={runtime:{onInstalled:{addListener(){}},onStartup:{addListener(){}},
  onMessage:{addListener(fn){handler=fn}},onConnect:{addListener(){}},getURL(value){return"chrome-extension://test/"+value},
  connectNative(){nativeConnections++;let listener;return{onMessage:{addListener(fn){listener=fn}},onDisconnect:{addListener(){}},
    disconnect(){},postMessage(message){if(message.type==="chunk")queueMicrotask(()=>listener({type:"ack",channel:message.channel,sequence:message.sequence}));
      if(message.type==="end")nativeReplies.push(value=>listener(value))}}},lastError:null},
  contextMenus:{removeAll(fn){fn()},create(){},onClicked:{addListener(){}}},action:{onClicked:{addListener(){}}},
  windows:{onRemoved:{addListener(){}}},permissions:{async contains({origins}){return origins.every(origin=>granted.has(origin))},
    async remove({origins}){for(const origin of origins)if(granted.delete(origin))removed.push(origin);return true}},
  storage:{session,local:localStorage,onChanged:{addListener(){}}},notifications:{async create(){},onButtonClicked:{addListener(){}}},
  tabs:{async create(){}}};
  const context={chrome,caches,crypto:webcrypto,URL,TextEncoder,Blob,Response,AbortSignal,setTimeout,clearTimeout,
    queueMicrotask,console,btoa:value=>Buffer.from(value,"binary").toString("base64")};
  vm.createContext(context);vm.runInContext(source,context);return{handler}}
function send(handler,message,sender={}){return new Promise(resolve=>handler(message,sender,resolve))}
async function waitFor(predicate){for(let i=0;i<100;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,0))}
  throw new Error("condition did not settle")}
const video=tab=>({schema:"lbrain.capture.v1",title:tab.title,summary:"Original video link captured without the video binary.",
  origin:tab.url,scope:"page",author:"",published_at:"",content_markdown:"Video",capture_kind:"video",
  has_video:true,preview_characters:0,extraction_status:"complete",remote_assets:[],assets:[]});
(async()=>{
  const activeTab={id:7,url:"https://example.invalid/active.mp4",title:"Active"};const live=worker();
  const preparing=await send(live.handler,{type:"confirmation.prepare",tab:activeTab,scope:"page"});
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.phase==="ready");
  await send(live.handler,{type:"confirmation.preflight",id:preparing.id,permission_origins:[]});
  const liveSave=send(live.handler,{type:"confirmation.decide",id:preparing.id,release_origins:[]});
  await waitFor(()=>nativeReplies.length===1&&shared["lbrain-popup-job-v1"]?.phase==="saving");
  shared["lbrain-save-reservation-v1"].created=Date.now()-11*60*1000;
  const resumed=await send(live.handler,{type:"confirmation.prepare",
    tab:{id:8,url:"https://example.invalid/other.mp4",title:"Other"},scope:"page"});
  const busyReserve=await send(live.handler,{type:"confirmation.reserve",id:"legacy-reserve",permission_origins:[]});
  const legacyId="legacy-preflight",legacyWindow=19;
  const busyPreflight=await send(live.handler,{type:"confirmation.preflight",id:legacyId,
    window_id:legacyWindow,permission_origins:[]},{url:`chrome-extension://test/confirm.html?id=${legacyId}`,
    tab:{windowId:legacyWindow}});
  const active={phase:resumed.phase,sameId:resumed.id===preparing.id,nativeConnections,
    reserveError:busyReserve.error||null,preflightError:busyPreflight.error||null};
  nativeReplies.shift()({status:"saved",target:"Inbox/Captures/active.md",capture_id:"active",version:1});await liveSave;

  for(const values of [shared,local,cached])for(const key of Object.keys(values))delete values[key];
  granted.clear();removed.length=0;granted.add("https://orphan.invalid/*");
  const orphanTab={id:9,url:"https://example.invalid/orphan.mp4",title:"Orphan"};
  shared["lbrain-popup-job-v1"]={id:"orphan",phase:"saving",tab:orphanTab};
  shared["lbrain-save-reservation-v1"]={id:"orphan",created:Date.now(),state:"saving",
    allowed_origins:["https://orphan.invalid/*"],release_origins:["https://orphan.invalid/*"]};
  local["lbrain-temporary-origins-v1"]=["https://orphan.invalid/*"];
  cached["https://lbrain.invalid/confirmation/orphan"]=JSON.stringify({capture:video(orphanTab),tab:orphanTab});
  const restartedOrphan=worker();
  const duplicateReserve=await send(restartedOrphan.handler,{type:"confirmation.reserve",id:"orphan",permission_origins:[]});
  const duplicateDecide=await send(restartedOrphan.handler,{type:"confirmation.decide",id:"orphan",release_origins:[]});
  const beforeRecovery={reserveError:duplicateReserve.error||null,decideError:duplicateDecide.error||null,nativeConnections};
  const recovered=await send(restartedOrphan.handler,{type:"confirmation.prepare",tab:orphanTab,scope:"page"});
  const afterRecovery={phase:recovered.phase,error:recovered.error,removed:[...removed],journal:local["lbrain-temporary-origins-v1"]||[],
    reservation:Boolean(shared["lbrain-save-reservation-v1"]),nativeConnections};
  const cancelled=await send(restartedOrphan.handler,{type:"confirmation.cancel",id:"orphan"});
  const retried=await send(restartedOrphan.handler,{type:"confirmation.prepare",tab:orphanTab,scope:"page"});
  await waitFor(()=>shared["lbrain-popup-job-v1"]?.phase==="ready");
  console.log(JSON.stringify({active,beforeRecovery,afterRecovery,cancelled:cancelled.cancelled,retry:{phase:retried.phase,
    newId:retried.id!=="orphan",stored:shared["lbrain-popup-job-v1"].phase},nativeConnections}));
})().catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            ["node", "-e", script, str(CAPTURE_EXTENSION / "service_worker.js")],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["active"]["phase"], "saving")
        self.assertTrue(output["active"]["sameId"])
        self.assertEqual(output["active"]["nativeConnections"], 1)
        self.assertIn("already being saved", output["active"]["reserveError"])
        self.assertIn("already being saved", output["active"]["preflightError"])
        self.assertIn("already being saved", output["beforeRecovery"]["reserveError"])
        self.assertIn("not ready", output["beforeRecovery"]["decideError"])
        self.assertEqual(output["beforeRecovery"]["nativeConnections"], 1)
        self.assertEqual(output["afterRecovery"]["phase"], "failed")
        self.assertTrue(output["afterRecovery"]["error"])
        self.assertEqual(output["afterRecovery"]["removed"], ["https://orphan.invalid/*"])
        self.assertEqual(output["afterRecovery"]["journal"], [])
        self.assertFalse(output["afterRecovery"]["reservation"])
        self.assertEqual(output["afterRecovery"]["nativeConnections"], 1)
        self.assertTrue(output["cancelled"])
        self.assertEqual(output["retry"], {"phase": "preparing", "newId": True, "stored": "ready"})
        self.assertEqual(output["nativeConnections"], 1)

    def test_bundle_extracts_pdf_and_subtitle_text_and_recovers_partial_media(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.copy_repo(base)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Capture Test"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "capture@example.invalid"], check=True
            )
            staging = base / "staging"
            tools = base / "tools"
            staging.mkdir()
            tools.mkdir()
            (tools / "pdftotext").write_text("#!/bin/sh\nprintf 'Searchable PDF sentence.\\n'\n", encoding="utf-8")
            (tools / "pdftotext").chmod(0o755)
            (staging / "report.pdf").write_bytes(b"%PDF synthetic fixture")
            (staging / "captions.vtt").write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nFirst subtitle line.\n",
                encoding="utf-8",
            )
            partial_payload: dict[str, object] = {
                "schema": "lbrain.capture.v1",
                "title": "Research Media",
                "summary": "A PDF and transcript saved with a recoverable image.",
                "origin": "https://example.invalid/research-media",
                "scope": "page",
                "content_markdown": (
                    "## Original analysis\n\nPreserve this source heading exactly once.\n\n"
                    "Literal marker: <!-- lbrain:capture:end -->\n\n"
                    "[PDF](lbrain-asset://pdf)\n\n[Subtitles](lbrain-asset://captions)\n\n"
                    "![Diagram](https://cdn.example.invalid/diagram.png)"
                ),
                "source_content_markdown": (
                    "## Original analysis\n\nPreserve this source heading exactly once.\n\n"
                    "Literal marker: <!-- lbrain:capture:end -->\n\n"
                    "[PDF](https://cdn.example.invalid/report.pdf)\n\n"
                    "[Subtitles](https://cdn.example.invalid/captions.vtt)\n\n"
                    "![Diagram](https://cdn.example.invalid/diagram.png)"
                ),
                "extraction_status": "partial",
                "assets": [
                    {"name": "documents/report.pdf", "staged_name": "report.pdf", "placeholder": "lbrain-asset://pdf", "media_type": "application/pdf"},
                    {"name": "transcripts/captions.vtt", "staged_name": "captions.vtt", "placeholder": "lbrain-asset://captions", "media_type": "text/vtt"},
                ],
            }
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{tools}{os.pathsep}{old_path}"
            try:
                initial_result, initial = self.run_capture_native_host(root, partial_payload, staging)
            finally:
                os.environ["PATH"] = old_path
            self.assertEqual(initial_result.returncode, 0, (initial_result.stderr.decode(), initial))
            self.assertEqual(initial["status"], "partial")
            note = root / str(initial["target"])
            initial_note = note.read_text(encoding="utf-8")
            self.assertIn("Searchable PDF sentence.", initial_note)
            self.assertIn("First subtitle line.", initial_note)
            edited = initial_note.replace("visibility: private", "visibility: private\ntags: [research]")
            edited += "\n## Research notes\n\nKeep this user note.\n"
            note.write_text(edited, encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "--", str(initial["target"])], check=True)

            (staging / "diagram.png").write_bytes(b"diagram bytes")
            complete_payload = {
                **partial_payload,
                "content_markdown": (
                    "## Original analysis\n\nPreserve this source heading exactly once.\n\n"
                    "Literal marker: <!-- lbrain:capture:end -->\n\n"
                    "[PDF](https://cdn.example.invalid/report.pdf)\n\n"
                    "[Subtitles](https://cdn.example.invalid/captions.vtt)\n\n"
                    "![Diagram](lbrain-asset://diagram)\n\n## Capture warnings\n\n"
                    "- Media could not be preserved: https://cdn.example.invalid/report.pdf\n"
                    "- Media could not be preserved: https://cdn.example.invalid/captions.vtt"
                ),
                "extraction_status": "complete",
                "recovery_target": initial["target"],
                "expected_hash": initial["expected_hash"],
                "failed_remote_assets": [
                    {"id": "pdf", "url": "https://cdn.example.invalid/report.pdf"},
                    {"id": "captions", "url": "https://cdn.example.invalid/captions.vtt"},
                ],
                "assets": [
                    {"name": "images/diagram.png", "staged_name": "diagram.png", "placeholder": "lbrain-asset://diagram", "media_type": "image/png"},
                ],
            }
            os.environ["PATH"] = f"{tools}{os.pathsep}{old_path}"
            try:
                recovered_result, recovered = self.run_capture_native_host(root, complete_payload, staging)
            finally:
                os.environ["PATH"] = old_path
            self.assertEqual(recovered_result.returncode, 0, (recovered_result.stderr.decode(), recovered))
            self.assertEqual(recovered["status"], "saved")
            self.assertEqual(recovered["version"], 1)
            self.assertEqual(recovered["target"], initial["target"])
            self.assertFalse(dict(recovered["git"])["committed"])
            staged_note = subprocess.run(
                ["git", "-C", str(root), "show", f":{initial['target']}"],
                text=True,
                capture_output=True,
                check=True,
            ).stdout
            self.assertEqual(staged_note, edited)
            recovered_note = note.read_text(encoding="utf-8")
            self.assertIn("tags: [research]", recovered_note)
            self.assertIn("Keep this user note.", recovered_note)
            self.assertIn("extraction_status: complete", recovered_note)
            self.assertIn("Searchable PDF sentence.", recovered_note)
            self.assertIn("First subtitle line.", recovered_note)
            self.assertEqual(recovered_note.count("Searchable PDF sentence."), 1)
            self.assertEqual(recovered_note.count("First subtitle line."), 1)
            self.assertEqual(recovered_note.count("Preserve this source heading exactly once."), 1)
            self.assertEqual(recovered_note.count("<!-- lbrain:capture:end -->"), 1)
            self.assertIn("&lt;!-- lbrain:capture:end -->", recovered_note)
            self.assertNotIn("https://cdn.example.invalid/report.pdf", recovered_note)
            self.assertNotIn("https://cdn.example.invalid/captions.vtt", recovered_note)
            self.assertIn("_assets/", recovered_note)
            manifest = json.loads(
                (root / f"Inbox/Captures/_assets/{initial['capture_id']}/v1/manifest.json").read_text()
            )
            self.assertEqual({asset["name"] for asset in manifest["assets"]}, {
                "documents/report.pdf", "transcripts/captions.vtt", "images/diagram.png"
            })

    def test_changed_partial_retry_creates_an_immutable_new_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            initial_payload = {
                "schema": "lbrain.capture.v1",
                "title": "Changing Article",
                "summary": "First rendered state.",
                "origin": "https://example.invalid/changing-article",
                "scope": "page",
                "author": "Example Author",
                "published_at": "2026-08-11",
                "content_markdown": "The first rendered body.",
                "extraction_status": "partial",
                "assets": [],
            }
            first_result, first = self.run_capture_native_host(root, initial_payload, root)
            self.assertEqual(first_result.returncode, 0, (first_result.stderr.decode(), first))
            first_note = root / str(first["target"])
            first_text = first_note.read_text(encoding="utf-8")

            changed_payload = {
                **initial_payload,
                "summary": "A changed rendered state.",
                "content_markdown": "The page now contains a different body.",
                "source_content_markdown": "The page now contains a different body.",
                "extraction_status": "complete",
                "recovery_target": first["target"],
                "expected_hash": first["expected_hash"],
            }
            changed_result, changed = self.run_capture_native_host(root, changed_payload, root)

            self.assertEqual(changed_result.returncode, 0, (changed_result.stderr.decode(), changed))
            self.assertEqual(changed["status"], "new_version")
            self.assertEqual(changed["version"], 2)
            self.assertNotEqual(changed["target"], first["target"])
            self.assertEqual(first_note.read_text(encoding="utf-8"), first_text)
            self.assertIn(
                "The page now contains a different body.",
                (root / str(changed["target"])).read_text(encoding="utf-8"),
            )

    def test_changed_asset_bytes_create_a_new_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.copy_repo(base)
            staging = base / "staging"
            staging.mkdir()
            asset = staging / "image.png"
            asset.write_bytes(b"first image bytes")
            payload = {
                "schema": "lbrain.capture.v1",
                "title": "Changing Image",
                "summary": "The page text stays stable while image bytes change.",
                "origin": "https://example.invalid/changing-image",
                "scope": "page",
                "content_markdown": "![Image](lbrain-asset://image)",
                "source_content_markdown": "![Image](https://cdn.example.invalid/image)",
                "extraction_status": "partial",
                "assets": [{
                    "name": "images/image.png",
                    "staged_name": "image.png",
                    "placeholder": "lbrain-asset://image",
                    "media_type": "image/png",
                }],
            }
            first_result, first = self.run_capture_native_host(root, payload, staging)
            self.assertEqual(first_result.returncode, 0, (first_result.stderr.decode(), first))
            asset.write_bytes(b"second image bytes")
            retry_result, retry = self.run_capture_native_host(
                root,
                {
                    **payload,
                    "extraction_status": "complete",
                    "recovery_target": first["target"],
                    "expected_hash": first["expected_hash"],
                },
                staging,
            )
            self.assertEqual(retry_result.returncode, 0, (retry_result.stderr.decode(), retry))
            self.assertEqual(retry["status"], "new_version")
            self.assertEqual(retry["version"], 2)
            capture_id = str(first["capture_id"])
            self.assertEqual(
                (root / f"Inbox/Captures/_assets/{capture_id}/v1/files/images/image.png").read_bytes(),
                b"first image bytes",
            )
            self.assertEqual(
                (root / f"Inbox/Captures/_assets/{capture_id}/v2/files/images/image.png").read_bytes(),
                b"second image bytes",
            )

    def test_capture_recovery_conflict_preserves_both_asset_states(self) -> None:
        spec = importlib.util.spec_from_file_location("capture_operations_recovery", CAPTURE_OPERATIONS)
        assert spec and spec.loader
        operations = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(operations)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.copy_repo(base)
            staging = base / "staging"
            staging.mkdir()
            (staging / "old.png").write_bytes(b"old asset")
            initial_payload = {
                "schema": "lbrain.capture.v1",
                "title": "Recovery Conflict",
                "summary": "Both asset states remain recoverable after a concurrent edit.",
                "origin": "https://example.invalid/recovery-conflict",
                "scope": "page",
                "content_markdown": "![Old](lbrain-asset://old)\n\n![New](https://cdn.example.invalid/new.png)",
                "source_content_markdown": "![Old](https://cdn.example.invalid/old.png)\n\n![New](https://cdn.example.invalid/new.png)",
                "extraction_status": "partial",
                "assets": [{
                    "name": "images/old.png",
                    "staged_name": "old.png",
                    "placeholder": "lbrain-asset://old",
                    "media_type": "image/png",
                }],
            }
            with mock.patch.object(operations, "validate", return_value=(True, "ok")), mock.patch.object(
                operations, "capture_git_commit", return_value={"committed": False, "warning": None}
            ):
                initial = operations.capture_bundle(root, initial_payload, staging)
            note = root / str(initial["target"])
            existing = note.read_text(encoding="utf-8")
            (staging / "new.png").write_bytes(b"new asset")
            retry_payload = {
                **initial_payload,
                "content_markdown": "![Old](lbrain-asset://old)\n\n![New](lbrain-asset://new)",
                "extraction_status": "complete",
                "recovery_target": initial["target"],
                "expected_hash": initial["expected_hash"],
                "assets": [{
                    "name": "images/new.png",
                    "staged_name": "new.png",
                    "placeholder": "lbrain-asset://new",
                    "media_type": "image/png",
                }],
            }
            original_write = operations.atomic_write

            def concurrent_write(
                operation_root: Path, path: Path, content: str, expected: object = operations.UNCHANGED
            ) -> None:
                original_write(operation_root, path, content, expected)
                if path == note and expected == existing:
                    path.write_text(content + "\nConcurrent user note.\n", encoding="utf-8")

            with mock.patch.object(operations, "validate", return_value=(False, "synthetic failure")), mock.patch.object(
                operations, "atomic_write", side_effect=concurrent_write
            ), mock.patch.object(
                operations, "capture_git_commit", return_value={"committed": False, "warning": None}
            ):
                with self.assertRaises(operations.OperationError) as raised:
                    operations.capture_bundle(root, retry_payload, staging)

            self.assertIn("asset states preserved", str(raised.exception))
            self.assertIn("Concurrent user note.", note.read_text(encoding="utf-8"))
            capture_id = str(initial["capture_id"])
            current = root / f"Inbox/Captures/_assets/{capture_id}/v1/files/images"
            self.assertEqual({path.name for path in current.iterdir()}, {"old.png", "new.png"})
            backups = list((root / f"Inbox/Captures/_assets/{capture_id}").glob(".v1.backup.*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / "files/images/old.png").read_bytes(), b"old asset")

    def test_new_capture_rollback_conflict_preserves_its_assets(self) -> None:
        spec = importlib.util.spec_from_file_location("capture_operations_new_conflict", CAPTURE_OPERATIONS)
        assert spec and spec.loader
        operations = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(operations)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.copy_repo(base)
            staging = base / "staging"
            staging.mkdir()
            (staging / "image.png").write_bytes(b"captured asset")
            payload = {
                "schema": "lbrain.capture.v1",
                "title": "New Capture Conflict",
                "summary": "Keep assets when a concurrently edited note cannot be removed.",
                "origin": "https://example.invalid/new-capture-conflict",
                "scope": "page",
                "content_markdown": "![Image](lbrain-asset://image)",
                "extraction_status": "complete",
                "assets": [{
                    "name": "images/image.png",
                    "staged_name": "image.png",
                    "placeholder": "lbrain-asset://image",
                    "media_type": "image/png",
                }],
            }
            original_write = operations.atomic_write

            def concurrent_write(
                operation_root: Path, path: Path, content: str, expected: object = operations.UNCHANGED
            ) -> None:
                original_write(operation_root, path, content, expected)
                if expected is None and path.suffix == ".md":
                    path.write_text(content + "\nConcurrent user note.\n", encoding="utf-8")

            with mock.patch.object(operations, "validate", return_value=(False, "synthetic failure")), mock.patch.object(
                operations, "atomic_write", side_effect=concurrent_write
            ):
                with self.assertRaises(operations.OperationError) as raised:
                    operations.capture_bundle(root, payload, staging)

            self.assertIn("captured assets preserved", str(raised.exception))
            notes = list((root / "Inbox/Captures").glob("*New-Capture-Conflict*.md"))
            self.assertEqual(len(notes), 1)
            self.assertIn("Concurrent user note.", notes[0].read_text(encoding="utf-8"))
            capture_id = operations.bundle_capture_id(str(payload["origin"]), "page")
            self.assertEqual(
                (root / f"Inbox/Captures/_assets/{capture_id}/v1/files/images/image.png").read_bytes(),
                b"captured asset",
            )

    def test_new_capture_validation_preserves_a_concurrently_edited_asset(self) -> None:
        spec = importlib.util.spec_from_file_location("capture_operations_asset_conflict", CAPTURE_OPERATIONS)
        assert spec and spec.loader
        operations = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(operations)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.copy_repo(base)
            staging = base / "staging"
            staging.mkdir()
            (staging / "image.png").write_bytes(b"captured asset")
            payload = {
                "schema": "lbrain.capture.v1",
                "title": "Concurrent asset",
                "summary": "Validation must not delete a changed captured asset.",
                "origin": "https://example.invalid/concurrent-asset",
                "scope": "page",
                "content_markdown": "![Image](lbrain-asset://image)",
                "extraction_status": "complete",
                "assets": [{
                    "name": "images/image.png",
                    "staged_name": "image.png",
                    "placeholder": "lbrain-asset://image",
                    "media_type": "image/png",
                }],
            }
            capture_id = operations.bundle_capture_id(str(payload["origin"]), "page")
            saved_asset = root / f"Inbox/Captures/_assets/{capture_id}/v1/files/images/image.png"

            def conflicting_validation(_: Path) -> tuple[bool, str]:
                saved_asset.write_bytes(b"concurrent user edit")
                return False, "synthetic failure"

            with mock.patch.object(operations, "validate", side_effect=conflicting_validation):
                with self.assertRaises(operations.OperationError) as raised:
                    operations.capture_bundle(root, payload, staging)

            self.assertIn("captured assets preserved", str(raised.exception))
            self.assertEqual(saved_asset.read_bytes(), b"concurrent user edit")
            self.assertFalse(list((root / "Inbox/Captures").glob("*Concurrent-asset*.md")))

    def test_capture_rejects_a_symlinked_vault_destination_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.copy_repo(base)
            outside = base / "outside"
            outside.mkdir()
            (root / "Inbox/Captures/_assets").symlink_to(outside, target_is_directory=True)

            result, failed = self.run_capture_native_host(
                root,
                {
                    "schema": "lbrain.capture.v1",
                    "title": "Escaped Capture",
                    "summary": "Must fail before any external write.",
                    "origin": "https://example.invalid/escaped-capture",
                    "scope": "page",
                    "content_markdown": "Synthetic body.",
                    "extraction_status": "complete",
                    "assets": [],
                },
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(list(outside.iterdir()), [])
            self.assertFalse(list((root / "Inbox/Captures").glob("*Escaped-Capture*.md")))

    def test_pdf_text_falls_back_to_local_ocr(self) -> None:
        spec = importlib.util.spec_from_file_location("capture_operations_pdf", CAPTURE_OPERATIONS)
        assert spec and spec.loader
        operations = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(operations)
        with tempfile.TemporaryDirectory() as temporary:
            pdf = Path(temporary) / "scan.pdf"
            pdf.write_bytes(b"%PDF scanned fixture")

            def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                if command[0] == "pdftotext":
                    return subprocess.CompletedProcess(command, 0, "", "")
                if command[0] == "pdftoppm":
                    page = int(command[command.index("-f") + 1])
                    if page == 1:
                        Path(f"{command[-1]}.png").write_bytes(b"page")
                        return subprocess.CompletedProcess(command, 0, "", "")
                    return subprocess.CompletedProcess(command, 1, "", "")
                output = kwargs["stdout"]
                assert hasattr(output, "write")
                output.write(b"OCR recovered sentence.\n")
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch.object(operations.shutil, "which", side_effect=lambda name: name), mock.patch.object(
                operations.subprocess, "run", side_effect=run
            ):
                text, method = operations.local_pdf_text(pdf)
            self.assertEqual(method, "ocr")
            self.assertEqual(text, "OCR recovered sentence.")

            clock = [0.0]
            commands: list[str] = []

            def slow_render(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                commands.append(command[0])
                if command[0] == "pdftotext":
                    return subprocess.CompletedProcess(command, 0, "", "")
                Path(f"{command[-1]}.png").write_bytes(b"page")
                clock[0] = operations.MAX_OCR_SECONDS + 1
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch.object(operations.shutil, "which", side_effect=lambda name: name), mock.patch.object(
                operations.subprocess, "run", side_effect=slow_render
            ), mock.patch.object(operations.time, "monotonic", side_effect=lambda: clock[0]):
                _, method = operations.local_pdf_text(pdf)
            self.assertEqual(method, "failed")
            self.assertNotIn("tesseract", commands)

            def timeout_after_first_page(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                if command[0] == "pdftotext":
                    return subprocess.CompletedProcess(command, 0, "", "")
                if command[0] == "pdftoppm":
                    page = int(command[command.index("-f") + 1])
                    if page == 2:
                        raise subprocess.TimeoutExpired(command, kwargs["timeout"])
                    Path(f"{command[-1]}.png").write_bytes(b"page")
                    return subprocess.CompletedProcess(command, 0, "", "")
                output = kwargs["stdout"]
                assert hasattr(output, "write")
                output.write(b"First page OCR text.\n")
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch.object(operations.shutil, "which", side_effect=lambda name: name), mock.patch.object(
                operations.subprocess, "run", side_effect=timeout_after_first_page
            ):
                text, method = operations.local_pdf_text(pdf)
            self.assertEqual(text, "First page OCR text.")
            self.assertEqual(method, "ocr-truncated")

    def test_pdf_text_finds_homebrew_tool_when_native_host_path_is_empty(self) -> None:
        spec = importlib.util.spec_from_file_location("capture_operations_pdf_path", CAPTURE_OPERATIONS)
        assert spec and spec.loader
        operations = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(operations)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            pdf = base / "document.pdf"
            pdf.write_bytes(b"%PDF synthetic fixture")
            tool = base / "pdftotext"
            tool.write_text("#!/bin/sh\nprintf 'Native Host PDF text.\\n'\n", encoding="utf-8")
            tool.chmod(0o755)
            with mock.patch.object(operations, "LOCAL_TOOL_DIRS", (str(base),)), mock.patch.dict(
                os.environ, {"PATH": ""}
            ):
                text, method = operations.local_pdf_text(pdf)
            self.assertEqual((text, method), ("Native Host PDF text.", "text"))

    def test_capture_validate_keeps_checker_message(self) -> None:
        spec = importlib.util.spec_from_file_location("capture_operations_validate", CAPTURE_OPERATIONS)
        assert spec and spec.loader
        operations = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(operations)
        completed = subprocess.CompletedProcess([], 1, stdout="ERROR broken capture\n", stderr="")
        with mock.patch.object(operations.subprocess, "run", return_value=completed) as run:
            self.assertEqual(operations.validate(ROOT), (False, "ERROR broken capture"))
        self.assertNotIn("--quiet", run.call_args.args[0])

    def test_capture_binary_assets_use_git_lfs_without_a_remote(self) -> None:
        if shutil.which("git-lfs") is None:
            self.skipTest("git-lfs is not installed")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.copy_repo(base)
            staging = base / "staging"
            staging.mkdir()
            (staging / "image.png").write_bytes(b"synthetic binary image")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Capture Test"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "capture@example.invalid"], check=True
            )
            result, saved = self.run_capture_native_host(
                root,
                {
                    "schema": "lbrain.capture.v1",
                    "title": "LFS Image",
                    "summary": "A binary capture tracked by Git LFS.",
                    "origin": "https://example.invalid/lfs-image",
                    "scope": "page",
                    "content_markdown": "![Image](lbrain-asset://image)",
                    "extraction_status": "complete",
                    "assets": [{
                        "name": "images/image.png",
                        "staged_name": "image.png",
                        "placeholder": "lbrain-asset://image",
                        "media_type": "image/png",
                    }],
                },
                staging,
            )
            self.assertEqual(result.returncode, 0, (result.stderr.decode(), saved))
            asset = next(path for path in saved["affected_paths"] if str(path).endswith("image.png"))
            committed = subprocess.run(
                ["git", "-C", str(root), "show", f"HEAD:{asset}"],
                text=True,
                capture_output=True,
                check=True,
            ).stdout
            self.assertTrue(committed.startswith("version https://git-lfs.github.com/spec/v1"))
            self.assertEqual(
                subprocess.run(
                    ["git", "-C", str(root), "remote"], text=True, capture_output=True, check=True
                ).stdout,
                "",
            )

    def test_native_host_installer_registers_and_removes_the_developer_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "config"
            extension_id = "abcdefghijklmnopabcdefghijklmnop"
            installed = subprocess.run(
                [
                    sys.executable,
                    str(CAPTURE_NATIVE_INSTALLER),
                    "install",
                    "--root",
                    str(ROOT),
                    "--extension-id",
                    extension_id,
                    "--config-root",
                    str(config),
                    "--staging-root",
                    str(config / "Staging"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            receipt = json.loads(installed.stdout)
            manifest = Path(str(receipt["manifest"]))
            launcher = Path(str(receipt["launcher"]))
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(data["name"], "io.lbrain.capture")
            self.assertEqual(data["allowed_origins"], [f"chrome-extension://{extension_id}/"])
            self.assertEqual(Path(data["path"]), launcher)
            self.assertTrue(launcher.stat().st_mode & 0o100)
            self.assertIn(str(CAPTURE_NATIVE_HOST), launcher.read_text(encoding="utf-8"))
            self.assertIn(str(ROOT), launcher.read_text(encoding="utf-8"))

            removed = subprocess.run(
                [
                    sys.executable,
                    str(CAPTURE_NATIVE_INSTALLER),
                    "uninstall",
                    "--config-root",
                    str(config),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(removed.returncode, 0, removed.stderr)
            self.assertFalse(manifest.exists())
            self.assertFalse(launcher.exists())

    def test_capture_create_reuses_a_matching_source_in_a_category(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            payload: dict[str, object] = {
                "destination": "inbox",
                "title": "Categorized Writing Guide",
                "summary": "A previously categorized source.",
                "origin": "https://example.invalid/categorized-writing-guide",
                "capture": "full",
                "content": "Write to discover new ideas.\n\n## Provenance notes\n\nThis heading belongs to the article.",
                "extraction_status": "complete",
            }
            existing = root / "Knowledge/Sources/Methodology/Categorized-Writing-Guide.md"
            existing.parent.mkdir(parents=True, exist_ok=True)
            existing.write_text(
                "---\ntype: source\nsummary: A previously categorized source.\nstatus: active\n"
                "visibility: private\norigin: https://example.invalid/categorized-writing-guide\n"
                "capture: full\nweaving: skip\n"
                "created: 2026-08-11\nupdated: 2026-08-11\n---\n# Categorized Writing Guide\n\n"
                "## Capture\n\nWrite to discover new ideas.\n\n## Provenance notes\n\n"
                "This heading belongs to the article.\n\n## Provenance notes\n\n"
                "- Origin: https://example.invalid/categorized-writing-guide\n",
                encoding="utf-8",
            )

            result, captured = self.run_capture_operation(root, "capture.create", payload)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(captured["status"], "already_saved")
            self.assertEqual(
                captured["target"],
                "Knowledge/Sources/Methodology/Categorized-Writing-Guide.md",
            )
            self.assertFalse(list((root / "Inbox/Captures").glob("*Categorized-Writing-Guide*.md")))

            changed_result, changed = self.run_capture_operation(
                root,
                "capture.create",
                {**payload, "content": "Write"},
            )
            self.assertEqual(changed_result.returncode, 0, changed_result.stderr)
            self.assertEqual(changed["status"], "saved")
            self.assertTrue(str(changed["target"]).startswith("Inbox/Captures/"))

    def test_capture_create_preserves_failed_extraction_and_rejects_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            failed_result, failed = self.run_capture_operation(
                root,
                "capture.create",
                {
                    "destination": "inbox",
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
            self.assertIn("type: note", source_text)
            self.assertIn("extraction_status: failed", source_text)
            self.assertIn("Original content was not available", source_text)
            self.assertIn("Retry this source later.", source_text)

            recovered_payload = {
                "destination": "inbox",
                "title": "Unavailable Article",
                "summary": "The recovered article.",
                "origin": "https://example.invalid/unavailable",
                "capture": "full",
                "content": "Recovered source body.",
                "note": "Extraction succeeded on retry.",
                "extraction_status": "complete",
                "expected_hash": failed["expected_hash"],
            }
            edited = (
                source.read_text(encoding="utf-8").replace(
                    "status: active\n",
                    "status: active\ntags:\n  - preserve-me\n",
                    1,
                )
                + "\n## Research notes\n\nPreserve this user-authored section.\n"
            )
            edited = edited.replace(
                "\n---\n<!-- lbrain:title:start -->",
                "\n---\n# Personal notes\n\n<!-- lbrain:title:start -->",
                1,
            )
            source.write_text(
                edited.replace(
                    "Original content was not available at capture time.",
                    "A concurrent edit changed the managed Capture body.",
                ),
                encoding="utf-8",
            )
            stale_result, stale = self.run_capture_operation(root, "capture.create", recovered_payload)
            self.assertNotEqual(stale_result.returncode, 0)
            self.assertIn("changed after its recovery receipt", stale["error"])
            source.write_text(
                edited.replace(
                    "# Unavailable Article",
                    "# Unavailable Article\n\n<!-- lbrain:capture:start -->\nInjected\n<!-- lbrain:capture:end -->",
                ),
                encoding="utf-8",
            )
            marker_result, marker_failure = self.run_capture_operation(
                root, "capture.create", recovered_payload
            )
            self.assertNotEqual(marker_result.returncode, 0)
            self.assertIn("managed sections are incomplete", marker_failure["error"])
            source.write_text(edited, encoding="utf-8")
            recovered_result, recovered = self.run_capture_operation(
                root, "capture.create", recovered_payload
            )
            self.assertEqual(recovered_result.returncode, 0, recovered_result.stderr)
            self.assertEqual(recovered["status"], "saved")
            self.assertEqual(recovered["target"], failed["target"])
            recovered_text = source.read_text(encoding="utf-8")
            self.assertIn("extraction_status: complete", recovered_text)
            self.assertIn("Recovered source body.", recovered_text)
            self.assertIn("tags:\n  - preserve-me", recovered_text)
            self.assertIn("# Personal notes", recovered_text)
            self.assertIn("Preserve this user-authored section.", recovered_text)

            repeat_result, repeated = self.run_capture_operation(
                root, "capture.create", recovered_payload
            )
            self.assertEqual(repeat_result.returncode, 0, repeat_result.stderr)
            self.assertEqual(repeated["status"], "already_saved")

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
            self.assertTrue(
                contains_document_secret(
                    "https://cdn.invalid/private.html?Policy=private&Signature=fixture&Key-Pair-Id=key"
                )
            )
            self.assertTrue(
                contains_document_secret("HTTPS://cdn.invalid/private?hdnea=fixture~hmac=private")
            )
            self.assertTrue(
                contains_document_secret(
                    '```javascript\nconst url = "https://cdn.invalid/private?Policy=private&Signature=fixture&Key-Pair-Id=key";\n```'
                )
            )
            self.assertTrue(
                contains_document_secret("https://alice:fixture-password-12345@cdn.invalid/private")
            )
            self.assertTrue(
                contains_document_secret("https://app.invalid/callback#id_token=fixture-secret-value")
            )
            self.assertTrue(
                contains_document_secret("https://app.invalid/#/callback?auth_token=fixture-secret-value")
            )
            self.assertTrue(
                contains_document_secret("https://app.invalid/#callback?code=fixture-secret-value")
            )
            self.assertFalse(contains_document_secret("https://app.invalid/#/document/42"))
            self.assertFalse(contains_document_secret("https://cdn.invalid/public.html?id=signed"))
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
            self.assertEqual(code_capture["status"], "saved")
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
                    "destination": "inbox",
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

    def test_atomic_weave_promotes_bundles_updates_wiki_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Weave Test"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "weave@example.invalid"], check=True
            )

            def capture(title: str, origin: str, content: str) -> dict[str, object]:
                result, saved = self.run_capture_native_host(
                    root,
                    {
                        "schema": "lbrain.capture.v1",
                        "title": title,
                        "summary": f"Original source for {title}.",
                        "origin": origin,
                        "scope": "page",
                        "content_markdown": content,
                        "extraction_status": "complete",
                        "assets": [],
                    },
                )
                self.assertEqual(result.returncode, 0, (result.stderr.decode(), saved))
                return saved

            woven = capture("Woven Original", "https://example.invalid/woven", "Original woven claim.")
            skipped = capture("Reference Only", "https://example.invalid/reference", "Useful raw reference.")
            pending = capture("Read Later", "https://example.invalid/read-later", "Still awaiting a decision.")
            rejected = capture("Rejected Original", "https://example.invalid/rejected", "Noise to archive.")
            wiki_content = (
                "---\ntype: knowledge\nkind: concept\nsummary: A tested woven concept.\n"
                "status: active\nvisibility: private\nsources:\n"
                '  - "[[Knowledge/Sources/Woven-Original]]"\n'
                "created: 2026-08-11\nupdated: 2026-08-11\n---\n"
                "# Woven Concept\n\n## Synthesis\n\nA source-grounded conclusion.\n\n"
                "## Evidence and uncertainty\n\nSupported by [[Knowledge/Sources/Woven-Original]].\n"
            )
            payload: dict[str, object] = {
                "bundles": [
                    {"path": woven["target"], "outcome": "woven", "source_path": "Knowledge/Sources/Woven-Original.md"},
                    {"path": skipped["target"], "outcome": "skip", "source_path": "Knowledge/Sources/Reference-Only.md"},
                    {"path": pending["target"], "outcome": "pending"},
                    {"path": rejected["target"], "outcome": "rejected", "reason": "Outside the retained research scope."},
                ],
                "wiki": [{"path": "Knowledge/Wiki/Concepts/Woven-Concept.md", "content": wiki_content}],
            }

            preview_result, preview = self.run_weave_operation(root, "weave.preview", payload)
            self.assertEqual(preview_result.returncode, 0, (preview_result.stderr, preview))
            self.assertEqual(preview["status"], "preview")
            self.assertEqual(preview["conflicts"], [])
            self.assertEqual({item["outcome"] for item in preview["bundles"]}, {"woven", "skip", "pending", "rejected"})

            apply_result, applied = self.run_weave_operation(
                root, "weave.apply", {**payload, "plan_hash": preview["plan_hash"]}
            )
            self.assertEqual(apply_result.returncode, 0, (apply_result.stderr, applied))
            self.assertEqual(applied["status"], "applied")
            self.assertTrue(dict(applied["git"])["committed"])
            woven_source = root / "Knowledge/Sources/Woven-Original.md"
            self.assertTrue(woven_source.is_file())
            self.assertIn("type: source", woven_source.read_text())
            self.assertIn("weaving: woven", woven_source.read_text())
            self.assertTrue(
                (root / f"Knowledge/Sources/_assets/{woven['capture_id']}/v1/manifest.json").is_file()
            )
            self.assertFalse(
                (root / f"Inbox/Captures/_assets/{woven['capture_id']}/v1/manifest.json").exists()
            )
            self.assertIn("weaving: skip", (root / "Knowledge/Sources/Reference-Only.md").read_text())
            self.assertTrue((root / str(pending["target"])).is_file())
            archived = root / f"Archives/Sources/{Path(str(rejected['target'])).name}"
            self.assertIn("Outside the retained research scope.", archived.read_text())
            self.assertTrue(
                (root / f"Archives/Sources/_assets/{rejected['capture_id']}/v1/manifest.json").is_file()
            )
            archived_result, archived_repeat = self.run_capture_native_host(
                root,
                {
                    "schema": "lbrain.capture.v1",
                    "title": "Rejected Original",
                    "summary": "Original source for Rejected Original.",
                    "origin": "https://example.invalid/rejected",
                    "scope": "page",
                    "content_markdown": "Noise to archive.",
                    "extraction_status": "complete",
                    "assets": [],
                },
            )
            self.assertEqual(archived_result.returncode, 0, (archived_result.stderr.decode(), archived_repeat))
            self.assertEqual(archived_repeat["status"], "already_saved")
            self.assertEqual(archived_repeat["target"], archived.relative_to(root).as_posix())
            self.assertTrue((root / "Knowledge/Wiki/Concepts/Woven-Concept.md").is_file())
            self.assertFalse((root / str(woven["target"])).exists())
            self.assertEqual(applied["skill_improvement"], "review_after_success")

            repeated_result, repeated_preview = self.run_weave_operation(root, "weave.preview", payload)
            self.assertEqual(repeated_result.returncode, 0, repeated_result.stderr)
            self.assertEqual(repeated_preview["status"], "noop")
            noop_result, noop = self.run_weave_operation(
                root, "weave.apply", {**payload, "plan_hash": repeated_preview["plan_hash"]}
            )
            self.assertEqual(noop_result.returncode, 0, noop_result.stderr)
            self.assertEqual(noop["status"], "noop")

            version_result, versioned = self.run_capture_native_host(
                root,
                {
                    "schema": "lbrain.capture.v1",
                    "title": "Woven Original",
                    "summary": "A changed source version.",
                    "origin": "https://example.invalid/woven",
                    "scope": "page",
                    "content_markdown": "A new version stays pending.",
                    "extraction_status": "complete",
                    "assets": [],
                },
            )
            self.assertEqual(version_result.returncode, 0, (version_result.stderr.decode(), versioned))
            self.assertEqual(versioned["version"], 2)
            self.assertTrue(str(versioned["target"]).startswith("Inbox/Captures/"))
            self.assertIn("Original woven claim.", woven_source.read_text())

    def test_weave_rejects_assets_changed_after_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.copy_repo(base)
            staging = base / "staging"
            staging.mkdir()
            (staging / "evidence.png").write_bytes(b"approved asset bytes")
            capture_result, captured = self.run_capture_native_host(
                root,
                {
                    "schema": "lbrain.capture.v1",
                    "title": "Asset evidence",
                    "summary": "A Capture with preview-bound media.",
                    "origin": "https://example.invalid/asset-evidence",
                    "scope": "page",
                    "content_markdown": "![Evidence](lbrain-asset://evidence)",
                    "extraction_status": "complete",
                    "assets": [{
                        "name": "images/evidence.png",
                        "staged_name": "evidence.png",
                        "placeholder": "lbrain-asset://evidence",
                        "media_type": "image/png",
                    }],
                },
                staging,
            )
            self.assertEqual(capture_result.returncode, 0, captured)
            payload = {
                "bundles": [{
                    "path": captured["target"],
                    "outcome": "woven",
                    "source_path": "Knowledge/Sources/Asset-Evidence.md",
                }],
                "wiki": [{
                    "path": "Knowledge/Wiki/Concepts/Asset-Evidence.md",
                    "content": (
                        "---\ntype: knowledge\nkind: concept\nsummary: Asset evidence.\n"
                        "status: active\nvisibility: private\nsources:\n"
                        '  - "[[Knowledge/Sources/Asset-Evidence]]"\n'
                        "created: 2026-08-12\nupdated: 2026-08-12\n---\n"
                        "# Asset Evidence\n\nSupported by [[Knowledge/Sources/Asset-Evidence]].\n"
                    ),
                }],
            }
            preview_result, preview = self.run_weave_operation(root, "weave.preview", payload)
            self.assertEqual(preview_result.returncode, 0, preview)
            stored_asset = root / (
                f"Inbox/Captures/_assets/{captured['capture_id']}/v1/files/images/evidence.png"
            )
            stored_asset.write_bytes(b"changed after preview")
            apply_result, rejected = self.run_weave_operation(
                root, "weave.apply", {**payload, "plan_hash": preview["plan_hash"]}
            )
            self.assertNotEqual(apply_result.returncode, 0)
            self.assertEqual(rejected["status"], "failed")
            self.assertTrue((root / str(captured["target"])).is_file())
            self.assertEqual(stored_asset.read_bytes(), b"changed after preview")

    def test_weave_git_commit_preserves_existing_staged_content(self) -> None:
        spec = importlib.util.spec_from_file_location("weave_operations_git", WEAVE_OPERATIONS)
        assert spec and spec.loader
        operations = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(operations)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Weave Test"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "weave@example.invalid"], check=True
            )
            note = root / "note.md"
            note.write_text("initial\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "note.md"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "initial"], check=True)
            note.write_text("user staged\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "note.md"], check=True)
            note.write_text("operation result\n", encoding="utf-8")

            result = operations.weave_git_commit(root, ["note.md"], 1)

            self.assertFalse(result["committed"])
            staged = subprocess.run(
                ["git", "-C", str(root), "show", ":note.md"], text=True, capture_output=True, check=True
            ).stdout
            self.assertEqual(staged, "user staged\n")
            self.assertEqual(note.read_text(encoding="utf-8"), "operation result\n")

            intent = root / "intent.md"
            intent.write_text("user intent\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "-N", "intent.md"], check=True)
            before = subprocess.run(
                ["git", "-C", str(root), "ls-files", "--debug", "--", "intent.md"],
                text=True,
                capture_output=True,
                check=True,
            ).stdout
            intent.write_text("operation result\n", encoding="utf-8")

            intent_result = operations.weave_git_commit(root, ["intent.md"], 1)

            self.assertFalse(intent_result["committed"])
            after = subprocess.run(
                ["git", "-C", str(root), "ls-files", "--debug", "--", "intent.md"],
                text=True,
                capture_output=True,
                check=True,
            ).stdout
            self.assertEqual(after, before)
            self.assertEqual(intent.read_text(encoding="utf-8"), "operation result\n")

    def test_weave_rejects_a_symlinked_destination_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.copy_repo(base)
            saved_result, saved = self.run_capture_native_host(
                root,
                {
                    "schema": "lbrain.capture.v1",
                    "title": "Symlink Weave",
                    "summary": "Must remain inside the selected Vault.",
                    "origin": "https://example.invalid/symlink-weave",
                    "scope": "page",
                    "content_markdown": "Synthetic source.",
                    "extraction_status": "complete",
                    "assets": [],
                },
            )
            self.assertEqual(saved_result.returncode, 0, (saved_result.stderr.decode(), saved))
            outside = base / "outside"
            outside.mkdir()
            (root / "Knowledge/Sources/Escape").symlink_to(outside, target_is_directory=True)
            payload = {
                "bundles": [{
                    "path": saved["target"],
                    "outcome": "skip",
                    "source_path": "Knowledge/Sources/Escape/Symlink-Weave.md",
                }],
                "wiki": [],
            }
            preview_result, preview = self.run_weave_operation(root, "weave.preview", payload)
            self.assertNotEqual(preview_result.returncode, 0)
            self.assertEqual(preview["status"], "failed")
            self.assertEqual(list(outside.iterdir()), [])
            self.assertTrue((root / str(saved["target"])).is_file())

    def test_atomic_weave_rolls_back_every_resource_when_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.copy_repo(Path(temporary))
            saved_result, saved = self.run_capture_native_host(
                root,
                {
                    "schema": "lbrain.capture.v1",
                    "title": "Rollback Source",
                    "summary": "A source used to prove atomic rollback.",
                    "origin": "https://example.invalid/weave-rollback",
                    "scope": "page",
                    "content_markdown": "Original content must survive.",
                    "extraction_status": "complete",
                    "assets": [],
                },
            )
            self.assertEqual(saved_result.returncode, 0, (saved_result.stderr.decode(), saved))
            wiki_content = (
                "---\ntype: knowledge\nkind: concept\nsummary: rollback fixture\nstatus: active\n"
                "visibility: private\nsources:\n  - \"[[Knowledge/Sources/Rollback-Source]]\"\n"
                "created: 2026-08-11\nupdated: 2026-08-11\n---\n# Rollback Wiki\n\n"
                "## Synthesis\n\nMust roll back.\n\n## Evidence and uncertainty\n\n"
                "[[Knowledge/Sources/Rollback-Source]]\n"
            )
            payload: dict[str, object] = {
                "bundles": [{
                    "path": saved["target"], "outcome": "woven", "source_path": "Knowledge/Sources/Rollback-Source.md"
                }],
                "wiki": [{"path": "Knowledge/Wiki/Concepts/Rollback-Wiki.md", "content": wiki_content}],
            }
            preview_result, preview = self.run_weave_operation(root, "weave.preview", payload)
            self.assertEqual(preview_result.returncode, 0, (preview_result.stderr, preview))
            spec = importlib.util.spec_from_file_location("weave_operations_rollback", WEAVE_OPERATIONS)
            assert spec and spec.loader
            operations = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(operations)
            operations.validate = lambda _: (False, "synthetic validation failure")
            failed = operations.weave_apply(root, {**payload, "plan_hash": preview["plan_hash"]})
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["rollback"], {"performed": True, "ok": True})
            self.assertTrue((root / str(saved["target"])).is_file())
            self.assertFalse((root / "Knowledge/Sources/Rollback-Source.md").exists())
            self.assertFalse((root / "Knowledge/Wiki/Concepts/Rollback-Wiki.md").exists())

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
