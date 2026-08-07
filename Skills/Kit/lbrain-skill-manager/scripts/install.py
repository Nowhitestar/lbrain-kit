#!/usr/bin/env python3
"""Install enabled LBrain skills into one explicit runtime directory."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path


ENABLED = re.compile(r"^\s*-\s+\[\[([^\]]+/SKILL)\]\]\s+[—-]\s+(.+?)\s*$", re.MULTILINE)
RUNTIMES = ("codex", "claude", "hermes")


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
        selected.append(package)
    if not selected:
        raise ValueError(f"no skills enabled for {runtime}")
    return selected


def install(root: Path, runtime: str, target: Path, mode: str, dry_run: bool) -> list[Path]:
    root = root.resolve()
    target = target.expanduser().resolve()
    if target == root or target.is_relative_to(root):
        raise ValueError("runtime target must be outside the canonical LBrain")
    packages = selected_skills(root, runtime)
    destinations = [target / package.name for package in packages]
    conflicts = [path for path in destinations if os.path.lexists(path)]
    if conflicts:
        raise FileExistsError("refusing to overwrite: " + ", ".join(str(path) for path in conflicts))
    if dry_run:
        return destinations

    target.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    try:
        for package, destination in zip(packages, destinations):
            if mode == "symlink":
                destination.symlink_to(package, target_is_directory=True)
            else:
                shutil.copytree(package, destination)
            created.append(destination)
    except Exception:
        for path in reversed(created):
            if path.is_symlink():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
        raise
    return destinations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", choices=RUNTIMES, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--mode", choices=("symlink", "copy"), default="symlink")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[4])
    args = parser.parse_args()
    try:
        destinations = install(args.root, args.runtime, args.target, args.mode, args.dry_run)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    verb = "WOULD INSTALL" if args.dry_run else "INSTALLED"
    for destination in destinations:
        print(f"{verb} {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
