---
name: lbrain-skill-manager
description: Creates, validates, enables, installs, updates, and archives LBrain Skills. Use when the user asks to manage Core or Personal Skills or runtime installations.
---
# LBrain Skill Manager

Treat `Skills/` as canonical and runtime directories as replaceable installations.

## Personal Skill lifecycle

1. Create `Skills/Personal/<name>/SKILL.md` with portable `name` and `description` frontmatter, then create a private `lbrain.json` lifecycle sidecar.
2. Add only resources the instructions reference. Keep the entrypoint concise and imperative.
3. Add `tests/cases.md` covering positive triggers, negative triggers, expected behavior, and a safety edge case.
4. Run `python3 System/Kit/check.py`. Set `status` to `active` in `lbrain.json` only after validation.
5. Add an active skill to `Skills/Enabled.md` for selected runtimes.
6. Version Personal Skills independently with semantic versions and Git history.
7. Deprecate before moving a skill to `Archives/Skills/`. Do not hard-delete by default.

Only the user may make a skill public or publish it. Public and published are separate states; distributed Personal Skills need their own license.

## Runtime installation

Read `references/runtimes.md`, preview with `scripts/install.py --dry-run`, then use an explicit target. The installer defaults to symlinks for Codex, Claude Code, and Hermes, and to copies for OpenClaw because OpenClaw rejects links that escape its configured Skill root. Reruns skip identical packages and add newly enabled Skills. Never overwrite a divergent existing target without an explicit user decision.

Core Skills update through Kit release tags. Never edit installed runtime copies as the source of truth. Read [[System/Kit/AGENT-RUNTIME#Portable Skill Contract]] before adding runtime-specific metadata.
