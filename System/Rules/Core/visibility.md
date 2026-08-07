<!-- ownership: kit -->
# Visibility

Every note declares one of three visibility levels:

- `private`: only the user and explicitly authorized local agents; the default.
- `trusted`: intentionally shareable with a defined trusted audience.
- `public`: approved for unrestricted disclosure.

Visibility applies to a note and everything it reveals through links, embeds, attachments, paths, and metadata. A public note must not depend on or identify a private or trusted note. Changing a note to public and publishing it are separate user approvals.

Before sharing, check for credentials, personal identifiers, private URLs, absolute local paths, symlinks, copyrighted full-text captures, and indirect Wikilink disclosure. The validator catches common metadata and link violations but cannot establish that content is safe.
