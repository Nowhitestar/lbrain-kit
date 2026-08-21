<!-- ownership: kit -->
# Changelog

All notable Kit-owned changes are documented here. Kit releases follow semantic versioning; Personal Skills carry their own versions.

## 0.5.0 — 2026-08-21

- Added a first-party Manifest V3 Web Clipper that previews the exact capture type before any write, streams the current authenticated rendered page directly to an on-demand local Native Messaging Host, and never uses Downloads, browsing history, permanent site permissions, a daemon, local port, cloud model, or automatic push.
- Added durable Inbox Capture Bundles with stable identity, immutable versions, SHA-256 manifests, Git LFS assets, Obsidian-relative media, no-op receipts, partial recovery, local `capture:` commits, and fail-safe path/disk/symlink validation.
- Preserved authenticated articles, WeChat articles, X Articles and first-author Threads, direct PDFs, non-video document attachments, images, audio, webpage subtitles/transcripts, video origin links, and sanitized offline HTML snapshots for non-article pages; video binaries remain excluded, captures are limited to 256 MiB per media file and 512 MiB total, and writes preserve a 512 MiB disk reserve.
- Added hash-bound `weave.preview`/`weave.apply` transactions that atomically promote woven or skipped Bundles, archive rejected originals with reasons, leave pending/deferred originals in Inbox, update multiple Wiki notes/backlinks, roll back on failure, and attempt local `weave:` commits.
- Upgraded the Personal Intelligence Tracer to prove the framed browser message → Inbox → Obsidian receipt → Source/Wiki → Skill Improvement lifecycle and idempotent replay.
- Kept Chrome Web Store distribution, videos without existing-subtitle local transcription, and a general MCP Capture/plugin protocol for later milestones.

## 0.4.1 — 2026-08-11

- Fixed the public-content validator so static pagination placeholders, empty or zero cursor initialization, getter key references, and explanatory docstrings remain valid while concrete opaque cursor values are still rejected.
- Kept Personal Skill versions and personal content unchanged; this release only patches the shared Kit validator used during upgrades and public Skill checks.

## 0.4.0 — 2026-08-10

- Added Agent-native Project Setup and recoverable Context Intake with preview/apply hashes, lazy v1 Profile markers, explicit partial runs, and complete-checkpoint advancement only after every required source succeeds.
- Added idempotent Source capture with provenance, failed-extraction preservation, secret rejection, legacy-origin reuse, validation, and rollback.
- Integrated passive Skill Improvement detection into Weave: only enabled active Personal Skills receive evidence-linked Proposals with a behavior delta and required behavior-case changes.
- Added immutable Skill Change Preview and exact-hash Skill Apply with semantic versioning, stale-preview rejection, validation, multi-runtime refresh, rollback, and idempotent replay.
- Bound runtime destinations and their state into the approved Skill preview, serialized write operations and runtime installation across processes, broadened credential and cursor rejection, and made rollback preserve conflicting concurrent edits.
- Made incomplete captures recoverable with an exact prior hash without deleting user metadata or sections, preserved Proposal sections during re-preview, and kept checkpoints inside an existing mid-document checkpoint section.
- Replaced the synthetic read-only tracer with a complete Personal Intelligence trace across Project, Knowledge, and Skill pipelines; retained four-runtime and v0.3 upgrade regressions.
- Deliberately did not add a user-facing CLI, general write MCP, browser/mobile collector, cloud sync, encryption, access control, or autonomous Identity/Skill mutation.

## 0.3.0 — 2026-08-09

- Added the Agent Runtime and Retrieval Contract, with qmd as the default derived retrieval provider and a deterministic filesystem fallback.
- Added a portable two-manifest Skill format: standard `SKILL.md` frontmatter plus LBrain-owned `lbrain.json` lifecycle metadata.
- Added the `lbrain-retrieve` CLI adapter for provider diagnosis, qmd maintenance and MCP launch, bounded reads, hybrid queries, and safe degraded retrieval.
- Added OpenClaw as a supported isolated runtime adapter and expanded compatibility validation across all enabled Skills.
- Added positive read bounds, Skill-package and Enabled-path containment checks, qmd status/exclusion health checks, validated qmd result paths, safe index names, and disclosure scanning for public manifests.
- Kept qmd MCP as the direct read transport and documented future atomic write extraction without introducing an LBrain Policy MCP.

## 0.2.4 — 2026-08-08

- Added Project Intake Profiles, required historical baselines, checkpointed incremental scans, anchor-level coverage reports, and explicit partial-run semantics.
- Defined a decision-complete durable record so concise Intake preserves available questions, alternatives, evidence, rationale, tradeoffs, outcomes, conflicts, and supersession.
- Added Capture behavior cases for baseline completeness, full-reading evidence, decision reasoning, and coverage reporting.

## 0.2.3 — 2026-08-08

- Isolated the Context Pack metadata-query fixture from personalized LBrain content, so real private analyses cannot create false test failures after migration.

## 0.2.2 — 2026-08-08

- Made Context Pack side-effect tests preserve and compare an existing `.gitmodules` file, so the suite remains valid after users add public Skill or Pack submodules.

## 0.2.1 — 2026-08-07

- Preserved imported Source bodies by excluding their author-provided Wikilink markup from repository link validation; Source-to-Wiki integrity remains enforced through `sources` and woven backlinks.
- Ignored local connector, tool-audit, and generated Wiki cache directories so runtime state is not committed with personal context.

## 0.2.0 — 2026-08-07

- Added full-source Context Intake guidance across Capture and Weave without introducing another semantic layer.
- Added the default-enabled `lbrain-context-pack` Core Skill and a complete Definition, preview, Candidate, safety, publication, update, verification, revocation, and fork lifecycle.
- Added independently versioned Pack repositories, CalVer releases, and private-LBrain Git Submodule registration.
- Added public-disclosure gates, Personal Skill licensing checks, separate GitHub repository-creation and publication approvals, and explicit non-recall semantics.
- Added synthetic owner-to-recipient and personalized Kit-upgrade acceptance tests without network access or real publication.

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
