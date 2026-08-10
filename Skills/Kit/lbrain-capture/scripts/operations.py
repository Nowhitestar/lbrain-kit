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
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any


PROFILE_START = "<!-- lbrain:intake-profile:v1:start -->"
PROFILE_END = "<!-- lbrain:intake-profile:end -->"
SOURCE_STATUSES = {"scanned", "no_durable_change", "partial", "failed", "stale", "no_match"}
SECRET = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|private[_-]?key)\b"
    r"\s*[:=]\s*\S{8,}"
)


class OperationError(ValueError):
    pass


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


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate(root: Path) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, str(root / "System/Kit/check.py"), "--root", str(root), "--quiet"],
        text=True,
        capture_output=True,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output


def project_configure(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    mode = payload.get("mode")
    if mode not in {"preview", "apply"}:
        raise OperationError("mode must be preview or apply")

    relative = relative_project_path(payload.get("project_path"))
    path = root.joinpath(*relative.parts)
    before = path.read_text(encoding="utf-8") if path.is_file() else None
    before_hash = digest(before) if before is not None else None
    profile = managed_profile(payload.get("profile_markdown"))
    after = replace_profile(before, profile) if before is not None else new_project(payload, profile)
    after_hash = digest(after)
    result = {
        "operation": "project.configure",
        "operation_id": operation_id("project.configure", relative.as_posix(), after),
        "mode": mode,
        "status": "noop" if before == after else "applied",
        "target": relative.as_posix(),
        "affected_paths": [] if before == after else [relative.as_posix()],
        "before_hash": before_hash,
        "after_hash": after_hash,
        "validation": {"ok": True, "message": "not run for preview"},
        "rollback": None,
    }
    if mode == "preview" or before == after:
        return result

    if "expected_hash" not in payload or payload.get("expected_hash") != before_hash:
        raise OperationError("project changed after preview; generate a new preview")

    atomic_write(path, after)
    valid, message = validate(root)
    if not valid:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, before)
        result["status"] = "failed"
        result["validation"] = {"ok": False, "message": message}
        result["rollback"] = {"performed": True, "ok": True}
        return result

    result["validation"] = {"ok": True, "message": message or "Kit validation passed"}
    return result


def one_line(value: object, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OperationError(f"{key} must be non-empty text")
    return " ".join(value.split()).replace("|", "\\|")


def checkpoint_block(payload: dict[str, Any]) -> tuple[str, bool]:
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
        if required and status in {"partial", "failed", "stale"}:
            incomplete = True
        rows.append((name, status, scope, required))

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
    return existing.rstrip() + f"\n\n{block}\n", False


def project_checkpoint(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    mode = payload.get("mode")
    if mode not in {"preview", "apply"}:
        raise OperationError("mode must be preview or apply")
    if "cursor" in payload or "raw_cursor" in payload:
        raise OperationError("raw connector cursors must stay outside LBrain")

    relative = relative_project_path(payload.get("project_path"))
    path = root.joinpath(*relative.parts)
    if not path.is_file():
        raise OperationError("target Project does not exist")
    before = path.read_text(encoding="utf-8")
    before_hash = digest(before)
    block, complete = checkpoint_block(payload)
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

    atomic_write(path, after)
    valid, message = validate(root)
    if not valid:
        atomic_write(path, before)
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
    if any(SECRET.search(value) for value in (title, summary, origin, content, note)):
        raise OperationError("capture contains a possible secret; remove or redact it")

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
    today = date.today().isoformat()
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
        f"created: {today}\nupdated: {today}\n---\n"
        f"# {title}\n\n"
        "## Capture\n\n"
        f"{content or 'Original content was not available at capture time.'}\n\n"
        "## Provenance notes\n\n"
        f"- Origin: {origin or 'user-provided'}\n"
        f"- Extraction: {extraction_status}\n"
    )
    if note:
        body += f"- User note: {note}\n"
    rendered = base + body
    atomic_write(path, rendered)
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
        path.unlink(missing_ok=True)
        result["status"] = "failed"
        result["rollback"] = {"performed": True, "ok": True}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("project.configure", "project.checkpoint", "capture.create"))
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()

    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise OperationError("operation input must be a JSON object")
        root = args.root.resolve()
        if not (root / "System/Kit/check.py").is_file():
            raise OperationError("root is not an LBrain Kit")
        if args.operation == "project.configure":
            result = project_configure(root, payload)
        elif args.operation == "project.checkpoint":
            result = project_checkpoint(root, payload)
        else:
            result = capture_create(root, payload)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["status"] != "failed" else 1
    except (OSError, json.JSONDecodeError, OperationError) as error:
        print(
            json.dumps(
                {
                    "operation": args.operation,
                    "status": "failed",
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
