#!/usr/bin/env python3
"""Read-only structural validator for an LBrain repository."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


BASE_FIELDS = {"type", "summary", "status", "visibility", "created", "updated"}
VISIBILITIES = {"private", "trusted", "public"}
CORE_SKILLS = {
    "lbrain-capture",
    "lbrain-weave",
    "lbrain-retrieve",
    "lbrain-review",
    "lbrain-write",
    "lbrain-skill-manager",
}
RUNTIMES = {"codex", "claude", "hermes"}
REQUIRED_DIRS = (
    "Inbox",
    "Knowledge",
    "Knowledge/Sources",
    "Knowledge/Wiki",
    "Knowledge/Wiki/Entities",
    "Knowledge/Wiki/Concepts",
    "Knowledge/Wiki/Analyses",
    "Knowledge/Wiki/Overviews",
    "Context",
    "Context/Identity",
    "Context/Areas",
    "Context/Projects",
    "Skills",
    "Skills/Kit",
    "Skills/Personal",
    "Outputs",
    "Outputs/Writing",
    "System",
    "System/Kit",
    "System/Rules",
    "System/Rules/Core",
    "System/Rules/Local",
    "System/Templates",
    "System/Templates/Core",
    "System/Proposals",
    "Archives",
    "Archives/Sources",
    "Archives/Wiki",
    "Archives/Context",
    "Archives/Skills",
    "Archives/Outputs",
)
CONTENT_PREFIXES = (
    "Inbox/",
    "Knowledge/Sources/",
    "Knowledge/Wiki/",
    "Context/Identity/",
    "Context/Areas/",
    "Context/Projects/",
    "Skills/Personal/",
    "Outputs/Writing/",
    "System/Rules/Local/",
    "System/Proposals/",
    "Archives/",
)
TYPE_FIELDS = {
    "source": {"origin", "capture", "weaving"},
    "knowledge": {"kind", "sources"},
    "identity": {"kind", "confirmed"},
    "project": {"outcome", "source_of_truth"},
    "writing": {"sources"},
    "proposal": {"target", "action"},
}
WIKILINK = re.compile(r"(?<!!)\[\[([^\]]+)\]\]")
RESOURCE = re.compile(r"\b((?:references|scripts|assets|examples|tests)/[A-Za-z0-9_./-]+)")
ENABLED = re.compile(r"^\s*-\s+\[\[([^\]]+/SKILL)\]\]\s+[—-]\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Finding:
    level: str
    path: str
    message: str


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def frontmatter(text: str) -> dict[str, object]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    data: dict[str, object] = {}
    current: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            return data
        item = re.match(r"^\s+-\s+(.+?)\s*$", line)
        if item and current:
            value = item.group(1).strip('"\'')
            existing = data.setdefault(current, [])
            if isinstance(existing, list):
                existing.append(value)
            continue
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*?)\s*$", line)
        if not match:
            continue
        current, value = match.groups()
        data[current] = value.strip('"\'') if value else []
    return {}


def without_code_fences(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def links(text: str) -> list[str]:
    result = []
    for raw in WIKILINK.findall(without_code_fences(text)):
        target = raw.split("|", 1)[0].split("#", 1)[0].strip()
        if target:
            result.append(target.removesuffix(".md"))
    return result


def is_content_note(relative: str) -> bool:
    if relative.endswith("/README.md") or relative == "README.md":
        return False
    if relative in {"HOME.md", "Knowledge/Wiki/Index.md", "Skills/Enabled.md"}:
        return True
    return relative.startswith(CONTENT_PREFIXES)


def resolve(target: str, by_path: dict[str, Path], by_stem: dict[str, list[Path]]) -> list[Path]:
    normalized = target.strip("/")
    if "/" in normalized:
        match = by_path.get(normalized.casefold())
        return [match] if match else []
    return by_stem.get(normalized.casefold(), [])


def git_value(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "config", "--get", *args],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def validate(root: Path) -> list[Finding]:
    root = root.resolve()
    findings: list[Finding] = []

    def add(level: str, path: str | Path, message: str) -> None:
        rendered = str(path.relative_to(root)) if isinstance(path, Path) and path.is_relative_to(root) else str(path)
        findings.append(Finding(level, rendered, message))

    for directory in REQUIRED_DIRS:
        path = root / directory
        if not path.is_dir():
            add("ERROR", directory, "required directory is missing")
        elif not (path / "README.md").is_file():
            add("ERROR", directory, "semantic directory is missing README.md")

    markdown = sorted(path for path in root.rglob("*.md") if ".git" not in path.parts)
    text_by_path: dict[Path, str] = {}
    meta_by_path: dict[Path, dict[str, object]] = {}
    by_path: dict[str, Path] = {}
    by_stem: dict[str, list[Path]] = {}

    for path in markdown:
        relative = path.relative_to(root).as_posix()
        text = read_text(path)
        meta = frontmatter(text)
        text_by_path[path] = text
        meta_by_path[path] = meta
        by_path[relative.removesuffix(".md").casefold()] = path
        by_stem.setdefault(path.stem.casefold(), []).append(path)

        if is_content_note(relative):
            missing = BASE_FIELDS - meta.keys()
            if missing:
                add("ERROR", path, f"missing frontmatter fields: {', '.join(sorted(missing))}")
            visibility = meta.get("visibility")
            if visibility and visibility not in VISIBILITIES:
                add("ERROR", path, f"invalid visibility: {visibility}")
            note_type = str(meta.get("type", ""))
            required = TYPE_FIELDS.get(note_type, set())
            missing_type = required - meta.keys()
            if missing_type:
                add("ERROR", path, f"{note_type} note missing fields: {', '.join(sorted(missing_type))}")
            if note_type == "source":
                if meta.get("capture") not in {"reference", "excerpt", "full"}:
                    add("ERROR", path, "source capture must be reference, excerpt, or full")
                if meta.get("weaving") not in {"pending", "woven", "skip"}:
                    add("ERROR", path, "source weaving must be pending, woven, or skip")
            if note_type == "knowledge" and meta.get("kind") not in {"entity", "concept", "analysis", "overview"}:
                add("ERROR", path, "knowledge kind must be entity, concept, analysis, or overview")
            if note_type == "identity" and meta.get("kind") not in {"profile", "state", "principle"}:
                add("ERROR", path, "identity kind must be profile, state, or principle")
            if note_type == "proposal" and meta.get("status") not in {"pending", "accepted", "applied", "rejected"}:
                add("ERROR", path, "proposal status has an invalid lifecycle state")

    for path, text in text_by_path.items():
        relative = path.relative_to(root).as_posix()
        if relative.startswith("System/Templates/Core/"):
            continue
        for target in links(text):
            matches = resolve(target, by_path, by_stem)
            if not matches:
                add("ERROR", path, f"unresolved Wikilink: [[{target}]]")
            elif len(matches) > 1:
                add("ERROR", path, f"ambiguous Wikilink: [[{target}]]; use a path")
            elif meta_by_path[path].get("visibility") == "public" and meta_by_path[matches[0]].get("visibility") in {"private", "trusted"}:
                add("ERROR", path, f"public note links non-public note: [[{target}]]")

    wiki_text = "\n".join(
        text for path, text in text_by_path.items()
        if path.relative_to(root).as_posix().startswith("Knowledge/Wiki/")
        and meta_by_path[path].get("type") == "knowledge"
    )
    for path, meta in meta_by_path.items():
        if meta.get("type") == "source" and meta.get("weaving") == "woven":
            source_relative = path.relative_to(root).as_posix().removesuffix(".md")
            if not any(target == source_relative or target == path.stem for target in links(wiki_text)):
                add("ERROR", path, "woven Source has no backlink from a knowledge note")

    core_root = root / "Skills/Kit"
    actual_core = {path.name for path in core_root.iterdir() if path.is_dir()} if core_root.is_dir() else set()
    for unexpected in sorted(actual_core - CORE_SKILLS):
        add("ERROR", f"Skills/Kit/{unexpected}", "unknown package in Kit-owned Core Skill path")
    for missing in sorted(CORE_SKILLS - actual_core):
        add("ERROR", f"Skills/Kit/{missing}", "required Core Skill is missing")

    skill_entries = sorted((root / "Skills").glob("*/*/SKILL.md")) if (root / "Skills").is_dir() else []
    skill_by_target: dict[str, tuple[Path, dict[str, object]]] = {}
    for skill in skill_entries:
        meta = frontmatter(read_text(skill))
        relative = skill.relative_to(root).as_posix().removesuffix(".md")
        skill_by_target[relative] = (skill, meta)
        missing = {"name", "description", "version", "status", "visibility", "created", "updated"} - meta.keys()
        if missing:
            add("ERROR", skill, f"skill manifest missing fields: {', '.join(sorted(missing))}")
        if meta.get("status") == "active" and not (skill.parent / "tests/cases.md").is_file():
            add("ERROR", skill, "active skill is missing tests/cases.md")
        for resource in RESOURCE.findall(read_text(skill)):
            candidate = resource.rstrip(".,;:)")
            if not (skill.parent / candidate).exists():
                add("ERROR", skill, f"referenced skill resource is missing: {candidate}")
        if "Skills/Personal/" in skill.relative_to(root).as_posix() and meta.get("visibility") == "public":
            if not any((skill.parent / name).is_file() for name in ("LICENSE", "LICENSE.md")):
                add("ERROR", skill, "public Personal Skill requires its own license")

    enabled_path = root / "Skills/Enabled.md"
    enabled_text = read_text(enabled_path) if enabled_path.is_file() else ""
    enabled_core: set[str] = set()
    for target, runtime_text in ENABLED.findall(enabled_text):
        skill = skill_by_target.get(target)
        if not skill:
            add("ERROR", enabled_path, f"enabled skill does not resolve: [[{target}]]")
            continue
        runtimes = {item.strip().casefold() for item in runtime_text.split(",")}
        unknown = runtimes - RUNTIMES
        if unknown:
            add("ERROR", enabled_path, f"unknown runtimes for [[{target}]]: {', '.join(sorted(unknown))}")
        name = str(skill[1].get("name", ""))
        if name in CORE_SKILLS:
            enabled_core.add(name)
    for missing in sorted(CORE_SKILLS - enabled_core):
        add("ERROR", enabled_path, f"required Core Skill is not enabled: {missing}")

    for path in root.rglob("*"):
        if path.is_symlink():
            target = Path(os.readlink(path))
            resolved = target if target.is_absolute() else (path.parent / target).resolve()
            if target.is_absolute() or not resolved.is_relative_to(root):
                add("ERROR", path, "symlink discloses or escapes the LBrain root")

    private_path = re.compile(r"(?:/Users/|/home/[^$<\s]+|[A-Za-z]:\\Users\\)")
    for path, text in text_by_path.items():
        relative = path.relative_to(root).as_posix()
        if ("<!-- ownership: kit -->" in text or meta_by_path[path].get("visibility") == "public") and private_path.search(text):
            add("ERROR", path, "Kit/public content contains an absolute private path")

    kit_url = git_value(root, "remote.kit.url")
    origin_url = git_value(root, "remote.origin.url")
    if kit_url:
        push_url = git_value(root, "remote.kit.pushurl")
        if push_url != "DISABLED":
            add("ERROR", ".git/config", "kit push URL must be explicitly DISABLED")
        if origin_url and origin_url == kit_url:
            add("ERROR", ".git/config", "origin and kit point to the same remote")
        if git_value(root, "branch.main.remote") == "kit":
            add("ERROR", ".git/config", "personal main must not track the public kit remote")
    else:
        add("WARN", ".git/config", "kit remote is not configured; expected in an initialized personal LBrain")
    if not origin_url:
        add("WARN", ".git/config", "private origin is not configured; local-only mode has no off-device backup")

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    findings = validate(args.root)
    errors = [finding for finding in findings if finding.level == "ERROR"]
    if not args.quiet:
        for finding in findings:
            print(f"{finding.level} {finding.path}: {finding.message}")
        print(f"LBrain check: {len(errors)} error(s), {len(findings) - len(errors)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
