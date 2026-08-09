#!/usr/bin/env python3
"""Portable LBrain retrieval adapter with qmd and filesystem providers."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


SCHEMA = "lbrain.retrieval.v1"
COLLECTION = "brain"
DEFAULT_INDEX = "lbrain"
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
IGNORED_PREFIXES = (
    "Outputs/Context-Packs/Candidates/",
    "Outputs/Context-Packs/Repos/",
    "System/session_logs/",
    "System/html-artifacts/",
    "legacy/",
)
IGNORED_PARTS = {".git", ".obsidian", ".mcp", ".gstack", ".wiki-cache", "__pycache__"}
CONTEXTS = {
    "": (
        "A private Markdown-native personal Agent Context using the LBrain seven-layer structure: "
        "Context, Knowledge, Inbox, Outputs, Skills, System, and Archives. Retrieve on demand."
    ),
    "knowledge/wiki": "Source-grounded synthesis and the preferred router for knowledge questions.",
    "knowledge/sources": "Original or imported source material used as evidence; preserve source bodies.",
    "context/projects": "Dated project goals, decisions, state, and declared live sources of truth.",
    "context/areas": "Long-lived areas of responsibility and research.",
    "context/identity": "Confirmed profile, dated state, and principles; do not infer or rewrite identity.",
    "outputs/writing": "Prior drafts and published writing used for established framing and voice.",
    "skills": "Portable Core and Personal Agent Skills plus their resources.",
    "system": "Kit contracts, rules, proposals, templates, and maintenance documentation.",
    "inbox": "Unreviewed captures and temporary intake material.",
    "archives": "Historical material that is not prioritized unless explicitly relevant.",
}


class AdapterError(RuntimeError):
    """Expected user-facing adapter failure."""


def is_lbrain(root: Path) -> bool:
    return (
        (root / "System/Kit/OWNERSHIP.md").is_file()
        and (root / "Knowledge/Wiki/Index.md").is_file()
        and (root / "Skills/Kit/lbrain-retrieve/SKILL.md").is_file()
    )


def lbrain_config_dir() -> Path:
    if os.environ.get("LBRAIN_CONFIG_DIR"):
        return Path(os.environ["LBRAIN_CONFIG_DIR"]).expanduser()
    if os.environ.get("XDG_CONFIG_HOME"):
        return Path(os.environ["XDG_CONFIG_HOME"]).expanduser() / "lbrain"
    return Path.home() / ".config/lbrain"


def registered_root() -> Path | None:
    path = lbrain_config_dir() / "root"
    if not path.is_file():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return Path(value) if value else None


def resolve_root(raw: str | None) -> Path:
    candidates: list[Path] = []
    if raw:
        candidates.append(Path(raw))
    if os.environ.get("LBRAIN_ROOT"):
        candidates.append(Path(os.environ["LBRAIN_ROOT"]))
    registry = registered_root()
    if registry:
        candidates.append(registry)
    candidates.extend((Path.cwd(), *Path.cwd().parents))
    script = Path(__file__).resolve()
    if len(script.parents) > 4:
        candidates.append(script.parents[4])
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if is_lbrain(resolved):
            return resolved
    raise AdapterError("LBrain root not found; pass --root or set LBRAIN_ROOT")


def qmd_binary(raw: str | None) -> str | None:
    configured = raw or os.environ.get("LBRAIN_QMD_BIN")
    if configured:
        path = Path(configured).expanduser()
        return str(path.resolve()) if path.is_file() and os.access(path, os.X_OK) else None
    return shutil.which("qmd")


def run_qmd(binary: str, index: str, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [binary, "--index", index, *arguments],
        text=True,
        capture_output=True,
        check=False,
    )


def collection_root(binary: str, index: str) -> Path | None:
    result = run_qmd(binary, index, ["collection", "show", COLLECTION])
    if result.returncode:
        return None
    match = re.search(r"^\s*Path:\s+(.+?)\s*$", result.stdout, re.MULTILINE)
    return Path(match.group(1)).expanduser().resolve() if match else None


def index_candidates(explicit: str | None) -> list[str]:
    values = [explicit, os.environ.get("LBRAIN_QMD_INDEX"), DEFAULT_INDEX, "index"]
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def matching_index(binary: str | None, root: Path, explicit: str | None) -> str | None:
    if not binary:
        return None
    for index in index_candidates(explicit):
        if collection_root(binary, index) == root:
            return index
    return None


def is_ignored(path: Path, root: Path) -> bool:
    relative = path.relative_to(root).as_posix()
    return any(part in IGNORED_PARTS or part.startswith(".") for part in path.relative_to(root).parts) or any(
        relative.startswith(prefix) for prefix in IGNORED_PREFIXES
    )


def markdown_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*.md")
        if path.is_file()
        and not path.is_symlink()
        and not is_ignored(path, root)
        and path.stat().st_size <= MAX_DOCUMENT_BYTES
    ]


def safe_path(root: Path, raw: str) -> Path:
    value = raw.strip()
    if value.startswith("qmd://brain/"):
        value = value.removeprefix("qmd://brain/")
    elif value.startswith("brain/"):
        value = value.removeprefix("brain/")
    candidate = Path(value)
    if candidate.is_absolute():
        raise AdapterError("absolute document paths are not accepted")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root) or is_ignored(resolved, root):
        raise AdapterError("document path escapes or targets an excluded LBrain path")
    return resolved


def terms(*values: str) -> list[str]:
    found: list[str] = []
    for value in values:
        for token in re.findall(r"[A-Za-z0-9_][A-Za-z0-9_-]*|[\u3400-\u9fff]+", value.casefold()):
            if len(token) > 1 and token not in found:
                found.append(token)
    return found


def title_for(text: str, path: Path) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
    return match.group(1) if match else path.stem


def snippet_for(text: str, needles: list[str]) -> str:
    lowered = text.casefold()
    positions = [lowered.find(item) for item in needles if lowered.find(item) >= 0]
    start = max(0, min(positions, default=0) - 120)
    return re.sub(r"\s+", " ", text[start : start + 480]).strip()


def filesystem_query(root: Path, lexical: str, semantic: str, limit: int) -> list[dict[str, object]]:
    needles = terms(lexical, semantic)
    if not needles:
        raise AdapterError("query has no searchable terms")
    ranked: list[tuple[float, Path, str]] = []
    for path in markdown_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        lowered = text.casefold()
        relative = path.relative_to(root).as_posix()
        path_text = relative.casefold()
        score = 0.0
        for needle in needles:
            score += min(lowered.count(needle), 8)
            if needle in path_text:
                score += 4
        if lexical.casefold() in lowered:
            score += 8
        if relative.startswith("Knowledge/Wiki/"):
            score += 2
        if score:
            ranked.append((score, path, text))
    ranked.sort(key=lambda item: (-item[0], item[1].relative_to(root).as_posix().casefold()))
    maximum = ranked[0][0] if ranked else 1.0
    return [
        {
            "docid": None,
            "score": round(score / maximum, 4),
            "file": path.relative_to(root).as_posix(),
            "title": title_for(text, path),
            "context": "filesystem lexical fallback; semantic retrieval unavailable",
            "snippet": snippet_for(text, needles),
            "provider": "filesystem",
            "degraded": True,
        }
        for score, path, text in ranked[:limit]
    ]


def qmd_config_dir() -> Path:
    if os.environ.get("QMD_CONFIG_DIR"):
        return Path(os.environ["QMD_CONFIG_DIR"]).expanduser()
    if os.environ.get("XDG_CONFIG_HOME"):
        return Path(os.environ["XDG_CONFIG_HOME"]).expanduser() / "qmd"
    return Path.home() / ".config/qmd"


def proposed_config(root: Path) -> dict[str, object]:
    return {
        "collections": {
            COLLECTION: {
                "path": str(root),
                "pattern": "**/*.md",
                "ignore": [
                    "Outputs/Context-Packs/Candidates/**",
                    "Outputs/Context-Packs/Repos/**",
                ],
                "context": CONTEXTS,
            }
        }
    }


def command_doctor(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    binary = qmd_binary(args.qmd_bin)
    index = matching_index(binary, root, args.index)
    report = {
        "schema": SCHEMA,
        "root": str(root),
        "provider": "qmd" if index else "filesystem",
        "degraded": index is None,
        "qmd": {"binary": binary, "index": index, "collection": COLLECTION},
        "filesystem": {"documents": len(markdown_files(root)), "available": True},
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if args.require_qmd and not index else 0


def command_status(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    binary = qmd_binary(args.qmd_bin)
    index = matching_index(binary, root, args.index)
    if not index:
        print(f"FILESYSTEM DEGRADED documents={len(markdown_files(root))} root={root}")
        return 0
    result = run_qmd(binary, index, ["status"])
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


def command_query(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    binary = qmd_binary(args.qmd_bin) if args.provider != "filesystem" else None
    index = matching_index(binary, root, args.index)
    semantic = args.semantic or args.query
    if index:
        document = "\n".join(
            line for line in (f"intent: {args.intent}" if args.intent else "", f"lex: {args.query}", f"vec: {semantic}") if line
        )
        command = ["query", document, "-c", COLLECTION, "-n", str(args.limit), "--min-score", str(args.min_score), "--json"]
        if args.no_rerank:
            command.append("--no-rerank")
        result = run_qmd(binary, index, command)
        if result.returncode == 0:
            sys.stdout.write(result.stdout)
            return 0
        if args.provider == "qmd":
            sys.stderr.write(result.stderr or "qmd query failed\n")
            return result.returncode
        sys.stderr.write("qmd query failed; using degraded filesystem retrieval\n")
    elif args.provider == "qmd":
        raise AdapterError("no qmd index has a brain collection for this LBrain")
    print(json.dumps(filesystem_query(root, args.query, semantic, args.limit), ensure_ascii=False, indent=2))
    return 0


def command_get(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    path = safe_path(root, args.file)
    if not path.is_file():
        raise AdapterError(f"document not found: {args.file}")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, args.from_line)
    selected = lines[start - 1 : start - 1 + args.max_lines]
    if args.line_numbers:
        selected = [f"{number}: {line}" for number, line in enumerate(selected, start=start)]
    print("\n".join(selected))
    return 0


def command_multi_get(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    values = [item.strip() for item in args.pattern.split(",") if item.strip()]
    paths: list[Path] = []
    for value in values:
        for candidate in root.glob(value):
            if candidate.is_file() and candidate.suffix.casefold() == ".md" and not is_ignored(candidate, root):
                resolved = safe_path(root, candidate.relative_to(root).as_posix())
                if resolved not in paths:
                    paths.append(resolved)
    for path in sorted(paths)[: args.limit]:
        print(f"--- {path.relative_to(root).as_posix()} ---")
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[: args.max_lines]
        print("\n".join(lines))
    return 0


def require_qmd(args: argparse.Namespace) -> tuple[Path, str, str]:
    root = resolve_root(args.root)
    binary = qmd_binary(args.qmd_bin)
    index = matching_index(binary, root, args.index)
    if not binary or not index:
        raise AdapterError("matching qmd provider not found; run configure and update first")
    return root, binary, index


def command_maintenance(args: argparse.Namespace) -> int:
    _, binary, index = require_qmd(args)
    result = run_qmd(binary, index, [args.command])
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


def command_mcp(args: argparse.Namespace) -> int:
    _, binary, index = require_qmd(args)
    os.execv(binary, [binary, "--index", index, "mcp"])
    return 1


def command_configure(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    binary = qmd_binary(args.qmd_bin)
    if not args.index and matching_index(binary, root, None):
        print("MATCHING QMD INDEX ALREADY CONFIGURED")
        return 0
    index = args.index or os.environ.get("LBRAIN_QMD_INDEX") or DEFAULT_INDEX
    destination = qmd_config_dir() / f"{index}.yml"
    rendered = json.dumps(proposed_config(root), ensure_ascii=False, indent=2) + "\n"
    print(f"QMD CONFIG {destination}")
    if not args.apply:
        print(rendered, end="")
        print("DRY RUN; rerun with --apply")
        return 0
    if destination.exists():
        if destination.read_text(encoding="utf-8") == rendered:
            print("ALREADY CONFIGURED")
            return 0
        raise AdapterError(f"refusing to overwrite divergent qmd config: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")
    print("CONFIGURED; run update then embed")
    return 0


def command_register(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    destination = lbrain_config_dir() / "root"
    rendered = f"{root}\n"
    print(f"LBRAIN ROOT {destination}")
    if not args.apply:
        print(rendered, end="")
        print("DRY RUN; rerun with --apply")
        return 0
    if destination.exists():
        if destination.read_text(encoding="utf-8") == rendered:
            print("ALREADY REGISTERED")
            return 0
        raise AdapterError(f"refusing to overwrite divergent LBrain root registry: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")
    print("REGISTERED")
    return 0


def common(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument("--root")
    subparser.add_argument("--index")
    subparser.add_argument("--qmd-bin")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor")
    common(doctor)
    doctor.add_argument("--require-qmd", action="store_true")
    doctor.set_defaults(handler=command_doctor)
    status = commands.add_parser("status")
    common(status)
    status.set_defaults(handler=command_status)
    query = commands.add_parser("query")
    common(query)
    query.add_argument("query")
    query.add_argument("--semantic")
    query.add_argument("--intent")
    query.add_argument("--limit", type=int, default=10)
    query.add_argument("--min-score", type=float, default=0.3)
    query.add_argument("--provider", choices=("auto", "qmd", "filesystem"), default="auto")
    query.add_argument("--no-rerank", action="store_true")
    query.set_defaults(handler=command_query)
    get = commands.add_parser("get")
    common(get)
    get.add_argument("file")
    get.add_argument("--from-line", type=int, default=1)
    get.add_argument("--max-lines", type=int, default=200)
    get.add_argument("--line-numbers", action="store_true")
    get.set_defaults(handler=command_get)
    multi = commands.add_parser("multi-get")
    common(multi)
    multi.add_argument("pattern")
    multi.add_argument("--limit", type=int, default=8)
    multi.add_argument("--max-lines", type=int, default=200)
    multi.set_defaults(handler=command_multi_get)
    configure = commands.add_parser("configure")
    common(configure)
    configure.add_argument("--apply", action="store_true")
    configure.set_defaults(handler=command_configure)
    register = commands.add_parser("register")
    common(register)
    register.add_argument("--apply", action="store_true")
    register.set_defaults(handler=command_register)
    for name in ("update", "embed"):
        maintenance = commands.add_parser(name)
        common(maintenance)
        maintenance.set_defaults(handler=command_maintenance)
    mcp = commands.add_parser("mcp")
    common(mcp)
    mcp.set_defaults(handler=command_mcp)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        return args.handler(args)
    except (AdapterError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
