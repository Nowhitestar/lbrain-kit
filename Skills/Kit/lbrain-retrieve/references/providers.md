# Retrieval Providers

Read this reference when configuring or diagnosing LBrain retrieval. The policy remains in `SKILL.md`; providers only search and read derived or canonical local data.

## Provider order

1. Use an already connected qmd MCP whose `brain` collection points to the active LBrain.
2. Otherwise use `scripts/retrieval.py`; it selects a matching qmd index when one exists.
3. If qmd is missing, broken, or points elsewhere, the adapter falls back to bounded filesystem lexical search and marks the result as degraded.

Do not answer from search snippets alone. Open 3–8 selected files and apply the source-role rules in `SKILL.md`.

## Root discovery

The adapter resolves the LBrain root in this order:

1. `--root <path>`;
2. `LBRAIN_ROOT`;
3. the local root registry at `$XDG_CONFIG_HOME/lbrain/root` or `$HOME/.config/lbrain/root`;
4. the current directory and its parents;
5. the canonical path of a symlink-installed Core Skill.

Copy-mode installations used outside the LBrain need the root registry, `LBRAIN_ROOT`, or `--root`. Preview and register it explicitly:

```sh
python3 scripts/retrieval.py register --root <lbrain-root>
python3 scripts/retrieval.py register --root <lbrain-root> --apply
```

Registration stores only the canonical local root path and refuses to overwrite a different existing registration.

## qmd discovery

The adapter resolves qmd from `--qmd-bin`, `LBRAIN_QMD_BIN`, or `qmd` on `PATH`. Use an absolute wrapper with `LBRAIN_QMD_BIN` when native Node modules were built for a different Node ABI.

It probes `LBRAIN_QMD_INDEX`, then `lbrain`, then `index`, and accepts an index only when `qmd collection show brain` resolves to the active LBrain root. This prevents an unrelated collection with the same name from being treated as personal context.

## Commands

```sh
# Provider and root diagnostics
python3 scripts/retrieval.py doctor --root <lbrain-root>
python3 scripts/retrieval.py doctor --root <lbrain-root> --require-qmd

# Hybrid qmd query with automatic filesystem fallback
python3 scripts/retrieval.py query "Context Pack decisions" \
  --semantic "What decisions did we make about portable context packs?" \
  --intent "Recover prior decisions and their rationale" \
  --root <lbrain-root>

# Bounded canonical reads
python3 scripts/retrieval.py get Knowledge/Wiki/Index.md --root <lbrain-root>
python3 scripts/retrieval.py multi-get "Knowledge/Wiki/**/*.md" --root <lbrain-root> --limit 5

# qmd maintenance
python3 scripts/retrieval.py update --root <lbrain-root>
python3 scripts/retrieval.py embed --root <lbrain-root>
```

`query --provider filesystem` is useful for testing the degraded path. `query --provider qmd` fails closed instead of falling back.

## Dedicated qmd configuration

When no matching index exists, preview before writing:

```sh
python3 scripts/retrieval.py configure --root <lbrain-root>
python3 scripts/retrieval.py configure --root <lbrain-root> --apply
python3 scripts/retrieval.py update --root <lbrain-root> --index lbrain
python3 scripts/retrieval.py embed --root <lbrain-root> --index lbrain
```

The generated `lbrain` index is stored in qmd's user configuration directory and excludes generated Context Pack Candidates and Repos. The command refuses to overwrite a different existing file.

## MCP-capable clients

Launch qmd through the adapter so root and index selection remain consistent.

Codex user configuration:

```toml
[mcp_servers.qmd]
command = "python3"
args = ["<installed-skill>/scripts/retrieval.py", "mcp", "--root", "<lbrain-root>"]

[mcp_servers.qmd.env]
LBRAIN_QMD_BIN = "<absolute-qmd-or-wrapper>"
```

Claude-compatible JSON configuration:

```json
{
  "mcpServers": {
    "qmd": {
      "command": "python3",
      "args": ["<installed-skill>/scripts/retrieval.py", "mcp", "--root", "<lbrain-root>"],
      "env": {"LBRAIN_QMD_BIN": "<absolute-qmd-or-wrapper>"}
    }
  }
}
```

Hermes and OpenClaw can use the same CLI adapter even when their MCP configuration surface differs. Do not make MCP availability a prerequisite for the Skill.

## Freshness and failure

- Treat a qmd index older than one day as stale when recent LBrain changes matter.
- Run `update` before `embed`.
- If either operation fails, read direct files and state that semantic results may be stale.
- A qmd failure is not an empty knowledge result. Distinguish provider failure, zero matches, and missing files.
- qmd paths and ranks are retrieval hints. Canonical Markdown content and source roles decide the answer.
