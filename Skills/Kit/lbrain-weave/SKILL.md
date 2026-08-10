---
name: lbrain-weave
description: Weaves Sources into traceable LBrain Wiki knowledge. Use when the user asks to synthesize, connect, distill, or update knowledge from sources.
---
# LBrain Weave

Turn evidence into reusable knowledge without erasing uncertainty.

1. Read the relevant Sources and search Wiki for an existing note to update.
2. Verify that every durable factual claim has a supporting Source.
3. Copy `System/Templates/Core/knowledge.md` only when a new note is necessary; choose the correct `kind` and Wiki subdirectory.
4. List supporting Sources in `sources`. Separate source claims, inference, conflict, and uncertainty.
5. Add useful Wikilinks without creating a dense link dump. Update `Knowledge/Wiki/Index.md` only when the new route is broadly useful.
6. Mark a Source `weaving: woven` only after a live Wiki note references it; use `skip` when synthesis is intentionally unnecessary.
7. Validate and commit authorized synthesis locally with `weave:`. Do not push.

Do not rewrite raw Source captures to make the synthesis appear cleaner.

## Skill Improvement discovery

After the Wiki synthesis is complete, check whether the new knowledge materially changes the behavior of an enabled Personal Skill.

1. Inspect only enabled, active Personal Skills. Never scan or target Core, disabled, deprecated, or unrelated Skills.
2. Require all of the following before proposing a change: a specific target Skill, Source or Wiki evidence, a concrete behavior delta, an expected diff, and at least one behavior-case change. Topic similarity alone is insufficient.
3. Use `scripts/operations.py` operation `proposal.create` to create or deduplicate the pending Skill Improvement Proposal. Never ask the user to run the script or a CLI.
4. If no existing Skill qualifies, do nothing. New Personal Skill creation remains an active user request handled by `lbrain-skill-manager`.
5. Never edit or version the target Skill during Weave. Skill Manager prepares the exact Change Preview only after the Proposal exists.
