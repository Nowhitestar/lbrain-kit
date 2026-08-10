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

## Explicit Skill improvement

1. Start from an active user request or a pending Skill Improvement Proposal. Read the evidence and canonical enabled Personal Skill; never target a Core, disabled, or deprecated Skill through this flow.
2. Prepare the complete proposed `SKILL.md`, behavior-case changes, and only the resources those instructions require. Classify the behavioral change as patch, minor, or major.
3. Use `scripts/operations.py` operation `skill.preview`. It validates the proposed package in isolation, recommends the next semantic version, writes the exact diff and preview hash to the Proposal, and does not modify the canonical Skill. Never ask the user to run the script or a CLI.
4. Show the exact Change Preview, including tests and version rationale. Ask for one explicit approval of that immutable preview. Any preview or Skill-baseline change invalidates the approval.
5. After approval, record the matching Proposal as `accepted` with the exact preview hash, then use operation `skill.apply` with that returned preview and hash. The operation rejects a pending Proposal; never reproduce the diff manually or edit a runtime copy as the source of truth.
6. Let the operation verify the Proposal, preview fingerprint, canonical Skill baseline, validation, and explicit runtime targets. It applies the canonical package and runtime refresh as one rollback-capable action.
7. A failure restores the canonical Skill, version, tests, and any changed runtime target. Keep the Proposal accepted but not applied with safe failure evidence. A stale baseline invalidates application and requires a new preview and decision.

Patch fixes or clarifies compatible behavior, minor adds compatible behavior or triggers, and major breaks an existing behavior contract. Rejected and no-op changes do not bump the version.

## Runtime installation

Read `references/runtimes.md`, preview with `scripts/install.py --dry-run`, then use an explicit target. The installer defaults to symlinks for Codex, Claude Code, and Hermes, and to copies for OpenClaw because OpenClaw rejects links that escape its configured Skill root. Reruns skip identical packages and add newly enabled Skills. Never overwrite a divergent existing target without an explicit user decision.

Core Skills update through Kit release tags. Never edit installed runtime copies as the source of truth. Read [[System/Kit/AGENT-RUNTIME#Portable Skill Contract]] before adding runtime-specific metadata.
