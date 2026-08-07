<!-- ownership: kit -->
# Knowledge Lifecycle

## Capture

Put uncertain or unclassified material in Inbox. If provenance is known and worth retaining, create a Source directly. Capture the smallest lawful amount needed: prefer `reference`, use `excerpt` when analysis needs exact language, and use `full` only when authorized.

## Process

Classify each capture by durable role. Preserve external claims in Sources; place personal state in Context; make created artifacts Outputs. Fix metadata and provenance before synthesis.

## Weave

Create or update a Wiki note that interprets one or more Sources. List every supporting Source in `sources`, distinguish fact from inference, and link the Source back through usage. Mark a Source `woven` only when at least one live Wiki note references it; use `skip` when synthesis is deliberately unnecessary.

## Retrieve

Route the question to the source with the right authority:

1. Source for what an original input claimed.
2. Wiki for synthesized understanding.
3. confirmed Identity for preferences and personal principles.
4. the named live `source_of_truth` for current project state.
5. Writing for the user's prior expression, not automatically their current belief.
6. System Rules for agent operation.
7. live external verification for changing facts.

Return the fewest relevant notes and state when context is dated, inferred, or in conflict.

## Review

Review Inbox, Sources with `weaving: pending`, notes past `review_after`, and pending Proposals. Update, archive, or explicitly defer each item. A Git commit records the review batch.

## Produce and publish

Build Outputs from traceable Sources, Wiki, and Context. Drafting does not authorize publication. Record `published_url` only after the destination confirms publication.

## Archive

Move inactive material into the matching Archives role and preserve links and replacement history. Do not hard-delete by default.
