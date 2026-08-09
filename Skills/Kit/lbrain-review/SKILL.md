---
name: lbrain-review
description: Reviews LBrain queues, stale notes, and proposals. Use when the user asks for inbox processing, maintenance, cleanup, or a context health review.
---
# LBrain Review

Keep context current without silently changing high-impact meaning.

1. Run `python3 System/Kit/check.py` and preserve its starting result.
2. Review four queues: Inbox, Sources with `weaving: pending`, notes past `review_after`, and Proposals with `status: pending`.
3. For each item, recommend or perform only an authorized action: process, weave, update verified routine state, defer explicitly, or archive by role.
4. Create Proposals for Identity, scope, rules, publication, visibility, restore, or other protected changes. Never self-approve them.
5. Do not hard-delete by default.
6. Re-run validation and commit authorized maintenance locally with the matching prefix. Do not push.

Report unresolved decisions separately from completed maintenance.
