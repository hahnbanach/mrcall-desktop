---
status: active
---
# OpenRouter credit routing — execution plan

Brief: [intent and invariants](../briefs/2026-09-13-openrouter-credits.md).

- [x] Independent contract review before implementation (openrouter_contract_review APPROVED).
- [ ] Server adapter, supported model catalog, bounded pricing/cost receipts and integration tests.
- [x] Engine OpenRouter model support, server model discovery and payment/model UX with regression tests.
- [ ] Deployment secret templates/scripts/env references; inject only OPENROUTER_API_KEY, never expose values.
- [x] Independent implementation review: server79tests; engine40tests including4cross-repository PostgreSQL/SQLite journeys; React and typecheck pass.
- [ ] Deploy reviewed server to test; verify live catalog/quote and bounded synthetic OpenRouter request.
- [ ] Deploy compatible server/engine/UI production release, preserve account pauses and caps.
- [ ] Finish small Opus/Sonnet/Haiku/K3 comparison within combined USD1; report limitations honestly.
- [ ] Reconcile docs, commits/push and delivery evidence. User owns personal-key GUI acceptance.

No full deployment-manifest apply against a drifted cluster: preserve the running
image and unrelated environment settings when wiring the new secret. Never
commit secret files. Production charging uses existing StarChat adapter and
durable bounded ledger. Missing cost preserves hold; zero verified cost must
not become a fabricated paid credit. Native paid tools and unsupported pricing
features are refused. A test-provider call must have a reserved maximum before
dispatch, no hidden retries or premium fallback.
