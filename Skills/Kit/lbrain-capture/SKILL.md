---
name: lbrain-capture
description: Captures new material into the correct LBrain intake path. Use when the user asks to save, capture, collect, or remember information.
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

1. Read an existing Project when present and inventory every source connector currently available to the agent before asking the user anything. Do not assume the work is a code repository.
2. Ask all independent missing questions together: Project outcome when new, enabled sources and anchors, retained domains, source precedence, schedule, and frequency. Use the agent runtime's automation facility; do not store credentials or create a Kit daemon.
3. Render one complete Project and Intake Profile preview. The Profile remains human-readable Markdown inside the Project note and records sources, anchors, retained domains, precedence, baseline status, cadence, and completeness review.
4. Use `scripts/operations.py` operation `project.configure` first in preview mode, then apply only after one explicit confirmation using the returned prior-state hash. Never ask the user to run the script or a CLI.
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
10. Use `scripts/operations.py` operation `project.checkpoint` to preview and then record the run. Pass only safe inspected scope, coverage, counts, changes, and conflicts; keep raw connector cursors outside LBrain. A partial or failed required source must not advance a complete checkpoint. Never ask the user to run the script.
11. Apply the most restrictive destination permission. A scheduled run cannot confirm Identity, publish an Output or Pack, change a remote, move a Submodule pointer, or push Git history.
12. A configured background workflow may hand updated canonical context to `lbrain-context-pack` for preview or Candidate build only. Publication still requires a separate explicit approval.
