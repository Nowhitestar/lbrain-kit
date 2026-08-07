# Context Pack Skill Cases

## Positive triggers

- "Create a Context Pack for the AgentKey growth project."
- "Preview what this Pack would disclose."
- "Build a local Candidate from this Definition."
- "Check whether my pinned Pack has an update."

## Negative triggers

- A request to remember one new fact uses LBrain Capture.
- A request to synthesize Sources into Knowledge uses LBrain Weave.
- A request to install an existing Skill uses LBrain Skill Manager.

## Expected behavior

- Preview is read-only and reports direct selections, dependencies, exclusions, blockers, and the complete redacted Candidate diff.
- Build creates only a local Candidate.
- Publication shows the full disclosure, redacted Candidate diff, license, version, and Git plan before asking for approval.
- Embedded Wikilinks and relative Markdown assets are included and rewritten to portable relative links.
- A consumer update verifies that remote `main` descends from the pinned release and has a newer manifest plus matching CalVer tag before offering to move the Submodule pointer.
- Duplicate Definition IDs and matching partial remote releases are handled deterministically: collisions stop, while an approved interrupted push can resume without recreating its repository.

## Safety edge

- A public Pack that reaches a private dependency, quoted secret, incompatible Personal Skill license, or symlink pauses for sanitize, omit, or cancel. It never changes the private note's visibility or publishes in the background.
