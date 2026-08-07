#!/usr/bin/env python3
"""Run a synthetic Capture -> Weave -> Retrieve trace in a temporary LBrain."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SOURCE = """---
type: source
summary: Fictional field guide entry about the amber telescope protocol.
status: active
visibility: private
origin: synthetic://lbrain-kit/tracer
capture: reference
weaving: woven
created: 2026-08-07
updated: 2026-08-07
---
# Synthetic Field Guide

The fictional amber telescope protocol says to verify a changing fact before reuse.
"""
KNOWLEDGE = """---
type: knowledge
kind: concept
summary: Fictional protocol for freshness-aware retrieval.
status: active
visibility: private
sources:
  - "[[Knowledge/Sources/Synthetic-Field-Guide]]"
created: 2026-08-07
updated: 2026-08-07
---
# Amber Telescope Protocol

The fictional amber telescope protocol treats stored context as dated and verifies changing facts before reuse.

Source: [[Knowledge/Sources/Synthetic-Field-Guide]].
"""


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        copy = Path(temporary) / "lbrain"
        shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__"))

        source = copy / "Knowledge/Sources/Synthetic-Field-Guide.md"
        source.write_text(SOURCE, encoding="utf-8")
        print(f"CAPTURE {source.relative_to(copy)}")

        knowledge = copy / "Knowledge/Wiki/Concepts/Amber-Telescope-Protocol.md"
        knowledge.write_text(KNOWLEDGE, encoding="utf-8")
        print(f"WEAVE {knowledge.relative_to(copy)}")

        matches = [
            path for path in (copy / "Knowledge/Wiki").rglob("*.md")
            if "amber telescope protocol" in path.read_text(encoding="utf-8").casefold()
        ]
        if knowledge not in matches:
            print("ERROR: synthetic knowledge was not retrieved", file=sys.stderr)
            return 1
        print(f"RETRIEVE {knowledge.relative_to(copy)}")

        checked = subprocess.run(
            [sys.executable, str(copy / "System/Kit/check.py"), "--root", str(copy), "--quiet"],
            check=False,
        )
        if checked.returncode:
            print("ERROR: traced LBrain failed validation", file=sys.stderr)
            return checked.returncode

    print("TRACE PASS: Capture -> Weave -> Retrieve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
