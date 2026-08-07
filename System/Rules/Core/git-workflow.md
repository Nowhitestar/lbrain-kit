<!-- ownership: kit -->
# Git Workflow

LBrain has two independent version lines:

- `kit/main` and local `kit-base` track the public Kit.
- `origin/main` and local `main` track the user's private context.

Personal `main` merges formal Kit release tags, never arbitrary Kit commits. The public `kit` remote must have a disabled push URL so a normal push cannot disclose personal content. The private `origin` remote is strongly recommended but optional.

Each published Context Pack has a third, independent version line. Its repository `main` is the latest approved release and CalVer tags identify releases. The private LBrain records an exact release commit as a Git Submodule under `Outputs/Context-Packs/Repos/`; Pack updates never move that pointer silently.

## Working branches

Use `main` for ordinary captures, weaving, reviews, and Personal Skill work. Use a short-lived branch for a major migration or broad reorganization, then merge only after validation and review.

## Agent behavior

After an authorized change, validate it and create a local commit by default. Never push, rewrite history, change a remote, or publish a release without explicit user approval.

Context Pack publication approval covers the disclosed Pack commit, release tag, named remote push, Submodule registration, and private parent commit shown in its publication plan. Preview and Candidate build authorize none of those actions.

## Commit prefixes

- `capture:` new Inbox or Source material
- `weave:` Wiki synthesis
- `identity:` accepted Identity change
- `project:` Area or Project state
- `writing:` draft output
- `publish:` confirmed publication state
- `skill:` Personal or Core Skill work
- `proposal:` protected changes awaiting a user decision
- `archive:` role-preserving archival
- `kit:` Kit structure, rules, releases, and migrations
