---
name: lbrain-write
description: Creates traceable writing from LBrain context. Use when the user asks to draft, rewrite, adapt, or publish content using their knowledge and style.
---
# LBrain Write

Create output grounded in the user's context and intended audience.

1. Retrieve relevant Sources, Wiki, confirmed Identity, and prior Writing without loading unrelated context.
2. Confirm audience, channel, and constraints from the request or existing context.
3. Copy `System/Templates/Core/writing.md` for a durable draft and list supporting notes in `sources`.
4. Preserve the boundary between sourced fact, inference, and creative framing. Verify changing public facts live.
5. Default the draft to private. Public visibility and publication each require explicit user approval.
6. After real publication succeeds, record the destination in `published_url`; do not mark an attempted publication as complete.
7. Validate and commit locally with `writing:` or `publish:`. Do not push unless explicitly asked.
