---
name: lbrain-capture
description: Captures new material into the correct LBrain intake path. Use when the user asks to save, capture, collect, or remember information.
version: 0.1.0
status: active
visibility: public
created: 2026-08-07
updated: 2026-08-07
---
# LBrain Capture

Capture information without prematurely turning it into truth.

1. Confirm the active LBrain root and read the nearest directory `README.md`.
2. Check whether the material already exists before creating a duplicate.
3. Put uncertain or unclassified material in `Inbox/`.
4. Create a Source directly when origin and durable value are clear. Copy `System/Templates/Core/source.md`, record provenance, and capture only the lawful amount needed.
5. Default to `visibility: private`. Never store credentials or secrets.
6. Preserve quoted or imported source text; add interpretation elsewhere.
7. Run `python3 System/Kit/check.py` and commit an authorized capture locally with `capture:`. Do not push.

Do not use this skill for source synthesis; use `lbrain-weave` after capture.
