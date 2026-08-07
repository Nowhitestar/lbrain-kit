<!-- ownership: kit -->
# LBrain Kit

LBrain Kit is a Git-versioned, Markdown-native personal context system for people and their agents. It keeps raw sources, synthesized knowledge, personal context, executable skills, and created outputs separate while remaining usable in Obsidian and any text editor. Selected context can be compiled into independently versioned Context Packs for another person or agent without sharing the private LBrain.

The Kit is private by default. It does not include cloud sync, a database, a custom updater, or a hosted service.

## Start here

1. Read [[HOME]].
2. Follow [[System/Kit/SETUP]].
3. Capture uncertain material in [[Inbox/README|Inbox]].
4. Run `python3 System/Kit/check.py` before committing significant changes.

All internal links use Obsidian-compatible Wikilinks such as `[[Knowledge/Wiki/Index]]`. Markdown readers that do not resolve Wikilinks can still browse the directory tree.

## Seven layers

| Layer | Purpose |
| --- | --- |
| `Inbox/` | Temporary, unprocessed captures |
| `Knowledge/` | Sources and source-grounded synthesis |
| `Context/` | Identity, enduring areas, and active projects |
| `Skills/` | Reusable agent capabilities |
| `Outputs/` | Draft and published work, including portable Context Packs |
| `System/` | Kit contracts, rules, templates, and proposals |
| `Archives/` | Role-preserving inactive material |

Each semantic directory contains a `README.md` contract. Kit releases may update those contracts. Put personal navigation in `Index.md` and local guidance in `LOCAL.md` instead of editing a Kit-owned README.

## Ownership

- **Kit-owned (K):** contracts, core rules, validators, and Core Skills. Updated by Kit releases.
- **Seeded (S):** useful starting notes copied once, then owned by the user.
- **User-owned (U):** personal knowledge and skills. Never overwritten by a Kit upgrade.

See [[System/Kit/OWNERSHIP]] for the complete boundary and [[System/Rules/Core/git-workflow]] for the two-remote Git model.

## License

Kit-owned material is released under the MIT License. Personal content added to a derived LBrain is not automatically licensed; see [[System/Kit/OWNERSHIP]].
