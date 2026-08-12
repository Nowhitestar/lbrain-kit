# LBrain Web Clipper

This unpacked Chrome extension saves the current rendered page through the on-demand LBrain Native Messaging Host. It uses the user's current browser session and does not refetch the source URL.

## Developer-mode install

1. Decide which LBrain/Obsidian Vault should receive captures. It must contain `System/Kit/check.py`; the Host refuses an arbitrary directory. When more than one Vault exists, give the Agent the exact selected root.
2. Open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**, and select this `browser-extension` directory.
3. Copy the extension ID shown by Chrome and ask the connected Agent to register that ID with the selected LBrain. The Agent uses `scripts/install_native_host.py`; the user does not need an LBrain CLI or a running background process.
4. Pin **LBrain Web Clipper** if desired. Click its toolbar action, review the extension confirmation that says exactly what will be saved, then confirm. The context-menu page and selection actions use the same gate.
5. Open the receipt in Obsidian. The original first appears under `Inbox/Captures`; classification and knowledge weaving happen later.

Chrome starts the local Host only for a save request. The extension requests no browsing-history or permanent site access, runs no cloud model, and never pushes Git history.

The extension never uses Chrome's Downloads API. The open confirmation window holds the prepared capture in memory, so suspending the extension worker while the user reviews it does not lose the preview and cancellation writes nothing locally. After confirmation, Chrome creates a snapshot of the current authenticated tab and streams it with per-chunk SHA-256 verification and backpressure to the on-demand Host. The Host extracts only requested MHTML parts with bounded memory, keeps only verified non-video assets, writes the Bundle atomically, and removes its temporary stream files. A failed image leaves the article as a `partial` Durable Capture instead of discarding its text.

There is no fixed media-size ceiling: the Host checks available disk space before accepting a stream, and the extension reads each browser Blob in bounded chunks. Video remains excluded by actual MIME/type checks and known container signatures rather than filename alone.

The confirmation distinguishes article body, X Thread, selection, direct file, video link/subtitles, and generic HTML. When no suitable article body is found and the page is not a direct file or supported video page, LBrain stores one sanitized, offline-readable HTML snapshot instead of pretending that navigation and cards are an article. Canceling the confirmation creates no local file or Native Host request.

The page adapter preserves WeChat article bodies, X Articles, and chronological self-replies explicitly connected to the first X post. Quoted posts inside that author's Thread remain part of the source; adjacent recommendations, unrelated replies, and action controls do not.

Direct PDFs, images, and non-video documents are preserved as local Bundle assets. PDF text is extracted locally, with OCR as a fallback when the local tools are available. Article attachments and subtitle files use the same browser-authenticated staging path. Video binaries are never downloaded; the page's original video link and available transcript are saved instead. A later retry can fill a partial Bundle without replacing user metadata or notes.

## Troubleshooting

- **Native Host not found:** copy the current extension ID again and ask the Agent to register it. Loading the same directory under a different Chrome profile can produce a different ID.
- **Capture needs attention:** keep the tab open and retry after checking page permission, free disk space, and the selected Vault. Extraction or routing failures are never converted into a false success.
- **`partial` receipt:** the readable article is already safe in Inbox. Retry from the same page to fill missing managed assets; edited metadata and user sections are preserved.
- **Saved note but missing local media:** inspect the note's `media_manifest`, keep the source tab available, and retry. No recovery file is left in Downloads.
- **PDF has no searchable text:** install local Poppler (`pdftotext`, `pdftoppm`) and Tesseract, then retry. The original PDF remains preserved even when extraction is unavailable.
- **Extension updated:** click **Reload** on `chrome://extensions`. Re-register only if Chrome shows a different extension ID or the LBrain root changed.

To remove the integration, remove the unpacked extension and ask the Agent to unregister the Native Host. Uninstall preserves the private Host staging directory but never deletes Capture Bundles.

## Privacy boundary

The extension has no browsing-history or permanent all-sites permission. When a linked document, subtitle, or audio file is on another origin, the confirmation may ask Chrome for temporary access to that exact origin; the extension removes only permission added by that capture after the save attempt. It runs only after a toolbar/context-menu gesture, does not monitor pages in the background, calls no cloud model, opens no local port, and starts the Python Host only for the Native Messaging request. Capture and Weave may create local Git commits but never push.

## Later roadmap

Chrome Web Store submission, local transcription when a video page exposes no subtitles, Firefox/Safari/mobile support, and a general MCP Capture/plugin protocol are deliberately outside this developer-mode milestone.
