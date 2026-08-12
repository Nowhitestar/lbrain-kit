"""Commit only operation-owned paths without disturbing the staged index."""

from __future__ import annotations

import subprocess
from pathlib import Path


def commit_paths(root: Path, paths: list[str], message: str) -> dict[str, str | bool]:
    repository = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        check=False,
    )
    if repository.returncode:
        return {"committed": False, "reason": "Git repository is unavailable"}
    staged = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--quiet", "--", *paths],
        capture_output=True,
        check=False,
    )
    if staged.returncode:
        return {"committed": False, "reason": "target paths already have staged changes"}
    intent_to_add = subprocess.run(
        ["git", "-C", str(root), "diff", "--quiet", "--diff-filter=A", "--", *paths],
        capture_output=True,
        check=False,
    )
    if intent_to_add.returncode:
        return {"committed": False, "reason": "target paths already have staged changes"}
    untracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "--", *paths],
        text=True,
        capture_output=True,
        check=False,
    )
    if untracked.returncode:
        return {"committed": False, "reason": "Git staging failed"}
    new_paths = [line for line in untracked.stdout.splitlines() if line]
    if new_paths:
        added = subprocess.run(
            ["git", "-C", str(root), "add", "-N", "--", *new_paths],
            capture_output=True,
            check=False,
        )
        if added.returncode:
            subprocess.run(
                ["git", "-C", str(root), "rm", "--cached", "--quiet", "--force", "--", *new_paths],
                capture_output=True,
                check=False,
            )
            return {"committed": False, "reason": "Git staging failed"}
    committed = subprocess.run(
        ["git", "-C", str(root), "commit", "--only", "-m", message, "--", *paths],
        capture_output=True,
        check=False,
    )
    if committed.returncode:
        if new_paths:
            subprocess.run(
                ["git", "-C", str(root), "rm", "--cached", "--quiet", "--force", "--", *new_paths],
                capture_output=True,
                check=False,
            )
        return {"committed": False, "reason": "local Git commit failed"}
    revision = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    return {"committed": True, "commit": revision.stdout.strip()}
