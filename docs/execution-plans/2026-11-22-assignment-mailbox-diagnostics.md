---
status: completed
---

# Diagnose unverified assignment mailboxes

[Approved brief](../briefs/2026-11-22-assignment-mailbox-diagnostics.md). Start at b61332db on the hosted source line.

## Implementation and verification

One engine milestone owns the configured-mailbox membership check, the diagnostic producer and regression coverage. Evaluate all active mailboxes within the existing twenty-mailbox limit. On a mismatch, log each rejected mailbox with a masked label and a stable reference derived from its stored ID. Emit one private authority event per rejected mailbox using the existing hashed evidence reference and inherited request trace. Include the projection root reference when available. Preserve the existing exception and generic projection reason even when a diagnostic sink fails. Empty, excessive and verified inventories follow their existing paths.

Exercise the actual projection RPC, the unit logger and the existing trace reader against synthetic profiles. Check distinct references for similar mailbox labels, per-request isolation, refusal on a broken sink and absence of raw private strings. Retain the existing generic diagnostic for unrelated failures. Run the assignment projection, provider and transport regression suites sequentially in an empty environment. Review the integrated source, reconcile the operator documentation and obtain a separate final review through the trace reader.

The installed engine and kernel have separate release authority. Rollback of the source change consists of reverting its diagnostic-only diff. No production switch or trust edit belongs to this plan.

## Verification results

The projection diagnostics suite passed all 13 tests, including the trace-filtered reader and continued refusal with failed diagnostic sinks. The provider, transport and member-hold suites passed 7, 10 and 17 tests respectively. The broader projection observation suite passed 49 and failed the same six named cases on both clean b61332db and this branch. The milestone review approved the implementation.
