<!-- ownership: kit -->
# Ownership Contract

Ownership determines what an upgrade may replace. It is independent of Git authorship.

## Kit-owned (K)

Kit releases may update these paths:

- root `README.md`, `AGENTS.md`, `LICENSE`, `.gitignore`, `CONTRIBUTING.md`, and `SECURITY.md`;
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

Kit releases must not modify seeded files after the initial release. A migration may describe an optional manual change but cannot apply it silently.

## User-owned (U)

All personal content is user-owned, including:

- captures, Sources, Wiki notes, Areas, Projects, Outputs, and Archives;
- `System/Rules/Local/`, `System/Proposals/`, and optional `LOCAL.md` or `Index.md` files;
- `Skills/Personal/` and each Personal Skill's history and license.

Kit upgrades never overwrite or delete User-owned material.

## Extension points

- Put directory-specific user guidance in `LOCAL.md`.
- Put curated navigation in `Index.md`.
- Put personal operating rules in `System/Rules/Local/`.
- Extend or override agent behavior through `Skills/Personal/` without editing Core Skills.

## Licensing boundary

The root MIT License covers Kit-owned material distributed by the Kit maintainers. It does not grant rights to personal content, private Sources, or Personal Skills added by a user. A Personal Skill intended for distribution needs an explicit license of its own.
