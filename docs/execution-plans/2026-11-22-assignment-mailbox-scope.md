---
status: completed
---

# Scope assignment mail reads to the authenticated member

Implements the [brief](../briefs/2026-11-22-assignment-mailbox-scope.md)
from hosted dev6 source on main. Engine assignment read services own the
change. The existing root-owned company trust, profile archive, provider Sent
coverage, stable actor and component rechecks remain prerequisites.

## M1 — projection membership and regression coverage

- [x] In the unassigned, unambiguous read-only projection, derive the complete
  actor mailbox set from verified membership and active profile rows. Exclude an
  unrelated row only when its address is verified for another company member.
  Require a nonempty archived component whose mailbox IDs all belong to the
  actor before using a reduced inventory. Unknown aliases, missing mailbox
  IDs, overlapping or mixed components and exhausted bounds remain held.
- [x] Apply the same membership selection to the early member witness, exact
  source reread and full Sent enumeration, including hold expiry. Keep all
  actor-owned mailboxes, including siblings with no local component row.
  Isolate this selection from signed reply evidence, closure snapshots and
  other direct callers. Revalidate membership, mailbox inventory and component
  row bindings before returning a conclusion based on reduced scope.
- [x] Test using the real projection entry point with synthetic profiles and
  counted provider connections. Contrast a last member reply with an ordinary
  eligible thread. Exercise a related foreign row, a missing or unknown
  binding, multiple actor aliases, and an authority change during observation.
  Check the direct strict caller and the existing diagnostics. Run suites
  sequentially under an empty environment. Record baseline failures separately.
- [x] The independent milestone review approved the implementation and ten
  synthetic RPC regressions. Seven existing impacted test files also ran on
  the baseline and candidate. The baseline has eleven failures across projection
  observation, preserved evidence, provider component, and the Sent index.
  The candidate added no failures in these files.

The final gate uses the same RPC entry point as the clone. Hosted acceptance
requires a deployment report with per-process verification and production RPC
results. The implementation tests use synthetic mail exclusively.

## Hosted acceptance

The operator authorized dev7 on all seven units after review. Both clone
schedules stay paused. Verify each process and listener, then read the exact
production conversation through the clone RPC. Confirm a member-reply hold
on real evidence and verify the separate ordinary-thread and restricted-mailbox
cases without sending mail. The single source release carries package version
`0.1.57.dev7+hosted20261122.mrcall`.

The dev7 rollout's dev6 unit binding is a pre-retirement rollback reference.
Today, stop writers and apply the [compatible rollback check](../mailbox-draft-migration.md#compatible-rollback)
before any old-engine restart. The current profile receipt and journal state
refuses dev6. A rollback must retain a compatible mailbox receipt reader and
preserve the profile database.
