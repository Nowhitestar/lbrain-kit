# Skill Manager Cases

## Should trigger

- “Create a private skill for my weekly review and enable it in Codex.” → create, test, validate, then preview installation.
- “Update my Personal Skill to 1.2.0.” → change the canonical package and its own version history.
- “Make these Skills work in Codex and Hermes.” → keep only `name` and `description` in `SKILL.md`, preserve lifecycle metadata in `lbrain.json`, and validate both contracts.
- “Install the Core Skills for OpenClaw.” → preview an explicit OpenClaw-visible target, then copy packages without overwriting divergent packages; reject escaped symlink mode.

## Should not trigger

- “Use my existing writing skill to draft a post.” → use the relevant writing skill.
- “Upgrade all Kit rules.” → follow the Kit release workflow, not a Personal Skill update.

## Safety case

- The runtime target already contains the same skill name → stop and report the conflict; do not overwrite it.
