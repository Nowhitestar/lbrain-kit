---
name: lbrain-weave
description: Weaves Sources into traceable LBrain Wiki knowledge. Use when the user asks to synthesize, connect, distill, or update knowledge from sources.
---
# LBrain Weave

Turn evidence into reusable knowledge without erasing uncertainty.

1. Read the selected Inbox Capture Bundles and search Wiki for an existing note to update.
2. Verify that every durable factual claim has a supporting Source.
3. Copy `System/Templates/Core/knowledge.md` only when a new note is necessary; choose the correct `kind` and Wiki subdirectory.
4. List supporting Sources in `sources`. Separate source claims, inference, conflict, and uncertainty.
5. Add useful Wikilinks without creating a dense link dump. Update `Knowledge/Wiki/Index.md` only when the new route is broadly useful.
6. Prepare one `weave.preview` transaction describing every selected Bundle, Source destination, Wiki create/update, conflict, and final outcome. A direct user request to weave authorizes the matching conflict-free plan; call `weave.apply` with its plan hash without asking again. Stop when the plan conflicts or expands beyond the request.
7. Use `woven` to promote the original note and assets to Sources only when a live Wiki note references it. Use `skip` to promote without Wiki synthesis, leave `pending` or `deferred` in Inbox, and archive `rejected` material with its reason. `reviewed_at` is optional.
8. Let the operation validate the multi-Bundle/multi-Wiki transaction, roll every managed resource back on failure, and attempt one local `weave:` commit. Do not push.

Do not rewrite raw Source captures to make the synthesis appear cleaner.

## Skill Improvement discovery

After `weave.apply` succeeds, check whether the new knowledge materially changes the behavior of an enabled Personal Skill.

1. Inspect only enabled, active Personal Skills. Never scan or target Core, disabled, deprecated, or unrelated Skills.
2. Require all of the following before proposing a change: a specific target Skill, Source or Wiki evidence, a concrete behavior delta, an expected diff, and at least one behavior-case change. Topic similarity alone is insufficient.
3. Use `scripts/operations.py` operation `proposal.create` to create or deduplicate the pending Skill Improvement Proposal. Never ask the user to run the script or a CLI.
4. If no existing Skill qualifies, do nothing. New Personal Skill creation remains an active user request handled by `lbrain-skill-manager`.
5. Never edit or version the target Skill during Weave. Skill Manager prepares the exact Change Preview only after the Proposal exists.
