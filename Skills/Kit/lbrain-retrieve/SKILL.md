---
name: lbrain-retrieve
description: Retrieves authoritative local LBrain context with Wiki-first hybrid search, freshness checks, citations, and filesystem fallback. Use for LBrain, knowledge-base or second-brain questions, prior decisions, personal or project history, saved research, prior views, or writing grounded in the user's existing context.
---
# LBrain Retrieve

Return the smallest trustworthy context set for the question.

Read `references/providers.md` before configuring a provider, diagnosing qmd, or using the bundled CLI adapter.

1. Do not preload the vault. Route through `Knowledge/Wiki/Index.md` when the topic may already be synthesized.
2. Check qmd status through its MCP tool when available. Otherwise run `scripts/retrieval.py doctor`. Prefer qmd when its `brain` collection resolves to the active LBrain.
3. If the qmd index is older than one day and recent LBrain changes matter, run `scripts/retrieval.py update`, then `scripts/retrieval.py embed`. If maintenance cannot complete, continue with direct files and disclose stale or degraded semantic retrieval.
4. Search with explicit intent plus lexical and semantic restatements. Prefer qmd MCP `query`, `get`, and `multi_get`; otherwise use `scripts/retrieval.py query`, which falls back to filesystem ranking when qmd is unavailable.
5. Route authority by question: Source for original claims, Wiki for synthesis, confirmed Identity for preferences, the declared live source of truth for current project state, Writing for prior expression, and System Rules for agent behavior.
6. Read 3–8 strong files rather than answering from snippets. Follow Wikilinks only when they add necessary evidence.
7. Distinguish dated LBrain records, current verified state, inference, and conflict. Verify changing external facts live when they affect the answer.
8. Cite the LBrain files actually read. Do not mutate LBrain unless the user separately asks to save or update it.

Never treat a prior draft as a current belief or a dated Project note as live operational truth.
