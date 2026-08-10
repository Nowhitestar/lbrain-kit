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


def package_hash_with_changes(skill: Path, files: dict[str, str]) -> str:
    current = {path.relative_to(skill).as_posix(): path for path in package_files(skill)}
    hasher = hashlib.sha256()
    for relative in sorted(current.keys() | files.keys()):
        hasher.update(relative.encode("utf-8"))
        hasher.update(b"\0")
        if relative in files:
            hasher.update(files[relative].encode("utf-8"))
        else:
            hasher.update(current[relative].read_bytes())
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
        "proposed_hash": package_hash_with_changes(skill, files),
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


def preview_identity(preview: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "proposal_id",
        "target",
        "base_hash",
        "base_version",
        "proposed_version",
        "change_level",
        "files",
        "proposed_hash",
    )
    missing = [key for key in keys if key not in preview]
    if missing:
        raise OperationError(f"preview is missing: {', '.join(missing)}")
    return {key: preview[key] for key in keys}


def computed_preview_hash(preview: dict[str, Any]) -> str:
    return digest_text(
        json.dumps(preview_identity(preview), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def replace_status(proposal: str, status: str) -> str:
    marker = "status: "
    start = proposal.find(marker, proposal.find("---\n") + 4)
    if start < 0 or start > proposal.find("\n---", 4):
        raise OperationError("Proposal status is missing")
    end = proposal.find("\n", start)
    return proposal[:start] + f"status: {status}" + proposal[end:]


def replace_decision(proposal: str, body: str) -> str:
    heading = "## Decision"
    start = proposal.find(heading)
    if start < 0:
        return proposal.rstrip() + f"\n\n{heading}\n\n{body}\n"
    next_heading = proposal.find("\n## ", start + len(heading))
    end = len(proposal) if next_heading < 0 else next_heading
    replacement = f"{heading}\n\n{body}\n"
    return proposal[:start] + replacement + proposal[end:]


def approved_proposal(proposal: str, preview_hash: str, outcome: str) -> str:
    accepted = replace_status(proposal, "accepted")
    return replace_decision(
        accepted,
        f"Approved exact Change Preview `{preview_hash}`. {outcome}",
    )


def applied_proposal(proposal: str, preview_hash: str, runtime_count: int) -> str:
    applied = replace_status(proposal, "applied")
    return replace_decision(
        applied,
        (
            f"Approved and applied exact Change Preview `{preview_hash}` on {date.today().isoformat()}. "
            f"Validation passed; {runtime_count} runtime target(s) were checked or refreshed."
        ),
    )


def safe_preview_files(skill: Path, preview: dict[str, Any]) -> dict[str, str]:
    values = preview.get("files")
    if not isinstance(values, dict) or not values:
        raise OperationError("preview files are missing")
    files: dict[str, str] = {}
    for value, content in values.items():
        if not isinstance(value, str) or not isinstance(content, str):
            raise OperationError("preview file paths and contents must be text")
        relative = PurePosixPath(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise OperationError("preview file path escapes the Personal Skill")
        path = skill.joinpath(*relative.parts)
        if path.exists() and (path.is_symlink() or not path.is_file()):
            raise OperationError("preview target must be a regular file")
        files[relative.as_posix()] = content
    if "SKILL.md" not in files or "tests/cases.md" not in files or "lbrain.json" not in files:
        raise OperationError("preview must include SKILL.md, tests/cases.md, and lbrain.json")
    return files


def remove_runtime_package(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def runtime_plan(
    root: Path,
    skill: Path,
    base_hash: str,
    values: object,
) -> list[tuple[str, Path, str]]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise OperationError("runtime_targets must be a list")
    plan: list[tuple[str, Path, str]] = []
    skill_name = skill.name
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            raise OperationError(f"runtime_targets[{index}] must be an object")
        runtime = item.get("runtime")
        target = item.get("target")
        if runtime not in {"codex", "claude", "hermes", "openclaw"}:
            raise OperationError(f"runtime_targets[{index}].runtime is invalid")
        if not isinstance(target, str) or not Path(target).is_absolute():
            raise OperationError(f"runtime_targets[{index}].target must be an explicit absolute directory")
        target_root = Path(target).resolve()
        if target_root == root or len(target_root.parts) < 3:
            raise OperationError("runtime target is too broad")
        package = target_root / skill_name
        if package.is_symlink():
            if package.resolve() != skill.resolve():
                raise OperationError("runtime target contains a divergent Skill symlink")
            plan.append((str(runtime), package, "linked"))
        elif package.is_dir():
            if package_hash(package) != base_hash:
                raise OperationError("runtime target contains a divergent Skill package")
            plan.append((str(runtime), package, "replace"))
        elif package.exists():
            raise OperationError("runtime target contains a non-package conflict")
        else:
            plan.append((str(runtime), package, "create"))
    return plan


def refresh_runtimes(
    skill: Path,
    plan: list[tuple[str, Path, str]],
    backup_root: Path,
    rollback: list[tuple[Path, Path | None]],
    affected: list[str],
) -> None:
    for index, (runtime, package, action) in enumerate(plan):
        if action == "linked":
            affected.append(f"runtime:{runtime}/{skill.name}")
            continue
        package.parent.mkdir(parents=True, exist_ok=True)
        backup: Path | None = None
        if action == "replace":
            backup = backup_root / str(index)
            shutil.copytree(package, backup, symlinks=True)
            remove_runtime_package(package)
        rollback.append((package, backup))
        if runtime == "openclaw":
            shutil.copytree(
                skill,
                package,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.pyo"),
            )
        else:
            package.symlink_to(skill, target_is_directory=True)
        affected.append(f"runtime:{runtime}/{skill.name}")


def rollback_runtimes(entries: list[tuple[Path, Path | None]]) -> None:
    for package, backup in reversed(entries):
        remove_runtime_package(package)
        if backup is not None:
            shutil.copytree(backup, package, symlinks=True)


def skill_apply(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path = proposal_path(root, payload.get("proposal_path"))
    before_proposal = path.read_text(encoding="utf-8")
    metadata = frontmatter(before_proposal)
    skill, target = target_skill(root, metadata)
    preview_value = payload.get("preview")
    if not isinstance(preview_value, dict):
        raise OperationError("preview must be the exact skill.preview result payload")
    preview = preview_value
    approved_hash = payload.get("approved_preview_hash")
    if not isinstance(approved_hash, str) or approved_hash != preview.get("preview_hash"):
        raise OperationError("approved preview hash does not match the supplied preview")
    if computed_preview_hash(preview) != approved_hash:
        raise OperationError("preview content does not match its hash")
    if f"Preview hash: `{approved_hash}`" not in before_proposal:
        raise OperationError("Proposal does not contain the approved Change Preview")
    if preview.get("proposal_path") != path.relative_to(root).as_posix():
        raise OperationError("preview belongs to a different Proposal")
    if preview.get("proposal_id") != metadata.get("proposal_id") or preview.get("target") != target:
        raise OperationError("preview does not match the Proposal target")

    files = safe_preview_files(skill, preview)
    proposed_hash = package_hash_with_changes(skill, files)
    if proposed_hash != preview.get("proposed_hash"):
        raise OperationError("preview proposed package hash is invalid")
    current_hash = package_hash(skill)
    status = metadata.get("status")
    if status == "applied":
        if current_hash != preview.get("proposed_hash"):
            raise OperationError("applied Proposal no longer matches the canonical Skill")
        return {
            "operation": "skill.apply",
            "operation_id": approved_hash[:20],
            "mode": "apply",
            "status": "noop",
            "target": target,
            "affected_paths": [],
            "validation": {"ok": True, "message": "approved preview is already applied"},
            "rollback": None,
        }
    if status not in {"pending", "accepted"}:
        raise OperationError("Proposal is not eligible for application")
    if current_hash != preview.get("base_hash"):
        raise OperationError("Personal Skill changed after preview; generate and approve a new preview")

    try:
        plan = runtime_plan(root, skill, current_hash, payload.get("runtime_targets", []))
    except OperationError as error:
        failure = approved_proposal(before_proposal, approved_hash, f"Application failed before mutation: {error}.")
        atomic_write(path, failure)
        return {
            "operation": "skill.apply",
            "operation_id": approved_hash[:20],
            "mode": "apply",
            "status": "failed",
            "target": target,
            "affected_paths": [path.relative_to(root).as_posix()],
            "validation": {"ok": False, "message": str(error)},
            "rollback": {"performed": False, "ok": True},
        }

    snapshots: dict[str, bytes | None] = {}
    for relative in files:
        target_path = skill.joinpath(*PurePosixPath(relative).parts)
        snapshots[relative] = target_path.read_bytes() if target_path.is_file() else None
    runtime_rollback: list[tuple[Path, Path | None]] = []
    runtime_affected: list[str] = []
    runtime_backup = tempfile.TemporaryDirectory()
    affected = [path.relative_to(root).as_posix()]
    affected.extend((skill / relative).relative_to(root).as_posix() for relative in sorted(files))
    try:
        for relative, content in files.items():
            target_path = skill.joinpath(*PurePosixPath(relative).parts)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(target_path, content)
        valid, message = validate_root(root)
        if not valid:
            raise OperationError(f"canonical Skill validation failed: {message}")
        refresh_runtimes(skill, plan, Path(runtime_backup.name), runtime_rollback, runtime_affected)
        affected.extend(runtime_affected)
        after_proposal = applied_proposal(before_proposal, approved_hash, len(plan))
        atomic_write(path, after_proposal)
        valid, message = validate_root(root)
        if not valid:
            raise OperationError(f"applied Proposal validation failed: {message}")
        return {
            "operation": "skill.apply",
            "operation_id": approved_hash[:20],
            "mode": "apply",
            "status": "applied",
            "target": target,
            "affected_paths": affected,
            "validation": {"ok": True, "message": message or "Skill and Kit validation passed"},
            "rollback": None,
        }
    except (OSError, OperationError) as error:
        rollback_runtimes(runtime_rollback)
        for relative, content in snapshots.items():
            target_path = skill.joinpath(*PurePosixPath(relative).parts)
            if content is None:
                target_path.unlink(missing_ok=True)
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                descriptor, temporary = tempfile.mkstemp(prefix=f".{target_path.name}.", dir=target_path.parent)
                try:
                    with os.fdopen(descriptor, "wb") as file:
                        file.write(content)
                    os.replace(temporary, target_path)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
        failure = approved_proposal(before_proposal, approved_hash, f"Application failed and rolled back: {error}.")
        atomic_write(path, failure)
        return {
            "operation": "skill.apply",
            "operation_id": approved_hash[:20],
            "mode": "apply",
            "status": "failed",
            "target": target,
            "affected_paths": affected,
            "validation": {"ok": False, "message": str(error)},
            "rollback": {"performed": True, "ok": True},
        }
    finally:
        runtime_backup.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("skill.preview", "skill.apply"))
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise OperationError("operation input must be a JSON object")
        root = args.root.resolve()
        if not (root / "System/Kit/check.py").is_file():
            raise OperationError("root is not an LBrain Kit")
        if args.operation == "skill.preview":
            result = skill_preview(root, payload)
        else:
            result = skill_apply(root, payload)
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
