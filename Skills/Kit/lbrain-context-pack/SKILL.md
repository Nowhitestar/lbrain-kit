---
name: lbrain-context-pack
description: Creates, previews, builds, verifies, publishes, updates, revokes, and forks portable Context Packs from canonical LBrain material. Use when the user asks to package or share selected context with another agent.
---
# LBrain Context Pack

Treat LBrain as canonical and every Pack as a compiled release artifact.

1. Read the Pack Definition under `Outputs/Context-Packs/`.
2. Run `scripts/pack.py --root <lbrain> preview <definition>` before any build or Git operation.
3. Resolve every blocked dependency by sanitizing it into portable text, omitting the dependent material, or cancelling. Never change canonical visibility automatically.
4. Build only a local Candidate. Building does not authorize publication.
5. Before publication, show the complete diff, disclosure summary, destination, visibility, license, and proposed version.
6. Publish, push, change a remote, move a Submodule pointer, revoke, or fork only after explicit approval for that operation.
   GitHub first publication requires separate approval to create the repository and to publish the reviewed Candidate.
7. Keep Pack `main` on the latest approved release and tag releases with `YYYY.MM.DD.N`.
8. Never claim revocation can recall downloaded copies.

Use the full lifecycle: `create`, `preview`, `build`, `publish`, `update`, `verify`, `revoke`, and `fork`. There is no Minimal profile.
