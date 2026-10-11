# Resolve selected billing businesses as opaque IDs

The CTO selected a returned business in 0.1.54 and received the warning that the
account cannot bill it. The selection has a non-UUID identifier. The new picker
resolves saved/selected values through free-text query routing, so numeric and
other non-UUID IDs are incorrectly searched as names. Settings Save already uses
an exact businessId filter; this incident does not establish a billing denial.

Correct selected/saved-value resolution to always use the exact opaque string
ID, independently of free-text discovery. Preserve server authorization, bounded
request serialization, cancellation, explicit selection and Save validation.
Do not infer numeric-looking free text is necessarily an ID; known selected
values and user-entered discovery text have distinct semantics. Include numeric
and other non-UUID synthetic IDs in actual-picker regressions, through selection,
label resolution, reopening and exact Save validation. Missing exact IDs must
still be rejected and failures must not become authority claims.

Publish a signed patch after integration and two fresh independent final reviews,
verify delivery, and record the regression and evidence under sandbox R5. R5
remains active until the real app journey and scratch lifecycle are accepted.
No live profile changes, paid calls, real business content, secrets or service
checkout modifications. Preserve concurrent root-clone work via this isolated
worktree. Do not record the actual business identifier from the user's report.
