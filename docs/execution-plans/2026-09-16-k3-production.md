---
status: active
---
# K3 production delivery

Brief: [K3 adoption](../briefs/2026-09-16-k3-production.md).

1. Review and finish both transport adapters, their bound calculations and
   function-history translation. Preserve legacy no-control proxy requests.
2. Exercise admission-before-dispatch, exact-cost settlement, invalid responses,
   truncation, unsupported inputs and quote replay with offline regressions.
3. Remove implicit Anthropic choices from auxiliary engine calls; preserve
   explicit overrides and reconcile memory serialization instructions.
4. Review the cross-repository contract and deployment procedure. Record actual
   test results. Deploy the compatible proxy before the pinned engine release.
5. Select K3/custom on authorized profiles, preserving current caps and queue
   state. Run only a bounded synthetic smoke, never restart the mail backlog.
6. Reconcile documentation and commit/push reviewed changes. Report separately
   what is implemented, tested, deployed and still awaiting billing preference.

## Verification and rollout state

- Initial focused engine suite: 267 passing tests. Follow-up K3/serialization
  regressions: 53 passing tests. Four cross-repository HTTP/ledger scenarios
  pass: normal settlement, lost-response recovery, zero budget and partial debit.
- Server billing suite: 108 passing tests against disposable PostgreSQL.
- Current four 124 profiles verified with automatic update disabled and
  preparation paused/not running. Their caps are preserved (20/5/5/5 USD).
- Server implementation is 99091c3; test CI pipeline 2854291723 is running.
  Deployment and profile activation are not yet complete.
