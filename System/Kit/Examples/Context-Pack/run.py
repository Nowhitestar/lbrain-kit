#!/usr/bin/env python3
"""Trace synthetic Context Intake through portable Pack consumption."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def run(*command: str) -> str:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip()


def git(repository: Path, *arguments: str) -> str:
    return run("git", "-C", str(repository), *arguments)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        lbrain = base / "lbrain"
        shutil.copytree(ROOT, lbrain, ignore=shutil.ignore_patterns(".git", "__pycache__", ".scratch"))
        git(lbrain, "init", "-b", "main")
        git(lbrain, "config", "user.name", "LBrain Tracer")
        git(lbrain, "config", "user.email", "tracer@example.invalid")
        git(lbrain, "add", ".")
        git(lbrain, "commit", "-m", "kit: initialize Context Pack tracer")

        write(
            lbrain / "Context/Projects/AgentKey.md",
            """---
type: project
summary: Synthetic AgentKey growth decisions from Git and Notion.
status: active
visibility: public
outcome: Give another agent reusable growth context.
source_of_truth: synthetic://git+notion/agentkey
created: 2026-08-07
updated: 2026-08-07
---
# AgentKey

The synthetic team approved one evidence-based growth experiment.
""",
        )
        write(
            lbrain / "Context/Projects/Yulu.md",
            """---
type: project
summary: Synthetic non-target Yulu decision from Zulip.
status: active
visibility: private
outcome: Preserve non-target context during focused intake.
source_of_truth: synthetic://zulip/yulu
created: 2026-08-07
updated: 2026-08-07
---
# Yulu

This non-target context remains private and outside the AgentKey Pack.
""",
        )
        write(
            lbrain / "Context/Areas/Operations.md",
            """---
type: area
summary: Synthetic recurring responsibility from Gmail.
status: active
visibility: private
created: 2026-08-07
updated: 2026-08-07
---
# Operations

Review the synthetic weekly operating report.
""",
        )
        write(
            lbrain / "Inbox/Ambiguous-Intake.md",
            """---
type: note
summary: Synthetic ambiguous durable item awaiting classification.
status: active
visibility: private
created: 2026-08-07
updated: 2026-08-07
---
# Ambiguous Intake

This item needs a later review.
""",
        )
        write(
            lbrain / "Skills/Personal/agentkey-growth-brief/SKILL.md",
            """---
name: agentkey-growth-brief
description: Summarizes the synthetic AgentKey growth context for another agent.
version: 1.0.0
status: active
visibility: public
license: MIT
created: 2026-08-07
updated: 2026-08-07
---
# AgentKey Growth Brief

Read the Pack context, preserve its limitations, and cite the Pack release. See `tests/cases.md`.
""",
        )
        write(
            lbrain / "Skills/Personal/agentkey-growth-brief/tests/cases.md",
            "# Cases\n\n- Summarize only claims present in the Pack context.\n",
        )
        write(
            lbrain / "Skills/Personal/agentkey-growth-brief/LICENSE",
            (lbrain / "LICENSE").read_text(encoding="utf-8"),
        )
        print("INTAKE sources=git,notion,zulip,gmail target=AgentKey coverage=complete")
        print("ROUTE target=AgentKey non_target=Yulu area=Operations ambiguous=Inbox")

        definition = lbrain / "Outputs/Context-Packs/agentkey-growth.md"
        write(
            definition,
            """---
type: context-pack
pack_id: agentkey-growth
summary: Synthetic portable AgentKey growth context.
status: draft
visibility: public
license: MIT
created: 2026-08-07
updated: 2026-08-07
---
# AgentKey Growth

## Purpose

Give another agent approved AgentKey growth context.

## Includes

- path: Context/Projects/AgentKey.md

## Excludes

## Skills

- path: Skills/Personal/agentkey-growth-brief/SKILL.md

## Build Notes

Synthetic public example only.
""",
        )
        git(lbrain, "add", "Context", "Inbox", str(definition.relative_to(lbrain)))
        git(lbrain, "add", "Skills/Personal/agentkey-growth-brief")
        git(lbrain, "commit", "-m", "capture: route synthetic full-source intake")
        pack = lbrain / "Skills/Kit/lbrain-context-pack/scripts/pack.py"
        previewed = run(sys.executable, str(pack), "--root", str(lbrain), "preview", str(definition.relative_to(lbrain)))
        if "blocked=0" not in previewed:
            raise RuntimeError("Pack preview did not pass disclosure checks")
        print("PREVIEW blocked=0 semantic_review=required")
        run(sys.executable, str(pack), "--root", str(lbrain), "build", str(definition.relative_to(lbrain)))

        remote = base / "agentkey-growth.git"
        run("git", "init", "--bare", str(remote))
        published = run(
            sys.executable,
            str(pack),
            "--root",
            str(lbrain),
            "publish",
            str(definition.relative_to(lbrain)),
            "--remote",
            str(remote),
            "--approve-publication",
        )
        if "PUBLISHED agentkey-growth" not in published:
            raise RuntimeError("Pack publication did not complete")

        source_pack = lbrain / "Outputs/Context-Packs/Repos/agentkey-growth"
        recipient = base / "recipient-pack"
        shutil.copytree(source_pack, recipient, ignore=shutil.ignore_patterns(".git"))
        verified = run(sys.executable, str(pack), "--root", str(lbrain), "verify", str(recipient))
        if "git=unavailable" not in verified:
            raise RuntimeError("copied Pack did not use structural-only verification")
        manifest = (recipient / "PACK.md").read_text(encoding="utf-8")
        if (
            "## Loading Order" not in manifest
            or not (recipient / "context/AgentKey.md").is_file()
            or not (recipient / "skills/agentkey-growth-brief/SKILL.md").is_file()
        ):
            raise RuntimeError("recipient Pack is not self-describing")
        if (recipient / "context/Yulu.md").exists() or "Ambiguous Intake" in "\n".join(
            path.read_text(encoding="utf-8") for path in recipient.rglob("*.md")
        ):
            raise RuntimeError("non-selected private context escaped into the Pack")
        print("CONSUME git=unavailable entry=PACK.md private_context=absent")

    print("CONTEXT PACK TRACE PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"ERROR {error}", file=sys.stderr)
        raise SystemExit(1) from error
