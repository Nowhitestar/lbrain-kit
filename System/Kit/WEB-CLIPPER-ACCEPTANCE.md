<!-- ownership: kit -->
# Web Clipper Developer-mode Acceptance

This is the release gate for the 0.5.0 browser-to-Wiki milestone. Public Kit tests use only synthetic or redacted fixtures. Real-site content and screenshots stay in the user's private LBrain and must never be committed to the public Kit.

## Repeatable automated evidence

- The Manifest V3 permission test rejects Downloads, browsing history, tabs, permanent host access, and `<all_urls>`.
- Real Chrome rendered-DOM fixtures cover a generic HTML page, authenticated article shape, WeChat, one X post, X Article, first-author X Thread, images, document links, subtitle files, and a YouTube-style rendered transcript.
- Native Messaging tests cover Inbox Bundle creation, Obsidian receipt, no-op, immutable new version, staged media hashes, path/symlink/disk checks, PDF text, local OCR fallback, subtitle extraction, partial recovery, Git LFS, validation rollback, and no remote.
- Atomic Weave tests cover multi-Bundle/multi-Wiki preview/apply, woven/skip/pending/rejected outcomes, Source/Wiki backlinks, idempotent replay, new versions returning to Inbox, local Git warning, and full rollback.
- `System/Kit/Examples/Tracer/run.py` covers the framed browser message → Inbox Bundle → Obsidian-openable receipt → Source/Wiki → Skill Improvement lifecycle in a temporary LBrain.

## Required real Chrome dogfood

Before a public 0.5.0 release, load the unpacked extension in the user's Chrome developer mode, register its actual extension ID with the selected Vault, and confirm each row with non-sensitive evidence:

- [x] Public article: heading/paragraph/list/quote/table/code order and canonical origin are readable in Obsidian. *(2026-08-17 private dogfood; MDN rendered article v4 preserved canonical origin, headings, lists, and tables, with the reading view checked in Obsidian after fixing DOM formatting whitespace.)*
- [x] Confirmation gate: before every save, the user sees the detected content type and planned contents; cancel creates no file, download, or Host request. *(2026-08-13 private dogfood; filesystem and Downloads checked before/after cancel. 2026-08-18 developer-mode dogfood; the toolbar-anchored popup appeared without a separate window, changed immediately to compact saving status after confirmation, then reported `already_saved` without a new version or note rewrite.)*
- [x] Generic page: a page without suitable article content is identified as an HTML snapshot, opens offline from Obsidian, and creates no files in Downloads. *(2026-08-13 private dogfood; local snapshot and all manifest hashes checked without recording page content.)*
- [x] User-authorized logged-in or paid article: rendered content saves without a server refetch or auth loss. *(2026-08-17 private dogfood; paid rendered view produced one complete v1 Bundle with two verified local images and a clean Obsidian reading view; duplicate save created no v2.)*
- [x] WeChat Official Account article: title, author, date, body order, lazy images, and origin are preserved. *(2026-08-18 private dogfood; the toolbar-anchored popup returned `already_saved` to the existing v1 target, with no v2, mtime, size, or SHA-256 change. The unchanged Obsidian note had already been checked for title, author, date, origin, readable body order, and 12 local images.)*
- [x] X Article: long-form body, author, figures/captions, and origin are preserved without timeline noise. *(2026-08-17 private dogfood; long-form v3, author/origin, three local JPEGs, captions, and reading order were checked in Obsidian without timeline/action chrome.)*
- [x] X post: author, timestamp, quoted content, media, and status origin are preserved as Markdown without replies/actions. *(2026-08-13 private dogfood; translated-view disclosure, exact status origin, one local JPEG, manifest hash, and reply/action exclusion checked.)*
- [x] X author Thread: first-author posts form one readable, chronological Markdown document with working inline images; repeated author/action chrome and unrelated replies are excluded; an automatic-translation view is disclosed before save and in the Capture. *(2026-08-13 private dogfood; six source posts, five local JPEGs, manifest hashes, canonical origin, and Obsidian reading view checked.)*
- [x] Direct PDF: original binary opens offline and extracted/OCR text is searchable with its extraction state shown. *(2026-08-17 private dogfood; the verified 35-page local PDF opened in Obsidian and extracted text was searchable with complete state shown.)*
- [x] Image/document article: images and non-video attachments open offline through stable relative links. *(2026-08-17 private dogfood; three local images rendered in Obsidian and a linked text attachment opened from the versioned asset tree.)*
- [x] Video page with existing subtitles/transcript: original video link and transcript are saved; no video binary appears in the manifest. *(2026-08-17 private dogfood; original link, five local VTT files, and extracted transcript were checked; the manifest contained no video/audio binary and correctly remained partial only for two missing decorative icons.)*
- [x] Receipt and lifecycle: `saved`, `already_saved`, `new_version`, and `partial` are correct; recovery preserves user metadata and notes. *(2026-08-17 private dogfood; a deliberately partial v1 recovered in place to complete v1 while preserving an injected metadata marker and user note; its local PNG matched the manifest SHA-256, an unchanged repeat was `already_saved` with no v2 or mtime change, and changed rendered content produced an immutable linked version.)*
- [x] Explicit Weave: Inbox original/assets move to Source, Wiki cites the Source, failure rolls everything back, and a new origin version stays in Inbox. *(2026-08-13 private dogfood; conflict-free preview/apply promoted one Thread and five verified JPEGs, created one cited Wiki analysis, and automated rollback/new-version tests passed.)*
- [x] Runtime boundary: no Downloads transport, history read, continuous page monitoring, daemon, local port, cloud model, automatic Weave, or Git push occurs. *(2026-08-13 developer-mode runtime and local process/filesystem boundary checked.)*

Do not mark this gate complete merely because automated fixtures pass. Do not publish private dogfood bodies, screenshots, authenticated URLs, or browser state as release evidence.

## Deliberately later

Chrome Web Store submission, video/audio transcription when the page exposes no subtitles, Firefox/Safari/mobile support, and a general MCP Capture/plugin protocol remain roadmap work.
