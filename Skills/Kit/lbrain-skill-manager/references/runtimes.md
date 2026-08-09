# Runtime Adapters

LBrain uses the common `SKILL.md` package shape and installs each enabled package as one directory.

| Runtime | Official user location | LBrain adapter behavior |
| --- | --- | --- |
| Codex | `$HOME/.agents/skills/<name>/SKILL.md` | symlink or copy package directory |
| Claude Code | `$HOME/.claude/skills/<name>/SKILL.md` | symlink or copy package directory |
| Hermes | `$HOME/.hermes/skills/<name>/SKILL.md` or configured external directory | symlink or copy package directory |
| OpenClaw | `$HOME/.agents/skills/<name>/SKILL.md`, `$HOME/.openclaw/skills/<name>/SKILL.md`, or configured extra directory | copy package directory |

The installer requires `--target`; it never assumes or writes one of these locations. This keeps previews and isolated tests safe. It defaults to symlink mode for Codex, Claude Code, and Hermes, and copy mode for OpenClaw. Current OpenClaw rejects a Skill symlink when it resolves outside the configured Skill root, so the installer fails closed if `--runtime openclaw --mode symlink` is requested. Copy mode excludes repository internals and generated caches (`.git`, `__pycache__`, bytecode, and `.DS_Store`).

Primary references checked for v0.1:

- [OpenAI: Build skills](https://developers.openai.com/codex/skills)
- [Anthropic: Extend Claude with skills](https://code.claude.com/docs/en/skills)
- [Nous Research: Skills](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/skills.md)
- [OpenClaw: Skills](https://github.com/openclaw/openclaw/blob/main/docs/tools/skills.md)

Hermes can scan configured external directories. OpenClaw also scans multiple Skill roots but applies root-containment checks to symlinks. Discovery remains separate from write permissions.
