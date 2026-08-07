<!-- ownership: kit -->
# Changelog

All notable Kit-owned changes are documented here. Kit releases follow semantic versioning; Personal Skills carry their own versions.

## 0.1.0 — 2026-08-07

- Promoted rc.3 after independent cold-start, cross-session retrieval, personalized upgrade, and isolated runtime acceptance passed without release blockers.
- No behavior or ownership contract changed from rc.3.

## 0.1.0-rc.3 — 2026-08-07

- Made the runtime adapter smoke test accept valid Personal Skills instead of assuming exactly six installed packages.
- Clarified that personal `main` merges a formal release tag, never the possibly newer `kit-base` branch.

## 0.1.0-rc.2 — 2026-08-07

- Made runtime installation idempotent and allowed newly enabled Skills to be added without overwriting existing packages.
- Clarified agent-assisted Identity initialization and full-clone requirements for the two-branch Git model.
- Added the `proposal:` commit prefix.

## 0.1.0-rc.1 — 2026-08-07

- Introduced the seven-layer Markdown architecture and per-directory contracts.
- Defined Kit, Seeded, and User ownership boundaries.
- Added source-grounded knowledge, permission, visibility, and Git workflows.
- Added six default-enabled Core Skills and the Personal Skill lifecycle.
- Added read-only validation and isolated Codex, Claude Code, and Hermes installation adapters.
- Added a synthetic Capture → Weave → Retrieve tracer and upgrade smoke test.
