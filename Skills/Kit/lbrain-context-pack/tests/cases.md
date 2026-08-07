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

- Preview is read-only and reports direct selections, dependencies, exclusions, and blockers.
- Build creates only a local Candidate.
- Publication shows the full disclosure and Git plan before asking for approval.

## Safety edge

- A public Pack that reaches a private dependency pauses for sanitize, omit, or cancel. It never changes the private note's visibility or publishes in the background.
