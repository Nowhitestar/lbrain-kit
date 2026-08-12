<!-- ownership: kit -->
# Contributing

Contributions should improve the public Kit: contracts, templates, Core Skills, validation, adapters, or synthetic examples. Do not submit personal context, credentials, private paths, copyrighted source captures, or private skills.

Before opening a change:

1. Keep the canonical Kit Markdown-first and Python tooling standard-library only. A first-party browser adapter may use dependency-free browser-native JavaScript; optional local extractors and Git LFS integration must fail safely when unavailable.
2. Preserve the Kit/Seeded/User ownership boundary.
3. Add or update the smallest runnable test for non-trivial logic.
4. Run `python3 -m unittest discover -s System/Kit/tests -v` and `python3 System/Kit/check.py`.
5. Describe any migration in `System/Kit/MIGRATIONS/` and `CHANGELOG.md`.

Proposals to promote a Personal Skill into the Kit must remove personal data, include `tests/cases.md`, use an explicit license, and meet the package contract in [[Skills/README]].
