#!/usr/bin/env python3
"""Install enabled LBrain skills into one explicit runtime directory."""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import re
import shutil
import sys
from pathlib import Path


ENABLED = re.compile(r"^\s*-\s+\[\[([^\]]+/SKILL)\]\]\s+[—-]\s+(.+?)\s*$", re.MULTILINE)
RUNTIMES = ("codex", "claude", "hermes", "openclaw")
PORTABLE_FIELDS = {"name", "description"}
LBRAIN_FIELDS = {"schema", "version", "status", "visibility", "created", "updated"}
COPY_IGNORED_NAMES = {".git", ".DS_Store", "__pycache__"}


def ignored_copy_name(name: str) -> bool:
    return name in COPY_IGNORED_NAMES or name.endswith((".pyc", ".pyo"))


def trees_equal(left: Path, right: Path) -> bool:
    comparison = filecmp.dircmp(left, right)
    left_only = {name for name in comparison.left_only if not ignored_copy_name(name)}
    right_only = {name for name in comparison.right_only if not ignored_copy_name(name)}
    common_funny = {name for name in comparison.common_funny if not ignored_copy_name(name)}
    funny_files = {name for name in comparison.funny_files if not ignored_copy_name(name)}
    if left_only or right_only or common_funny or funny_files:
        return False
    if any(
        not filecmp.cmp(left / name, right / name, shallow=False)
        for name in comparison.common_files
        if not ignored_copy_name(name)
    ):
        return False
    return all(
        trees_equal(left / name, right / name)
        for name in comparison.common_dirs
        if not ignored_copy_name(name)
    )


def copy_ignore(_: str, names: list[str]) -> set[str]:
    return {name for name in names if ignored_copy_name(name)}


def validate_package(package: Path) -> None:
    skill = package / "SKILL.md"
    content = skill.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        raise ValueError(f"invalid portable Skill frontmatter: {skill}")
    fields = {
        item.group(1)
        for line in match.group(1).splitlines()
        if (item := re.match(r"^([A-Za-z0-9_-]+):", line))
    }
    if fields != PORTABLE_FIELDS:
        raise ValueError(f"SKILL.md must contain only name and description: {skill}")
    manifest_path = package / "lbrain.json"
    if not manifest_path.is_file():
        raise ValueError(f"missing LBrain Skill manifest: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid LBrain Skill manifest: {manifest_path}: {error}") from error
    if not isinstance(manifest, dict) or not LBRAIN_FIELDS <= manifest.keys():
        raise ValueError(f"incomplete LBrain Skill manifest: {manifest_path}")


def selected_skills(root: Path, runtime: str) -> list[Path]:
    enabled = (root / "Skills/Enabled.md").read_text(encoding="utf-8")
    selected = []
    for target, runtime_text in ENABLED.findall(enabled):
        runtimes = {item.strip().casefold() for item in runtime_text.split(",")}
        if runtime not in runtimes:
            continue
        package = root / Path(target).parent
        if not (package / "SKILL.md").is_file():
            raise ValueError(f"enabled skill is missing: {target}")
        validate_package(package)
        selected.append(package)
    if not selected:
        raise ValueError(f"no skills enabled for {runtime}")
    return selected


def install(root: Path, runtime: str, target: Path, mode: str, dry_run: bool) -> tuple[list[Path], set[Path]]:
    root = root.resolve()
    target = target.expanduser().resolve()
    if target == root or target.is_relative_to(root):
        raise ValueError("runtime target must be outside the canonical LBrain")
    packages = selected_skills(root, runtime)
    destinations = [target / package.name for package in packages]
    existing: set[Path] = set()
    conflicts: list[Path] = []
    for package, destination in zip(packages, destinations):
        if not os.path.lexists(destination):
            continue
        identical = (
            mode == "symlink" and destination.is_symlink() and destination.resolve() == package
        ) or (
            mode == "copy" and destination.is_dir() and not destination.is_symlink() and trees_equal(package, destination)
        )
        if identical:
            existing.add(destination)
        else:
            conflicts.append(destination)
    if conflicts:
        raise FileExistsError("refusing to overwrite: " + ", ".join(str(path) for path in conflicts))
    if dry_run:
        return destinations, existing

    target.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    try:
        for package, destination in zip(packages, destinations):
            if destination in existing:
                continue
            if mode == "symlink":
                destination.symlink_to(package, target_is_directory=True)
            else:
                shutil.copytree(package, destination, ignore=copy_ignore)
            created.append(destination)
    except Exception:
        for path in reversed(created):
            if path.is_symlink():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
        raise
    return destinations, existing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", choices=RUNTIMES, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("symlink", "copy"),
        help="Defaults to copy for OpenClaw and symlink for other runtimes.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[4])
    args = parser.parse_args()
    mode = args.mode or ("copy" if args.runtime == "openclaw" else "symlink")
    if args.runtime == "openclaw" and mode == "symlink":
        print("ERROR: OpenClaw rejects Skill symlinks that resolve outside its configured root; use copy mode", file=sys.stderr)
        return 1
    try:
        destinations, existing = install(args.root, args.runtime, args.target, mode, args.dry_run)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for destination in destinations:
        if destination in existing:
            verb = "ALREADY INSTALLED"
        else:
            verb = "WOULD INSTALL" if args.dry_run else "INSTALLED"
        print(f"{verb} {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
