"""Small cross-process locks for deterministic LBrain mutations."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO


class TransactionError(RuntimeError):
    pass


def lock_path(path: Path) -> Path:
    identity = str(path.expanduser().resolve())
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    directory = Path(tempfile.gettempdir()) / "lbrain-operation-locks"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{key}.lock"


def acquire(file: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt  # pylint: disable=import-outside-toplevel

        file.seek(0)
        if not file.read(1):
            file.write(b"\0")
            file.flush()
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl  # pylint: disable=import-outside-toplevel

    fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def release(file: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt  # pylint: disable=import-outside-toplevel

        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl  # pylint: disable=import-outside-toplevel

    fcntl.flock(file.fileno(), fcntl.LOCK_UN)


@contextmanager
def mutation_locks(paths: Sequence[Path]) -> Iterator[None]:
    files: list[BinaryIO] = []
    try:
        for path in sorted({lock_path(item) for item in paths}, key=str):
            file = path.open("a+b")
            try:
                acquire(file)
            except (BlockingIOError, OSError) as error:
                file.close()
                raise TransactionError("another LBrain mutation is in progress") from error
            files.append(file)
        yield
    finally:
        for file in reversed(files):
            release(file)
            file.close()
