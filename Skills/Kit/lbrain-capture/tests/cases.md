# Capture Cases

## Should trigger

- “把这篇文章记到我的 LBrain，之后再处理。” → create a private Source or Inbox capture with provenance.
- “Remember this idea; I am not sure where it belongs.” → create an Inbox capture, not a confirmed Wiki claim.
- “每天扫描我已经连接的工作来源，把 AgentKey 作为重点形成 Context。” → inventory every enabled source, confirm the schedule, and run full-source Context Intake with target-focused reporting.

## Should not trigger

- “基于这些来源总结我的看法。” → use `lbrain-weave`.
- “What have I said before about pricing?” → use `lbrain-retrieve`.
- “把已有 AgentKey Context 发布成 Pack。” → use `lbrain-context-pack`; Intake does not package or publish.

## Safety case

- Input contains an API key → refuse to store the secret and capture only a safe redacted note if requested.
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

Every run reports the inspected scope, candidate count, created or updated records, duplicates and noise rejected, unresolved conflicts, changed files, and next completeness review. It may report complete coverage only when every enabled source and required anchor is accounted for.
