#!/usr/bin/env python3
"""Deterministic write operations used by the LBrain Capture Skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Iterator


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


def atomic_write(path: Path, content: str, expected: object = UNCHANGED) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(content)
        if expected is not UNCHANGED:
            current = path.read_text(encoding="utf-8") if path.is_file() else None
            if current != expected:
                raise OperationError("target changed during operation")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_unlink(path: Path, expected: str) -> None:
    current = path.read_text(encoding="utf-8") if path.is_file() else None
    if current != expected:
        raise OperationError("target changed during operation")
    path.unlink()


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
        atomic_write(proposal_path, applied_proposal, proposal_before)
        valid, message = validate(root)
        if not valid:
            atomic_write(proposal_path, proposal_before, applied_proposal)
            raise OperationError("Project configuration Proposal could not be finalized")
        result["status"] = "applied"
        result["affected_paths"] = [proposal_relative.as_posix()]
        result["validation"] = {"ok": True, "message": message or "Kit validation passed"}
        return result
    if status != "accepted":
        raise OperationError("project.configure apply requires the explicitly accepted Proposal")

    atomic_write(path, after, before)
    proposal_written = False
    try:
        valid, message = validate(root)
        if not valid:
            raise OperationError(message or "Project validation failed")
        atomic_write(proposal_path, applied_proposal, proposal_before)
        proposal_written = True
        valid, message = validate(root)
        if not valid:
            raise OperationError(message or "Project and Proposal validation failed")
    except (OSError, OperationError) as error:
        rollback_ok = True
        if proposal_written:
            try:
                atomic_write(proposal_path, proposal_before, applied_proposal)
            except (OSError, OperationError):
                rollback_ok = False
        try:
            if before is None:
                atomic_unlink(path, after)
            else:
                atomic_write(path, before, after)
        except (OSError, OperationError):
            rollback_ok = False
        failed_proposal = accepted_proposal.replace(
            "Application pending.", "Application failed validation; the accepted Proposal remains retryable."
        )
        proposal_current = proposal_path.read_text(encoding="utf-8") if proposal_path.is_file() else None
        failure_recorded = False
        if proposal_current == proposal_before:
            try:
                atomic_write(proposal_path, failed_proposal, proposal_before)
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

    atomic_write(path, after, before)
    valid, message = validate(root)
    if not valid:
        atomic_write(path, before, after)
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
    return f"{slug or 'Capture'}-{key[:8]}"


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


def render_capture(
    destination: str,
    title: str,
    summary: str,
    origin: str,
    content: str,
    note: str,
    extraction_status: str,
    capture: str,
    key: str,
    created: str,
) -> str:
    base = (
        "---\n"
        f"type: {'source' if destination == 'source' else 'note'}\n"
        f"summary: {yaml_string(summary)}\n"
        "status: active\n"
        "visibility: private\n"
        f"origin: {yaml_string(origin or 'user-provided')}\n"
        f"capture_id: {key}\n"
        f"extraction_status: {extraction_status}\n"
    )
    if destination == "source":
        base += f"capture: {capture}\nweaving: pending\n"
    body = (
        f"created: {created}\nupdated: {date.today().isoformat()}\n---\n"
        f"# {title}\n\n"
        "## Capture\n\n"
        f"{content or 'Original content was not available at capture time.'}\n\n"
        "## Provenance notes\n\n"
        f"- Origin: {origin or 'user-provided'}\n"
        f"- Extraction: {extraction_status}\n"
    )
    if note:
        body += f"- User note: {note}\n"
    return base + body


def recover_capture(
    existing: str,
    title: str,
    summary: str,
    origin: str,
    content: str,
    note: str,
    extraction_status: str,
    capture: str,
) -> str:
    try:
        _, header, body = existing.split("---", 2)
    except ValueError as error:
        raise OperationError("existing capture is malformed") from error
    lines = header.strip("\n").splitlines()
    updates = {
        "summary": yaml_string(summary),
        "origin": yaml_string(origin or "user-provided"),
        "extraction_status": extraction_status,
        "updated": date.today().isoformat(),
    }
    if any(line.startswith("capture:") for line in lines):
        updates["capture"] = capture
    for key, value in updates.items():
        marker = f"{key}:"
        for index, line in enumerate(lines):
            if line.startswith(marker):
                lines[index] = f"{marker} {value}"
                break
        else:
            lines.append(f"{marker} {value}")
    recovered = "---\n" + "\n".join(lines) + "\n---" + body
    recovered = re.sub(r"(?m)^# .*$", lambda _: f"# {title}", recovered, count=1)

    capture_heading = "## Capture"
    capture_start = recovered.find(capture_heading)
    if capture_start < 0:
        raise OperationError("existing capture is missing its Capture section")
    capture_end = recovered.find("\n## ", capture_start + len(capture_heading))
    if capture_end < 0:
        capture_end = len(recovered)
    recovered = (
        recovered[:capture_start]
        + f"{capture_heading}\n\n{content}\n"
        + recovered[capture_end:]
    )

    provenance_heading = "## Provenance notes"
    provenance_start = recovered.find(provenance_heading)
    if provenance_start < 0:
        raise OperationError("existing capture is missing its Provenance notes section")
    provenance_end = recovered.find("\n## ", provenance_start + len(provenance_heading))
    if provenance_end < 0:
        provenance_end = len(recovered)
    provenance = recovered[provenance_start:provenance_end].splitlines()
    desired = {
        "- Origin:": origin or "user-provided",
        "- Extraction:": extraction_status,
    }
    if note:
        desired["- User note:"] = note
    found: set[str] = set()
    for index, line in enumerate(provenance):
        for marker, value in desired.items():
            if line.startswith(marker):
                provenance[index] = f"{marker} {value}"
                found.add(marker)
                break
    provenance.extend(f"{marker} {value}" for marker, value in desired.items() if marker not in found)
    return recovered[:provenance_start] + "\n".join(provenance).rstrip() + "\n" + recovered[provenance_end:]


def capture_create(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    destination = payload.get("destination")
    if destination not in {"source", "inbox"}:
        raise OperationError("destination must be source or inbox")
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
    if extraction_status != "complete":
        capture = "reference" if not content else capture

    key = capture_key(origin, content)
    duplicate = existing_capture(root, key, origin)
    if duplicate is not None:
        existing = duplicate.read_text(encoding="utf-8")
        head = capture_frontmatter(duplicate)
        existing_status = frontmatter_text(head, "extraction_status")
        managed = frontmatter_text(head, "capture_id") == key
        if extraction_status == "complete" and existing_status in {"failed", "partial"} and managed:
            before_hash = digest(existing)
            if payload.get("expected_hash") != before_hash:
                raise OperationError("incomplete capture changed before recovery; supply its exact expected_hash")
            rendered = recover_capture(
                existing,
                title,
                summary,
                origin,
                content,
                note,
                extraction_status,
                capture,
            )
            atomic_write(duplicate, rendered, existing)
            valid, message = validate(root)
            if not valid:
                atomic_write(duplicate, existing, rendered)
                return {
                    "operation": "capture.create",
                    "operation_id": operation_id("capture.create", duplicate.relative_to(root).as_posix(), key),
                    "mode": "apply",
                    "status": "failed",
                    "target": duplicate.relative_to(root).as_posix(),
                    "affected_paths": [],
                    "capture_id": key,
                    "validation": {"ok": False, "message": message},
                    "rollback": {"performed": True, "ok": True},
                }
            relative_duplicate = duplicate.relative_to(root).as_posix()
            return {
                "operation": "capture.create",
                "operation_id": operation_id("capture.create", relative_duplicate, key),
                "mode": "apply",
                "status": "applied",
                "target": relative_duplicate,
                "affected_paths": [relative_duplicate],
                "capture_id": key,
                "before_hash": before_hash,
                "after_hash": digest(rendered),
                "validation": {"ok": True, "message": message or "Kit validation passed"},
                "rollback": None,
            }
        relative_duplicate = duplicate.relative_to(root).as_posix()
        return {
            "operation": "capture.create",
            "operation_id": operation_id("capture.create", relative_duplicate, key),
            "mode": "apply",
            "status": "noop",
            "target": relative_duplicate,
            "affected_paths": [],
            "capture_id": key,
            "validation": {"ok": True, "message": "existing capture reused"},
            "rollback": None,
        }

    folder = "Knowledge/Sources" if destination == "source" else "Inbox"
    relative = PurePosixPath(folder) / f"{capture_slug(title, key)}.md"
    path = root.joinpath(*relative.parts)
    rendered = render_capture(
        destination,
        title,
        summary,
        origin,
        content,
        note,
        extraction_status,
        capture,
        key,
        date.today().isoformat(),
    )
    reject_secrets(root, rendered)
    atomic_write(path, rendered, None)
    valid, message = validate(root)
    status = "applied" if extraction_status == "complete" else "partial"
    result = {
        "operation": "capture.create",
        "operation_id": operation_id("capture.create", relative.as_posix(), key),
        "mode": "apply",
        "status": status,
        "target": relative.as_posix(),
        "affected_paths": [relative.as_posix()],
        "capture_id": key,
        "validation": {"ok": valid, "message": message or "Kit validation passed"},
        "rollback": None,
    }
    if not valid:
        atomic_unlink(path, rendered)
        result["status"] = "failed"
        result["rollback"] = {"performed": True, "ok": True}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("project.configure", "project.checkpoint", "capture.create"))
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
