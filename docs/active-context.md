---
doc_baseline_commit: c4593726f69199f15f36a317216893efe4bf3927
doc_baseline_date: 2026-10-16
---

# Active Context — Isolated model metadata publisher

<!-- doc-scope:start -->
Scope: current status of this isolated publisher branch, its consumer/data
boundaries and remaining verification. Runtime delivery lives on the hosted
mailbox branch and in HB's November 23 plan. Previous base snapshots are history
in active-context-archive.md.
<!-- doc-scope:end -->

## State now

This branch extends the existing model-table publisher from `652c0007` for the
[mailbox endpoint-capability dependency](execution-plans/2026-11-25-mailbox-endpoint-capabilities.md).
It is neither an installed engine nor a replacement for the hosted mailbox line.
All seven actual engines remain on dev13 `2e27f02e`; their separate immutable
source-reviewed dev14 artifact is inactive. Both normal operators retain local
kernel v0.76.1 and paused schedules. HB's November 23 plan owns installed release
and acceptance. The October base snapshot is retained verbatim as history.

Publisher and gateway M1 revision 2 are approved. The producer retains exact
optional endpoint parameters without changing global intersection, reference
pricing, admission policy or role rankings. Producer/Agent schemas are byte
identical. The free-only refresh uses canonical committed requirements and
binds clean source, complete raw read, unchanged table and exact data head.
Its focused suite passes 85 cases. Independent refutation confirms an alternate
requirements path refuses before provider reads or data changes.

The ordinary model-resolution workflow can spend and is outside this update.
The new refresh previews first and publishes only a separately reviewed snapshot.
No live provider read, model inference, data publication or service switch is
established by the source checks. [Published contract](../engine/zylch/llm/roles/contract/README.md).

## Unresolved

- Scoped documentation criticism and separate data/release review remain open.
  Live complete catalog/endpoint reads, unchanged-table gates and currently
  selected model compatibility must pass before publishing any candidate.
- Both actual gateway realms still use old readers. Compatible source must
  deploy main → dev → production with exact images/source and authenticated free
  quotes before publishing the optional field. Old endpoint schemas reject it.
- After exact snapshot publication, the serving gateway must expose its frozen
  version and admit the authenticated pinned format. These quotes establish no
  paid inference or actual credit settlement. Existing uncertain records remain.
- Desktop dev14 activation, the ordinary support reply, public kernel provenance,
  Gmail client interaction and the parent delivery's other installed obligations
  remain separate and open. Historical M10 and unrelated runtime work stay under
  their existing plans; this publisher branch does not certify their deployment.

## Next

1. Reconcile and review these scoped documents, then commit the reviewed task
   paths and obtain a clean source checkout for the free-only preview.
2. Read the complete current catalog and endpoints, validate unchanged policy,
   exact table bytes and both consumer gates, then review the concrete data diff.
3. Verify deployed compatible gateway readers and publish only that reviewed
   snapshot. Verify actual remote bytes and authenticated pinned quotes before
   returning activation and ordinary acceptance to the hosted mailbox delivery.
