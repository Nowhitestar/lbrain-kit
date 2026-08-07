---
name: lbrain-capture
description: Captures new material into the correct LBrain intake path. Use when the user asks to save, capture, collect, or remember information.
version: 0.2.0
status: active
visibility: public
created: 2026-08-07
updated: 2026-08-07
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

1. Inventory every source connector currently available to the agent. Ask which sources to enable, whether intake should be scheduled, and at what frequency. Use the agent runtime's automation facility; do not store credentials or create a Kit daemon.
2. On every run, scan all enabled sources. A named target Project changes attention and the final report, never source coverage.
3. Report each enabled source as scanned, failed, or stale. A failed source makes the run partial; never imply full coverage.
4. Retain only durable decisions, rationale, actions, outcomes, status, and reusable learning with safe provenance pointers. Do not mirror complete threads, mailboxes, page trees, or repositories by default.
5. Deduplicate the same durable event across sources and retain every useful source pointer.
6. Route verified Project and Area context to the matching existing note. Send reusable synthesis to `lbrain-weave`, Identity claims to a Proposal, created artifacts to Outputs, and ambiguity to Inbox. Keep work, life, personal, and cross-project relationships in metadata rather than a new directory entity.
7. Apply the most restrictive destination permission. A scheduled run cannot confirm Identity, publish an Output or Pack, change a remote, move a Submodule pointer, or push Git history.
8. A configured background workflow may hand updated canonical context to `lbrain-context-pack` for preview or Candidate build only. Publication still requires a separate explicit approval.
