<!-- ownership: kit -->
# Agent Permissions

Every change is either **Direct**, **Proposal**, or **Forbidden without explicit instruction**.

| Scope | Direct | Proposal required | Forbidden without explicit instruction |
| --- | --- | --- | --- |
| Inbox | capture, classify, organize | — | publish private material |
| Sources | create, fix metadata, add provenance | materially rewrite captured text | fabricate or remove provenance |
| Wiki | source-grounded create/update | unsupported interpretation presented as durable truth | invent sources |
| Identity | read | any content change | silently infer and confirm identity |
| Areas | verified routine status | scope, ownership, or policy change | claim unverified current state |
| Projects | sync verified source status | outcome or scope change | override the declared source of truth |
| Writing | create and revise drafts | public visibility or publication | publish without approval |
| Local Rules | draft | activate a rule that changes permissions | weaken a safety boundary silently |
| Core Rules, Templates, Kit Skills | — | change through a Kit contribution/release | edit as personal customization |
| Personal Skills | draft, validate, activate privately | public visibility, publication, destructive install | expose private assets or secrets |
| Proposals | create and update evidence | accept, reject, or apply | self-approve |
| Archives | add inactive material | restore when impact is material | hard-delete by default |
| Git | validated local commit | push, remote change, history rewrite | push personal main to kit |

When several rows apply, use the most restrictive one. A Proposal records intent; only an explicit user decision changes it to `accepted` or `rejected`. Apply an accepted Proposal separately and record evidence.
