#!/usr/bin/env python3
"""Register the LBrain Capture Native Messaging host for Chrome on macOS."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path


HOST_NAME = "io.lbrain.capture"


def atomic_text(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def paths(config_root: Path) -> tuple[Path, Path, Path]:
    manifest = config_root / "Google/Chrome/NativeMessagingHosts" / f"{HOST_NAME}.json"
    runtime = config_root / "LBrain/Capture"
    return manifest, runtime / "native_host.sh", runtime / "Staging"


def install(config_root: Path, root: Path, extension_id: str, staging_root: Path) -> dict[str, object]:
    if not re.fullmatch(r"[a-p]{32}", extension_id):
        raise ValueError("extension-id must be the 32-letter Chrome extension ID")
    root = root.expanduser().resolve()
    host = root / "Skills/Kit/lbrain-capture/scripts/native_host.py"
    if not host.is_file() or not (root / "System/Kit/check.py").is_file():
        raise ValueError("root is not an LBrain with the Capture Native Host")
    manifest, launcher, _ = paths(config_root.expanduser().resolve())
    staging = staging_root.expanduser().resolve()
    staging.mkdir(parents=True, exist_ok=True)
    command = " ".join(
        shlex.quote(str(value))
        for value in (sys.executable, host, "--root", root, "--staging-root", staging)
    )
    atomic_text(launcher, f"#!/bin/sh\nexec {command}\n", 0o755)
    atomic_text(
        manifest,
        json.dumps(
            {
                "name": HOST_NAME,
                "description": "LBrain on-demand Capture Bundle receiver",
                "path": str(launcher),
                "type": "stdio",
                "allowed_origins": [f"chrome-extension://{extension_id}/"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    return {
        "status": "installed",
        "manifest": str(manifest),
        "launcher": str(launcher),
        "staging": str(staging),
    }


def uninstall(config_root: Path) -> dict[str, object]:
    manifest, launcher, staging = paths(config_root.expanduser().resolve())
    for path in (manifest, launcher):
        if path.is_file() or path.is_symlink():
            path.unlink()
    return {
        "status": "uninstalled",
        "manifest": str(manifest),
        "launcher": str(launcher),
        "staging_preserved": str(staging),
    }


def main() -> int:
    default = Path.home() / "Library/Application Support"
    default_staging = default / "LBrain/Capture/Staging"
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    add = subparsers.add_parser("install")
    add.add_argument("--root", required=True, type=Path)
    add.add_argument("--extension-id", required=True)
    add.add_argument("--config-root", type=Path, default=default)
    add.add_argument("--staging-root", type=Path, default=default_staging)
    remove = subparsers.add_parser("uninstall")
    remove.add_argument("--config-root", type=Path, default=default)
    args = parser.parse_args()
    try:
        result = (
            install(args.config_root, args.root, args.extension_id, args.staging_root)
            if args.command == "install"
            else uninstall(args.config_root)
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
