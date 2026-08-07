#!/usr/bin/env python3
"""Create and preview portable Context Pack definitions."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


PACK_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MANAGED_PARTS = {"Candidates", "Repos"}
SECTION = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def load_check_helpers(root: Path):
    kit = root / "System/Kit"
    if str(kit) not in sys.path:
        sys.path.insert(0, str(kit))
    sys.dont_write_bytecode = True
    from check import frontmatter, links  # pylint: disable=import-outside-toplevel

    return frontmatter, links


@dataclass(frozen=True)
class Definition:
    path: Path
    metadata: dict[str, object]
    sections: dict[str, list[str]]

    @property
    def pack_id(self) -> str:
        return str(self.metadata.get("pack_id", ""))

    @property
    def visibility(self) -> str:
        return str(self.metadata.get("visibility", ""))


@dataclass
class Preview:
    direct: set[Path] = field(default_factory=set)
    dependencies: set[Path] = field(default_factory=set)
    excluded: set[Path] = field(default_factory=set)
    blocked: list[str] = field(default_factory=list)


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def parse_sections(text: str) -> dict[str, list[str]]:
    matches = list(SECTION.finditer(text))
    sections: dict[str, list[str]] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        entries = []
        for line in text[match.end():end].splitlines():
            item = re.match(r"^\s*-\s+(path|query):\s*(.+?)\s*$", line)
            if item:
                entries.append(f"{item.group(1)}:{item.group(2)}")
        sections[match.group(1).strip().casefold()] = entries
    return sections


def load_definition(path: Path, root: Path) -> Definition:
    resolved = path if path.is_absolute() else root / path
    resolved = resolved.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"definition does not exist inside LBrain: {path}")
    frontmatter, _ = load_check_helpers(root)
    text = resolved.read_text(encoding="utf-8")
    metadata = frontmatter(text)
    if metadata.get("type") != "context-pack":
        raise ValueError("definition type must be context-pack")
    pack_id = str(metadata.get("pack_id", ""))
    if not PACK_ID.fullmatch(pack_id):
        raise ValueError(f"invalid pack_id: {pack_id}")
    sections = parse_sections(text)
    missing = {"purpose", "includes", "excludes", "skills", "build notes"} - sections.keys()
    if missing:
        raise ValueError(f"definition missing sections: {', '.join(sorted(missing))}")
    return Definition(resolved, metadata, sections)


def selector_path(raw: str, root: Path) -> tuple[Path | None, str | None]:
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None, f"selector escapes LBrain root: {raw}"
    if len(candidate.parts) >= 3 and candidate.parts[:2] == ("Outputs", "Context-Packs") and candidate.parts[2] in MANAGED_PARTS:
        return None, f"selector enters managed Pack content: {raw}"
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        return None, f"selector escapes LBrain root: {raw}"
    if not resolved.exists():
        return None, f"selector does not exist: {raw}"
    if resolved.is_symlink() or any(parent.is_symlink() for parent in resolved.parents if parent != root.parent):
        if not resolved.resolve().is_relative_to(root):
            return None, f"selector follows external symlink: {raw}"
    return resolved, None


def selected_files(path: Path) -> set[Path]:
    if path.is_file():
        return {path}
    return {
        item for item in path.rglob("*")
        if item.is_file() and ".git" not in item.parts
    }


def query_values(raw: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in raw.split(","):
        if "=" not in item:
            raise ValueError(f"invalid metadata query: {raw}")
        key, value = (part.strip() for part in item.split("=", 1))
        if not key or not value:
            raise ValueError(f"invalid metadata query: {raw}")
        values[key] = value
    return values


def matches_query(metadata: dict[str, object], query: dict[str, str]) -> bool:
    for key, expected in query.items():
        actual = metadata.get(key)
        if isinstance(actual, list):
            if expected not in {str(item) for item in actual}:
                return False
        elif str(actual) != expected:
            return False
    return True


def source_markdown(root: Path) -> list[Path]:
    managed = root / "Outputs/Context-Packs"
    result = []
    for path in root.rglob("*.md"):
        if ".git" in path.parts or ".scratch" in path.parts:
            continue
        if path.is_relative_to(managed / "Candidates") or path.is_relative_to(managed / "Repos"):
            continue
        result.append(path)
    return sorted(result)


def resolve_definition(definition: Definition, root: Path) -> Preview:
    frontmatter, links = load_check_helpers(root)
    preview = Preview()
    markdown = source_markdown(root)

    for entry in definition.sections["includes"] + definition.sections["skills"]:
        kind, raw = entry.split(":", 1)
        if kind == "path":
            path, error = selector_path(raw, root)
            if error:
                preview.blocked.append(error)
            elif path:
                preview.direct.update(selected_files(path))
        else:
            try:
                query = query_values(raw)
            except ValueError as error:
                preview.blocked.append(str(error))
                continue
            preview.direct.update(
                path for path in markdown
                if matches_query(frontmatter(path.read_text(encoding="utf-8")), query)
            )

    excluded_candidates: set[Path] = set()
    for entry in definition.sections["excludes"]:
        kind, raw = entry.split(":", 1)
        if kind == "path":
            path, error = selector_path(raw, root)
            if error:
                preview.blocked.append(error)
            elif path:
                excluded_candidates.update(selected_files(path))
        else:
            try:
                query = query_values(raw)
            except ValueError as error:
                preview.blocked.append(str(error))
                continue
            excluded_candidates.update(
                path for path in markdown
                if matches_query(frontmatter(path.read_text(encoding="utf-8")), query)
            )
    preview.excluded = preview.direct & excluded_candidates
    preview.direct -= excluded_candidates

    by_path = {relative(path, root).removesuffix(".md").casefold(): path for path in markdown}
    by_stem: dict[str, list[Path]] = {}
    for path in markdown:
        by_stem.setdefault(path.stem.casefold(), []).append(path)

    queue = [path for path in preview.direct if path.suffix.casefold() == ".md"]
    visited = set(queue)
    while queue:
        source = queue.pop()
        for target in links(source.read_text(encoding="utf-8")):
            normalized = target.strip("/").removesuffix(".md")
            found = [by_path[normalized.casefold()]] if normalized.casefold() in by_path else by_stem.get(normalized.casefold(), [])
            if len(found) != 1:
                preview.blocked.append(f"unresolved or ambiguous dependency: {target}")
                continue
            dependency = found[0]
            if dependency in excluded_candidates:
                preview.blocked.append(f"required dependency excluded: {relative(dependency, root)}")
                continue
            if dependency not in preview.direct:
                preview.dependencies.add(dependency)
            if dependency not in visited:
                visited.add(dependency)
                queue.append(dependency)

    if definition.visibility == "public":
        for dependency in sorted(preview.dependencies):
            metadata = frontmatter(dependency.read_text(encoding="utf-8"))
            if metadata.get("visibility") in {"private", "trusted"}:
                preview.blocked.append(f"private dependency: {relative(dependency, root)}")
    return preview


def render_definition(pack_id: str, summary: str, visibility: str, audience: str | None, license_name: str | None) -> str:
    today = date.today().isoformat()
    conditional = ""
    if audience:
        conditional += f"audience:\n  - {audience}\n"
    if license_name:
        conditional += f"license: {license_name}\n"
    title = pack_id.replace("-", " ").title()
    return f"""---
type: context-pack
pack_id: {pack_id}
summary: {summary}
status: draft
visibility: {visibility}
{conditional}created: {today}
updated: {today}
---
# {title}

## Purpose

{summary}

## Includes

## Excludes

## Skills

## Build Notes
"""


def create(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    if not PACK_ID.fullmatch(args.pack_id):
        raise ValueError("pack_id must use lowercase letters, digits, and single hyphens")
    if args.visibility == "trusted" and not args.audience:
        raise ValueError("trusted Definition requires --audience")
    if args.visibility == "public" and not args.license:
        raise ValueError("public Definition requires --license")
    destination = root / "Outputs/Context-Packs" / f"{args.pack_id}.md"
    if destination.exists():
        raise ValueError(f"Definition already exists: {relative(destination, root)}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        render_definition(args.pack_id, args.summary, args.visibility, args.audience, args.license),
        encoding="utf-8",
    )
    print(f"CREATED {relative(destination, root)}")
    return 0


def preview(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    definition = load_definition(Path(args.definition), root)
    result = resolve_definition(definition, root)
    print(f"PACK {definition.pack_id}")
    for path in sorted(result.direct):
        print(f"DIRECT {relative(path, root)}")
    for path in sorted(result.dependencies):
        print(f"DEPENDENCY {relative(path, root)}")
    for path in sorted(result.excluded):
        print(f"EXCLUDED {relative(path, root)}")
    for message in sorted(set(result.blocked)):
        print(f"BLOCK {message}")
    print(
        f"SUMMARY direct={len(result.direct)} dependencies={len(result.dependencies)} "
        f"excluded={len(result.excluded)} blocked={len(set(result.blocked))}"
    )
    return 2 if result.blocked else 0


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[4])
    subcommands = command.add_subparsers(dest="operation", required=True)

    create_parser = subcommands.add_parser("create")
    create_parser.add_argument("pack_id")
    create_parser.add_argument("--summary", required=True)
    create_parser.add_argument("--visibility", choices=("private", "trusted", "public"), default="private")
    create_parser.add_argument("--audience")
    create_parser.add_argument("--license")
    create_parser.set_defaults(handler=create)

    preview_parser = subcommands.add_parser("preview")
    preview_parser.add_argument("definition")
    preview_parser.set_defaults(handler=preview)
    return command


def main() -> int:
    args = parser().parse_args()
    try:
        return args.handler(args)
    except (OSError, ValueError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
