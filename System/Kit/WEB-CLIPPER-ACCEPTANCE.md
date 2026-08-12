<!-- ownership: kit -->
# Web Clipper Developer-mode Acceptance

This is the release gate for the 0.5.0 browser-to-Wiki milestone. Public Kit tests use only synthetic or redacted fixtures. Real-site content and screenshots stay in the user's private LBrain and must never be committed to the public Kit.

## Repeatable automated evidence

- The Manifest V3 permission test rejects Downloads, browsing history, tabs, permanent host access, and `<all_urls>`.
- Real Chrome rendered-DOM fixtures cover a generic HTML page, authenticated article shape, WeChat, X Article, first-author X Thread, images, document links, subtitle files, and a YouTube-style rendered transcript.
- Native Messaging tests cover Inbox Bundle creation, Obsidian receipt, no-op, immutable new version, staged media hashes, path/symlink/disk checks, PDF text, local OCR fallback, subtitle extraction, partial recovery, Git LFS, validation rollback, and no remote.
- Atomic Weave tests cover multi-Bundle/multi-Wiki preview/apply, woven/skip/pending/rejected outcomes, Source/Wiki backlinks, idempotent replay, new versions returning to Inbox, local Git warning, and full rollback.
- `System/Kit/Examples/Tracer/run.py` covers the framed browser message → Inbox Bundle → Obsidian-openable receipt → Source/Wiki → Skill Improvement lifecycle in a temporary LBrain.

## Required real Chrome dogfood

Before a public 0.5.0 release, load the unpacked extension in the user's Chrome developer mode, register its actual extension ID with the selected Vault, and confirm each row with non-sensitive evidence:

- [ ] Public article: heading/paragraph/list/quote/table/code order and canonical origin are readable in Obsidian.
- [ ] Confirmation gate: before every save, the user sees the detected content type and planned contents; cancel creates no file, download, or Host request.
- [ ] Generic page: a page without suitable article content is identified as an HTML snapshot, opens offline from Obsidian, and creates no files in Downloads.
- [ ] User-authorized logged-in or paid article: rendered content saves without a server refetch or auth loss.
- [ ] WeChat Official Account article: title, author, date, body order, lazy images, and origin are preserved.
- [ ] X Article: long-form body, author, figures/captions, and origin are preserved without timeline noise.
- [ ] X author Thread: first-author posts and quoted posts are preserved; unrelated replies/actions are excluded.
- [ ] Direct PDF: original binary opens offline and extracted/OCR text is searchable with its extraction state shown.
- [ ] Image/document article: images and non-video attachments open offline through stable relative links.
- [ ] Video page with existing subtitles/transcript: original video link and transcript are saved; no video binary appears in the manifest.
- [ ] Receipt and lifecycle: `saved`, `already_saved`, `new_version`, and `partial` are correct; recovery preserves user metadata and notes.
- [ ] Explicit Weave: Inbox original/assets move to Source, Wiki cites the Source, failure rolls everything back, and a new origin version stays in Inbox.
- [ ] Runtime boundary: no Downloads transport, history read, continuous page monitoring, daemon, local port, cloud model, automatic Weave, or Git push occurs.

Do not mark this gate complete merely because automated fixtures pass. Do not publish private dogfood bodies, screenshots, authenticated URLs, or browser state as release evidence.

## Deliberately later

Chrome Web Store submission, video/audio transcription when the page exposes no subtitles, Firefox/Safari/mobile support, and a general MCP Capture/plugin protocol remain roadmap work.
