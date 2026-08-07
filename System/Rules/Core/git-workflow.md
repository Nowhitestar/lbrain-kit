<!-- ownership: kit -->
# Git Workflow

LBrain has two independent version lines:

- `kit/main` and local `kit-base` track the public Kit.
- `origin/main` and local `main` track the user's private context.

Personal `main` merges formal Kit release tags, never arbitrary Kit commits. The public `kit` remote must have a disabled push URL so a normal push cannot disclose personal content. The private `origin` remote is strongly recommended but optional.

## Working branches

Use `main` for ordinary captures, weaving, reviews, and Personal Skill work. Use a short-lived branch for a major migration or broad reorganization, then merge only after validation and review.

## Agent behavior

After an authorized change, validate it and create a local commit by default. Never push, rewrite history, change a remote, or publish a release without explicit user approval.

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
