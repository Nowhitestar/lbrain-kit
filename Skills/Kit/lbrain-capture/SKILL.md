---
name: lbrain-capture
description: Captures new material into the correct LBrain intake path. Use when the user asks to save, capture, collect, or remember information.
---
# LBrain Capture

Capture information without prematurely turning it into truth.

1. Confirm the active LBrain root and read the nearest directory `README.md`.
2. Send every external original to Inbox first. Do not bypass the user's chance to read it merely because its likely category is obvious. Verified Project Context and Agent-created Wiki, Outputs, Identity Proposals, and Skills continue to use their own layers.
3. Use `scripts/operations.py` operation `capture.create` for Agent-provided text. A first-party browser Capture Surface uses `scripts/native_host.py`, which calls the same locked `capture.bundle` operation without requiring a running Agent. Never ask the user to run an operation script or CLI.
4. Let the operation deduplicate by stable capture identity, validate the new note, and return the existing capture on an idempotent retry.
5. When extraction fails, retain the origin, user note, and failure state as a reference capture; never fabricate missing article text. A later complete retry may recover that managed capture in place only with its exact managed-section recovery hash, while preserving unrecognized metadata and user-authored sections excluded from that hash.
6. Default to `visibility: private`. The shared disclosure gate rejects secret-like material before any Project, checkpoint, or capture write.
7. Preserve quoted or imported source text; add interpretation elsewhere.
8. A validated Capture Bundle attempts a local `capture:` commit automatically. A Git or LFS failure returns a warning without discarding the Durable Capture. Do not push.

## Browser Capture mode

1. Use the unpacked Manifest V3 extension in `browser-extension/` for first-party Chrome capture. It reads the current rendered DOM only after a toolbar or context-menu gesture and never asks a server or Agent to refetch the URL.
2. Register `io.lbrain.capture` with `scripts/install_native_host.py` using the active LBrain root and the developer-mode extension ID. The installer creates an on-demand launcher and a private staging directory; it does not install a daemon.
3. Before any local write, use the extension confirmation window to show the extracted title and whether the save will contain article text, a Thread, selection, original file, video link/subtitles, or a generic HTML snapshot. Continue only after explicit confirmation; cancellation has no write or Native Host side effect. Request only temporary exact-origin access when a confirmed capture needs a cross-origin document, subtitle, or audio attachment, then remove only the permission added by that capture after the attempt.
4. Treat the Native Host receipt as final for normal saves. Show only `saved`, `partial`, `already_saved`, or `new_version` and the Obsidian target. Ask for help only when extraction, permission, routing, or local persistence fails.
5. Keep project, directory, and tag classification out of the save interaction. An Agent may suggest those later while the original remains in Inbox.
6. Preserve direct PDFs and article attachments as Bundle assets. Extract searchable PDF text locally, falling back to local OCR when available; a missing extractor makes the receipt `partial` and never discards the original.
7. Preserve webpage subtitle files and rendered transcript text. Record the original video link, but never download the video binary. Never use the browser Downloads directory as capture transport.
8. When no suitable article body exists and the page is neither a direct file nor a supported video page, preserve one sanitized local HTML snapshot as the original. Do not label navigation/card text as an article.
9. A `partial` receipt carries an exact hash of the managed Bundle fields/sections and a verified original-content fingerprint. A later browser retry may replace only those managed sections and the asset manifest for that same version when both values still match; preserve prior verified assets that were not downloaded again. Changed originals create a new version, while unknown frontmatter and user-authored sections are excluded from the recovery hash and remain untouched.

Do not use this skill for source synthesis; use `lbrain-weave` after capture.

## Context Intake mode

Context Intake is the batch and scheduled form of Capture. It uses the same provenance, routing, and permission rules rather than a separate Intake Skill.

### Configure a Project

1. Read an existing Project when present and inventory every source connector currently available to the agent before asking the user anything. Do not assume the work is a code repository.
2. Ask all independent missing questions together: Project outcome when new, enabled sources and anchors, retained domains, source precedence, schedule, and frequency. Use the agent runtime's automation facility; do not store credentials or create a Kit daemon.
3. Render one complete Project and Intake Profile preview. The Profile remains human-readable Markdown inside the Project note and records sources, anchors, retained domains, precedence, baseline status, cadence, and completeness review. Under `### Sources and anchors`, write one required coverage row per line as `- source: anchor`; the checkpoint operation reconciles against those rows and rejects omissions.
4. Use `scripts/operations.py` operation `project.configure` first in preview mode. After one explicit confirmation, record the returned Project Proposal preview as `accepted`, then call apply with the returned prior-state hash. The operation applies only that already accepted Proposal; it never self-approves. Never ask the user to run the script or a CLI.
5. Let the operation add versioned boundaries around the Profile. An existing unmarked Profile migrates lazily through the same content-preserving preview; never bulk-rewrite personal Projects during a Kit upgrade.
6. Treat a newly configured Project as `baseline_pending`. Do not represent a recent-window scan as complete historical coverage. Keep connector credentials and raw cursors outside LBrain.

### Run Intake

1. Finish a baseline backfill before relying on incremental intake. Enumerate and read the relevant history behind every configured anchor, discover additional high-signal anchors, and report what was discovered, read, excluded, failed, or left unresolved. Search hits and message listings count as discovery, not as reading the underlying page or discussion.
2. After the baseline is complete, scan every enabled source on every run using its last successful checkpoint plus a small overlap. Revisit stable anchors periodically so edits, late replies, and missed decisions can be recovered. A named target Project changes attention and the final report, never source coverage.
3. Read decision-bearing material at the page, topic, thread, change, or issue level before extracting it. Prefer topic- and anchor-based retrieval over a broad recent-message feed when the latter is noisy.
4. Report each enabled source as `scanned`, `failed`, `stale`, `partial`, or `no match`, with the inspected scope. A failed or partial source makes the run partial; never imply full coverage.
5. Retain only durable decisions, rationale, actions, outcomes, current status, and reusable learning with safe provenance pointers. Do not mirror complete threads, mailboxes, page trees, or repositories by default.
6. A durable decision record preserves enough reasoning for another agent to judge it: domain and status; date or time span; question; material options or disagreements; evidence; decision or current conclusion; rationale and tradeoffs; consequences or actions; outcome or validation state; supersession or unresolved conflict; and every useful source pointer. Omit fields that truly did not exist, but never reduce a decision to a conclusion when its reasoning is available.
7. Deduplicate the same durable event across sources. Update the existing record when later evidence implements, rejects, or supersedes it; retain the historical state and all useful source pointers.
8. Route verified Project and Area context to the matching existing note. Keep the Project note as the current-state entry point; when decision history would overwhelm it, use one adjacent `<Project>-Decisions.md` ledger before adding directories or domain-specific files. Send reusable cross-project synthesis to `lbrain-weave`, Identity claims to a Proposal, created artifacts to Outputs, and ambiguity to Inbox. Keep work, life, personal, and cross-project relationships in metadata rather than a new directory entity.
9. End every run with a coverage report: enabled source and anchor statuses, time range, durable candidates found, full reads, records created or updated, duplicates and noise rejected, unresolved conflicts, files changed, and next completeness review. A run is complete only when every enabled source and required anchor is accounted for.
10. Use `scripts/operations.py` operation `project.checkpoint` to preview and then record the run. Pass only safe inspected scope, coverage, counts, changes, and conflicts; keep raw connector cursors outside LBrain. A partial or failed required source must not advance a complete checkpoint. Serialized apply rejects a stale Project instead of overwriting a concurrent edit. Never ask the user to run the script.
11. Apply the most restrictive destination permission. A scheduled run cannot confirm Identity, publish an Output or Pack, change a remote, move a Submodule pointer, or push Git history.
12. A configured background workflow may hand updated canonical context to `lbrain-context-pack` for preview or Candidate build only. Publication still requires a separate explicit approval.
