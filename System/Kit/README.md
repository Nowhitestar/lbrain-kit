<!-- ownership: kit -->
# Kit

This directory is the release and maintenance control plane for LBrain Kit.

- `VERSION` is the installed Kit version.
- `CHANGELOG.md` explains release changes.
- `SETUP.md` defines initialization and upgrades.
- `OWNERSHIP.md` defines files a Kit release may and may not change.
- `AGENT-RUNTIME.md` defines portable Skill metadata, retrieval providers, qmd integration, and arbitrary-session boundaries.
- `CONTEXT_PACK_SPEC.md` records the implemented Context Pack contract and lifecycle.
- `MIGRATIONS/` contains explicit, reviewable migration instructions.
- `Examples/` contains synthetic material only, including complete LBrain and Context Pack traces.
- `check.py` validates an LBrain without modifying it.

The Kit uses Git releases as its updater. There is no custom update service.
