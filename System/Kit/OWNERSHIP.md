<!-- ownership: kit -->
# Ownership Contract

Ownership determines what an upgrade may replace. It is independent of Git authorship.

## Kit-owned (K)

Kit releases may update these paths:

- root `README.md`, `AGENTS.md`, `LICENSE`, `.gitignore`, `.gitattributes`, `CONTRIBUTING.md`, and `SECURITY.md`;
- every semantic directory `README.md`;
- all of `System/Kit/`, `System/Rules/Core/`, and `System/Templates/Core/`;
- all of `Skills/Kit/`.

Do not personalize these files. Use the extension points below.

## Seeded (S)

These files are copied once and then become user-owned:

- `HOME.md`;
- `Knowledge/Wiki/Index.md`;
- `Context/Identity/Profile.md`, `State.md`, and `Principles.md`;
- `Skills/Enabled.md`.

The public Kit may update a seed for new installations, but an installed copy is user-owned and must not be silently overwritten. A migration must identify any required manual reconciliation, preserve personalization, and show the exact intended change.

## User-owned (U)

All personal content is user-owned, including:

- captures, Sources, Wiki notes, Areas, Projects, Outputs, and Archives;
- `System/Rules/Local/`, `System/Proposals/`, and optional `LOCAL.md` or `Index.md` files;
- `Skills/Personal/` and each Personal Skill's history and license.
- Pack Definitions, `.gitmodules`, and Pack Submodule gitlinks under `Outputs/Context-Packs/Repos/`.

Kit upgrades never overwrite or delete User-owned material.

Pack repository contents have their own Git history and explicit license. They are not Kit-owned merely because a Submodule is mounted inside LBrain.

## Extension points

- Put directory-specific user guidance in `LOCAL.md`.
- Put curated navigation in `Index.md`.
- Put personal operating rules in `System/Rules/Local/`.
- Extend or override agent behavior through `Skills/Personal/` without editing Core Skills.

## Licensing boundary

The root MIT License covers Kit-owned material distributed by the Kit maintainers. It does not grant rights to personal content, private Sources, or Personal Skills added by a user. A Personal Skill intended for distribution needs an explicit license of its own.
