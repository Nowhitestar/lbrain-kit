<!-- ownership: kit -->
# LBrain Kit 0.5.0 Release Evidence

Date: 2026-08-21

## Browser Capture and Weave acceptance

- The first-party Manifest V3 extension captures rendered authenticated pages through an on-demand Native Messaging Host without Downloads, browsing history, permanent site permissions, a daemon, local port, cloud model, or automatic push.
- Durable Capture Bundles preserve stable identity, immutable asset versions, SHA-256 manifests, Obsidian-relative media, idempotent receipts, partial recovery, and local-only commits.
- Hash-bound Weave transactions promote or archive Bundles atomically and roll back failed multi-note updates.
- The Personal Intelligence Tracer passes the browser message → Inbox → receipt → Source/Wiki → Skill Improvement lifecycle and idempotent replay.

## Final local verification

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s System/Kit/tests -v`: 113 tests passed; 3 optional real-Chrome tests skipped because `LBRAIN_NODE_PATH` was not configured.
- `PYTHONDONTWRITEBYTECODE=1 python3 System/Kit/check.py`: 0 errors; the standalone public release repository reports only the expected missing-personal-`kit`-remote warning.
- `PYTHONDONTWRITEBYTECODE=1 python3 System/Kit/Examples/Tracer/run.py`: Personal Intelligence trace passed.
- Browser-extension JavaScript syntax checks, manifest JSON parsing, relevant Python compilation, and `git diff --check` passed.

## Release boundary

This evidence covers only the public, Kit-owned contents of v0.5.0. The release contains no private Capture or Context content, Personal Skills, credentials, real extension IDs, local runtime state, or automatic publication behavior.
