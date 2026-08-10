#!/usr/bin/env python3
"""Deterministic write operations used by the LBrain Capture Skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any


PROFILE_START = "<!-- lbrain:intake-profile:v1:start -->"
PROFILE_END = "<!-- lbrain:intake-profile:end -->"


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("project.configure",))
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()

    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise OperationError("operation input must be a JSON object")
        root = args.root.resolve()
        if not (root / "System/Kit/check.py").is_file():
            raise OperationError("root is not an LBrain Kit")
        result = project_configure(root, payload)
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
