<!-- ownership: kit -->
# Security

LBrain is designed for private context, not as an access-control or encryption system.

- Keep the personal `origin` repository private.
- Do not store credentials, secrets, recovery codes, session cookies, or private keys in Markdown.
- Review `visibility` and links before sharing or exporting any note.
- Treat symlinks and absolute paths as possible disclosure vectors.
- Never push personal `main` to the public `kit` remote; use the protected remote setup in [[System/Rules/Core/git-workflow]].
- The validator detects common disclosure risks but is not a security boundary.
- Treat a public Context Pack repository as irreversible disclosure. Review the Candidate semantically after automated checks; repository creation and Pack publication require separate approvals.

Report vulnerabilities privately to the maintainer rather than opening a public issue containing sensitive details.
