#!/usr/bin/env python3
"""Deterministic proposal operations used by the LBrain Weave Skill."""

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


class OperationError(ValueError):
    pass


def required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise OperationError(f"{key} must be non-empty text")
    return value.strip()


def yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def evidence_path(root: Path, value: object) -> PurePosixPath:
    if not isinstance(value, str):
        raise OperationError("evidence paths must be text")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.suffix != ".md":
        raise OperationError("evidence must be a Markdown file inside LBrain")
    allowed = path.parts[:2] == ("Knowledge", "Sources") or path.parts[:2] == ("Knowledge", "Wiki")
    if not allowed or not root.joinpath(*path.parts).is_file():
        raise OperationError("evidence must be an existing Source or Wiki note")
    return path


def enabled_personal_skill(root: Path, name: object) -> tuple[Path, str]:
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise OperationError("skill_name must use lowercase letters, digits, and single hyphens")
    relative = f"Skills/Personal/{name}/SKILL.md"
    skill = root / relative
    manifest = skill.parent / "lbrain.json"
    if not skill.is_file() or not manifest.is_file():
        raise OperationError("target must be an existing Personal Skill")
    try:
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OperationError("target Personal Skill manifest is invalid") from error
    if metadata.get("status") != "active":
        raise OperationError("target Personal Skill must be active")
    enabled = (root / "Skills/Enabled.md").read_text(encoding="utf-8")
    if f"[[Skills/Personal/{name}/SKILL]]" not in enabled:
        raise OperationError("target Personal Skill must be enabled")
    return skill, relative


def proposal_key(target: str, evidence: list[PurePosixPath], behavior_delta: str) -> str:
    identity = {
        "target": target,
        "evidence": sorted(path.as_posix() for path in evidence),
        "behavior_delta": " ".join(behavior_delta.split()),
    }
    return digest(json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def existing_proposal(root: Path, key: str) -> tuple[Path, str] | None:
    marker = f"proposal_id: {key}"
    for path in sorted((root / "System/Proposals").glob("*.md")):
        try:
            frontmatter = path.read_text(encoding="utf-8").split("---", 2)[1]
        except (IndexError, OSError, UnicodeError):
            continue
        lines = frontmatter.splitlines()
        if marker not in lines:
            continue
        status = next((line.split(":", 1)[1].strip() for line in lines if line.startswith("status:")), "")
        return path, status
    return None


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "skill-improvement"


def proposal_create(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    title = required_text(payload, "title")
    summary = required_text(payload, "summary")
    rationale = required_text(payload, "rationale")
    behavior_delta = required_text(payload, "behavior_delta")
    expected_diff = required_text(payload, "expected_diff")
    _, target = enabled_personal_skill(root, payload.get("skill_name"))

    evidence_values = payload.get("evidence")
    if not isinstance(evidence_values, list) or not evidence_values:
        raise OperationError("evidence must contain at least one Source or Wiki note")
    evidence = [evidence_path(root, value) for value in evidence_values]
    test_changes = payload.get("test_changes")
    if not isinstance(test_changes, list) or not test_changes or not all(
        isinstance(item, str) and item.strip() for item in test_changes
    ):
        raise OperationError("test_changes must contain at least one behavior-case change")

    key = proposal_key(target, evidence, behavior_delta)
    duplicate = existing_proposal(root, key)
    if duplicate is not None and duplicate[1] in {"pending", "accepted", "applied"}:
        relative_duplicate = duplicate[0].relative_to(root).as_posix()
        return {
            "operation": "proposal.create",
            "operation_id": key[:20],
            "mode": "apply",
            "status": "noop",
            "target": relative_duplicate,
            "affected_paths": [],
            "proposal_id": key,
            "validation": {"ok": True, "message": "equivalent Proposal already exists"},
            "rollback": None,
        }

    filename = f"{slug(title)}-{key[:8]}.md"
    path = root / "System/Proposals" / filename
    if path.exists():
        counter = 2
        while (path.parent / f"{path.stem}-{counter}.md").exists():
            counter += 1
        path = path.parent / f"{path.stem}-{counter}.md"
    relative = path.relative_to(root).as_posix()
    today = date.today().isoformat()
    evidence_lines = "\n".join(f"- [[{item.as_posix().removesuffix('.md')}]]" for item in evidence)
    tests = "\n".join(f"- {' '.join(item.split())}" for item in test_changes)
    content = (
        "---\n"
        "type: proposal\n"
        f"summary: {yaml_string(summary)}\n"
        "status: pending\n"
        "visibility: private\n"
        f"target: {yaml_string(target)}\n"
        "action: update\n"
        "proposal_kind: skill_improvement\n"
        f"proposal_id: {key}\n"
        f"created: {today}\nupdated: {today}\n"
        "---\n"
        f"# {title}\n\n"
        f"## Rationale\n\n{rationale}\n\n"
        f"## Evidence\n\n{evidence_lines}\n\n"
        f"## Behavior delta\n\n{behavior_delta}\n\n"
        f"## Expected diff\n\n{expected_diff}\n\n"
        f"## Test changes\n\n{tests}\n\n"
        "## Decision\n\nPending user review.\n"
    )
    atomic_write(path, content)
    valid, message = validate(root)
    result = {
        "operation": "proposal.create",
        "operation_id": key[:20],
        "mode": "apply",
        "status": "applied" if valid else "failed",
        "target": relative,
        "affected_paths": [relative] if valid else [],
        "proposal_id": key,
        "validation": {"ok": valid, "message": message or "Kit validation passed"},
        "rollback": None,
    }
    if not valid:
        path.unlink(missing_ok=True)
        result["rollback"] = {"performed": True, "ok": True}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("proposal.create",))
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    payload: dict[str, Any] = {}
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise OperationError("operation input must be a JSON object")
        root = args.root.resolve()
        if not (root / "System/Kit/check.py").is_file():
            raise OperationError("root is not an LBrain Kit")
        result = proposal_create(root, payload)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["status"] != "failed" else 1
    except (OSError, json.JSONDecodeError, OperationError) as error:
        target = payload.get("skill_name", "")
        target = target if isinstance(target, str) else ""
        identity = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        print(
            json.dumps(
                {
                    "operation": args.operation,
                    "operation_id": digest(f"{args.operation}\0{target}\0{identity}")[:20],
                    "mode": "apply",
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
