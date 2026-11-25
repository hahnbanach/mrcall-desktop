---
doc_baseline_commit: 9719b6b9567b031e7cd1e85afec217cf757e1dce
doc_baseline_date: 2026-11-25
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
HB's November 23 plan owns installed engine versions, normal clone pins,
recurring controls, release and acceptance. The October base snapshot is retained verbatim as history.

Publisher and gateway M1 revision 2 are approved. The producer retains exact
optional endpoint parameters without changing global intersection, reference
pricing, admission policy or role rankings. Producer/Agent schemas are byte
identical. The free-only refresh uses canonical committed requirements and
binds clean source, complete raw read, unchanged table and exact data head.
Its focused suite passes 85 cases. Independent refutation confirms an alternate
requirements path refuses before provider reads or data changes.

The ordinary model-resolution workflow can spend and is outside this update.
The new refresh previews first and publishes only a separately reviewed snapshot.
The exact source commit is `d79e2cf6`. A complete free live read covers 472
catalog models and 228 endpoint responses. Independent review matches all 577
admitted rows and preserves the five configured model prices. Data commit
`b7e2d960` changes only snapshot.json; the five other blobs remain exact.
Both immutable-ref and branch downloads match the reviewed snapshot and table.
Both deployed gateway realms run compatible `2bf3a56b`, with 78 matching files,
healthy HTTP 200 and twelve passing authenticated after-pin checks per realm.
Their serving snapshot is `ceba39da…`. Publication and quotes invoke no model
inference or credit debit. [Published contract](../engine/zylch/llm/roles/contract/README.md).

## Unresolved

- Actual source/data/reader gates retain their independent approval and execution
  evidence. Paid inference and credit settlement retain their separate acceptance
  owners. Existing uncertain records remain fenced.
- The active gateway keeps its image-build snapshot as a fallback. Its actual
  authenticated quotes, rather than that build file, prove the serving version.
  Old readers must not be reinstated against incompatible data without the
  reviewed recovery procedure.
- The parent HB plan owns mailbox behavior, ordinary operators, Gmail client
  interaction, public kernel/installer provenance and final installed acceptance.
  Historical M10 and unrelated runtime work retain their existing plans.

## Next

1. Preserve canonical requirements, reviewed snapshot bytes and reader
   compatibility for each explicit free refresh on this isolated source line.
2. Continue parent installed delivery under HB's mailbox plan, retaining the
   public publication and compatible-reader evidence.
3. Keep future refreshes free-only unless their separate paid workflow is
   explicitly invoked under its existing spending policy.
