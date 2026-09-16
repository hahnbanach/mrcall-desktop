---
status: blocked
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
- Server implementation 99091c3 is deployed to test and production; pipelines
  2854291723 and 2854312079 succeeded. Scoped ingress timeout changes preserve
  the running configuration; infrastructure commit 295eb8e is local (no remote).
- Engine release 8d83193 is pinned on the four units. Production uses custom K3
  for its base model, five worker roles and reply classification. Other profile
  values are unchanged. Protected rollback copies are under
  `/root/mrcall-k3-rollout-20260916` on the engine host.
- Production authenticated identity, available K3 credit catalog and paused/not
  running preparation assertions pass. BYOK and credit translated payloads match
  on a system-block/function-history fixture.
- Paid acceptance is blocked by HTTP402 insufficient MrCall credits before
  server admission/provider dispatch. No credit debit or live K3 answer was
  obtained. The isolated USD0.30 test ledger retains USD0.209 as a conservative
  reservation; it does not affect hosted profile budgets. An earlier local
  preflight rejected an uninitialized test ledger before dispatch.
- Remaining: a funded credit response/receipt smoke, and the billing preference
  for the other three profiles. No backlog resumption is authorized by this plan.

## Personal-key acceptance

The CTO added a personal OpenRouter key to production. Corrected its misspelled
variable name (OPENROUTER_APY_KEY) to OPENROUTER_API_KEY, selected provider
openrouter and OPENROUTER_MODEL=moonshotai/kimi-k3, preserving every other setting.
A private pre-change backup exists on the host. Restarted only production.
The actual configured client factory resolves OpenRouter/K3; service is active
and preparation remains paused/not running.

A single synthetic personal-key call returned OK/end_turn with 68 reasoning
tokens and exact provider cost USD0.00137515. The isolated USD0.20 test ledger
settled USD0.001376 with no remaining reservation. Evidence is at
`/home/mrcalld/k3-personal-smoke-20260916/result.json`, without credentials.
This verifies transport/reasoning/accounting, not business-answer quality.
Production now uses the personal key, superseding the credit selection recorded
above. Funded credit acceptance and other profiles' billing choices remain open.
