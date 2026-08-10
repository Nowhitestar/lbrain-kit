#!/usr/bin/env python3
"""Deterministic preview and apply operations for Personal Skill improvements."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any


class OperationError(ValueError):
    pass


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_text(value: str) -> str:
    return digest_bytes(value.encode("utf-8"))


def required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise OperationError(f"{key} must be non-empty text")
    return value.strip()


def frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        raise OperationError("note is missing frontmatter")
    try:
        block = text.split("---", 2)[1]
    except IndexError as error:
        raise OperationError("note frontmatter is malformed") from error
    values: dict[str, str] = {}
    for line in block.splitlines():
        if not line or line[0].isspace() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        raw = value.strip()
        if raw.startswith('"'):
            try:
                parsed = json.loads(raw)
                values[key] = str(parsed)
                continue
            except json.JSONDecodeError:
                pass
        values[key] = raw
    return values


def proposal_path(root: Path, value: object) -> Path:
    if not isinstance(value, str):
        raise OperationError("proposal_path must be text")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or len(relative.parts) != 3
        or relative.parts[:2] != ("System", "Proposals")
        or relative.suffix != ".md"
    ):
        raise OperationError("proposal_path must name one Proposal inside System/Proposals")
    path = root.joinpath(*relative.parts)
    if not path.is_file():
        raise OperationError("Proposal does not exist")
    return path


def target_skill(root: Path, metadata: dict[str, str]) -> tuple[Path, str]:
    if metadata.get("proposal_kind") != "skill_improvement":
        raise OperationError("Proposal is not a Skill Improvement Proposal")
    target = metadata.get("target", "")
    relative = PurePosixPath(target)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or len(relative.parts) != 4
        or relative.parts[:2] != ("Skills", "Personal")
        or relative.name != "SKILL.md"
    ):
        raise OperationError("Proposal target must be a Personal Skill")
    skill = root.joinpath(*relative.parts).parent
    manifest = skill / "lbrain.json"
    if not (skill / "SKILL.md").is_file() or not manifest.is_file():
        raise OperationError("target Personal Skill package is incomplete")
    enabled = (root / "Skills/Enabled.md").read_text(encoding="utf-8")
    link = relative.as_posix().removesuffix(".md")
    if f"[[{link}]]" not in enabled:
        raise OperationError("target Personal Skill is not enabled")
    return skill, relative.as_posix()


def package_files(skill: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(skill.rglob("*")):
        if path.is_symlink():
            raise OperationError("Personal Skill packages must not contain symlinks")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
            files.append(path)
    return files


def package_hash(skill: Path) -> str:
    hasher = hashlib.sha256()
    for path in package_files(skill):
        relative = path.relative_to(skill).as_posix()
        hasher.update(relative.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def semver(value: object) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise OperationError("Personal Skill version must be semantic x.y.z")
    parts = value.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise OperationError("Personal Skill version must be semantic x.y.z")
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


def bump_version(current: str, level: object) -> str:
    major, minor, patch = semver(current)
    if level == "patch":
        patch += 1
    elif level == "minor":
        minor += 1
        patch = 0
    elif level == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        raise OperationError("change_level must be patch, minor, or major")
    return f"{major}.{minor}.{patch}"


def proposed_files(skill: Path, payload: dict[str, Any]) -> tuple[dict[str, str], str, str]:
    changes = payload.get("changes")
    if not isinstance(changes, dict) or not changes:
        raise OperationError("changes must be a non-empty object of package-relative files")
    if "SKILL.md" not in changes or "tests/cases.md" not in changes:
        raise OperationError("Skill improvement must change SKILL.md and tests/cases.md")
    proposed: dict[str, str] = {}
    for value, content in changes.items():
        if not isinstance(value, str) or not isinstance(content, str):
            raise OperationError("change paths and contents must be text")
        relative = PurePosixPath(value)
        if relative.is_absolute() or ".." in relative.parts or value == "lbrain.json":
            raise OperationError("change path must stay inside the Skill; lbrain.json is managed")
        current = skill.joinpath(*relative.parts)
        if current.exists() and (current.is_symlink() or not current.is_file()):
            raise OperationError("change target must be a regular file")
        proposed[relative.as_posix()] = content

    manifest_path = skill / "lbrain.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OperationError("Personal Skill manifest is invalid") from error
    if manifest.get("status") != "active":
        raise OperationError("target Personal Skill must be active")
    current_version = manifest.get("version")
    proposed_version = bump_version(current_version, payload.get("change_level"))
    manifest["version"] = proposed_version
    manifest["updated"] = date.today().isoformat()
    proposed["lbrain.json"] = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return proposed, str(current_version), proposed_version


def validate_proposed(root: Path, skill: Path, files: dict[str, str]) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as temporary:
        copy = Path(temporary) / "lbrain"
        shutil.copytree(root, copy, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        relative_skill = skill.relative_to(root)
        target = copy / relative_skill
        for relative, content in files.items():
            path = target.joinpath(*PurePosixPath(relative).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(copy / "System/Kit/check.py"), "--root", str(copy), "--quiet"],
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode == 0, (result.stdout + result.stderr).strip()


def unified_diff(skill: Path, files: dict[str, str]) -> str:
    chunks: list[str] = []
    prefix = skill.relative_to(skill.parents[2]).as_posix()
    for relative, content in sorted(files.items()):
        path = skill.joinpath(*PurePosixPath(relative).parts)
        before = path.read_text(encoding="utf-8") if path.is_file() else ""
        chunks.extend(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=f"a/{prefix}/{relative}",
                tofile=f"b/{prefix}/{relative}",
            )
        )
    return "".join(chunks)


def replace_preview(proposal: str, preview_block: str) -> str:
    heading = "## Change Preview"
    start = proposal.find(heading)
    if start < 0:
        return proposal.rstrip() + f"\n\n{preview_block}\n"
    return proposal[:start] + preview_block + "\n"


def atomic_write(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_root(root: Path) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, str(root / "System/Kit/check.py"), "--root", str(root), "--quiet"],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def skill_preview(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path = proposal_path(root, payload.get("proposal_path"))
    before_proposal = path.read_text(encoding="utf-8")
    metadata = frontmatter(before_proposal)
    if metadata.get("status") != "pending":
        raise OperationError("Skill preview requires a pending Proposal")
    skill, target = target_skill(root, metadata)
    rationale = required_text(payload, "rationale")
    files, base_version, proposed_version = proposed_files(skill, payload)
    base_hash = package_hash(skill)
    valid, message = validate_proposed(root, skill, files)
    if not valid:
        raise OperationError(f"proposed Skill does not validate: {message}")
    diff = unified_diff(skill, files)
    if not diff:
        raise OperationError("proposed Skill has no effective change")

    preview_identity = {
        "proposal_id": metadata.get("proposal_id"),
        "target": target,
        "base_hash": base_hash,
        "base_version": base_version,
        "proposed_version": proposed_version,
        "change_level": payload.get("change_level"),
        "files": files,
    }
    preview_hash = digest_text(
        json.dumps(preview_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    preview = {
        **preview_identity,
        "proposal_path": path.relative_to(root).as_posix(),
        "preview_hash": preview_hash,
        "rationale": rationale,
        "diff": diff,
    }
    block = (
        "## Change Preview\n\n"
        f"- Preview hash: `{preview_hash}`\n"
        f"- Base hash: `{base_hash}`\n"
        f"- Base version: {base_version}\n"
        f"- Proposed version: {proposed_version}\n"
        f"- Change level: {payload.get('change_level')}\n"
        f"- Rationale: {rationale}\n\n"
        "```diff\n"
        f"{diff.rstrip()}\n"
        "```"
    )
    after_proposal = replace_preview(before_proposal, block)
    relative = path.relative_to(root).as_posix()
    duplicate = before_proposal == after_proposal
    result = {
        "operation": "skill.preview",
        "operation_id": preview_hash[:20],
        "mode": "apply",
        "status": "noop" if duplicate else "applied",
        "target": relative,
        "affected_paths": [] if duplicate else [relative],
        "preview": preview,
        "validation": {"ok": True, "message": message or "proposed Skill validation passed"},
        "rollback": None,
    }
    if duplicate:
        return result

    atomic_write(path, after_proposal)
    root_valid, root_message = validate_root(root)
    if not root_valid:
        atomic_write(path, before_proposal)
        result["status"] = "failed"
        result["validation"] = {"ok": False, "message": root_message}
        result["rollback"] = {"performed": True, "ok": True}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("skill.preview",))
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise OperationError("operation input must be a JSON object")
        root = args.root.resolve()
        if not (root / "System/Kit/check.py").is_file():
            raise OperationError("root is not an LBrain Kit")
        result = skill_preview(root, payload)
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
