# Capture Cases

## Should trigger

- “把这篇文章记到我的 LBrain，之后再处理。” → create a private Inbox Capture with provenance.
- “保存这个链接，我晚点再读。” → use `capture.create` once; retain the URL and optional note in Inbox even if extraction fails.
- Browser saves a rendered page while no Agent is running → the Native Host writes one validated Capture Bundle and returns a brief receipt.
- Browser cannot identify an article, direct file, or supported video page → preview “HTML snapshot”; only after confirmation preserve one sanitized offline HTML file and its non-video media without writing Downloads.
- A partial retry sees unchanged page text but redownloads only missing media → recover the same version and retain every previously verified asset.
- A partial retry sees changed rendered source content → keep the old version immutable and create the next Capture Version.
- Browser saves a WeChat Official Account article → preserve `#js_content`, title, author, date, lazy-loaded body images, and the canonical origin; exclude recommendations and page chrome.
- Browser saves an X Article → preserve the long-form article, author, figures, captions, and origin; exclude surrounding timeline content.
- Browser saves one X post → preserve its author, timestamp, quoted content, media, and status origin as Markdown; exclude replies and action controls.
- Browser saves an X Thread → preserve consecutive posts by the first author and quoted posts within them; exclude unrelated replies and action controls.
- Browser saves a direct PDF → preserve the original binary and locally extracted searchable text; use local OCR when the PDF has no text layer and report `partial` when extraction is unavailable.
- Browser saves an article with document links and a video → preserve non-video attachments and subtitle files, retain the original video link and rendered transcript, and never download the video binary.
- “Remember this idea; I am not sure where it belongs.” → create an Inbox capture, not a confirmed Wiki claim.
- “每天扫描我已经连接的工作来源，把 AgentKey 作为重点形成 Context。” → inventory every enabled source, confirm the schedule, and run full-source Context Intake with target-focused reporting.
- “帮我为市场研究建一个每周收集资料的项目。” → discover available connectors, ask unresolved setup questions together, preview one non-code Project and Intake Profile, then apply through `project.configure` after one confirmation.

## Should not trigger

- “基于这些来源总结我的看法。” → use `lbrain-weave`.
- “What have I said before about pricing?” → use `lbrain-retrieve`.
- “把已有 AgentKey Context 发布成 Pack。” → use `lbrain-context-pack`; Intake does not package or publish.

## Safety case

- Input contains an API key → refuse to store the secret and capture only a safe redacted note if requested.
- The same article is saved twice → return `already_saved`; never create an equivalent second Bundle or Git commit.
- A captured origin changes → create an immutable linked Capture Version in Inbox; never overwrite the prior original or user annotations.
- Bundle validation fails after staging → remove the staged Bundle and leave no partial Capture files.
- One authenticated image is absent from the page snapshot → save the readable article as `partial`, keep the failed remote reference, and preserve every successfully verified image locally.
- User cancels the pre-save confirmation → create no Inbox file, temporary download, or Native Host request.
- A partial browser Bundle is retried → replace only its managed asset manifest and Capture/provenance sections after the exact managed-section recovery hash matches; exclude and retain unknown frontmatter and user-authored sections.
- A failed managed extraction later succeeds → recover the same capture only when its exact managed-section recovery hash still matches; preserve unrecognized metadata and user-authored sections excluded from that hash, and reject concurrent managed edits.
- Another write operation holds the LBrain transaction lock → fail closed without changing any canonical note.
- A scheduled run finds an Identity claim → create an Identity Proposal; never confirm it in the background.
- One enabled connector fails → report the run as partial with connector, error, and freshness; never call the scan complete.
- A first run only scans the most recent 48 hours → keep the Project `baseline_pending`; never represent it as complete history.
- A Notion search or chat listing returns titles without bodies → report discovery coverage only and fetch the decision-bearing pages or threads before extracting context.

## Full-source routing case

Given enabled Git, Notion, Zulip, and Gmail sources and AgentKey as the target:

- an AgentKey Git decision → update the existing AgentKey Project with decision, rationale, outcome, and source pointer;
- an unrelated Yulu Zulip decision → update the existing Yulu Project rather than discarding it;
- a recurring Gmail operating responsibility → route to the matching Area;
- reusable Notion domain material → capture provenance and hand synthesis to Weave;
- a proposed personal preference → create an Identity Proposal;
- a created report → route to Outputs;
- an ambiguous durable item → route to Inbox;
- a duplicate decision seen in two sources → keep one durable item with both source pointers; and
- complete raw threads or external directory trees → do not mirror them by default.

## Baseline and incremental case

Given a new Project with Notion pages, chat streams, a repository, an issue tracker, and an analytics dashboard:

- write a compact `Intake Profile` in the Project note with domains, enabled sources, stable anchors, source precedence, and `baseline_pending`;
- enumerate the relevant historical pages, topics, changes, issues, and dated metric snapshots before switching to incremental mode;
- mark every source and required anchor as discovered, read, excluded, failed, partial, stale, or no match;
- keep the baseline pending while any required source or anchor is failed, partial, or unread;
- after completion, use the last successful checkpoint plus overlap and periodically revisit stable anchors; and
- keep connector credentials and raw cursors outside LBrain.

## Project Setup case

Given a user requests Context Intake for work that has no code repository:

- reuse an existing Project's outcome and configuration when present;
- discover available connectors before asking questions;
- group independent missing questions into one round;
- show one exact human-readable Project and Intake Profile preview;
- use one confirmation and the preview's prior-state hash to apply;
- after the one confirmation, record the previewed Project Proposal as accepted before `project.configure` applies it;
- keep exactly one version-bounded Intake Profile after idempotent reruns; and
- migrate an unmarked Profile only through a content-preserving preview.

## Decision completeness case

Given a product discussion with alternatives, evidence, disagreement, a final choice, and a later implementation result, retain one decision record with:

- domain, status, and date or time span;
- the question and material options or disagreements;
- evidence, decision, rationale, and tradeoffs;
- consequences or actions and the observed outcome;
- supersession or unresolved conflict when applicable; and
- every useful source pointer.

A one-line conclusion is insufficient when the source contains the reasoning. A later implementation or reversal updates the existing record without deleting its prior state.

## Coverage report case

Every run reports the inspected scope, candidate count, full-read count, created or updated records, duplicates and noise rejected, unresolved conflicts, changed files, and next completeness review. It previews and records that report through `project.checkpoint`. It may report complete coverage only when every enabled source and required anchor is accounted for; omitting a canonical `- source: anchor` row fails before write, while partial or failed runs retain the last complete checkpoint and idempotent retries do not duplicate a run. A checkpoint section before another level-two section keeps new runs inside the checkpoint section. Raw connector cursors and cursor-like text assignments never enter the checkpoint.
