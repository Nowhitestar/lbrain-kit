#!/usr/bin/env python3
"""Run the synthetic Personal Intelligence pipelines in a temporary LBrain."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def operation(script: Path, name: str, root: Path, payload: dict[str, object]) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, str(script), name, "--root", str(root)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(result.stdout + result.stderr) from error
    if result.returncode:
        raise RuntimeError(json.dumps(output, ensure_ascii=False) + result.stderr)
    return output


def add_personal_skill(root: Path) -> Path:
    skill = root / "Skills/Personal/synthetic-writing"
    (skill / "tests").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: synthetic-writing\ndescription: Improves synthetic writing.\n---\n"
        "# Synthetic Writing\n\nUse concrete verbs.\n",
        encoding="utf-8",
    )
    (skill / "lbrain.json").write_text(
        '{"schema":"lbrain.skill.v1","version":"1.0.0","status":"active",'
        '"visibility":"private","created":"2026-08-10","updated":"2026-08-10"}\n',
        encoding="utf-8",
    )
    (skill / "tests/cases.md").write_text(
        "# Cases\n\n- Draft with concrete verbs.\n",
        encoding="utf-8",
    )
    with (root / "Skills/Enabled.md").open("a", encoding="utf-8") as file:
        file.write("\n- [[Skills/Personal/synthetic-writing/SKILL]] — codex, openclaw\n")
    return skill


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        root = base / "lbrain"
        shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        capture_operations = root / "Skills/Kit/lbrain-capture/scripts/operations.py"
        weave_operations = root / "Skills/Kit/lbrain-weave/scripts/operations.py"
        skill_operations = root / "Skills/Kit/lbrain-skill-manager/scripts/operations.py"
        skill = add_personal_skill(root)

        project_payload: dict[str, object] = {
            "mode": "preview",
            "project_path": "Context/Projects/Synthetic-Research.md",
            "title": "Synthetic Research",
            "summary": "A non-code Personal Intelligence tracer Project.",
            "outcome": "Produce one evidence-backed writing rule.",
            "profile_markdown": (
                "## Context Intake Profile\n\n"
                "### Sources and anchors\n\n- Web: reading list\n- Notes: notebook\n\n"
                "### Retained domains\n\n- Evidence and writing decisions\n\n"
                "### Schedule\n\n- Cadence: weekly\n- Baseline: baseline_pending\n"
            ),
        }
        project_preview = operation(capture_operations, "project.configure", root, project_payload)
        project_payload.update(mode="apply", expected_hash=project_preview["before_hash"])
        configured = operation(capture_operations, "project.configure", root, project_payload)
        print(f"PROJECT CONFIGURE status={configured['status']}")

        partial_payload: dict[str, object] = {
            "mode": "apply",
            "project_path": project_payload["project_path"],
            "run_id": "synthetic-partial",
            "range": "historical baseline",
            "sources": [
                {"name": "web", "status": "scanned", "scope": "reading list", "required": True},
                {"name": "notes", "status": "failed", "scope": "notebook", "required": True},
            ],
            "candidates": 1,
            "full_reads": 1,
            "changes": [],
            "conflicts": ["notebook unavailable"],
            "next_review": "after recovery",
            "expected_hash": configured["after_hash"],
        }
        partial = operation(capture_operations, "project.checkpoint", root, partial_payload)
        print(
            f"CHECKPOINT status={partial['status']} "
            f"advanced={int(bool(partial['complete_checkpoint_advanced']))}"
        )
        complete_payload = {
            **partial_payload,
            "run_id": "synthetic-complete",
            "sources": [
                {"name": "web", "status": "scanned", "scope": "reading list", "required": True},
                {
                    "name": "notes",
                    "status": "no_durable_change",
                    "scope": "notebook",
                    "required": True,
                },
            ],
            "conflicts": [],
            "expected_hash": partial["after_hash"],
        }
        complete = operation(capture_operations, "project.checkpoint", root, complete_payload)
        print(
            f"CHECKPOINT status={complete['status']} "
            f"advanced={int(bool(complete['complete_checkpoint_advanced']))}"
        )

        capture_payload: dict[str, object] = {
            "destination": "source",
            "title": "Synthetic Writing Evidence",
            "summary": "Fictional evidence for a concrete-opening rule.",
            "origin": "synthetic://personal-intelligence/writing-evidence",
            "capture": "full",
            "content": "A useful opening makes one concrete claim before adding context.",
            "note": "Evaluate this against the enabled writing Skill.",
            "extraction_status": "complete",
        }
        captured = operation(capture_operations, "capture.create", root, capture_payload)
        print(f"CAPTURE status={captured['status']}")
        source = root / str(captured["target"])
        source.write_text(
            source.read_text(encoding="utf-8").replace("weaving: pending", "weaving: woven", 1),
            encoding="utf-8",
        )
        source_link = str(captured["target"]).removesuffix(".md")
        wiki = root / "Knowledge/Wiki/Concepts/Synthetic-Concrete-Opening.md"
        wiki.write_text(
            "---\n"
            "type: knowledge\nkind: concept\nsummary: Fictional concrete-opening rule.\n"
            "status: active\nvisibility: private\nsources:\n"
            f"  - \"[[{source_link}]]\"\n"
            "created: 2026-08-10\nupdated: 2026-08-10\n"
            "---\n# Synthetic Concrete Opening\n\n"
            f"Make one concrete claim before adding context. Source: [[{source_link}]].\n",
            encoding="utf-8",
        )

        proposal_payload: dict[str, object] = {
            "title": "Improve synthetic writing opening",
            "summary": "Add the concrete-opening rule to the enabled writing Skill.",
            "skill_name": "synthetic-writing",
            "evidence": [str(captured["target"]), "Knowledge/Wiki/Concepts/Synthetic-Concrete-Opening.md"],
            "rationale": "The woven evidence supplies a specific testable behavior.",
            "behavior_delta": "Require one concrete claim before contextual framing.",
            "expected_diff": "Update instructions and the opening behavior case.",
            "test_changes": ["Add a case rejecting context-first abstract openings."],
        }
        proposed = operation(weave_operations, "proposal.create", root, proposal_payload)
        print(f"WEAVE proposal={proposed['status']}")

        before_skill = (skill / "SKILL.md").read_text(encoding="utf-8")
        before_cases = (skill / "tests/cases.md").read_text(encoding="utf-8")
        preview_payload: dict[str, object] = {
            "proposal_path": proposed["target"],
            "change_level": "minor",
            "rationale": "Adds compatible evidence-backed opening behavior.",
            "changes": {
                "SKILL.md": before_skill.replace(
                    "Use concrete verbs.",
                    "Use concrete verbs. Make one concrete claim before adding context.",
                ),
                "tests/cases.md": before_cases + "- Reject a context-first abstract opening.\n",
            },
        }
        previewed = operation(skill_operations, "skill.preview", root, preview_payload)
        preview = previewed["preview"]
        if not isinstance(preview, dict):
            raise RuntimeError("skill.preview returned no preview")
        print(f"SKILL PREVIEW status={previewed['status']} version={preview['proposed_version']}")

        codex_root = base / "codex"
        openclaw_root = base / "openclaw"
        shutil.copytree(skill, openclaw_root / skill.name)
        apply_payload: dict[str, object] = {
            "proposal_path": proposed["target"],
            "approved_preview_hash": preview["preview_hash"],
            "preview": preview,
            "runtime_targets": [
                {"runtime": "codex", "target": str(codex_root)},
                {"runtime": "openclaw", "target": str(openclaw_root)},
            ],
        }
        applied = operation(skill_operations, "skill.apply", root, apply_payload)
        print(f"SKILL APPLY status={applied['status']}")

        repeated_capture = operation(capture_operations, "capture.create", root, capture_payload)
        repeated_proposal = operation(weave_operations, "proposal.create", root, proposal_payload)
        repeated_apply = operation(skill_operations, "skill.apply", root, apply_payload)
        print(
            f"RERUN capture={repeated_capture['status']} "
            f"proposal={repeated_proposal['status']} apply={repeated_apply['status']}"
        )

        matches = [
            path
            for path in (root / "Knowledge/Wiki").rglob("*.md")
            if "concrete claim before adding context" in path.read_text(encoding="utf-8").casefold()
        ]
        if wiki not in matches:
            raise RuntimeError("woven synthetic knowledge was not retrieved")
        checked = subprocess.run(
            [sys.executable, str(root / "System/Kit/check.py"), "--root", str(root), "--quiet"],
            text=True,
            capture_output=True,
            check=False,
        )
        if checked.returncode:
            raise RuntimeError(checked.stdout + checked.stderr)

    print("PERSONAL INTELLIGENCE TRACE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
