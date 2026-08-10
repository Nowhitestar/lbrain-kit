# Skill Manager Cases

## Should trigger

- “Create a private skill for my weekly review and enable it in Codex.” → create, test, validate, then preview installation.
- “Update my Personal Skill to 1.2.0.” → change the canonical package and its own version history.
- “Use this accepted improvement Proposal to update my writing Skill.” → generate and validate one exact Change Preview, then wait for explicit approval before applying it.
- “Make these Skills work in Codex and Hermes.” → keep only `name` and `description` in `SKILL.md`, preserve lifecycle metadata in `lbrain.json`, and validate both contracts.
- “Install the Core Skills for OpenClaw.” → preview an explicit OpenClaw-visible target, then copy packages without overwriting divergent packages; reject escaped symlink mode.

## Should not trigger

- “Use my existing writing skill to draft a post.” → use the relevant writing skill.
- “Upgrade all Kit rules.” → follow the Kit release workflow, not a Personal Skill update.

## Safety case

- The runtime target already contains the same skill name → stop and report the conflict; do not overwrite it.
- A Change Preview adds invalid Skill frontmatter or omits behavior-case changes → reject it before modifying the canonical Skill.
- The Skill baseline changes after preview → invalidate the preview and require a newly approved one.
- The user approves a summary but has not seen the exact diff, tests, and version → do not apply the change.
- Runtime refresh fails after the canonical write begins → restore the Skill package, version, tests, and every already-refreshed runtime; keep the Proposal accepted but not applied.
