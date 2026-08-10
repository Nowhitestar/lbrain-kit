<!-- ownership: kit -->
# Agent Runtime and Retrieval Contract

This document defines how an LBrain becomes discoverable, portable, efficient, and predictable across Codex, Claude Code, Hermes, OpenClaw, and future file-capable agents.

## Problem

The seven-layer Markdown structure establishes where authoritative information lives, but structure alone does not guarantee that a fresh agent session will retrieve the right context. A complete runtime needs four independent properties:

1. **Discovery:** the runtime can find the LBrain Skill from any project or conversation on the same machine and user account.
2. **Portability:** the same `SKILL.md` package is accepted by different Agent Skill loaders.
3. **Retrieval:** the runtime can search and open a small, trustworthy context set without preloading the vault.
4. **Execution discipline:** policy decides when and how to retrieve; deterministic code handles operations whose correctness should not depend on free-form model behavior.

The previous Kit described source authority but did not ship a retrieval provider contract. The working qmd configuration therefore lived outside the Kit and could not be reproduced by a new installation.

## Decisions

### Markdown is canonical

LBrain Markdown and Git history are the source of truth. Search indexes, embeddings, caches, MCP processes, and runtime installations are derived state. They may be deleted and rebuilt without losing knowledge.

### Skill is policy; provider is execution

`lbrain-retrieve` decides whether LBrain is relevant, which source role is authoritative, how much context to read, how freshness affects the answer, and when to fall back. It does not implement a second policy server.

The retrieval provider performs bounded operations:

| Operation | Contract |
| --- | --- |
| `status` | Report provider availability and index state without changing knowledge. |
| `query` | Return ranked candidate documents for lexical and semantic intent. |
| `get` | Read one document or a bounded line range. |
| `multi-get` | Read a bounded set of known documents. |
| `update` | Refresh the derived document index. |
| `embed` | Refresh derived vector embeddings. |
| `mcp` | Expose qmd's read-only MCP surface when the host supports MCP. |
| `doctor` | Verify root discovery, provider routing, and fallback readiness. |
| `register` | Record the canonical local LBrain root for copy-installed Skills after an explicit dry run. |

qmd is the default high-quality provider. The bundled filesystem provider is the degraded fallback. The fallback preserves availability, not semantic equivalence: it performs lexical ranking and must identify itself as degraded.

### No LBrain Policy MCP in this version

qmd already exposes the read operations shared by MCP-capable agents. Adding a second LBrain MCP that merely forwards those calls would duplicate the Skill policy, add another schema and process boundary, and create two places for behavior to drift.

A future LBrain MCP is justified only when several runtimes need the same deterministic write transaction and a CLI is no longer an adequate common interface. The unit of extraction is one observed atomic operation, not a speculative all-purpose server.

### Portable Skill Contract

Every LBrain Skill package uses two manifests with separate ownership:

```text
<skill>/
├── SKILL.md       portable Agent Skill entrypoint
├── lbrain.json    LBrain lifecycle and provenance metadata
├── tests/cases.md behavior contract
└── ...            referenced scripts, references, and assets
```

`SKILL.md` frontmatter contains exactly:

```yaml
---
name: example-skill
description: What the skill does and when an agent should use it.
---
```

This is the common baseline accepted by the Agent Skills standard and the supported runtimes. Runtime-specific optional metadata must not be required for core behavior.

`lbrain.json` uses `lbrain.skill.v1` and carries:

- required: `schema`, `version`, `status`, `visibility`, `created`, `updated`;
- optional: `license` and a free-form `provenance` object.

The sidecar is managed and validated by LBrain. Agent runtimes may ignore it. This prevents LBrain lifecycle fields from being rejected by a stricter `SKILL.md` validator while preserving versioning and publication metadata.

## Runtime architecture

```text
User request in any project or conversation
                    |
                    v
        globally installed lbrain-retrieve
          policy, routing, freshness, citations
                    |
          +---------+----------+
          |                    |
          v                    v
      qmd MCP             bundled CLI adapter
   query/get/status     doctor/update/embed/get
          |                    |
          +---------+----------+
                    |
                    v
       qmd local derived index, when healthy
                    |
             unavailable or mismatched
                    |
                    v
       filesystem lexical fallback, degraded
                    |
                    v
          canonical LBrain Markdown files
```

MCP is an optional transport optimization. A shell-capable agent can use the bundled adapter directly. A runtime without access to the local filesystem cannot claim arbitrary-session LBrain access merely because it understands the Skill format.

## Arbitrary-session guarantee

The Kit guarantees on-demand discovery only when all of these conditions hold:

- the session runs as a user who can read the LBrain root;
- the runtime scans the selected global Skill directory;
- the Core Skills have been installed or linked there;
- a copy-installed runtime can resolve the local root registry, `LBRAIN_ROOT`, or an explicit root;
- either qmd or the filesystem fallback can execute;
- remote and sandboxed sessions mount the LBrain explicitly.

The guarantee does not extend to an unrelated machine, cloud sandbox, container, or OS user without the files. Those environments need an explicit mount, synchronization mechanism, or intentionally scoped Context Pack.

## Retrieval behavior

1. Start at `Knowledge/Wiki/Index.md` when a synthesized topic may exist.
2. Use a structured hybrid query with an explicit intent plus lexical and semantic restatements.
3. Rank by source role, not score alone. Prefer Wiki for synthesis, Sources for claims, confirmed Identity for preferences, Projects plus their live source for current state, and Writing for prior expression.
4. Read 3–8 strong documents. Search snippets are candidates, not evidence.
5. Treat an index older than one day as stale when recent LBrain changes matter. Run `update`, then `embed`; if maintenance cannot complete, use direct files and disclose degraded semantic freshness.
6. Cite only files actually read. Separate LBrain records, current verified state, conflicts, and inference.

## qmd configuration

The recommended collection is named `brain`, indexes `**/*.md`, and excludes generated Context Pack trees:

```yaml
collections:
  brain:
    path: /absolute/path/to/LBrain
    pattern: "**/*.md"
    ignore:
      - Outputs/Context-Packs/Candidates/**
      - Outputs/Context-Packs/Repos/**
      - System/session_logs/**
      - System/html-artifacts/**
      - legacy/**
      - .git/**
      - .gstack/**
      - .mcp/**
      - .obsidian/**
      - .wiki-cache/**
```

The adapter reuses an existing matching qmd index when possible. `doctor` checks qmd status and confirms that excluded roots have no indexed files. Query output is path-validated before it is returned; an automatic query falls back to the filesystem when qmd fails, while explicit qmd mode fails closed. A fresh installation may generate a dedicated `lbrain` index without changing another qmd index. The local root registry, qmd configuration, and SQLite files live outside Git and contain no canonical knowledge.

The minimum path contexts are the root, `Knowledge/Wiki`, `Knowledge/Sources`, `Context/Projects`, `Context/Identity`, `Outputs/Writing`, `Skills`, `System`, `Inbox`, and `Archives`. These descriptions help an agent distinguish source roles before opening documents.

## Personal Intelligence write operations

Kit v0.4.0 exposes six deterministic operations through the Core Skill scripts. They are internal Agent entrypoints that read one JSON object from standard input and return one JSON result; they do not introduce a user-facing CLI or a Policy MCP.

| Operation | Contract |
| --- | --- |
| `project.configure` | Preview or apply one human-readable v1 Context Intake Profile while preserving an existing legacy Profile body and recording the accepted/applied Project Proposal. |
| `project.checkpoint` | Reconcile the canonical `source: anchor` rows, append one idempotent complete or partial Intake run, and advance the complete checkpoint only when every required row succeeds. |
| `capture.create` | Save or reuse one private Source/Inbox item with provenance, extraction state, validation, and rollback. |
| `proposal.create` | Create one evidence-linked Skill Improvement Proposal for an enabled active Personal Skill. |
| `skill.preview` | Validate and persist one immutable exact diff, semantic version change, base hash, proposed hash, and preview hash. |
| `skill.apply` | Apply only the approved exact preview, refresh declared runtimes, validate, roll back on failure, and make a replay a no-op. |

Successful results identify the operation, stable operation ID, status, target, affected paths, validation outcome, and rollback outcome. Rejected inputs fail closed before mutation. Core Skills retain semantic decisions such as what to collect, how to weave knowledge, whether a Skill is relevant, and when the user has approved a preview.

## Future atomic write operations

The current Core Skills remain the policy layer. Promote a write to deterministic code only after the same operation is needed by multiple runtimes or free-form execution has produced repeatable errors.

Remaining candidates, in extraction order:

1. `wiki.create` and `wiki.update`: write source-linked synthesis without modifying imported Source bodies.
2. `note.move`: move or rename a note while updating resolvable Wikilinks.
3. `archive.propose` and `archive.apply`: preserve role and history instead of hard deletion.
4. `identity.propose` and `identity.apply`: keep proposal and explicit acceptance as separate transactions.
5. `skill.enable`, `skill.disable`, and `skill.install`: extend the existing Skill Manager transaction surface.
6. `context-pack.preview`, `build`, `publish`, `update`, `verify`, and `revoke`: continue using the existing deterministic Pack implementation.
7. `validate` and `commit`: validate the exact authorized diff and create a local, scoped commit.

Each extracted operation must define inputs, preconditions, idempotency, affected paths, dry-run output, validation, rollback, and a stable machine-readable result before it is exposed through MCP.

## Implementation goals and acceptance

| Goal | Acceptance evidence |
| --- | --- |
| Portable Core Skills | Every installed Skill passes the Kit validator and the current Codex `quick_validate.py`; `SKILL.md` contains no LBrain-only keys. |
| Four-runtime installation | Isolated installation uses symlinks for Codex, Claude Code, and Hermes and copies for OpenClaw, while refusing divergent packages and OpenClaw escaped-link requests. |
| High-quality local retrieval | On a configured machine, `doctor` selects the qmd index whose `brain` collection resolves to this LBrain; a hybrid query returns the expected Wiki material. |
| Arbitrary-session root discovery | The adapter resolves `--root`, `LBRAIN_ROOT`, a local root registry, a current working tree, or a canonical symlinked package without a personal path embedded in Kit files. |
| Degraded availability | With qmd unavailable, `doctor` reports filesystem mode and a lexical query retrieves a deterministic fixture. |
| Safe retrieval | Read bounds must be positive; `get` rejects absolute paths and traversal outside the LBrain; qmd results, generated Pack trees, and hidden/runtime state are excluded. |
| Reproducible setup | A dry run shows the dedicated qmd configuration; apply refuses to overwrite a divergent existing config. |
| No policy duplication | Runtime docs route MCP-capable hosts directly to qmd and other hosts to the adapter; no LBrain Policy MCP is introduced. |

## Non-goals

- bundling qmd binaries, models, embeddings, or SQLite databases in Git;
- guaranteeing access from machines or sandboxes that do not contain LBrain;
- making qmd the source of truth;
- introducing a general write MCP around the six local operations;
- shipping a browser/mobile collector, cloud sync, encryption, or fine-grained access control;
- making autonomous Identity or Skill changes without an explicit review boundary;
- silently editing runtime MCP configuration or overwriting an existing qmd index.
