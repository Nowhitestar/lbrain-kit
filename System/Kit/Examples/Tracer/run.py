#!/usr/bin/env python3
"""Run the synthetic Personal Intelligence pipelines in a temporary LBrain."""

from __future__ import annotations

import json
import shutil
import struct
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


def native_capture(
    host: Path,
    root: Path,
    payload: dict[str, object],
    staging: Path,
) -> dict[str, object]:
    raw = json.dumps(payload).encode("utf-8")
    result = subprocess.run(
        [sys.executable, str(host), "--root", str(root), "--staging-root", str(staging)],
        input=struct.pack("=I", len(raw)) + raw,
        capture_output=True,
        check=False,
    )
    if len(result.stdout) < 4:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    length = struct.unpack("=I", result.stdout[:4])[0]
    output = json.loads(result.stdout[4 : 4 + length])
    if result.returncode:
        raise RuntimeError(json.dumps(output, ensure_ascii=False))
    return output


def accept_project_preview(root: Path, preview: dict[str, object]) -> None:
    proposal = preview.get("proposal")
    if not isinstance(proposal, dict):
        raise RuntimeError("project.configure returned no Proposal preview")
    (root / str(proposal["path"])).write_text(str(proposal["accepted_markdown"]), encoding="utf-8")


def accept_skill_preview(root: Path, proposal_path: object, preview_hash: object) -> None:
    path = root / str(proposal_path)
    content = path.read_text(encoding="utf-8")
    content = content.replace("status: pending", "status: accepted", 1)
    content = content.replace(
        "## Decision\n\nPending user review.",
        f"## Decision\n\nApproved exact Change Preview `{preview_hash}` after explicit user confirmation.",
        1,
    )
    path.write_text(content, encoding="utf-8")


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
        capture_host = root / "Skills/Kit/lbrain-capture/scripts/native_host.py"
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
        accept_project_preview(root, project_preview)
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

        staging = base / "browser-staging"
        staging.mkdir()
        (staging / "figure.png").write_bytes(b"synthetic browser image")
        capture_payload: dict[str, object] = {
            "schema": "lbrain.capture.v1",
            "title": "Synthetic Writing Evidence",
            "summary": "Fictional evidence for a concrete-opening rule.",
            "origin": "https://example.invalid/authenticated-writing-evidence",
            "scope": "page",
            "author": "Synthetic Author",
            "published_at": "2026-08-11",
            "content_markdown": (
                "# Synthetic Writing Evidence\n\n"
                "A useful opening makes one concrete claim before adding context.\n\n"
                "![Figure](lbrain-asset://figure)"
            ),
            "extraction_status": "complete",
            "assets": [
                {
                    "name": "images/figure.png",
                    "staged_name": "figure.png",
                    "placeholder": "lbrain-asset://figure",
                    "media_type": "image/png",
                }
            ],
        }
        captured = native_capture(capture_host, root, capture_payload, staging)
        inbox = root / str(captured["target"])
        if not str(captured.get("open_uri", "")).startswith("obsidian://open?path="):
            raise RuntimeError("Capture receipt is not openable in Obsidian")
        if "synthetic browser image" not in (
            root / f"Inbox/Captures/_assets/{captured['capture_id']}/v1/files/images/figure.png"
        ).read_bytes().decode():
            raise RuntimeError("browser-staged asset was not preserved")
        print(f"BROWSER CAPTURE status={captured['status']} inbox={int(inbox.is_file())} obsidian=1")

        source_relative = "Knowledge/Sources/Synthetic-Writing-Evidence.md"
        source_link = source_relative.removesuffix(".md")
        wiki_relative = "Knowledge/Wiki/Concepts/Synthetic-Concrete-Opening.md"
        wiki_content = (
            "---\n"
            "type: knowledge\nkind: concept\nsummary: Fictional concrete-opening rule.\n"
            "status: active\nvisibility: private\nsources:\n"
            f"  - \"[[{source_link}]]\"\n"
            "created: 2026-08-10\nupdated: 2026-08-10\n"
            "---\n# Synthetic Concrete Opening\n\n"
            f"Make one concrete claim before adding context. Source: [[{source_link}]].\n",
        )
        weave_payload: dict[str, object] = {
            "bundles": [{"path": captured["target"], "outcome": "woven", "source_path": source_relative}],
            "wiki": [{"path": wiki_relative, "content": "".join(wiki_content)}],
        }
        weave_preview = operation(weave_operations, "weave.preview", root, weave_payload)
        woven = operation(
            weave_operations,
            "weave.apply",
            root,
            {**weave_payload, "plan_hash": weave_preview["plan_hash"]},
        )
        source = root / source_relative
        wiki = root / wiki_relative
        if inbox.exists() or not source.is_file() or not wiki.is_file():
            raise RuntimeError("Inbox Bundle was not atomically promoted to Source and Wiki")
        if not (root / f"Knowledge/Sources/_assets/{captured['capture_id']}/v1/files/images/figure.png").is_file():
            raise RuntimeError("promoted Source lost its browser-staged asset")
        print(f"WEAVE status={woven['status']} source=1 wiki=1")

        proposal_payload: dict[str, object] = {
            "title": "Improve synthetic writing opening",
            "summary": "Add the concrete-opening rule to the enabled writing Skill.",
            "skill_name": "synthetic-writing",
            "evidence": [source_relative, wiki_relative],
            "rationale": "The woven evidence supplies a specific testable behavior.",
            "behavior_delta": "Require one concrete claim before contextual framing.",
            "expected_diff": "Update instructions and the opening behavior case.",
            "test_changes": ["Add a case rejecting context-first abstract openings."],
        }
        proposed = operation(weave_operations, "proposal.create", root, proposal_payload)
        print(f"WEAVE proposal={proposed['status']}")

        before_skill = (skill / "SKILL.md").read_text(encoding="utf-8")
        before_cases = (skill / "tests/cases.md").read_text(encoding="utf-8")
        codex_root = base / "codex"
        openclaw_root = base / "openclaw"
        shutil.copytree(skill, openclaw_root / skill.name)
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
            "runtime_targets": [
                {"runtime": "codex", "target": str(codex_root)},
                {"runtime": "openclaw", "target": str(openclaw_root)},
            ],
        }
        previewed = operation(skill_operations, "skill.preview", root, preview_payload)
        preview = previewed["preview"]
        if not isinstance(preview, dict):
            raise RuntimeError("skill.preview returned no preview")
        print(f"SKILL PREVIEW status={previewed['status']} version={preview['proposed_version']}")
        accept_skill_preview(root, proposed["target"], preview["preview_hash"])

        apply_payload: dict[str, object] = {
            "proposal_path": proposed["target"],
            "approved_preview_hash": preview["preview_hash"],
            "preview": preview,
        }
        applied = operation(skill_operations, "skill.apply", root, apply_payload)
        print(f"SKILL APPLY status={applied['status']}")

        repeated_capture = native_capture(capture_host, root, capture_payload, staging)
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
