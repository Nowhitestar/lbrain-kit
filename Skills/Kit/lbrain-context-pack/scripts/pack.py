#!/usr/bin/env python3
"""Create and preview portable Context Pack definitions."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


PACK_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MANAGED_PARTS = {"Candidates", "Repos"}
SECTION = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
SECRET = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|secret|password|private[_-]?key)\b"
    r"\s*[:=]\s*[^\s'\"`]{8,}"
)
ABSOLUTE_PRIVATE_PATH = re.compile(r"(?:/Users/|/home/[^$<\s]+|[A-Za-z]:\\Users\\)")
PRIVATE_URL = re.compile(r"https?://[^\s)\]]*(?:localhost|127\.0\.0\.1|\.internal\b|[?&](?:token|key|secret)=)", re.IGNORECASE)
SENSITIVE_NAMES = {".env", "credentials", "credentials.json", "secrets", "secrets.json"}


def load_check_helpers(root: Path):
    kit = root / "System/Kit"
    if str(kit) not in sys.path:
        sys.path.insert(0, str(kit))
    sys.dont_write_bytecode = True
    from check import RESOURCE, frontmatter, links  # pylint: disable=import-outside-toplevel

    return frontmatter, links, RESOURCE


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
    frontmatter, _, _ = load_check_helpers(root)
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
    frontmatter, links, resource_pattern = load_check_helpers(root)
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
        if source.name == "SKILL.md":
            for resource in resource_pattern.findall(source.read_text(encoding="utf-8")):
                dependency = source.parent / resource.rstrip(".,;:")
                if not dependency.is_file():
                    preview.blocked.append(f"missing Skill resource: {relative(dependency, root)}")
                    continue
                if dependency not in preview.direct:
                    preview.dependencies.add(dependency)

    selected = preview.direct | preview.dependencies
    personal_packages = {
        root.joinpath(*path.relative_to(root).parts[:3])
        for path in selected
        if len(path.relative_to(root).parts) >= 3
        and path.relative_to(root).parts[:2] == ("Skills", "Personal")
    }
    for package in sorted(personal_packages):
        license_path = next((package / name for name in ("LICENSE", "LICENSE.md") if (package / name).is_file()), None)
        if license_path:
            if license_path not in preview.direct:
                preview.dependencies.add(license_path)
        elif definition.visibility == "public":
            preview.blocked.append(f"public Personal Skill missing license: {relative(package, root)}")

    if definition.visibility == "public":
        if not definition.metadata.get("license"):
            preview.blocked.append("public Definition missing license")
        for dependency in sorted(preview.dependencies):
            metadata = frontmatter(dependency.read_text(encoding="utf-8"))
            if metadata.get("visibility") in {"private", "trusted"}:
                preview.blocked.append(f"private dependency: {relative(dependency, root)}")
        for path in sorted(preview.direct | preview.dependencies):
            rendered = relative(path, root)
            if path.is_symlink():
                preview.blocked.append(f"unsafe symlink: {rendered}")
                continue
            if path.name.casefold() in SENSITIVE_NAMES:
                preview.blocked.append(f"sensitive file name: {rendered}")
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            metadata = frontmatter(text) if path.suffix.casefold() == ".md" else {}
            if metadata.get("visibility") in {"private", "trusted"}:
                preview.blocked.append(f"non-public selected content: {rendered}")
            if SECRET.search(text):
                preview.blocked.append(f"possible secret in {rendered}")
            if ABSOLUTE_PRIVATE_PATH.search(text):
                preview.blocked.append(f"absolute private path in {rendered}")
            if PRIVATE_URL.search(text):
                preview.blocked.append(f"private URL in {rendered}")
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
    if result.blocked:
        print("RESOLVE sanitize, omit, or cancel")
    destination = str(definition.metadata.get("repository") or "unconfigured")
    print(
        f"DISCLOSURE visibility={definition.visibility} "
        f"license={definition.metadata.get('license') or 'missing'} destination={destination}"
    )
    print("REVIEW semantic content and license compatibility before publication")
    print(
        f"SUMMARY direct={len(result.direct)} dependencies={len(result.dependencies)} "
        f"excluded={len(result.excluded)} blocked={len(set(result.blocked))}"
    )
    return 2 if result.blocked else 0


def destination_for(source: Path, root: Path) -> Path:
    source_relative = source.relative_to(root)
    parts = source_relative.parts
    if len(parts) >= 4 and parts[0] == "Skills" and parts[1] in {"Kit", "Personal"}:
        package_root = root.joinpath(*parts[:3])
        return Path("skills") / parts[2] / source.relative_to(package_root)
    if source.suffix.casefold() != ".md":
        return Path("artifacts") / source.name
    frontmatter, _, _ = load_check_helpers(root)
    note_type = str(frontmatter(source.read_text(encoding="utf-8")).get("type", ""))
    if note_type in {"knowledge", "source"}:
        return Path("knowledge") / source.name
    if note_type in {"identity", "project", "area", "proposal", "note"}:
        return Path("context") / source.name
    return Path("artifacts") / source.name


def selected_markdown_index(paths: set[Path], root: Path) -> tuple[dict[str, Path], dict[str, list[Path]]]:
    markdown = [path for path in paths if path.suffix.casefold() == ".md"]
    by_path = {relative(path, root).removesuffix(".md").casefold(): path for path in markdown}
    by_stem: dict[str, list[Path]] = {}
    for path in markdown:
        by_stem.setdefault(path.stem.casefold(), []).append(path)
    return by_path, by_stem


def rewrite_wikilinks(text: str, source: Path, destinations: dict[Path, Path], root: Path) -> str:
    pattern = re.compile(r"(?<!!)\[\[([^\]]+)\]\]")
    by_path, by_stem = selected_markdown_index(set(destinations), root)

    def replace(match: re.Match[str]) -> str:
        raw = match.group(1)
        target_with_anchor, separator, label = raw.partition("|")
        target, anchor_separator, anchor = target_with_anchor.partition("#")
        normalized = target.strip("/").removesuffix(".md").casefold()
        matches = [by_path[normalized]] if normalized in by_path else by_stem.get(normalized, [])
        if len(matches) != 1:
            return match.group(0)
        destination = destinations[matches[0]]
        current = destinations[source].parent
        link = Path(os.path.relpath(destination, current)).as_posix()
        if anchor_separator:
            link += f"#{anchor}"
        rendered_label = label if separator else (anchor or matches[0].stem)
        return f"[{rendered_label}]({link})"

    return pattern.sub(replace, text)


def next_version(definition: Definition, root: Path) -> str:
    prefix = date.today().isoformat().replace("-", ".")
    submodule_path = str(definition.metadata.get("submodule_path") or "")
    if not submodule_path or not (root / submodule_path).is_dir():
        return f"{prefix}.1"
    result = subprocess.run(
        ["git", "-C", str(root / submodule_path), "tag", "--list", f"{prefix}.*"],
        text=True,
        capture_output=True,
        check=False,
    )
    numbers = []
    if result.returncode == 0:
        for tag in result.stdout.splitlines():
            suffix = tag.removeprefix(f"{prefix}.")
            if suffix.isdigit():
                numbers.append(int(suffix))
    return f"{prefix}.{max(numbers, default=0) + 1}"


def manifest(
    definition: Definition,
    destinations: dict[Path, Path],
    version: str,
    release_status: str,
) -> str:
    today = date.today().isoformat()
    summary = str(definition.metadata.get("summary", ""))
    license_name = str(definition.metadata.get("license", "UNLICENSED"))
    audience = definition.metadata.get("audience")
    audience_line = f"audience: {audience}\n" if audience else ""
    inventory = "\n".join(
        f"- [{path.as_posix()}]({path.as_posix()})"
        for path in sorted(destinations.values())
    ) or "- No selected content."
    return f"""---
type: context-pack-release
pack_id: {definition.pack_id}
summary: {summary}
version: {version}
release_status: {release_status}
visibility: {definition.visibility}
{audience_line}license: {license_name}
created: {today}
updated: {today}
---
# {definition.pack_id.replace('-', ' ').title()}

{summary}

## Loading Order

1. Read this manifest and its limitations.
2. Load only the relevant files from `context/` and `knowledge/`.
3. Load a package under `skills/` only when its behavior is needed.
4. Open `artifacts/` only when referenced by the task.

## Contents

{inventory}

## Limitations

- This Pack is a compiled snapshot, not its source LBrain.
- Verify changing external facts before relying on dated context.
"""


def sources_document(paths: set[Path], root: Path) -> str:
    frontmatter, _, _ = load_check_helpers(root)
    entries = []
    for path in sorted(paths):
        if path.suffix.casefold() == ".md":
            metadata = frontmatter(path.read_text(encoding="utf-8"))
            label = str(metadata.get("summary") or path.stem)
        else:
            label = path.name
        entries.append(f"- {label}")
    return "# Sources\n\nSafe provenance summary for this compiled Pack.\n\n" + "\n".join(entries) + "\n"


def write_candidate(
    definition: Definition,
    selection: Preview,
    root: Path,
    candidate: Path,
    version: str,
    release_status: str = "candidate",
) -> int:
    selected = selection.direct | selection.dependencies
    destinations: dict[Path, Path] = {}
    occupied: dict[Path, Path] = {}
    for source in sorted(selected):
        destination = destination_for(source, root)
        if destination in occupied and occupied[destination] != source:
            raise ValueError(
                f"compiled path collision: {relative(occupied[destination], root)} and "
                f"{relative(source, root)} -> {destination.as_posix()}"
            )
        occupied[destination] = source
        destinations[source] = destination

    if candidate.exists():
        shutil.rmtree(candidate)
    candidate.mkdir(parents=True)
    for source, destination in sorted(destinations.items(), key=lambda item: item[1].as_posix()):
        target = candidate / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.casefold() == ".md":
            target.write_text(
                rewrite_wikilinks(source.read_text(encoding="utf-8"), source, destinations, root),
                encoding="utf-8",
            )
        else:
            shutil.copy2(source, target)
    (candidate / "PACK.md").write_text(
        manifest(definition, destinations, version, release_status),
        encoding="utf-8",
    )
    (candidate / "SOURCES.md").write_text(sources_document(selected, root), encoding="utf-8")
    return len(destinations) + 2


def build(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    definition = load_definition(Path(args.definition), root)
    selection = resolve_definition(definition, root)
    if selection.blocked:
        raise ValueError("preview blocked: " + "; ".join(sorted(set(selection.blocked))))
    candidate = root / "Outputs/Context-Packs/Candidates" / definition.pack_id
    version = next_version(definition, root)
    file_count = write_candidate(definition, selection, root, candidate, version)
    print(f"BUILT {relative(candidate, root)}")
    print(f"SUMMARY files={file_count} version={version} status=candidate")
    return 0


def git(repository: Path, *arguments: str, file_transport: bool = False) -> str:
    command = ["git"]
    if file_transport:
        command.extend(["-c", "protocol.file.allow=always"])
    command.extend(["-C", str(repository), *arguments])
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        message = (result.stderr or result.stdout).strip()
        raise ValueError(f"git {' '.join(arguments)} failed: {message}")
    return result.stdout.strip()


def tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.parts
    }


def comparable_snapshot(root: Path) -> dict[str, bytes]:
    snapshot = tree_snapshot(root)
    manifest_bytes = snapshot.get("PACK.md")
    if manifest_bytes is not None:
        manifest_text = manifest_bytes.decode("utf-8")
        manifest_text = re.sub(r"^version: .+$", "version: <release>", manifest_text, flags=re.MULTILINE)
        manifest_text = re.sub(
            r"^release_status: .+$",
            "release_status: <release>",
            manifest_text,
            flags=re.MULTILINE,
        )
        snapshot["PACK.md"] = manifest_text.encode("utf-8")
    return snapshot


def yaml_scalar(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z0-9_./:@+\-]+", value) else json.dumps(value)


def update_definition_registration(definition: Definition, root: Path, remote: str, submodule_path: str) -> None:
    text = definition.path.read_text(encoding="utf-8")
    lines = text.splitlines()
    try:
        end = lines[1:].index("---") + 1
    except ValueError as error:
        raise ValueError("Definition frontmatter is not closed") from error
    fields = {
        "status": "active",
        "repository": remote,
        "submodule_path": submodule_path,
        "updated": date.today().isoformat(),
    }
    seen: set[str] = set()
    for index in range(1, end):
        match = re.match(r"^([A-Za-z0-9_-]+):", lines[index])
        if match and match.group(1) in fields:
            key = match.group(1)
            lines[index] = f"{key}: {yaml_scalar(fields[key])}"
            seen.add(key)
    insert_at = end
    for key in ("repository", "submodule_path"):
        if key not in seen:
            lines.insert(insert_at, f"{key}: {yaml_scalar(fields[key])}")
            insert_at += 1
    definition.path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_publishable_parent(root: Path) -> None:
    try:
        top = Path(git(root, "rev-parse", "--show-toplevel")).resolve()
    except ValueError as error:
        raise ValueError("publication requires an initialized parent LBrain Git repository") from error
    if top != root:
        raise ValueError("--root must be the parent LBrain Git repository root")
    dirty = git(root, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise ValueError("parent LBrain Git working tree must be clean before publication")


def validate_remote(remote: str) -> None:
    if re.search(r"://[^/@\s]+:[^/@\s]+@", remote):
        raise ValueError("remote URL must not contain embedded credentials")


def create_github_repository(repository: str, visibility: str) -> str:
    access = "--public" if visibility == "public" else "--private"
    created = subprocess.run(
        ["gh", "repo", "create", repository, access],
        text=True,
        capture_output=True,
        check=False,
    )
    if created.returncode:
        raise ValueError(f"GitHub repository creation failed: {(created.stderr or created.stdout).strip()}")
    viewed = subprocess.run(
        ["gh", "repo", "view", repository, "--json", "sshUrl", "--jq", ".sshUrl"],
        text=True,
        capture_output=True,
        check=False,
    )
    if viewed.returncode or not viewed.stdout.strip():
        raise ValueError(
            "GitHub repository was created but its Git URL could not be read; preserve it and attach the remote manually"
        )
    remote = viewed.stdout.strip()
    validate_remote(remote)
    return remote


def publish(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    definition = load_definition(Path(args.definition), root)
    selection = resolve_definition(definition, root)
    if selection.blocked:
        raise ValueError("preview blocked: " + "; ".join(sorted(set(selection.blocked))))
    candidate = root / "Outputs/Context-Packs/Candidates" / definition.pack_id
    if not (candidate / "PACK.md").is_file():
        raise ValueError("Candidate is missing; run build before publication")
    candidate_meta, _, _ = load_check_helpers(root)
    pack_metadata = candidate_meta((candidate / "PACK.md").read_text(encoding="utf-8"))
    version = str(pack_metadata.get("version", ""))
    if pack_metadata.get("release_status") != "candidate" or not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}\.\d+", version):
        raise ValueError("Candidate manifest has invalid version or release_status")
    registered_remote = str(definition.metadata.get("repository") or "")
    github_repository = getattr(args, "github_repository", None)
    if github_repository and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", github_repository):
        raise ValueError("--github-repository must be owner/name")
    if github_repository and (args.remote or registered_remote):
        raise ValueError("GitHub repository creation is only for a new Pack without another remote")
    remote = args.remote or registered_remote
    github_pending = bool(github_repository and not remote)
    if not remote and not github_pending:
        raise ValueError("publication requires --remote or --github-repository for a new Pack")
    if remote:
        validate_remote(remote)
    if registered_remote and remote != registered_remote:
        raise ValueError("--remote does not match the registered Pack repository")
    existing_release = bool(registered_remote)
    submodule_path = f"Outputs/Context-Packs/Repos/{definition.pack_id}"
    remote_display = remote or f"github:{github_repository}"
    print(
        f"PLAN pack={definition.pack_id} version={version} visibility={definition.visibility} "
        f"remote={remote_display} submodule={submodule_path}"
    )
    print("REVIEW Candidate diff, disclosure summary, destination, visibility, license, and version")
    missing_approval = False
    if github_pending and not getattr(args, "approve_repository_creation", False):
        print("REPOSITORY APPROVAL REQUIRED: rerun with --approve-repository-creation")
        missing_approval = True
    if not args.approve_publication:
        label = "PUBLICATION APPROVAL REQUIRED" if github_pending else "APPROVAL REQUIRED"
        print(f"{label}: rerun with --approve-publication after semantic review")
        missing_approval = True
    if missing_approval:
        return 2

    ensure_publishable_parent(root)
    with tempfile.TemporaryDirectory() as temporary:
        temporary_root = Path(temporary)
        expected = temporary_root / "expected"
        write_candidate(definition, selection, root, expected, version)
        if tree_snapshot(expected) != tree_snapshot(candidate):
            raise ValueError("Candidate is stale or modified; rebuild and review before publication")

        if github_pending:
            remote = create_github_repository(str(github_repository), definition.visibility)

        remote_refs = subprocess.run(
            ["git", "ls-remote", "--heads", "--tags", remote],
            text=True,
            capture_output=True,
            check=False,
        )
        if remote_refs.returncode:
            raise ValueError(f"remote is unavailable: {(remote_refs.stderr or remote_refs.stdout).strip()}")
        if existing_release and not remote_refs.stdout.strip():
            raise ValueError("registered Pack remote has no published refs")
        if not existing_release and remote_refs.stdout.strip():
            raise ValueError("first publication requires an empty remote repository")

        release = temporary_root / "release"
        if existing_release:
            cloned = subprocess.run(
                ["git", "-c", "protocol.file.allow=always", "clone", remote, str(release)],
                text=True,
                capture_output=True,
                check=False,
            )
            if cloned.returncode:
                raise ValueError(f"cannot clone registered Pack remote: {(cloned.stderr or cloned.stdout).strip()}")
            if version in git(release, "tag", "--list", version).splitlines():
                raise ValueError(f"release tag already exists: {version}")
            current = comparable_snapshot(release)
            for path in release.iterdir():
                if path.name == ".git":
                    continue
                shutil.rmtree(path) if path.is_dir() else path.unlink()
            for path in candidate.iterdir():
                target = release / path.name
                shutil.copytree(path, target) if path.is_dir() else shutil.copy2(path, target)
            if current == comparable_snapshot(release):
                raise ValueError("Candidate has no changes from the current Pack release")
        else:
            shutil.copytree(candidate, release)
        pack_path = release / "PACK.md"
        pack_path.write_text(
            pack_path.read_text(encoding="utf-8").replace(
                "release_status: candidate", "release_status: published", 1
            ),
            encoding="utf-8",
        )
        if not existing_release:
            git(release, "init", "-b", "main")
        parent_name = git(root, "config", "user.name") or "LBrain Context Pack"
        parent_email = git(root, "config", "user.email") or "context-pack@example.invalid"
        git(release, "config", "user.name", parent_name)
        git(release, "config", "user.email", parent_email)
        git(release, "add", ".")
        git(release, "commit", "-m", f"publish: {definition.pack_id} {version}")
        git(release, "tag", version)
        if not existing_release:
            git(release, "remote", "add", "origin", remote)
        git(release, "push", "-u", "origin", "main")
        git(release, "push", "origin", version)

    remote_path = Path(remote)
    if remote_path.is_dir() and (remote_path / "HEAD").is_file():
        subprocess.run(
            ["git", "--git-dir", str(remote_path), "symbolic-ref", "HEAD", "refs/heads/main"],
            check=False,
            capture_output=True,
        )
    repos = root / "Outputs/Context-Packs/Repos"
    repos.mkdir(parents=True, exist_ok=True)
    try:
        if existing_release:
            submodule = root / submodule_path
            if not submodule.is_dir():
                raise ValueError("registered Pack Submodule is not initialized")
            git(submodule, "fetch", "--tags", "origin", file_transport=True)
            git(submodule, "checkout", "--detach", version)
        else:
            git(root, "submodule", "add", remote, submodule_path, file_transport=True)
        update_definition_registration(definition, root, remote, submodule_path)
        git(root, "add", ".gitmodules", submodule_path, relative(definition.path, root))
        action = "update" if existing_release else "add"
        git(root, "commit", "-m", f"publish: {action} {definition.pack_id} {version}")
    except ValueError as error:
        raise ValueError(
            f"Pack release {version} exists on the remote but parent registration is incomplete; "
            f"preserve the remote and repair the Submodule registration: {error}"
        ) from error
    print(f"PUBLISHED {definition.pack_id} {version}")
    print(f"SUBMODULE {submodule_path}")
    return 0


def update(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    definition = load_definition(Path(args.definition), root)
    if args.check_remote:
        return update_from_remote(args, definition, root)
    selection = resolve_definition(definition, root)
    if selection.blocked:
        raise ValueError("preview blocked: " + "; ".join(sorted(set(selection.blocked))))
    candidate = root / "Outputs/Context-Packs/Candidates" / definition.pack_id
    version = next_version(definition, root)
    write_candidate(definition, selection, root, candidate, version)
    submodule_path = str(definition.metadata.get("submodule_path") or "")
    if submodule_path and (root / submodule_path).is_dir():
        if comparable_snapshot(candidate) == comparable_snapshot(root / submodule_path):
            print(f"OWNER UPDATE none pack={definition.pack_id}")
            return 0
    print(f"OWNER UPDATE candidate={version} pack={definition.pack_id}")
    if not args.approve_publication:
        print("APPROVAL REQUIRED: review the Candidate and rerun with --approve-publication")
        return 2
    publication_args = argparse.Namespace(
        root=root,
        definition=args.definition,
        remote=None,
        approve_publication=True,
    )
    return publish(publication_args)


def remote_main(remote: str) -> str:
    result = subprocess.run(
        ["git", "ls-remote", remote, "refs/heads/main"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(f"cannot read Pack remote: {(result.stderr or result.stdout).strip()}")
    return result.stdout.partition("\t")[0].strip()


def update_from_remote(args: argparse.Namespace, definition: Definition, root: Path) -> int:
    remote = str(definition.metadata.get("repository") or "")
    submodule_path = str(definition.metadata.get("submodule_path") or "")
    if not remote or not submodule_path:
        raise ValueError("remote update requires a published Pack Definition")
    submodule = root / submodule_path
    if not submodule.is_dir():
        raise ValueError("Pack Submodule is not initialized")
    current = git(submodule, "rev-parse", "HEAD")
    available = remote_main(remote)
    if not available:
        raise ValueError("Pack remote main is missing")
    if current == available:
        print(f"REMOTE UPDATE none pack={definition.pack_id} commit={current}")
        return 0
    print(f"REMOTE UPDATE available pack={definition.pack_id} current={current} remote={available}")
    if not args.approve_pointer:
        print("APPROVAL REQUIRED: rerun with --approve-pointer to move the Submodule")
        return 2
    ensure_publishable_parent(root)
    git(submodule, "fetch", "--tags", "origin", file_transport=True)
    git(submodule, "checkout", "--detach", available)
    git(root, "add", submodule_path)
    git(root, "commit", "-m", f"publish: update {definition.pack_id} pointer")
    print(f"SUBMODULE UPDATED {definition.pack_id} {available}")
    return 0


def verify_pack(pack_root: Path, root: Path) -> tuple[str, str, str]:
    if not pack_root.is_dir():
        raise ValueError(f"Pack root does not exist: {pack_root}")
    manifest_path = pack_root / "PACK.md"
    sources_path = pack_root / "SOURCES.md"
    if not manifest_path.is_file() or not sources_path.is_file():
        raise ValueError("Pack requires PACK.md and SOURCES.md")
    frontmatter, _, _ = load_check_helpers(root)
    metadata = frontmatter(manifest_path.read_text(encoding="utf-8"))
    required = {"type", "pack_id", "summary", "version", "release_status", "visibility", "license"}
    missing = required - metadata.keys()
    if missing:
        raise ValueError(f"Pack manifest missing fields: {', '.join(sorted(missing))}")
    if metadata.get("type") != "context-pack-release":
        raise ValueError("invalid Pack manifest type")
    status = str(metadata.get("release_status"))
    if status not in {"candidate", "published", "revoked"}:
        raise ValueError(f"invalid release_status: {status}")
    version = str(metadata.get("version"))
    if not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}\.\d+", version):
        raise ValueError(f"invalid Pack version: {version}")
    markdown_link = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
    for markdown_path in pack_root.rglob("*.md"):
        for raw in markdown_link.findall(markdown_path.read_text(encoding="utf-8")):
            target = raw.split("#", 1)[0].strip()
            if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                continue
            resolved = (markdown_path.parent / target).resolve()
            if not resolved.is_relative_to(pack_root.resolve()) or not resolved.exists():
                raise ValueError(f"unresolved or escaping Pack link in {markdown_path.relative_to(pack_root)}")
    git_check = subprocess.run(
        ["git", "-C", str(pack_root), "rev-parse", "--is-inside-work-tree"],
        text=True,
        capture_output=True,
        check=False,
    )
    if git_check.returncode:
        return str(metadata.get("pack_id")), version, "unavailable"
    if git(pack_root, "status", "--porcelain"):
        raise ValueError("Pack Git working tree is dirty")
    if status in {"published", "revoked"} and version not in git(pack_root, "tag", "--points-at", "HEAD").splitlines():
        raise ValueError("Pack version tag does not point at HEAD")
    return str(metadata.get("pack_id")), version, "verified"


def verify(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    target = Path(args.target)
    resolved = target if target.is_absolute() else root / target
    if resolved.is_file():
        definition = load_definition(resolved, root)
        submodule_path = str(definition.metadata.get("submodule_path") or "")
        if not submodule_path:
            candidate = root / "Outputs/Context-Packs/Candidates" / definition.pack_id
            pack_root = candidate
        else:
            pack_root = root / submodule_path
        pack_id, version, git_state = verify_pack(pack_root, root)
        if pack_id != definition.pack_id:
            raise ValueError("Definition pack_id does not match Pack manifest")
        if git_state == "verified" and submodule_path:
            pointer = git(root, "ls-tree", "HEAD", submodule_path).split()
            if len(pointer) < 3 or pointer[2] != git(pack_root, "rev-parse", "HEAD"):
                raise ValueError("parent Submodule pointer does not match Pack HEAD")
            origin = git(pack_root, "config", "--get", "remote.origin.url")
            if origin != str(definition.metadata.get("repository")):
                raise ValueError("Pack origin does not match Definition repository")
    else:
        pack_id, version, git_state = verify_pack(resolved, root)
    print(f"VERIFY OK pack={pack_id} version={version} git={git_state}")
    return 0


def replace_manifest_fields(path: Path, fields: dict[str, str], extra: dict[str, str] | None = None) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        end = lines[1:].index("---") + 1
    except ValueError as error:
        raise ValueError("Pack manifest frontmatter is not closed") from error
    seen: set[str] = set()
    for index in range(1, end):
        match = re.match(r"^([A-Za-z0-9_-]+):", lines[index])
        if match and match.group(1) in fields:
            key = match.group(1)
            lines[index] = f"{key}: {yaml_scalar(fields[key])}"
            seen.add(key)
    for key, value in (extra or {}).items():
        if key not in seen:
            lines.insert(end, f"{key}: {yaml_scalar(value)}")
            end += 1
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def clone_local_or_remote(remote: str, destination: Path) -> None:
    cloned = subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "clone", remote, str(destination)],
        text=True,
        capture_output=True,
        check=False,
    )
    if cloned.returncode:
        raise ValueError(f"cannot clone Pack remote: {(cloned.stderr or cloned.stdout).strip()}")


def configure_identity(repository: Path, parent: Path) -> None:
    name = subprocess.run(
        ["git", "-C", str(parent), "config", "--get", "user.name"],
        text=True,
        capture_output=True,
        check=False,
    ).stdout.strip() or "LBrain Context Pack"
    email = subprocess.run(
        ["git", "-C", str(parent), "config", "--get", "user.email"],
        text=True,
        capture_output=True,
        check=False,
    ).stdout.strip() or "context-pack@example.invalid"
    git(repository, "config", "user.name", name)
    git(repository, "config", "user.email", email)


def revoke(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    definition = load_definition(Path(args.definition), root)
    remote = str(definition.metadata.get("repository") or "")
    submodule_path = str(definition.metadata.get("submodule_path") or "")
    if not remote or not submodule_path:
        raise ValueError("revocation requires a published Pack Definition")
    if "\n" in args.reason or SECRET.search(args.reason) or ABSOLUTE_PRIVATE_PATH.search(args.reason):
        raise ValueError("revocation reason contains unsafe content")
    if args.replacement and not re.fullmatch(r"https?://[^\s]+", args.replacement):
        raise ValueError("replacement must be an HTTP or HTTPS URL")
    pack_root = root / submodule_path
    pack_id, current_version, git_state = verify_pack(pack_root, root)
    if git_state != "verified":
        raise ValueError("revocation requires a Git-verified Pack")
    current_meta, _, _ = load_check_helpers(root)
    if current_meta((pack_root / "PACK.md").read_text(encoding="utf-8")).get("release_status") == "revoked":
        raise ValueError("Pack is already revoked")
    version = next_version(definition, root)
    print(
        f"PLAN revoke pack={pack_id} current={current_version} version={version} "
        f"remote={remote} reason={args.reason}"
    )
    print("NOTICE revocation is forward-only and cannot recall downloaded copies")
    if not args.approve_revocation:
        print("APPROVAL REQUIRED: rerun with --approve-revocation")
        return 2
    ensure_publishable_parent(root)
    with tempfile.TemporaryDirectory() as temporary:
        release = Path(temporary) / "release"
        clone_local_or_remote(remote, release)
        manifest_path = release / "PACK.md"
        replace_manifest_fields(
            manifest_path,
            {
                "version": version,
                "release_status": "revoked",
                "updated": date.today().isoformat(),
            },
        )
        replacement = f"\nReplacement: {args.replacement}\n" if args.replacement else ""
        with manifest_path.open("a", encoding="utf-8") as manifest_file:
            manifest_file.write(
                "\n## Revocation\n\n"
                f"Reason: {args.reason}\n"
                f"{replacement}\n"
                "This revocation cannot recall copies already downloaded.\n"
            )
        configure_identity(release, root)
        git(release, "add", "PACK.md")
        git(release, "commit", "-m", f"publish: revoke {pack_id} {version}")
        git(release, "tag", version)
        git(release, "push", "origin", "main")
        git(release, "push", "origin", version)
    git(pack_root, "fetch", "--tags", "origin", file_transport=True)
    git(pack_root, "checkout", "--detach", version)
    update_definition_registration(definition, root, remote, submodule_path)
    git(root, "add", submodule_path, relative(definition.path, root))
    git(root, "commit", "-m", f"publish: revoke {pack_id} {version}")
    print(f"REVOKED {pack_id} {version}")
    print("NOTICE downloaded copies remain outside the owner's control")
    return 0


def fork_pack(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    if not PACK_ID.fullmatch(args.pack_id):
        raise ValueError("fork pack_id must use lowercase letters, digits, and single hyphens")
    source = Path(args.source)
    source = source.resolve() if source.is_absolute() else (root / source).resolve()
    source_id, source_version, git_state = verify_pack(source, root)
    if git_state == "verified":
        source_status = load_check_helpers(root)[0]((source / "PACK.md").read_text(encoding="utf-8")).get("release_status")
        if source_status == "revoked":
            raise ValueError("a revoked Pack must be corrected before it can be forked as published")
    destination = Path(args.destination)
    destination = destination.resolve() if destination.is_absolute() else (Path.cwd() / destination).resolve()
    if destination.exists():
        raise ValueError(f"destination already exists: {destination}")
    if destination == source or destination.is_relative_to(source):
        raise ValueError("fork destination cannot be inside the source Pack")
    version = f"{date.today().isoformat().replace('-', '.')}.1"
    print(
        f"PLAN fork source={source_id}@{source_version} pack={args.pack_id} "
        f"version={version} destination={destination}"
    )
    if not args.approve_fork:
        print("APPROVAL REQUIRED: rerun with --approve-fork")
        return 2
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".git"))
    manifest_path = destination / "PACK.md"
    replace_manifest_fields(
        manifest_path,
        {
            "pack_id": args.pack_id,
            "version": version,
            "release_status": "published",
            "updated": date.today().isoformat(),
        },
        {"forked_from": f"{source_id}@{source_version}"},
    )
    with manifest_path.open("a", encoding="utf-8") as manifest_file:
        manifest_file.write(
            "\n## Lineage\n\n"
            f"Forked from `{source_id}` release `{source_version}`. "
            "Original attribution and license obligations remain in force.\n"
        )
    git(destination, "init", "-b", "main")
    configure_identity(destination, root)
    git(destination, "add", ".")
    git(destination, "commit", "-m", f"publish: fork {args.pack_id} {version}")
    git(destination, "tag", version)
    print(f"FORKED {args.pack_id} {version} destination={destination}")
    return 0


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

    build_parser = subcommands.add_parser("build")
    build_parser.add_argument("definition")
    build_parser.set_defaults(handler=build)

    publish_parser = subcommands.add_parser("publish")
    publish_parser.add_argument("definition")
    publish_parser.add_argument("--remote")
    publish_parser.add_argument("--github-repository")
    publish_parser.add_argument("--approve-repository-creation", action="store_true")
    publish_parser.add_argument("--approve-publication", action="store_true")
    publish_parser.set_defaults(handler=publish)

    update_parser = subcommands.add_parser("update")
    update_parser.add_argument("definition")
    update_parser.add_argument("--approve-publication", action="store_true")
    update_parser.add_argument("--check-remote", action="store_true")
    update_parser.add_argument("--approve-pointer", action="store_true")
    update_parser.set_defaults(handler=update)

    verify_parser = subcommands.add_parser("verify")
    verify_parser.add_argument("target")
    verify_parser.set_defaults(handler=verify)

    revoke_parser = subcommands.add_parser("revoke")
    revoke_parser.add_argument("definition")
    revoke_parser.add_argument("--reason", required=True)
    revoke_parser.add_argument("--replacement")
    revoke_parser.add_argument("--approve-revocation", action="store_true")
    revoke_parser.set_defaults(handler=revoke)

    fork_parser = subcommands.add_parser("fork")
    fork_parser.add_argument("source")
    fork_parser.add_argument("--pack-id", required=True)
    fork_parser.add_argument("--destination", required=True)
    fork_parser.add_argument("--approve-fork", action="store_true")
    fork_parser.set_defaults(handler=fork_pack)
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
