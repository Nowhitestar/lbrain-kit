"""Shared path-safe conditional file mutations for Kit operations."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


UNCHANGED = object()


class FileTransactionError(ValueError):
    pass


def assert_safe_target(root: Path, path: Path) -> None:
    root, path = root.absolute(), path.absolute()
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise FileTransactionError("target must stay inside the LBrain root") from error
    current = root.resolve()
    for index, part in enumerate(relative.parts):
        current /= part
        if current.is_symlink():
            raise FileTransactionError("target path must not contain symlinks")
        if current.exists() and index < len(relative.parts) - 1 and not current.is_dir():
            raise FileTransactionError("target parent must be a directory")
    if path.exists() and not path.is_file():
        raise FileTransactionError("target must be a regular file")


def atomic_write(root: Path, path: Path, content: str, expected: object = UNCHANGED) -> None:
    assert_safe_target(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(content)
        if expected is not UNCHANGED:
            current = path.read_text(encoding="utf-8") if path.is_file() else None
            if current != expected:
                raise FileTransactionError("target changed during operation")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_unlink(root: Path, path: Path, expected: str) -> None:
    assert_safe_target(root, path)
    current = path.read_text(encoding="utf-8") if path.is_file() else None
    if current != expected:
        raise FileTransactionError("target changed during operation")
    path.unlink()
