# Runtime Adapters

LBrain uses the common `SKILL.md` package shape and installs each enabled package as one directory.

| Runtime | Official user location | LBrain adapter behavior |
| --- | --- | --- |
| Codex | `$HOME/.agents/skills/<name>/SKILL.md` | symlink or copy package directory |
| Claude Code | `$HOME/.claude/skills/<name>/SKILL.md` | symlink or copy package directory |
| Hermes | `$HOME/.hermes/skills/<name>/SKILL.md` or configured external directory | symlink or copy package directory |

The installer requires `--target`; it never assumes or writes one of these locations. This keeps previews and isolated tests safe.

Primary references checked for v0.1:

- [OpenAI: Build skills](https://developers.openai.com/codex/skills)
- [Anthropic: Extend Claude with skills](https://code.claude.com/docs/en/skills)
- [Nous Research: Skills](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/skills.md)

Hermes can scan shared external directories, but those directories remain writable unless protected by filesystem permissions. Do not mistake discovery for a write boundary.
