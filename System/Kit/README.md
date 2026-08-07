<!-- ownership: kit -->
# Kit

This directory is the release and maintenance control plane for LBrain Kit.

- `VERSION` is the installed Kit version.
- `CHANGELOG.md` explains release changes.
- `SETUP.md` defines initialization and upgrades.
- `OWNERSHIP.md` defines files a Kit release may and may not change.
- `MIGRATIONS/` contains explicit, reviewable migration instructions.
- `Examples/` contains synthetic material only.
- `check.py` validates an LBrain without modifying it.

The Kit uses Git releases as its updater. There is no custom update service.
