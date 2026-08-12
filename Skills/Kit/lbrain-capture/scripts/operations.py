#!/usr/bin/env python3
"""Deterministic write operations used by the LBrain Capture Skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Iterator
from urllib.parse import quote


PROFILE_START = "<!-- lbrain:intake-profile:v1:start -->"
PROFILE_END = "<!-- lbrain:intake-profile:end -->"
SOURCE_STATUSES = {"scanned", "no_durable_change", "partial", "failed", "stale", "no_match"}
UNCHANGED = object()


class OperationError(ValueError):
    pass


def load_kit_helper(root: Path, module: str, name: str) -> Any:
    kit = str(root / "System/Kit")
    if kit not in sys.path:
        sys.path.insert(0, kit)
    return getattr(__import__(module, fromlist=[name]), name)


@contextmanager
def operation_lock(root: Path) -> Iterator[None]:
    mutation_locks = load_kit_helper(root, "transaction", "mutation_locks")
    transaction_error = load_kit_helper(root, "transaction", "TransactionError")
    try:
        with mutation_locks([root]):
            yield
    except transaction_error as error:
        raise OperationError(str(error)) from error


def reject_secrets(root: Path, *values: str) -> None:
    secret_check = load_kit_helper(root, "disclosure", "contains_document_secret")
    runtime_state_check = load_kit_helper(root, "disclosure", "contains_document_runtime_state")
    if secret_check(*values) or runtime_state_check(*values):
        raise OperationError("operation contains possible credentials or runtime state; remove or redact them")


def reject_secret_file(root: Path, path: Path) -> None:
    tail = ""
    try:
        with path.open(encoding="utf-8") as file:
            for chunk in iter(lambda: file.read(128 * 1024), ""):
                reject_secrets(root, tail + chunk)
                tail = (tail + chunk)[-128 * 1024:]
    except UnicodeError as error:
        raise OperationError("text Capture Bundle asset is not valid UTF-8") from error


def reject_binary_secret_file(root: Path, path: Path, media_type: str) -> None:
    def scan(source: BinaryIO) -> None:
        tail = b""
        for chunk in iter(lambda: source.read(128 * 1024), b""):
            body = tail + chunk
            reject_secrets(
                root,
                body.decode("latin-1"),
                body[: len(body) - len(body) % 2].decode("utf-16le", errors="ignore"),
                body[1 : len(body) - (len(body) - 1) % 2].decode("utf-16le", errors="ignore"),
            )
            tail = body[-128 * 1024:]

    with path.open("rb") as source:
        scan(source)
    if media_type == "application/pdf" and (pdftotext := shutil.which("pdftotext")):
        try:
            with tempfile.TemporaryFile() as output:
                result = subprocess.run(
                    [pdftotext, "-layout", str(path), "-"],
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=120,
                )
                if result.returncode == 0:
                    output.seek(0)
                    scan(output)
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not zipfile.is_zipfile(path):
        return
    try:
        with zipfile.ZipFile(path) as archive:
            remaining = max(64 * 1024 * 1024, path.stat().st_size * 100)
            for member in archive.infolist():
                if member.is_dir() or member.flag_bits & 0x1 or not member.filename.lower().endswith(
                    (".xml", ".rels", ".txt", ".csv", ".json", ".html", ".xhtml")
                ):
                    continue
                if member.file_size > remaining:
                    raise OperationError("document Capture Bundle asset expands beyond its inspection budget")
                remaining -= member.file_size
                with archive.open(member) as source:
                    scan(source)
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        raise OperationError("document Capture Bundle asset could not be inspected") from error


def digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def operation_id(name: str, target: str, content: str) -> str:
    value = f"{name}\0{target}\0{digest(content)}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def relative_project_path(value: object) -> PurePosixPath:
    if not isinstance(value, str):
        raise OperationError("project_path must be a string")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise OperationError("project_path must stay inside Context/Projects")
    if len(path.parts) != 3 or path.parts[:2] != ("Context", "Projects") or path.suffix != ".md":
        raise OperationError("project_path must name one Markdown file in Context/Projects")
    return path


def required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise OperationError(f"{key} must be non-empty text")
    return value.strip()


def yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def managed_profile(value: object) -> str:
    if not isinstance(value, str):
        raise OperationError("profile_markdown must be text")
    profile = value.strip()
    if not profile.startswith("## Context Intake Profile"):
        raise OperationError("profile_markdown must start with '## Context Intake Profile'")
    if PROFILE_START in profile or PROFILE_END in profile:
        raise OperationError("profile_markdown must not contain management markers")
    return f"{PROFILE_START}\n{profile}\n{PROFILE_END}"


def profile_requirements(content: str) -> list[tuple[str, str]]:
    in_sources = False
    requirements: list[tuple[str, str]] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "### Sources and anchors":
            in_sources = True
            continue
        if in_sources and stripped.startswith("### "):
            break
        if not in_sources or not stripped.startswith("- "):
            continue
        value = stripped[2:]
        if ":" not in value:
            raise OperationError("each Intake Profile source must use '- source: anchor'")
        source, anchor = (" ".join(part.split()).casefold() for part in value.split(":", 1))
        if not source or not anchor:
            raise OperationError("each Intake Profile source must name a source and anchor")
        requirements.append((source, anchor))
    if not requirements:
        raise OperationError("Intake Profile must contain a '### Sources and anchors' contract")
    return requirements


def new_project(payload: dict[str, Any], profile: str) -> str:
    today = date.today().isoformat()
    title = required_text(payload, "title")
    summary = required_text(payload, "summary")
    outcome = required_text(payload, "outcome")
    return (
        "---\n"
        "type: project\n"
        f"summary: {yaml_string(summary)}\n"
        "status: active\n"
        "visibility: private\n"
        f"outcome: {yaml_string(outcome)}\n"
        "source_of_truth: internal\n"
        f"review_after: {today}\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        "---\n"
        f"# {title}\n\n"
        f"{profile}\n"
    )


def replace_profile(existing: str, profile: str) -> str:
    start = existing.find(PROFILE_START)
    if start >= 0:
        end = existing.find(PROFILE_END, start)
        if end < 0:
            raise OperationError("managed Intake Profile is missing its end marker")
        end += len(PROFILE_END)
        return existing[:start] + profile + existing[end:]

    heading = "## Context Intake Profile"
    start = existing.find(heading)
    if start < 0:
        return existing.rstrip() + f"\n\n{profile}\n"

    next_heading = existing.find("\n## ", start + len(heading))
    if next_heading < 0:
        return existing[:start] + profile + "\n"
    return existing[:start] + profile + "\n" + existing[next_heading:]


def assert_safe_target(root: Path, path: Path) -> None:
    try:
        load_kit_helper(root, "file_transaction", "assert_safe_target")(root, path)
    except ValueError as error:
        raise OperationError(str(error)) from error


def atomic_write(root: Path, path: Path, content: str, expected: object = UNCHANGED) -> None:
    try:
        writer = load_kit_helper(root, "file_transaction", "atomic_write")
        writer(root, path, content) if expected is UNCHANGED else writer(root, path, content, expected)
    except ValueError as error:
        raise OperationError(str(error)) from error


def atomic_unlink(root: Path, path: Path, expected: str) -> None:
    try:
        load_kit_helper(root, "file_transaction", "atomic_unlink")(root, path, expected)
    except ValueError as error:
        raise OperationError(str(error)) from error


def validate(root: Path) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, str(root / "System/Kit/check.py"), "--root", str(root), "--quiet"],
        text=True,
        capture_output=True,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output


def project_proposal(
    relative: PurePosixPath,
    before_hash: str | None,
    after_hash: str,
    identifier: str,
    status: str,
    outcome: str,
) -> tuple[PurePosixPath, str, str]:
    today = date.today().isoformat()
    proposal_id = digest(f"project.configure\0{relative.as_posix()}\0{after_hash}")
    proposal = PurePosixPath("System/Proposals") / f"project-configure-{identifier}.md"
    action = "create" if before_hash is None else "update"
    content = (
        "---\n"
        "type: proposal\n"
        'summary: "Configure one Project and its Context Intake Profile."\n'
        f"status: {status}\n"
        "visibility: private\n"
        f"target: {yaml_string(relative.as_posix())}\n"
        f"action: {action}\n"
        "proposal_kind: project_configuration\n"
        f"proposal_id: {proposal_id}\n"
        f"created: {today}\nupdated: {today}\n"
        "---\n"
        "# Configure Project Context Intake\n\n"
        "## Rationale\n\nProject outcome or collection scope requires an explicit Proposal.\n\n"
        "## Evidence\n\n"
        f"- Prior Project hash: `{before_hash or 'new'}`\n"
        f"- Previewed Project hash: `{after_hash}`\n\n"
        "## Expected diff\n\nCreate or update the named Project and its bounded v1 Intake Profile.\n\n"
        f"## Decision\n\n{outcome}\n"
    )
    return proposal, content, proposal_id


def project_configure(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    mode = payload.get("mode")
    if mode not in {"preview", "apply"}:
        raise OperationError("mode must be preview or apply")

    relative = relative_project_path(payload.get("project_path"))
    path = root.joinpath(*relative.parts)
    before = path.read_text(encoding="utf-8") if path.is_file() else None
    before_hash = digest(before) if before is not None else None
    profile = managed_profile(payload.get("profile_markdown"))
    supplied = [profile]
    supplied.extend(str(payload[key]) for key in ("title", "summary", "outcome") if key in payload)
    reject_secrets(root, *supplied)
    legacy_migration = before is not None and PROFILE_START not in before and "## Context Intake Profile" in before
    if not legacy_migration:
        profile_requirements(profile)
    after = replace_profile(before, profile) if before is not None else new_project(payload, profile)
    after_hash = digest(after)
    identifier = operation_id("project.configure", relative.as_posix(), after)
    proposal_relative, accepted_proposal, proposal_id = project_proposal(
        relative,
        before_hash,
        after_hash,
        identifier,
        "accepted",
        f"Accepted exact Project configuration `{identifier}` after explicit confirmation. Application pending.",
    )
    _, applied_proposal, _ = project_proposal(
        relative,
        before_hash,
        after_hash,
        identifier,
        "applied",
        (
            f"Accepted exact Project configuration `{identifier}` after explicit confirmation. "
            f"Applied exact Project configuration `{identifier}` after validation."
        ),
    )
    proposal_path = root.joinpath(*proposal_relative.parts)
    result = {
        "operation": "project.configure",
        "operation_id": identifier,
        "mode": mode,
        "status": "noop" if before == after else "applied",
        "target": relative.as_posix(),
        "affected_paths": [] if before == after else [relative.as_posix(), proposal_relative.as_posix()],
        "before_hash": before_hash,
        "after_hash": after_hash,
        "proposal": {
            "path": proposal_relative.as_posix(),
            "proposal_id": proposal_id,
            "accepted_markdown": accepted_proposal,
        },
        "validation": {"ok": True, "message": "not run for preview"},
        "rollback": None,
    }
    if mode == "preview":
        return result

    if "expected_hash" not in payload or payload.get("expected_hash") != before_hash:
        raise OperationError("project changed after preview; generate a new preview")

    if not proposal_path.is_file():
        if before == after:
            return result
        raise OperationError("project.configure apply requires the explicitly accepted Proposal")
    proposal_before = proposal_path.read_text(encoding="utf-8")
    try:
        proposal_head = proposal_before.split("---", 2)[1].splitlines()
    except IndexError as error:
        raise OperationError("Project configuration Proposal is malformed") from error
    recorded_id = frontmatter_text(proposal_head, "proposal_id")
    status = frontmatter_text(proposal_head, "status")
    target = frontmatter_text(proposal_head, "target")
    if recorded_id != proposal_id or target != relative.as_posix():
        raise OperationError("Project configuration Proposal does not match the approved preview")
    if before == after:
        if status == "applied":
            return result
        if status != "accepted":
            raise OperationError("Project configuration Proposal must be explicitly accepted")
        atomic_write(root, proposal_path, applied_proposal, proposal_before)
        valid, message = validate(root)
        if not valid:
            atomic_write(root, proposal_path, proposal_before, applied_proposal)
            raise OperationError("Project configuration Proposal could not be finalized")
        result["status"] = "applied"
        result["affected_paths"] = [proposal_relative.as_posix()]
        result["validation"] = {"ok": True, "message": message or "Kit validation passed"}
        return result
    if status != "accepted":
        raise OperationError("project.configure apply requires the explicitly accepted Proposal")

    atomic_write(root, path, after, before)
    proposal_written = False
    try:
        valid, message = validate(root)
        if not valid:
            raise OperationError(message or "Project validation failed")
        atomic_write(root, proposal_path, applied_proposal, proposal_before)
        proposal_written = True
        valid, message = validate(root)
        if not valid:
            raise OperationError(message or "Project and Proposal validation failed")
    except (OSError, OperationError) as error:
        rollback_ok = True
        if proposal_written:
            try:
                atomic_write(root, proposal_path, proposal_before, applied_proposal)
            except (OSError, OperationError):
                rollback_ok = False
        try:
            if before is None:
                atomic_unlink(root, path, after)
            else:
                atomic_write(root, path, before, after)
        except (OSError, OperationError):
            rollback_ok = False
        failed_proposal = accepted_proposal.replace(
            "Application pending.", "Application failed validation; the accepted Proposal remains retryable."
        )
        proposal_current = proposal_path.read_text(encoding="utf-8") if proposal_path.is_file() else None
        failure_recorded = False
        if proposal_current == proposal_before:
            try:
                atomic_write(root, proposal_path, failed_proposal, proposal_before)
                failure_recorded = True
            except (OSError, OperationError):
                pass
        result["status"] = "failed"
        result["affected_paths"] = [proposal_relative.as_posix()] if failure_recorded else []
        result["validation"] = {"ok": False, "message": str(error)}
        result["rollback"] = {"performed": True, "ok": rollback_ok}
        return result

    result["validation"] = {"ok": True, "message": message or "Kit validation passed"}
    return result


def one_line(value: object, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OperationError(f"{key} must be non-empty text")
    return " ".join(value.split()).replace("|", "\\|")


def checkpoint_block(
    payload: dict[str, Any],
    requirements: list[tuple[str, str]],
) -> tuple[str, bool]:
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", run_id):
        raise OperationError("run_id must use 1-80 letters, numbers, dots, underscores, or hyphens")
    inspected_range = one_line(payload.get("range"), "range")
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise OperationError("sources must be a non-empty list")

    rows: list[tuple[str, str, str, bool]] = []
    incomplete = False
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise OperationError(f"sources[{index}] must be an object")
        name = one_line(source.get("name"), f"sources[{index}].name")
        scope = one_line(source.get("scope"), f"sources[{index}].scope")
        status = source.get("status")
        if status not in SOURCE_STATUSES:
            raise OperationError(f"sources[{index}].status is invalid")
        required = source.get("required", True)
        if not isinstance(required, bool):
            raise OperationError(f"sources[{index}].required must be boolean")
        if required and status in {"partial", "failed", "stale", "no_match"}:
            incomplete = True
        rows.append((name, status, scope, required))

    normalized_rows = {
        (" ".join(name.split()).casefold(), " ".join(scope.split()).casefold()): required
        for name, _, scope, required in rows
    }
    for requirement in requirements:
        if requirement not in normalized_rows:
            raise OperationError(
                f"checkpoint does not account for configured source and anchor: {requirement[0]}: {requirement[1]}"
            )
        if not normalized_rows[requirement]:
            raise OperationError("configured Intake Profile coverage cannot be marked optional")

    def count(key: str) -> int:
        value = payload.get(key, 0)
        if not isinstance(value, int) or value < 0:
            raise OperationError(f"{key} must be a non-negative integer")
        return value

    def items(key: str) -> list[str]:
        value = payload.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise OperationError(f"{key} must be a list of text values")
        return [" ".join(item.split()) for item in value if item.strip()]

    candidates = count("candidates")
    full_reads = count("full_reads")
    changes = items("changes")
    conflicts = items("conflicts")
    next_review = one_line(payload.get("next_review"), "next_review")
    status = "partial" if incomplete else "complete"
    source_rows = "\n".join(
        f"| {name} | {source_status} | {scope} | {'yes' if required else 'no'} |"
        for name, source_status, scope, required in rows
    )
    changes_text = ", ".join(changes) if changes else "none"
    conflicts_text = ", ".join(conflicts) if conflicts else "none"
    block = (
        f"<!-- lbrain:intake-checkpoint:{run_id}:start -->\n"
        f"### Intake Checkpoint {run_id}\n\n"
        f"- Status: {status}\n"
        f"- Inspected range: {inspected_range}\n"
        f"- Candidates: {candidates}\n"
        f"- Full reads: {full_reads}\n"
        f"- Changes: {changes_text}\n"
        f"- Conflicts: {conflicts_text}\n"
        f"- Next review: {next_review}\n\n"
        "| Source | Status | Scope | Required |\n"
        "| --- | --- | --- | --- |\n"
        f"{source_rows}\n"
        "<!-- lbrain:intake-checkpoint:end -->"
    )
    return block, not incomplete


def append_checkpoint(existing: str, block: str, run_id: str) -> tuple[str, bool]:
    start_marker = f"<!-- lbrain:intake-checkpoint:{run_id}:start -->"
    start = existing.find(start_marker)
    if start >= 0:
        end_marker = "<!-- lbrain:intake-checkpoint:end -->"
        end = existing.find(end_marker, start)
        if end < 0:
            raise OperationError("existing Intake Checkpoint is missing its end marker")
        existing_block = existing[start : end + len(end_marker)]
        if existing_block != block:
            raise OperationError("run_id already exists with different checkpoint content")
        return existing, True

    heading = "## Context Intake Checkpoints"
    if heading not in existing:
        return existing.rstrip() + f"\n\n{heading}\n\n{block}\n", False
    heading_start = existing.find(heading)
    next_heading = existing.find("\n## ", heading_start + len(heading))
    if next_heading < 0:
        return existing.rstrip() + f"\n\n{block}\n", False
    return existing[:next_heading].rstrip() + f"\n\n{block}\n" + existing[next_heading:], False


def project_checkpoint(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    mode = payload.get("mode")
    if mode not in {"preview", "apply"}:
        raise OperationError("mode must be preview or apply")
    contains_key = load_kit_helper(root, "disclosure", "contains_key")
    if contains_key(payload, {"cursor", "raw_cursor"}):
        raise OperationError("raw connector cursors must stay outside LBrain")

    relative = relative_project_path(payload.get("project_path"))
    path = root.joinpath(*relative.parts)
    if not path.is_file():
        raise OperationError("target Project does not exist")
    before = path.read_text(encoding="utf-8")
    before_hash = digest(before)
    block, complete = checkpoint_block(payload, profile_requirements(before))
    reject_secrets(root, block)
    run_id = str(payload["run_id"])
    after, duplicate = append_checkpoint(before, block, run_id)
    after_hash = digest(after)
    status = "noop" if duplicate else ("applied" if complete else "partial")
    result = {
        "operation": "project.checkpoint",
        "operation_id": operation_id("project.checkpoint", relative.as_posix(), block),
        "mode": mode,
        "status": status,
        "target": relative.as_posix(),
        "affected_paths": [] if duplicate else [relative.as_posix()],
        "before_hash": before_hash,
        "after_hash": after_hash,
        "complete_checkpoint_advanced": complete and not duplicate and mode == "apply",
        "validation": {"ok": True, "message": "not run for preview"},
        "rollback": None,
    }
    if mode == "preview" or duplicate:
        return result
    if "expected_hash" not in payload or payload.get("expected_hash") != before_hash:
        raise OperationError("Project changed after preview; generate a new checkpoint preview")

    atomic_write(root, path, after, before)
    valid, message = validate(root)
    if not valid:
        atomic_write(root, path, before, after)
        result["status"] = "failed"
        result["complete_checkpoint_advanced"] = False
        result["validation"] = {"ok": False, "message": message}
        result["rollback"] = {"performed": True, "ok": True}
        return result
    result["validation"] = {"ok": True, "message": message or "Kit validation passed"}
    return result


def capture_key(origin: str, content: str) -> str:
    identity = f"origin:{origin.strip().rstrip('/')}" if origin.strip() else f"content:{content.strip()}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def capture_slug(title: str, key: str) -> str:
    slug = re.sub(r"[^\w-]+", "-", title, flags=re.UNICODE).strip("-_")
    suffix = f"-{key[:8]}"
    slug = slug.encode("utf-8")[: 160 - len(suffix)].decode("utf-8", errors="ignore")
    return f"{slug or 'Capture'}{suffix}"


def frontmatter_text(lines: list[str], key: str) -> str:
    marker = f"{key}:"
    for line in lines:
        if not line.startswith(marker):
            continue
        raw = line.split(":", 1)[1].strip()
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw.strip("\"'")
        return value if isinstance(value, str) else ""
    return ""


def existing_capture(root: Path, key: str, origin: str) -> Path | None:
    marker = f"capture_id: {key}"
    for directory in (root / "Inbox", root / "Knowledge/Sources"):
        for path in sorted(directory.rglob("*.md")):
            try:
                head = path.read_text(encoding="utf-8").split("---", 2)[1]
            except (IndexError, OSError, UnicodeError):
                continue
            lines = head.splitlines()
            legacy_origin = frontmatter_text(lines, "origin").strip().rstrip("/")
            if marker in lines or (origin and legacy_origin == origin.strip().rstrip("/")):
                return path
    return None


def capture_frontmatter(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").split("---", 2)[1].splitlines()
    except (IndexError, OSError, UnicodeError) as error:
        raise OperationError("existing capture is malformed") from error


def capture_create(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("destination", "inbox") != "inbox":
        raise OperationError("capture.create writes external originals to inbox only")
    title = required_text(payload, "title")
    summary = required_text(payload, "summary")
    origin_value = payload.get("origin", "")
    content_value = payload.get("content", "")
    note_value = payload.get("note", "")
    if not isinstance(origin_value, str) or not isinstance(content_value, str) or not isinstance(note_value, str):
        raise OperationError("origin, content, and note must be text")
    origin = origin_value.strip()
    content = content_value.strip()
    note = note_value.strip()
    if not origin and not content:
        raise OperationError("capture requires an origin or content")
    reject_secrets(root, title, summary, origin, content, note)

    extraction_status = payload.get("extraction_status", "complete")
    if extraction_status not in {"complete", "partial", "failed"}:
        raise OperationError("extraction_status must be complete, partial, or failed")
    capture = payload.get("capture", "reference")
    if capture not in {"reference", "excerpt", "full"}:
        raise OperationError("capture must be reference, excerpt, or full")
    if capture in {"excerpt", "full"} and not content and extraction_status == "complete":
        raise OperationError("complete excerpt or full capture requires content")
    stable_origin = origin or f"lbrain:user-provided/{capture_key('', content)}"
    legacy = existing_capture(root, capture_key(origin, content), origin)
    if legacy is not None and frontmatter_number(capture_frontmatter(legacy), "capture_version") == 0:
        legacy_body = legacy.read_text(encoding="utf-8").split("---", 2)[-1]
        legacy_body = re.sub(r"(?m)^# .+\n+", "", legacy_body, count=1)
        legacy_body = re.sub(r"(?m)^## Capture\s*\n+", "", legacy_body, count=1)
        provenance = list(re.finditer(r"(?m)^## Provenance notes\s*$", legacy_body))
        weave_decision = list(re.finditer(r"(?m)^## Weave decision\s*$", legacy_body))
        boundary = provenance[-1].start() if provenance else (weave_decision[-1].start() if weave_decision else None)
        if boundary is not None:
            legacy_body = legacy_body[:boundary]
        if not content or legacy_body.strip() == content:
            relative = legacy.relative_to(root).as_posix()
            return {
                "operation": "capture.create",
                "operation_id": operation_id("capture.create", relative, stable_origin),
                "status": "already_saved",
                "target": relative,
                "affected_paths": [],
                "validation": {"ok": True, "message": "existing legacy capture reused"},
                "rollback": None,
            }
    bundle_content = content
    if not bundle_content and capture == "reference" and extraction_status == "complete":
        bundle_content = f"- Original link: [{origin}]({origin})"
    bundle_payload: dict[str, Any] = {
        "schema": "lbrain.capture.v1",
        "title": title,
        "summary": summary,
        "origin": stable_origin,
        "scope": "page",
        "content_markdown": bundle_content,
        "source_content_markdown": bundle_content,
        "capture_note": note,
        "extraction_status": extraction_status,
        "assets": [],
    }
    versions = bundle_versions(root, bundle_capture_id(stable_origin, "page"))
    if extraction_status == "complete" and versions:
        latest = versions[-1][2]
        latest_head = capture_frontmatter(latest)
        if frontmatter_text(latest_head, "extraction_status") in {"partial", "failed"}:
            bundle_payload["recovery_target"] = latest.relative_to(root).as_posix()
            bundle_payload["expected_hash"] = payload.get("expected_hash")
    result = capture_bundle(root, bundle_payload)
    result["operation"] = "capture.create"
    return result


def bundle_capture_id(origin: str, scope: str) -> str:
    identity = f"{origin.strip().rstrip('/')}\0{scope}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def frontmatter_number(lines: list[str], key: str) -> int:
    marker = f"{key}:"
    for line in lines:
        if line.startswith(marker):
            value = line.split(":", 1)[1].strip()
            return int(value) if value.isdigit() else 0
    return 0


def bundle_versions(root: Path, capture_id: str) -> list[tuple[int, str, Path]]:
    versions: list[tuple[int, str, Path]] = []
    for directory in (root / "Inbox/Captures", root / "Knowledge/Sources", root / "Archives/Sources"):
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.md")):
            try:
                lines = capture_frontmatter(path)
            except OperationError:
                continue
            if frontmatter_text(lines, "capture_id") != capture_id:
                continue
            versions.append(
                (
                    frontmatter_number(lines, "capture_version"),
                    frontmatter_text(lines, "content_hash"),
                    path,
                )
            )
    return sorted(versions)


def safe_asset_path(value: object, field: str) -> PurePosixPath:
    if not isinstance(value, str) or not value.strip():
        raise OperationError(f"{field} must be a relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise OperationError(f"{field} must stay inside its asset directory")
    if any(re.search(r'[\x00-\x1f\x7f<>:"|?*\\]', part) for part in path.parts):
        raise OperationError(f"{field} contains unsafe filename characters")
    if any(len(part.encode("utf-8")) > 200 for part in path.parts):
        raise OperationError(f"{field} contains an overlong filename")
    return path


def asset_manifest(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_assets = payload.get("assets", [])
    if not isinstance(raw_assets, list):
        raise OperationError("assets must be a list")
    assets: list[dict[str, Any]] = []
    for raw in raw_assets:
        if not isinstance(raw, dict):
            raise OperationError("each asset must be an object")
        name = safe_asset_path(raw.get("name"), "asset name").as_posix()
        staged_name = safe_asset_path(raw.get("staged_name"), "asset staged_name").as_posix()
        expected_hash = raw.get("sha256")
        size = raw.get("size")
        placeholder = raw.get("placeholder", "")
        media_type = raw.get("media_type", "application/octet-stream")
        if expected_hash is not None and (
            not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
        ):
            raise OperationError("asset sha256 must be a lowercase SHA-256 digest")
        if size is not None and (not isinstance(size, int) or isinstance(size, bool) or size < 0):
            raise OperationError("asset size must be a non-negative integer")
        if not isinstance(placeholder, str) or (
            placeholder and not re.fullmatch(r"lbrain-asset://[A-Za-z0-9._-]+", placeholder)
        ):
            raise OperationError("asset placeholder must use lbrain-asset:// followed by a stable identifier")
        if not isinstance(media_type, str) or not media_type.strip():
            raise OperationError("asset media_type must be text")
        assets.append(
            {
                "name": name,
                "staged_name": staged_name,
                "sha256": expected_hash,
                "size": size,
                "placeholder": placeholder,
                "media_type": media_type.strip(),
            }
        )
    names = [asset["name"] for asset in assets]
    if len(names) != len(set(names)):
        raise OperationError("asset names must be unique")
    placeholders = [asset["placeholder"] for asset in assets if asset["placeholder"]]
    if len(placeholders) != len(set(placeholders)):
        raise OperationError("asset placeholders must be unique")
    return assets


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def directory_digest(path: Path) -> str | None:
    if not path.is_dir():
        return None
    value = hashlib.sha256()
    for current, directories, files in os.walk(path, followlinks=False):
        directories.sort()
        files.sort()
        base = Path(current)
        for name in [*directories, *files]:
            item = base / name
            relative = item.relative_to(path).as_posix().encode()
            if item.is_symlink():
                value.update(b"L\0" + relative + b"\0" + os.readlink(item).encode())
            elif item.is_file():
                value.update(b"F\0" + relative + b"\0" + file_digest(item).encode())
            else:
                value.update(b"D\0" + relative)
    return value.hexdigest()


def inside_without_symlinks(base: Path, relative: PurePosixPath) -> Path:
    base = base.resolve()
    candidate = base.joinpath(*relative.parts)
    current = candidate
    while current != base:
        if current.is_symlink():
            raise OperationError("asset path must not contain symlinks")
        current = current.parent
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(base) or not resolved.is_file():
        raise OperationError("staged asset must be a regular file inside the staging directory")
    return resolved


def verified_staged_assets(
    assets: list[dict[str, Any]], staging_root: Path | None
) -> list[dict[str, Any]]:
    if assets and staging_root is None:
        raise OperationError("assets require a configured staging directory")
    assert staging_root is not None or not assets
    verified: list[dict[str, Any]] = []
    for asset in assets:
        source = inside_without_symlinks(staging_root, PurePosixPath(str(asset["staged_name"])))
        size = source.stat().st_size
        sha256 = file_digest(source)
        if asset["size"] is not None and asset["size"] != size:
            raise OperationError("staged asset does not match its declared size")
        if asset["sha256"] is not None and asset["sha256"] != sha256:
            raise OperationError("staged asset does not match its declared SHA-256")
        verified.append({**asset, "size": size, "sha256": sha256, "_source": source})
    return verified


MAX_EXTRACTED_TEXT_BYTES = 8 * 1024 * 1024
MAX_OCR_PAGES = 100
MAX_OCR_SECONDS = 10 * 60
OCR_DISK_RESERVE_BYTES = 256 * 1024 * 1024


def limited_text(source: BinaryIO, limit: int = MAX_EXTRACTED_TEXT_BYTES) -> tuple[str, bool]:
    body = source.read(limit + 1)
    return body[:limit].decode("utf-8-sig", errors="replace"), len(body) > limit


def readable_subtitles(path: Path) -> tuple[str, bool]:
    lines: list[str] = []
    previous = ""
    with path.open("rb") as source:
        body, truncated = limited_text(source)
    for raw in body.splitlines():
        line = re.sub(r"<[^>]+>", "", raw).strip()
        if not line or line == "WEBVTT" or "-->" in line or line.isdigit() or line == previous:
            continue
        lines.append(line)
        previous = line
    return "\n".join(lines), truncated


def local_pdf_text(path: Path) -> tuple[str, str]:
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        try:
            with tempfile.TemporaryFile() as output:
                result = subprocess.run(
                    [pdftotext, "-layout", str(path), "-"],
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=120,
                )
                output.seek(0)
                extracted, truncated = limited_text(output)
            if result.returncode == 0 and extracted.strip():
                return extracted.strip(), "text-truncated" if truncated else "text"
        except (OSError, subprocess.TimeoutExpired):
            pass

    pdftoppm, tesseract = shutil.which("pdftoppm"), shutil.which("tesseract")
    if not pdftoppm or not tesseract:
        return "", "unavailable"
    try:
        with tempfile.TemporaryDirectory(prefix="lbrain-pdf-ocr-") as temporary:
            prefix = Path(temporary) / "page"
            pages: list[str] = []
            remaining = MAX_EXTRACTED_TEXT_BYTES
            truncated = False
            page_number = 1
            deadline = time.monotonic() + MAX_OCR_SECONDS
            while remaining > 0 and page_number <= MAX_OCR_PAGES and time.monotonic() < deadline:
                if shutil.disk_usage(temporary).free < OCR_DISK_RESERVE_BYTES:
                    truncated = True
                    break
                page = prefix.with_suffix(".png")
                try:
                    rendered = subprocess.run(
                        [
                            pdftoppm, "-f", str(page_number), "-l", str(page_number),
                            "-singlefile", "-scale-to", "4000", "-png", str(path), str(prefix),
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                        timeout=min(120, max(deadline - time.monotonic(), 0.001)),
                    )
                except subprocess.TimeoutExpired:
                    truncated = True
                    break
                if rendered.returncode or not page.is_file():
                    break
                if time.monotonic() >= deadline:
                    truncated = True
                    break
                with tempfile.TemporaryFile() as output:
                    try:
                        result = subprocess.run(
                            [tesseract, str(page), "stdout"],
                            stdout=output,
                            stderr=subprocess.DEVNULL,
                            check=False,
                            timeout=min(120, max(deadline - time.monotonic(), 0.001)),
                        )
                    except subprocess.TimeoutExpired:
                        truncated = True
                        break
                    output.seek(0)
                    extracted, page_truncated = limited_text(output, max(remaining, 0))
                if result.returncode == 0 and extracted.strip():
                    pages.append(extracted.strip())
                    remaining -= len(extracted.encode("utf-8"))
                truncated = truncated or page_truncated
                page.unlink()
                page_number += 1
                if remaining <= 0:
                    truncated = True
                    break
            if page_number > MAX_OCR_PAGES or time.monotonic() >= deadline:
                truncated = True
            return ("\n\n".join(pages), "ocr-truncated" if truncated else "ocr") if pages else ("", "failed")
    except (OSError, subprocess.TimeoutExpired):
        return "", "failed"


def enriched_bundle_content(content: str, assets: list[dict[str, Any]]) -> tuple[str, bool]:
    sections: list[str] = []
    incomplete = False
    for asset in assets:
        media_type = str(asset["media_type"]).lower()
        name = str(asset["name"])
        source = Path(asset["_source"])
        if media_type == "application/pdf":
            extracted, method = local_pdf_text(source)
            sections.append(
                f"### Extracted PDF text — {name}\n\n- Extraction: {method}\n\n"
                + (extracted or "_No searchable text could be produced; the original PDF is preserved._")
            )
            incomplete = incomplete or not extracted or method.endswith("-truncated")
        elif media_type in {"text/vtt", "application/x-subrip"}:
            try:
                extracted, truncated = readable_subtitles(source)
            except (OSError, UnicodeError):
                extracted, truncated = "", False
            sections.append(
                f"### Extracted transcript — {name}\n\n"
                + (extracted or "_No subtitle text could be produced; the original subtitle file is preserved._")
            )
            incomplete = incomplete or not extracted or truncated
    return "\n\n".join([content, *sections]).strip(), incomplete


def render_bundle(
    title: str,
    summary: str,
    origin: str,
    scope: str,
    content: str,
    author: str,
    published_at: str,
    extraction_status: str,
    capture_id: str,
    source_content_hash: str,
    content_hash: str,
    version: int,
    manifest_path: str,
    assets: list[dict[str, Any]],
    previous: str,
    capture_note: str,
) -> str:
    today = date.today().isoformat()
    header = (
        "---\n"
        "type: note\n"
        f"summary: {yaml_string(summary)}\n"
        "status: active\n"
        "visibility: private\n"
        f"origin: {yaml_string(origin)}\n"
        f"capture_id: {capture_id}\n"
        f"capture_version: {version}\n"
        f"source_content_hash: {yaml_string(source_content_hash)}\n"
        f"content_hash: {content_hash}\n"
        f"capture_scope: {scope}\n"
        f"extraction_status: {extraction_status}\n"
        "weaving: pending\n"
        f"media_manifest: {yaml_string(manifest_path)}\n"
    )
    if previous:
        header += f"previous_version: {yaml_string(previous)}\n"
    marker_safe = lambda value: value.replace("<!-- lbrain:", "&lt;!-- lbrain:")
    capture_body = marker_safe(content) or "Original content was not available at capture time."
    media_body = ""
    if assets:
        media_body = "## Preserved media\n\n"
        prefix = PurePosixPath(*PurePosixPath(manifest_path).parts[2:]).parent / "files"
        for asset in assets:
            target = (prefix / str(asset["name"])).as_posix()
            link_target = quote(target, safe="/")
            if asset["placeholder"]:
                capture_body = capture_body.replace(str(asset["placeholder"]), link_target)
            label = str(asset["name"]).replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
            media_body += f"- [{label}]({link_target})\n"
    provenance = (
        "## Provenance notes\n\n"
        f"- Origin: {marker_safe(origin)}\n"
        f"- Scope: {marker_safe(scope)}\n"
        f"- Extraction: {marker_safe(extraction_status)}\n"
    )
    if author:
        provenance += f"- Author: {marker_safe(author)}\n"
    if published_at:
        provenance += f"- Published: {marker_safe(published_at)}\n"
    if capture_note:
        provenance += f"- Capture note: {marker_safe(capture_note)}\n"
    body = (
        f"created: {today}\nupdated: {today}\n---\n"
        "<!-- lbrain:title:start -->\n"
        f"# {marker_safe(title)}\n\n"
        "<!-- lbrain:title:end -->\n\n"
        "<!-- lbrain:capture:start -->\n"
        "## Capture\n\n"
        f"{capture_body}\n"
        "<!-- lbrain:capture:end -->\n\n"
        "<!-- lbrain:media:start -->\n"
        f"{media_body.rstrip()}\n"
        "<!-- lbrain:media:end -->\n\n"
        "<!-- lbrain:provenance:start -->\n"
        f"{provenance.rstrip()}\n"
        "<!-- lbrain:provenance:end -->\n"
    )
    return header + body


BUNDLE_MANAGED_FIELDS = {
    "type",
    "summary",
    "status",
    "visibility",
    "origin",
    "capture_id",
    "capture_version",
    "source_content_hash",
    "content_hash",
    "capture_scope",
    "extraction_status",
    "weaving",
    "media_manifest",
    "previous_version",
    "created",
    "updated",
}


def split_note(value: str) -> tuple[list[str], str]:
    if not value.startswith("---\n"):
        raise OperationError("Capture Bundle is missing frontmatter")
    end = value.find("\n---\n", 4)
    if end < 0:
        raise OperationError("Capture Bundle frontmatter is incomplete")
    return value[4:end].splitlines(), value[end + 5 :]


def bundle_marker_bounds(value: str, name: str) -> tuple[int, int]:
    start_marker, end_marker = f"<!-- lbrain:{name}:start -->", f"<!-- lbrain:{name}:end -->"
    if value.count(start_marker) != 1 or value.count(end_marker) != 1:
        raise OperationError("Capture Bundle managed sections are incomplete")
    start = value.find(start_marker)
    end = value.find(end_marker, start + len(start_marker))
    if end < start:
        raise OperationError("Capture Bundle managed sections are incomplete")
    return start, end + len(end_marker)


def replace_bundle_block(existing: str, rendered: str, name: str) -> str:
    old_start, old_end = bundle_marker_bounds(existing, name)
    new_start, new_end = bundle_marker_bounds(rendered, name)
    return existing[:old_start] + rendered[new_start:new_end] + existing[old_end:]


def managed_bundle_hash(value: str) -> str:
    lines, body = split_note(value)
    managed = sorted(
        line for line in lines if ":" in line and line.split(":", 1)[0] in BUNDLE_MANAGED_FIELDS
    )
    blocks: list[str] = []
    for name in ("title", "capture", "media", "provenance"):
        start, end = bundle_marker_bounds(body, name)
        blocks.append(body[start:end])
    return digest(json.dumps([managed, blocks], ensure_ascii=False))


def recover_bundle_note(existing: str, rendered: str) -> str:
    old_lines, old_body = split_note(existing)
    new_lines, new_body = split_note(rendered)
    new_fields = {
        line.split(":", 1)[0]: line
        for line in new_lines
        if ":" in line and line.split(":", 1)[0] in BUNDLE_MANAGED_FIELDS
    }
    seen: set[str] = set()
    merged: list[str] = []
    for line in old_lines:
        key = line.split(":", 1)[0] if ":" in line else ""
        if key in new_fields:
            merged.append(new_fields[key])
            seen.add(key)
        else:
            merged.append(line)
    merged.extend(new_fields[key] for key in new_fields if key not in seen)

    body = old_body
    for name in ("title", "capture", "media", "provenance"):
        body = replace_bundle_block(body, new_body, name)
    return "---\n" + "\n".join(merged) + "\n---\n" + body.strip() + "\n"


def preserved_recovery_assets(
    root: Path,
    recovery_head: list[str],
    assets: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    capture_id = frontmatter_text(recovery_head, "capture_id")
    version = frontmatter_number(recovery_head, "capture_version")
    expected = PurePosixPath("Inbox/Captures/_assets") / capture_id / f"v{version}" / "manifest.json"
    if frontmatter_text(recovery_head, "media_manifest") != expected.as_posix():
        raise OperationError("incomplete Capture Bundle has an invalid media manifest")
    manifest = inside_without_symlinks(root, expected)
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise OperationError("incomplete Capture Bundle media manifest is invalid") from error
    raw_assets = data.get("assets") if isinstance(data, dict) else None
    if not isinstance(raw_assets, list):
        raise OperationError("incomplete Capture Bundle media manifest is invalid")

    current = {str(asset["name"]): asset for asset in assets}
    names = set(current)
    preserved: list[dict[str, Any]] = []
    changed = False
    for raw in raw_assets:
        if not isinstance(raw, dict):
            raise OperationError("incomplete Capture Bundle media manifest is invalid")
        name = safe_asset_path(raw.get("name"), "preserved asset name").as_posix()
        sha256, size = raw.get("sha256"), raw.get("size")
        media_type, placeholder = raw.get("media_type"), raw.get("placeholder", "")
        if (
            not isinstance(sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", sha256)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(media_type, str)
            or not media_type.strip()
            or not isinstance(placeholder, str)
            or (placeholder and not re.fullmatch(r"lbrain-asset://[A-Za-z0-9._-]+", placeholder))
        ):
            raise OperationError("incomplete Capture Bundle media manifest is invalid")
        source = inside_without_symlinks(manifest.parent / "files", PurePosixPath(name))
        if source.stat().st_size != size or file_digest(source) != sha256:
            raise OperationError("preserved Capture Bundle asset does not match its manifest")
        if name in current:
            replacement = current[name]
            if placeholder != "lbrain-asset://html-snapshot" and any(
                replacement[key] != value
                for key, value in (
                    ("sha256", sha256),
                    ("size", size),
                    ("media_type", media_type.strip()),
                    ("placeholder", placeholder),
                )
            ):
                changed = True
            continue
        preserved.append(
            {
                "name": name,
                "staged_name": "",
                "sha256": sha256,
                "size": size,
                "placeholder": placeholder,
                "media_type": media_type.strip(),
                "_source": source,
            }
        )
        names.add(name)
    return [*assets, *preserved], preserved, changed


def restore_preserved_links(
    content: str,
    assets: list[dict[str, Any]],
    preserved: list[dict[str, Any]],
    failures: list[tuple[str, str, str, str]],
) -> tuple[str, set[str]]:
    by_placeholder = {str(asset["placeholder"]): asset for asset in preserved}
    resolved: set[str] = set()
    for placeholder, asset_url, missing_markdown, _ in failures:
        if placeholder not in by_placeholder:
            continue
        resolved.add(placeholder)
        content = content.replace(f"- Media could not be preserved: {asset_url}\n", "")
        content = content.replace(f"- Media could not be preserved: {asset_url}", "")
        content = content.replace(missing_markdown, placeholder)
        content = re.sub(
            r"(?<![A-Za-z0-9%/?=&])" + re.escape(asset_url) + r"(?=$|[\s\"'<>\]\)])",
            lambda _: placeholder,
            content,
        )
    content = re.sub(r"(?m)^## Capture warnings\n(?:\s*\n)*(?=## |\Z)", "", content).strip()

    snapshot = next((asset for asset in assets if asset["placeholder"] == "lbrain-asset://html-snapshot"), None)
    if snapshot is not None and resolved:
        source = Path(snapshot["_source"])
        replacements = {
            missing_html.encode(): f"../{quote(str(by_placeholder[placeholder]['name']), safe='/')}".encode()
            for placeholder, _, _, missing_html in failures
            if placeholder in by_placeholder
        }
        for old, new in replacements.items():
            with tempfile.NamedTemporaryFile(dir=source.parent, delete=False) as target:
                temporary = Path(target.name)
                tail = b""
                with source.open("rb") as current:
                    for chunk in iter(lambda: current.read(64 * 1024), b""):
                        body = tail + chunk
                        boundary = max(0, len(body) - len(old) + 1)
                        offset = 0
                        while True:
                            found = body.find(old, offset)
                            if found < 0 or found >= boundary:
                                break
                            target.write(body[offset:found])
                            target.write(new)
                            offset = found + len(old)
                        safe = max(offset, boundary)
                        target.write(body[offset:safe])
                        tail = body[safe:]
                    target.write(tail.replace(old, new))
            os.replace(temporary, source)
        snapshot["size"] = source.stat().st_size
        snapshot["sha256"] = file_digest(source)
    return content, resolved


def build_bundle_assets(
    root: Path,
    capture_id: str,
    version: int,
    assets: list[dict[str, Any]],
) -> tuple[Path, Path, str, list[str]]:
    relative = PurePosixPath("Inbox/Captures/_assets") / capture_id / f"v{version}"
    final = root.joinpath(*relative.parts)
    assert_safe_target(root, final / "manifest.json")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".v{version}.", dir=final.parent))
    copied: list[str] = []
    try:
        for asset in assets:
            source = Path(asset["_source"])
            if source.stat().st_size != asset["size"] or file_digest(source) != asset["sha256"]:
                raise OperationError("staged asset does not match its declared size and SHA-256")
            destination = temporary / "files" / Path(str(asset["name"]))
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            copied.append((relative / "files" / str(asset["name"])).as_posix())
        manifest = {
            "schema": "lbrain.capture-assets.v1",
            "capture_id": capture_id,
            "version": version,
            "assets": [
                {key: asset[key] for key in ("name", "sha256", "size", "media_type", "placeholder")}
                for asset in assets
            ],
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        if final.parent.is_dir() and not any(final.parent.iterdir()):
            final.parent.rmdir()
        raise
    manifest_path = (relative / "manifest.json").as_posix()
    return temporary, final, manifest_path, [manifest_path, *copied]


def stage_bundle_assets(
    root: Path,
    capture_id: str,
    version: int,
    assets: list[dict[str, Any]],
) -> tuple[Path, str, list[str]]:
    temporary, final, manifest_path, copied = build_bundle_assets(root, capture_id, version, assets)
    if final.exists():
        shutil.rmtree(temporary, ignore_errors=True)
        raise OperationError("capture asset version already exists")
    os.replace(temporary, final)
    return final, manifest_path, copied


def capture_git_commit(root: Path, paths: list[str], title: str) -> dict[str, Any]:
    subject = " ".join(title.split())[:120]
    commit_paths = load_kit_helper(root, "git_commit", "commit_paths")
    result = commit_paths(root, paths, f"capture: {subject}")
    if result["committed"]:
        return result
    return {"committed": False, "warning": f"capture saved; {result['reason']}"}


def capture_bundle(
    root: Path,
    payload: dict[str, Any],
    staging_root: Path | None = None,
) -> dict[str, Any]:
    if payload.get("schema") != "lbrain.capture.v1":
        raise OperationError("capture schema must be lbrain.capture.v1")
    title = required_text(payload, "title")
    summary = required_text(payload, "summary")
    origin = required_text(payload, "origin")
    scope = payload.get("scope", "page")
    if scope not in {"page", "selection"}:
        raise OperationError("scope must be page or selection")
    content_value = payload.get("content_markdown", "")
    if not isinstance(content_value, str):
        raise OperationError("content_markdown must be text")
    content = content_value.strip()
    failed_value = payload.get("failed_remote_assets", [])
    if not isinstance(failed_value, list):
        raise OperationError("failed_remote_assets must be a list")
    failed_remote_assets: list[tuple[str, str, str, str]] = []
    for failed in failed_value:
        if not isinstance(failed, dict):
            raise OperationError("each failed remote asset must be an object")
        asset_id, asset_url = failed.get("id"), failed.get("url")
        if (
            not isinstance(asset_id, str)
            or not re.fullmatch(r"[A-Za-z0-9._-]+", asset_id)
            or not isinstance(asset_url, str)
            or not asset_url.strip()
        ):
            raise OperationError("failed remote assets require a stable id and URL")
        failed_remote_assets.append(
            (
                f"lbrain-asset://{asset_id}",
                asset_url.strip(),
                f"lbrain-missing://{asset_id}",
                f"about:blank#lbrain-missing-{asset_id}",
            )
        )
    author_value = payload.get("author", "")
    published_value = payload.get("published_at", "")
    if not isinstance(author_value, str) or not isinstance(published_value, str):
        raise OperationError("author and published_at must be text")
    author = author_value.strip()
    published_at = published_value.strip()
    capture_note_value = payload.get("capture_note", "")
    if not isinstance(capture_note_value, str):
        raise OperationError("capture_note must be text")
    capture_note = capture_note_value.strip()
    source_content_value = payload.get("source_content_markdown", content_value)
    if not isinstance(source_content_value, str):
        raise OperationError("source_content_markdown must be text")
    source_content = source_content_value.strip()
    computed_source_hash = digest("\0".join((title, author, published_at, source_content)))
    source_hash_value = payload.get("source_content_hash")
    if source_hash_value is not None and (
        not isinstance(source_hash_value, str) or not re.fullmatch(r"[0-9a-f]{64}", source_hash_value)
    ):
        raise OperationError("source_content_hash must be a lowercase SHA-256 digest")
    if source_hash_value is not None and source_hash_value != computed_source_hash:
        raise OperationError("source_content_hash does not match the original rendered content")
    source_content_hash = computed_source_hash
    extraction_status = payload.get("extraction_status", "complete")
    if extraction_status not in {"complete", "partial", "failed"}:
        raise OperationError("extraction_status must be complete, partial, or failed")
    if extraction_status == "complete" and not content:
        raise OperationError("complete capture requires content_markdown")
    pre_media_status = payload.get("pre_media_extraction_status")
    if pre_media_status not in {None, "complete", "partial", "failed"}:
        raise OperationError("pre_media_extraction_status is invalid")
    assets = verified_staged_assets(asset_manifest(payload), staging_root)
    for asset in assets:
        media_type = str(asset["media_type"]).lower()
        if media_type.startswith("text/") or media_type in {
            "application/json", "application/xhtml+xml", "image/svg+xml"
        }:
            reject_secret_file(root, Path(asset["_source"]))
        else:
            reject_binary_secret_file(root, Path(asset["_source"]), media_type)
    content, enrichment_incomplete = enriched_bundle_content(content, assets)
    if enrichment_incomplete and extraction_status == "complete":
        extraction_status = "partial"
    reject_secrets(root, title, summary, origin, content, author, published_at, capture_note)
    reject_secrets(
        root,
        *(str(asset[key]) for asset in assets for key in ("name", "media_type", "placeholder")),
    )
    capture_id = bundle_capture_id(origin, str(scope))
    normalized_assets = [
        {key: asset[key] for key in ("name", "sha256", "size", "media_type")}
        for asset in assets
    ]
    content_hash = digest(
        json.dumps(
            {
                "title": title,
                "author": author,
                "published_at": published_at,
                "content_markdown": content,
                "assets": normalized_assets,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    versions = bundle_versions(root, capture_id)
    for version, existing_hash, path in reversed(versions):
        if existing_hash == content_hash:
            target = path.relative_to(root).as_posix()
            existing = path.read_text(encoding="utf-8")
            existing_status = frontmatter_text(capture_frontmatter(path), "extraction_status")
            return {
                "operation": "capture.bundle",
                "operation_id": operation_id("capture.bundle", target, content_hash),
                "status": "partial" if existing_status != "complete" else "already_saved",
                "target": target,
                "open_uri": f"obsidian://open?path={quote(str(path))}",
                "affected_paths": [],
                "capture_id": capture_id,
                "version": version,
                "expected_hash": managed_bundle_hash(existing),
                "source_content_hash": source_content_hash,
                "git": {"committed": False, "warning": None},
                "validation": {"ok": True, "message": "existing Capture Version reused"},
                "rollback": None,
            }

    recovery_value = payload.get("recovery_target")
    recovery_assets: list[dict[str, Any]] | None = None
    preserved_assets: list[dict[str, Any]] = []
    if recovery_value is not None:
        if not isinstance(recovery_value, str):
            raise OperationError("recovery_target must be an Inbox Capture path")
        recovery_relative = PurePosixPath(recovery_value)
        if (
            recovery_relative.is_absolute()
            or ".." in recovery_relative.parts
            or recovery_relative.parts[:2] != ("Inbox", "Captures")
            or recovery_relative.suffix != ".md"
        ):
            raise OperationError("recovery_target must be an Inbox Capture path")
        recovery_note = root.joinpath(*recovery_relative.parts)
        if not versions or recovery_note != versions[-1][2] or not recovery_note.is_file():
            raise OperationError("recovery_target must be the latest Capture Version")
        recovery_head = capture_frontmatter(recovery_note)
        recovery_status = frontmatter_text(recovery_head, "extraction_status")
        if recovery_status not in {"partial", "failed"}:
            raise OperationError("only an incomplete Capture Version can be recovered")
        if recovery_status != "failed" and frontmatter_text(recovery_head, "source_content_hash") != source_content_hash:
            recovery_value = None
        else:
            existing = recovery_note.read_text(encoding="utf-8")
            if payload.get("expected_hash") != managed_bundle_hash(existing):
                raise OperationError("incomplete Capture Bundle changed after its recovery receipt")
            recovery_assets, preserved_assets, assets_changed = preserved_recovery_assets(
                root, recovery_head, assets
            )
            if assets_changed:
                recovery_value = None

    if recovery_value is not None:
        recovery_relative = PurePosixPath(recovery_value)
        recovery_note = root.joinpath(*recovery_relative.parts)
        recovery_head = capture_frontmatter(recovery_note)
        existing = recovery_note.read_text(encoding="utf-8")
        assert recovery_assets is not None
        assets = recovery_assets
        if preserved_assets:
            content, resolved_failures = restore_preserved_links(
                content, assets, preserved_assets, failed_remote_assets
            )
            preserved_content, preserved_incomplete = enriched_bundle_content("", preserved_assets)
            content = "\n\n".join(item for item in (content, preserved_content) if item).strip()
            if (
                pre_media_status == "complete"
                and len(resolved_failures) == len(failed_remote_assets)
                and not enrichment_incomplete
                and not preserved_incomplete
            ):
                extraction_status = "complete"
            if preserved_incomplete and extraction_status == "complete":
                extraction_status = "partial"
            reject_secrets(
                root,
                *(str(asset[key]) for asset in preserved_assets for key in ("name", "media_type", "placeholder")),
            )
            normalized_assets = [
                {key: asset[key] for key in ("name", "sha256", "size", "media_type")}
                for asset in assets
            ]
            content_hash = digest(
                json.dumps(
                    {
                        "title": title,
                        "author": author,
                        "published_at": published_at,
                        "content_markdown": content,
                        "assets": normalized_assets,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        version = frontmatter_number(recovery_head, "capture_version")
        previous = frontmatter_text(recovery_head, "previous_version")
        required_bytes = sum(int(asset["size"]) for asset in assets) + len(content.encode("utf-8")) + 4096
        if shutil.disk_usage(root).free < required_bytes:
            raise OperationError("not enough disk space for Capture Bundle")
        temporary, asset_directory, manifest_path, asset_paths = build_bundle_assets(
            root, capture_id, version, assets
        )
        try:
            rendered = render_bundle(
                title,
                summary,
                origin,
                str(scope),
                content,
                author,
                published_at,
                str(extraction_status),
                capture_id,
                source_content_hash,
                content_hash,
                version,
                manifest_path,
                assets,
                previous,
                capture_note,
            )
            recovered = recover_bundle_note(existing, rendered)
            reject_secrets(root, recovered)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        backup = Path(tempfile.mkdtemp(prefix=f".{asset_directory.name}.backup.", dir=asset_directory.parent))
        backup.rmdir()
        prior_asset_digest = directory_digest(asset_directory)
        applied_asset_digest: str | None = None
        note_written = False
        try:
            os.replace(asset_directory, backup)
            os.replace(temporary, asset_directory)
            applied_asset_digest = directory_digest(asset_directory)
            atomic_write(root, recovery_note, recovered, existing)
            note_written = True
            valid, message = validate(root)
            if not valid:
                raise OperationError(message or "Capture Bundle recovery failed Kit validation")
        except Exception as error:
            note_rollback_ok = True
            if note_written:
                try:
                    atomic_write(root, recovery_note, existing, recovered)
                except OperationError:
                    note_rollback_ok = False
            assets_unchanged = (
                directory_digest(asset_directory) == applied_asset_digest
                and directory_digest(backup) == prior_asset_digest
            )
            if not note_rollback_ok or not assets_unchanged:
                recovery_paths = [
                    path.relative_to(root).as_posix()
                    for path in (asset_directory, backup)
                    if path.exists()
                ]
                raise OperationError(
                    f"Capture Bundle rollback conflicted; asset states preserved at {', '.join(recovery_paths)}"
                ) from error
            displaced = Path(
                tempfile.mkdtemp(prefix=f".{asset_directory.name}.failed.", dir=asset_directory.parent)
            )
            displaced.rmdir()
            try:
                if asset_directory.exists():
                    os.replace(asset_directory, displaced)
                if backup.exists():
                    os.replace(backup, asset_directory)
            except OSError as rollback_error:
                recovery_paths = [path.relative_to(root).as_posix() for path in (backup, displaced) if path.exists()]
                raise OperationError(
                    f"Capture Bundle asset rollback failed; recovery paths: {', '.join(recovery_paths)}"
                ) from rollback_error
            shutil.rmtree(displaced, ignore_errors=True)
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        shutil.rmtree(backup, ignore_errors=True)
        affected = [recovery_relative.as_posix(), *asset_paths]
        git = capture_git_commit(root, affected, title)
        return {
            "operation": "capture.bundle",
            "operation_id": operation_id("capture.bundle", recovery_relative.as_posix(), content_hash),
            "status": "partial" if extraction_status != "complete" else "saved",
            "target": recovery_relative.as_posix(),
            "open_uri": f"obsidian://open?path={quote(str(recovery_note))}",
            "affected_paths": affected,
            "capture_id": capture_id,
            "version": version,
            "expected_hash": managed_bundle_hash(recovered),
            "source_content_hash": source_content_hash,
            "git": git,
            "validation": {"ok": True, "message": message or "Kit validation passed"},
            "rollback": None,
        }

    version = max((item[0] for item in versions), default=0) + 1
    previous = versions[-1][2].relative_to(root).as_posix() if versions else ""
    required_bytes = sum(int(asset["size"]) for asset in assets) + len(content.encode("utf-8")) + 4096
    if shutil.disk_usage(root).free < required_bytes:
        raise OperationError("not enough disk space for Capture Bundle")
    asset_directory: Path | None = None
    asset_digest: str | None = None
    note: Path | None = None
    rendered = ""
    try:
        asset_directory, manifest_path, asset_paths = stage_bundle_assets(
            root, capture_id, version, assets
        )
        asset_digest = directory_digest(asset_directory)
        slug = capture_slug(title, capture_id)
        suffix = "" if version == 1 else f"-v{version}"
        relative = PurePosixPath("Inbox/Captures") / f"{date.today().isoformat()}-{slug}{suffix}.md"
        note = root.joinpath(*relative.parts)
        rendered = render_bundle(
            title,
            summary,
            origin,
            str(scope),
            content,
            author,
            published_at,
            str(extraction_status),
            capture_id,
            source_content_hash,
            content_hash,
            version,
            manifest_path,
            assets,
            previous,
            capture_note,
        )
        reject_secrets(root, rendered)
        atomic_write(root, note, rendered, None)
        valid, message = validate(root)
        if not valid:
            raise OperationError(message or "Capture Bundle failed Kit validation")
    except Exception as error:
        if note is not None and note.is_file() and rendered:
            try:
                atomic_unlink(root, note, rendered)
            except OperationError as rollback_error:
                recovery_path = asset_directory.relative_to(root).as_posix() if asset_directory else ""
                raise OperationError(
                    f"Capture Bundle rollback conflicted; captured assets preserved at {recovery_path}"
                ) from error
        if asset_directory is not None and directory_digest(asset_directory) != asset_digest:
            recovery_path = asset_directory.relative_to(root).as_posix()
            raise OperationError(
                f"Capture Bundle rollback conflicted; captured assets preserved at {recovery_path}"
            ) from error
        if asset_directory is not None:
            shutil.rmtree(asset_directory, ignore_errors=True)
            if asset_directory.parent.is_dir() and not any(asset_directory.parent.iterdir()):
                asset_directory.parent.rmdir()
        raise

    affected = [relative.as_posix(), *asset_paths]
    git = capture_git_commit(root, affected, title)
    status = "partial" if extraction_status != "complete" else ("new_version" if version > 1 else "saved")
    return {
        "operation": "capture.bundle",
        "operation_id": operation_id("capture.bundle", relative.as_posix(), content_hash),
        "status": status,
        "target": relative.as_posix(),
        "open_uri": f"obsidian://open?path={quote(str(note))}",
        "affected_paths": affected,
        "capture_id": capture_id,
        "version": version,
        "expected_hash": managed_bundle_hash(rendered),
        "source_content_hash": source_content_hash,
        "git": git,
        "validation": {"ok": True, "message": message or "Kit validation passed"},
        "rollback": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "operation", choices=("project.configure", "project.checkpoint", "capture.create", "capture.bundle")
    )
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()

    payload: dict[str, Any] = {}
    root: Path | None = None
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise OperationError("operation input must be a JSON object")
        root = args.root.resolve()
        if not (root / "System/Kit/check.py").is_file():
            raise OperationError("root is not an LBrain Kit")
        with operation_lock(root):
            if args.operation == "project.configure":
                result = project_configure(root, payload)
            elif args.operation == "project.checkpoint":
                result = project_checkpoint(root, payload)
            elif args.operation == "capture.bundle":
                result = capture_bundle(root, payload)
            else:
                result = capture_create(root, payload)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["status"] != "failed" else 1
    except (OSError, json.JSONDecodeError, OperationError) as error:
        target = ""
        if root is not None and args.operation.startswith("project."):
            try:
                candidate = relative_project_path(payload.get("project_path")).as_posix()
                secret_check = load_kit_helper(root, "disclosure", "contains_secret")
                runtime_state_check = load_kit_helper(root, "disclosure", "contains_runtime_state")
                if not secret_check(candidate) and not runtime_state_check(candidate):
                    target = candidate
            except OperationError:
                pass
        identity = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        print(
            json.dumps(
                {
                    "operation": args.operation,
                    "operation_id": operation_id(args.operation, target, identity),
                    "mode": payload.get("mode") if payload.get("mode") in {"preview", "apply"} else "apply",
                    "status": "failed",
                    "target": target,
                    "error": str(error),
                    "affected_paths": [],
                    "validation": {"ok": False, "message": "operation rejected"},
                    "rollback": None,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
