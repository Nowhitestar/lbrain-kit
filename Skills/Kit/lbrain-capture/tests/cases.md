# Capture Cases

## Should trigger

- “把这篇文章记到我的 LBrain，之后再处理。” → create a private Source or Inbox capture with provenance.
- “Remember this idea; I am not sure where it belongs.” → create an Inbox capture, not a confirmed Wiki claim.

## Should not trigger

- “基于这些来源总结我的看法。” → use `lbrain-weave`.
- “What have I said before about pricing?” → use `lbrain-retrieve`.

## Safety case

- Input contains an API key → refuse to store the secret and capture only a safe redacted note if requested.
