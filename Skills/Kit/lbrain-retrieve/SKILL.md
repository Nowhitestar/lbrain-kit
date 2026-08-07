---
name: lbrain-retrieve
description: Retrieves authoritative personal context from LBrain. Use when the user asks about prior decisions, views, history, projects, or saved research.
version: 0.1.0
status: active
visibility: public
created: 2026-08-07
updated: 2026-08-07
---
# LBrain Retrieve

Return the smallest trustworthy context set for the question.

1. Search by filenames, frontmatter, and text; do not preload the vault.
2. Route authority by question: Source for original claims, Wiki for synthesis, confirmed Identity for preferences, the declared live source of truth for current project state, Writing for prior expression, and System Rules for agent behavior.
3. Open the fewest relevant notes and follow their Wikilinks only when needed.
4. Distinguish dated context, current verified state, inference, and conflict.
5. Verify changing external facts live when they affect the answer.
6. Cite the LBrain files actually read. Do not mutate LBrain unless the user separately asks to save or update it.

Never treat a prior draft as a current belief or a dated Project note as live operational truth.
