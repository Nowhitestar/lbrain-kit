# Retrieve Cases

## Should trigger

- “我们以前对 Context Pack 做过什么决定？” → retrieve the decision notes and cite them.
- “What is my preferred writing style?” → use confirmed Identity and relevant prior Writing, noting uncertainty.

## Should not trigger

- “Save this preference.” → use `lbrain-capture` or an Identity Proposal.
- “Review every stale note.” → use `lbrain-review`.

## Freshness case

- A Project note names a live issue tracker as source of truth → check the tracker for current status instead of asserting the Markdown status is current.

## Provider cases

- qmd MCP exposes a `brain` collection for this LBrain → run an intent-aware lexical plus semantic query, then read the selected files.
- qmd is missing or its `brain` collection points elsewhere → use `scripts/retrieval.py query`, report filesystem retrieval as degraded, and do not treat provider failure as zero matches.
- qmd index is older than one day and recent LBrain changes matter → run `update`, then `embed`, before relying on semantic ranking.
- The user requests a path outside the LBrain root → reject it; do not use traversal or an absolute path as a retrieval shortcut.

## Session case

- A newly opened Codex, Claude Code, Hermes, or OpenClaw session starts in an unrelated project on the same machine → the globally installed Skill resolves LBrain through `LBRAIN_ROOT`, an explicit root, or a canonical symlink and retrieves on demand.
- An OpenClaw copy starts outside LBrain → resolve the explicitly registered local root and retrieve without embedding a personal path in the portable Skill package.
