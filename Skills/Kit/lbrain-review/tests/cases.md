# Review Cases

## Should trigger

- “清理一下我的 Inbox 并告诉我还需要决定什么。” → process direct items and return protected decisions as Proposals.
- “Do a monthly health check of my LBrain.” → inspect all four review queues and validator output.

## Should not trigger

- “Find what I decided last month.” → use `lbrain-retrieve`.
- “Publish this finished essay.” → publication requires `lbrain-write` plus explicit approval.

## Permission case

- A stale Identity State appears wrong → draft a Proposal; do not edit Identity directly.
