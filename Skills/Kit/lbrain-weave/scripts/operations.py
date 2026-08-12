#!/usr/bin/env python3
"""Deterministic proposal operations used by the LBrain Weave Skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Iterator


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


def required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise OperationError(f"{key} must be non-empty text")
    return value.strip()


def yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def validate(root: Path) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, str(root / "System/Kit/check.py"), "--root", str(root), "--quiet"],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def atomic_unlink(root: Path, path: Path, expected: str) -> None:
    try:
        load_kit_helper(root, "file_transaction", "atomic_unlink")(root, path, expected)
    except ValueError as error:
        raise OperationError(str(error)) from error


def safe_note_path(value: object, prefix: tuple[str, str], field: str) -> PurePosixPath:
    if not isinstance(value, str):
        raise OperationError(f"{field} must be text")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.parts[:2] != prefix or path.suffix != ".md":
        raise OperationError(f"{field} must be a Markdown file inside {'/'.join(prefix)}")
    return path


def note_frontmatter(value: str) -> tuple[list[str], str]:
    if not value.startswith("---\n"):
        raise OperationError("note is missing frontmatter")
    end = value.find("\n---\n", 4)
    if end < 0:
        raise OperationError("note frontmatter is incomplete")
    return value[4:end].splitlines(), value[end + 5 :]


def metadata_value(lines: list[str], key: str) -> str:
    marker = f"{key}:"
    for line in lines:
        if line.startswith(marker):
            value = line.split(":", 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                try:
                    loaded = json.loads(value)
                    return loaded if isinstance(loaded, str) else value
                except json.JSONDecodeError:
                    pass
            return value
    return ""


def update_note_metadata(content: str, updates: dict[str, str]) -> str:
    lines, body = note_frontmatter(content)
    remaining = dict(updates)
    for index, line in enumerate(lines):
        key = line.split(":", 1)[0] if ":" in line else ""
        if key in remaining:
            lines[index] = f"{key}: {remaining.pop(key)}"
    lines.extend(f"{key}: {value}" for key, value in remaining.items())
    return "---\n" + "\n".join(lines) + "\n---\n" + body


def promoted_bundle(content: str, inbox: PurePosixPath, destination: PurePosixPath, outcome: str, reason: str) -> str:
    lines, _ = note_frontmatter(content)
    capture_id = metadata_value(lines, "capture_id")
    version = metadata_value(lines, "capture_version")
    if not capture_id or not version:
        raise OperationError("Inbox Capture is missing its Bundle identity")
    manifest = (destination.parent / "_assets" / capture_id / f"v{version}" / "manifest.json").as_posix()
    updates = {
        "type": "source",
        "status": "archived" if outcome == "rejected" else "active",
        "capture": "full",
        "weaving": "woven" if outcome == "woven" else "skip",
        "media_manifest": yaml_string(manifest),
        "capture_inbox": yaml_string(inbox.as_posix()),
        "updated": date.today().isoformat(),
    }
    if reason:
        updates["rejection_reason"] = yaml_string(reason)
    rendered = update_note_metadata(content, updates)
    decision = "woven into Wiki" if outcome == "woven" else (reason if outcome == "rejected" else "retained as Source without synthesis")
    return rendered.rstrip() + f"\n\n## Weave decision\n\n- Outcome: {outcome}\n- Decision: {decision}\n"


def weave_request(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bundles = payload.get("bundles")
    wiki = payload.get("wiki", [])
    if not isinstance(bundles, list) or not bundles or not all(isinstance(item, dict) for item in bundles):
        raise OperationError("bundles must contain at least one Capture decision")
    if not isinstance(wiki, list) or not all(isinstance(item, dict) for item in wiki):
        raise OperationError("wiki must be a list of knowledge changes")
    return bundles, wiki


def weave_preview(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    bundles, wiki = weave_request(payload)
    secret_check = load_kit_helper(root, "disclosure", "contains_document_secret")
    runtime_check = load_kit_helper(root, "disclosure", "contains_document_runtime_state")
    conflicts: list[str] = []
    planned_bundles: list[dict[str, Any]] = []
    source_links: list[str] = []
    seen_paths: set[str] = set()
    seen_destinations: set[str] = set()

    for raw in bundles:
        inbox = safe_note_path(raw.get("path"), ("Inbox", "Captures"), "bundle path")
        if inbox.as_posix() in seen_paths:
            raise OperationError("each Capture Bundle may appear only once")
        seen_paths.add(inbox.as_posix())
        outcome = raw.get("outcome")
        if outcome not in {"woven", "skip", "pending", "deferred", "rejected"}:
            raise OperationError("bundle outcome must be woven, skip, pending, deferred, or rejected")
        reason = raw.get("reason", "")
        if not isinstance(reason, str):
            raise OperationError("bundle reason must be text")
        if outcome == "rejected" and not reason.strip():
            raise OperationError("rejected Capture requires a reason")
        if secret_check(reason) or runtime_check(reason):
            raise OperationError("Weave decision contains possible credentials or runtime state")

        if outcome in {"woven", "skip"}:
            destination = safe_note_path(raw.get("source_path"), ("Knowledge", "Sources"), "source_path")
            if outcome == "woven":
                source_links.append(destination.as_posix().removesuffix(".md"))
        elif outcome == "rejected":
            destination = PurePosixPath("Archives/Sources") / inbox.name
        else:
            destination = inbox
        if outcome not in {"pending", "deferred"}:
            if destination.as_posix() in seen_destinations:
                conflicts.append(f"{destination}: destination is selected more than once")
            seen_destinations.add(destination.as_posix())

        source = root.joinpath(*inbox.parts)
        target = root.joinpath(*destination.parts)
        assert_safe_target(root, source)
        assert_safe_target(root, target)
        if source.is_file():
            content = source.read_text(encoding="utf-8")
            lines, _ = note_frontmatter(content)
            if metadata_value(lines, "weaving") != "pending":
                conflicts.append(f"{inbox}: Capture is not pending")
            action = "keep" if outcome in {"pending", "deferred"} else ("archive" if outcome == "rejected" else "promote")
            if action != "keep" and target.exists():
                conflicts.append(f"{destination}: destination already exists")
            planned_bundles.append(
                {
                    "path": inbox.as_posix(),
                    "outcome": outcome,
                    "action": action,
                    "destination": destination.as_posix(),
                    "before_hash": digest(content),
                    "reason": reason.strip(),
                }
            )
            continue

        if target.is_file() and outcome not in {"pending", "deferred"}:
            target_content = target.read_text(encoding="utf-8")
            lines, _ = note_frontmatter(target_content)
            expected_weaving = "woven" if outcome == "woven" else "skip"
            if metadata_value(lines, "capture_inbox") == inbox.as_posix() and metadata_value(lines, "weaving") == expected_weaving:
                planned_bundles.append(
                    {
                        "path": inbox.as_posix(),
                        "outcome": outcome,
                        "action": "keep",
                        "destination": destination.as_posix(),
                        "before_hash": digest(target_content),
                        "reason": reason.strip(),
                    }
                )
                continue
        conflicts.append(f"{inbox}: Capture Bundle is missing")
        planned_bundles.append(
            {"path": inbox.as_posix(), "outcome": outcome, "action": "conflict", "destination": destination.as_posix(), "reason": reason.strip()}
        )

    planned_wiki: list[dict[str, Any]] = []
    seen_wiki: set[str] = set()
    wiki_text = "\n".join(str(item.get("content", "")) for item in wiki)
    for source_link in source_links:
        if f"[[{source_link}]]" not in wiki_text:
            conflicts.append(f"{source_link}: woven Source is not referenced by a Wiki change")
    for raw in wiki:
        path = safe_note_path(raw.get("path"), ("Knowledge", "Wiki"), "Wiki path")
        if path.as_posix() in seen_wiki:
            raise OperationError("each Wiki target may appear only once")
        seen_wiki.add(path.as_posix())
        content = raw.get("content")
        if not isinstance(content, str) or "type: knowledge" not in content:
            raise OperationError("Wiki content must be a complete knowledge note")
        if secret_check(content) or runtime_check(content):
            raise OperationError("Wiki change contains possible credentials or runtime state")
        target = root.joinpath(*path.parts)
        before = target.read_text(encoding="utf-8") if target.is_file() else None
        action = "keep" if before == content else ("update" if before is not None else "create")
        planned_wiki.append(
            {
                "path": path.as_posix(),
                "action": action,
                "before_hash": digest(before) if before is not None else None,
                "after_hash": digest(content),
            }
        )

    plan_value = {"bundles": planned_bundles, "wiki": planned_wiki}
    plan_hash = digest(json.dumps(plan_value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    mutates = any(item["action"] in {"promote", "archive"} for item in planned_bundles) or any(
        item["action"] in {"create", "update"} for item in planned_wiki
    )
    return {
        "operation": "weave.preview",
        "operation_id": plan_hash[:20],
        "mode": "preview",
        "status": "conflict" if conflicts else ("preview" if mutates else "noop"),
        "plan_hash": plan_hash,
        "bundles": planned_bundles,
        "wiki": planned_wiki,
        "conflicts": conflicts,
        "skill_improvement": "review_after_success",
        "affected_paths": [],
        "validation": {"ok": not conflicts, "message": "Weave plan is ready" if not conflicts else "Weave plan has conflicts"},
        "rollback": None,
    }


def weave_git_commit(root: Path, paths: list[str], count: int) -> dict[str, Any]:
    commit_paths = load_kit_helper(root, "git_commit", "commit_paths")
    result = commit_paths(
        root, paths, f"weave: process {count} Capture Bundle{'s' if count != 1 else ''}"
    )
    if result["committed"]:
        return result
    return {"committed": False, "warning": f"Weave applied; {result['reason']}"}


def weave_apply(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    preview = weave_preview(root, payload)
    requested_hash = payload.get("plan_hash")
    if requested_hash != preview["plan_hash"]:
        raise OperationError("Weave plan changed; preview the current transaction before apply")
    if preview["conflicts"]:
        raise OperationError("Weave plan has conflicts")
    if preview["status"] == "noop":
        return {
            **preview,
            "operation": "weave.apply",
            "mode": "apply",
            "status": "noop",
            "git": {"committed": False, "warning": None},
            "skill_improvement": "review_after_success",
        }

    bundles, wiki = weave_request(payload)
    bundle_input = {str(item["path"]): item for item in bundles}
    wiki_input = {str(item["path"]): item for item in wiki}
    bundle_records: list[dict[str, Any]] = []
    wiki_records: list[dict[str, Any]] = []
    affected: list[str] = []
    try:
        for plan in preview["bundles"]:
            if plan["action"] not in {"promote", "archive"}:
                continue
            source_relative = PurePosixPath(plan["path"])
            destination_relative = PurePosixPath(plan["destination"])
            source = root.joinpath(*source_relative.parts)
            destination = root.joinpath(*destination_relative.parts)
            original = source.read_text(encoding="utf-8")
            if digest(original) != plan["before_hash"]:
                raise OperationError("Capture Bundle changed after preview")
            lines, _ = note_frontmatter(original)
            capture_id = metadata_value(lines, "capture_id")
            version = metadata_value(lines, "capture_version")
            asset_source_relative = source_relative.parent / "_assets" / capture_id / f"v{version}"
            asset_destination_relative = destination_relative.parent / "_assets" / capture_id / f"v{version}"
            asset_source = root.joinpath(*asset_source_relative.parts)
            asset_destination = root.joinpath(*asset_destination_relative.parts)
            assert_safe_target(root, asset_source / "manifest.json")
            assert_safe_target(root, asset_destination / "manifest.json")
            if not asset_source.is_dir() or asset_destination.exists():
                raise OperationError("Capture Bundle assets changed after preview")
            raw = bundle_input[source_relative.as_posix()]
            rendered = promoted_bundle(
                original,
                source_relative,
                destination_relative,
                str(plan["outcome"]),
                str(raw.get("reason", "")).strip(),
            )
            record = {
                "source": source,
                "source_relative": source_relative,
                "destination": destination,
                "destination_relative": destination_relative,
                "original": original,
                "rendered": rendered,
                "asset_source": asset_source,
                "asset_source_relative": asset_source_relative,
                "asset_destination": asset_destination,
                "asset_destination_relative": asset_destination_relative,
                "destination_written": False,
                "assets_moved": False,
                "source_removed": False,
            }
            bundle_records.append(record)
            atomic_write(root, destination, rendered, None)
            record["destination_written"] = True
            assert_safe_target(root, asset_destination / "manifest.json")
            asset_destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(asset_source, asset_destination)
            record["assets_moved"] = True
            atomic_unlink(root, source, original)
            record["source_removed"] = True
            affected.extend(
                [
                    source_relative.as_posix(),
                    destination_relative.as_posix(),
                    asset_source_relative.as_posix(),
                    asset_destination_relative.as_posix(),
                ]
            )

        for plan in preview["wiki"]:
            if plan["action"] == "keep":
                continue
            relative = PurePosixPath(plan["path"])
            path = root.joinpath(*relative.parts)
            before = path.read_text(encoding="utf-8") if path.is_file() else None
            if (digest(before) if before is not None else None) != plan["before_hash"]:
                raise OperationError("Wiki note changed after preview")
            content = str(wiki_input[relative.as_posix()]["content"])
            record = {"path": path, "relative": relative, "before": before, "after": content, "written": False}
            wiki_records.append(record)
            atomic_write(root, path, content, before)
            record["written"] = True
            affected.append(relative.as_posix())

        valid, message = validate(root)
        if not valid:
            raise OperationError(message or "Weave transaction failed Kit validation")
    except Exception as error:
        rollback_ok = True
        for record in reversed(wiki_records):
            if not record["written"]:
                continue
            try:
                if record["before"] is None:
                    atomic_unlink(root, record["path"], record["after"])
                else:
                    atomic_write(root, record["path"], record["before"], record["after"])
            except (OSError, OperationError):
                rollback_ok = False
        for record in reversed(bundle_records):
            if record["source_removed"]:
                try:
                    atomic_write(root, record["source"], record["original"], None)
                except (OSError, OperationError):
                    rollback_ok = False
            if record["assets_moved"]:
                try:
                    record["asset_source"].parent.mkdir(parents=True, exist_ok=True)
                    os.replace(record["asset_destination"], record["asset_source"])
                except OSError:
                    rollback_ok = False
            if record["destination_written"]:
                try:
                    atomic_unlink(root, record["destination"], record["rendered"])
                except (OSError, OperationError):
                    rollback_ok = False
        return {
            "operation": "weave.apply",
            "operation_id": str(preview["operation_id"]),
            "mode": "apply",
            "status": "failed",
            "target": "",
            "error": str(error),
            "affected_paths": [],
            "validation": {"ok": False, "message": "Weave transaction rejected"},
            "rollback": {"performed": True, "ok": rollback_ok},
            "git": {"committed": False, "warning": None},
            "skill_improvement": "not_run",
        }

    affected = list(dict.fromkeys(affected))
    processed = sum(item["action"] in {"promote", "archive"} for item in preview["bundles"])
    git = weave_git_commit(root, affected, processed)
    return {
        "operation": "weave.apply",
        "operation_id": str(preview["operation_id"]),
        "mode": "apply",
        "status": "applied",
        "target": "",
        "affected_paths": affected,
        "bundles": preview["bundles"],
        "wiki": preview["wiki"],
        "validation": {"ok": True, "message": message or "Kit validation passed"},
        "rollback": None,
        "git": git,
        "skill_improvement": "review_after_success",
    }


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
    secret_check = load_kit_helper(root, "disclosure", "contains_document_secret")
    runtime_state_check = load_kit_helper(root, "disclosure", "contains_document_runtime_state")
    if secret_check(content) or runtime_state_check(content):
        raise OperationError("Proposal contains possible credentials or runtime state; remove or redact them")
    atomic_write(root, path, content, None)
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
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current != content:
            raise OperationError("target changed during operation")
        path.unlink()
        result["rollback"] = {"performed": True, "ok": True}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("weave.preview", "weave.apply", "proposal.create"))
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
        contains_key = load_kit_helper(root, "disclosure", "contains_key")
        if contains_key(payload, {"cursor", "raw_cursor"}):
            raise OperationError("raw connector cursors must stay outside LBrain")
        with operation_lock(root):
            if args.operation == "weave.preview":
                result = weave_preview(root, payload)
            elif args.operation == "weave.apply":
                result = weave_apply(root, payload)
            else:
                result = proposal_create(root, payload)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["status"] != "failed" else 1
    except (OSError, json.JSONDecodeError, OperationError) as error:
        target = ""
        if root is not None and args.operation == "proposal.create":
            try:
                skill, _ = enabled_personal_skill(root, payload.get("skill_name"))
                target = skill.name
            except OperationError:
                pass
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
