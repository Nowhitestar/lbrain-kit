---
name: lbrain-capture
description: Captures new material into the correct LBrain intake path. Use when the user asks to save, capture, collect, or remember information.
version: 0.3.0
status: active
visibility: public
created: 2026-08-07
updated: 2026-08-08
---
# LBrain Capture

Capture information without prematurely turning it into truth.

1. Confirm the active LBrain root and read the nearest directory `README.md`.
2. Check whether the material already exists before creating a duplicate.
3. Put uncertain or unclassified material in `Inbox/`.
4. Create a Source directly when origin and durable value are clear. Copy `System/Templates/Core/source.md`, record provenance, and capture only the lawful amount needed.
5. Default to `visibility: private`. Never store credentials or secrets.
6. Preserve quoted or imported source text; add interpretation elsewhere.
7. Run `python3 System/Kit/check.py` and commit an authorized capture locally with `capture:`. Do not push.

Do not use this skill for source synthesis; use `lbrain-weave` after capture.

## Context Intake mode

Context Intake is the batch and scheduled form of Capture. It uses the same provenance, routing, and permission rules rather than a separate Intake Skill.

### Configure a Project

1. Inventory every source connector currently available to the agent. Ask which sources to enable, whether intake should be scheduled, and at what frequency. Use the agent runtime's automation facility; do not store credentials or create a Kit daemon.
2. Add a compact `Intake Profile` section to the target Project note. Record the enabled sources, project-specific anchors such as repositories, pages, streams, topics, dashboards, and issue projects, the context domains to retain, source precedence, baseline status, and last completeness review. Keep connector credentials and raw cursors outside LBrain.
3. Treat a newly configured Project as `baseline_pending`. Do not represent a recent-window scan as complete historical coverage.

### Run Intake

1. Finish a baseline backfill before relying on incremental intake. Enumerate and read the relevant history behind every configured anchor, discover additional high-signal anchors, and report what was discovered, read, excluded, failed, or left unresolved. Search hits and message listings count as discovery, not as reading the underlying page or discussion.
2. After the baseline is complete, scan every enabled source on every run using its last successful checkpoint plus a small overlap. Revisit stable anchors periodically so edits, late replies, and missed decisions can be recovered. A named target Project changes attention and the final report, never source coverage.
3. Read decision-bearing material at the page, topic, thread, change, or issue level before extracting it. Prefer topic- and anchor-based retrieval over a broad recent-message feed when the latter is noisy.
4. Report each enabled source as `scanned`, `failed`, `stale`, `partial`, or `no match`, with the inspected scope. A failed or partial source makes the run partial; never imply full coverage.
5. Retain only durable decisions, rationale, actions, outcomes, current status, and reusable learning with safe provenance pointers. Do not mirror complete threads, mailboxes, page trees, or repositories by default.
6. A durable decision record preserves enough reasoning for another agent to judge it: domain and status; date or time span; question; material options or disagreements; evidence; decision or current conclusion; rationale and tradeoffs; consequences or actions; outcome or validation state; supersession or unresolved conflict; and every useful source pointer. Omit fields that truly did not exist, but never reduce a decision to a conclusion when its reasoning is available.
7. Deduplicate the same durable event across sources. Update the existing record when later evidence implements, rejects, or supersedes it; retain the historical state and all useful source pointers.
8. Route verified Project and Area context to the matching existing note. Keep the Project note as the current-state entry point; when decision history would overwhelm it, use one adjacent `<Project>-Decisions.md` ledger before adding directories or domain-specific files. Send reusable cross-project synthesis to `lbrain-weave`, Identity claims to a Proposal, created artifacts to Outputs, and ambiguity to Inbox. Keep work, life, personal, and cross-project relationships in metadata rather than a new directory entity.
9. End every run with a coverage report: enabled source and anchor statuses, time range or checkpoint, durable candidates found, records created or updated, duplicates and noise rejected, unresolved conflicts, files changed, and next completeness review. A run is complete only when every enabled source and required anchor is accounted for.
10. Apply the most restrictive destination permission. A scheduled run cannot confirm Identity, publish an Output or Pack, change a remote, move a Submodule pointer, or push Git history.
11. A configured background workflow may hand updated canonical context to `lbrain-context-pack` for preview or Candidate build only. Publication still requires a separate explicit approval.
