# Exact endpoint capabilities for mailbox generation

## Parent delivery and problem

The HB November 23 mailbox draft plan governs the product delivery. The approved
Agent brief `2026-11-25-mailbox-structured-output` requires bounded structured
generation on the existing direct, Messages and pinned Chat transports.

At this brief's initial data baseline, the published snapshot retains only
the intersection of admitted endpoints' parameters. That cannot establish a separately pinned endpoint's capabilities.
The current public DigitalOcean endpoint advertises structured output and response
format support, while the published model-wide intersection does not. The gateway
must not turn that global false value into a hardcoded exception. It needs exact
capability evidence in its frozen, quoted snapshot.

## Existing code and isolated source

This branch extends the existing pure snapshot builder, endpoint schema, gates
and data-branch publisher from Desktop source
`652c00079e8a59770bd242a7a63fa3529ff17703`. The hosted mailbox line does not contain
that publisher. This source branch is not installed as an engine or merged over
the current hosted line. Existing runtime and unrelated M10 work are preserved.

`roles.snapshot._endpoint_rows` already selects exactly admitted endpoints and
writes their tag, quantization and prices. Add their optional sorted distinct
`supported_parameters` from the same provider record. Preserve the global
intersection, admission policy, pricing algorithm, pin policy and role decisions.
The schema remains version 1 and the optional field participates in the existing
canonical content hash. Unknown endpoint capability remains unknown.

The existing `resolve_models` reader and builder plus `DataBranch.lock/read/push`
support a free snapshot-only publication by explicit composition. The ordinary
model-table job can run paid smoke or measurements and is excluded. Do not call
its workflow or relabel a restamped old snapshot as a fresh provider read.

## Scope and safeguards

- Extend the authoritative endpoint schema, producer, examples and focused
  contract tests. Coordinate the Agent's vendored schema and pinned-format gate.
- A pinned formatted request requires the exact admitted pin to advertise both
  `response_format` and `structured_outputs`. Ordinary unpinned requests retain
  the existing global metadata rule. Missing, malformed or incompatible evidence
  refuses before paid dispatch. Old snapshots without the field remain readable.
- Deploy compatible gateway readers before publishing the new optional field.
  Old readers reject extra endpoint properties and cannot be assumed compatible.
- Refresh through the existing complete catalog and endpoint reader with the
  unchanged requirements and policy. Keep `table.json` and all rankings unchanged.
  Refuse publication if the unchanged table fails its gates against the new
  snapshot. Preserve all other data-branch files and staged work.
- Bind the clean source ref, complete read, new snapshot hash, prior data-branch
  head, schema gates and exact one-file data diff before publishing. Serialize
  publisher activity and require a clean data checkout. A failed push is reconciled
  against actual remote state; it does not authorize a second inference or debit.
- Use existing credentials privately for free catalog/benchmark reads and Git
  publication. No model inference, credit consumption, paid cohort, secret output,
  selected-model change or spending-cap increase is introduced.

## Acceptance

1. Real pure-builder and schema tests prove exact endpoint parameter provenance,
   deterministic hashing, unchanged global intersection/pricing/policy, old-data
   compatibility and rejection of malformed or duplicate capability fields.
2. Both producer and gateway gates accept the same new fixture. The gateway binds
   capability to the quoted snapshot and exact pin; another endpoint's parameters
   cannot authorize that pin. Replay keeps its existing no-inference/debit rule.
3. Independent review verifies the free publication call graph and unchanged table
   bytes before any data push. The fresh live snapshot passes both gates and the
   unchanged role table gates. No model or debit endpoint is called.
4. The actual public data ref and bytes match the reviewed one-file publication.
   The deployed gateway accepts an authenticated free quote for the configured
   pinned format and refuses missing/altered capability cases in controlled tests.
5. The parent mailbox delivery still requires corrected installed generation,
   ordinary support sending, shared mailbox behavior and its remaining acceptance.
   A free quote or data publication alone establishes none of those outcomes.
