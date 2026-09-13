---
status: completed
---
# OpenRouter credit routing — execution plan

Brief: [intent and invariants](../briefs/2026-09-13-openrouter-credits.md).

- [x] Independent contract review before implementation (openrouter_contract_review APPROVED).
- [x] Server adapter, supported model catalog, bounded pricing/cost receipts and integration tests.
- [x] Engine OpenRouter model support, server model discovery and payment/model UX with regression tests.
- [x] Deployment secret templates/scripts/env references; inject only OPENROUTER_API_KEY, never expose values.
- [x] Independent implementation review: server79tests; engine40tests including4cross-repository PostgreSQL/SQLite journeys; React and typecheck pass.
- [x] Deploy reviewed server to test; verify catalog and sampling guard. The test identity has no business (`no_business_for_user`), so the bounded paid request was verified on the production identity.
- [x] Deploy compatible server/engine/UI production release, preserve account pauses and caps.
- [x] Finish small Opus/Sonnet/Haiku/K3 comparison within combined USD1; report limitations honestly.
- [x] Reconcile docs, commits/push and delivery evidence. User owns personal-key GUI acceptance.

No full deployment-manifest apply against a drifted cluster: preserve the running
image and unrelated environment settings when wiring the new secret. Never
commit secret files. Production charging uses existing StarChat adapter and
durable bounded ledger. Missing cost preserves hold; zero verified cost must
not become a fabricated paid credit. Native paid tools and unsupported pricing
features are refused. A test-provider call must have a reserved maximum before
dispatch, no hidden retries or premium fallback.

## Verified delivery evidence

- Server test `dev-5640e87f`, production `prod-a522596c`; pipelines
  2844633835 and 2844635557 pass. Production catalog and all five OpenRouter
  quotes pass; unsupported Sonnet sampling refuses before admission.
- Server227 tests; independent server failure/concurrency and cross-repository
  credit journeys approved. Engine160 tests and39 Sonnet regressions pass;
  React journeys, typecheck and build pass.
- Four affected hosted engines pin `10477fd`; profile files remain byte-identical,
  services active, USD5 caps and durable pauses preserved.
- One synthetic GLM production call returned OK: provider cost USD0.00000941192,
  one-credit debit (USD0.011 wallet value), balance4→3. Integer-credit rounding
  dominates very small calls; fractional aggregation is not implemented.
- The twelve-call uniform4096-token blinded comparison records consequential
  Haiku errors. No model choice or automatic processing was changed. Total
  isolated ledger after acceptance: USD0.253826 spent + USD0.171170 held,
  against the combined USD1 allowance. Uncertain earlier attempts remain held.
- Desktop PR12 merged as `225f455`; v0.1.49 signed/notarized Apple Silicon installer is published. The user
  will enter personal keys through the GUI; this manual acceptance is pending.

Release workflow34759876569 succeeded. Its custom afterSign hook awaited
notarytool completion before DMG creation; the unsigned fallback was not used.
[Installer](https://github.com/hahnbanach/mrcall-desktop/releases/tag/v0.1.49):
237,167,306 bytes; SHA256
`e84e81219f54c268ac3bab5a4f1162a3e349659679fb1c35eada8d9f10d0f8a5`.
Independent documentation review verified30 load-bearing claims with zero
remaining stale findings; manual Mac installation/personal-key entry remain
explicit acceptance limits. Desktop mechanical gate passes; server/deployment
harness versions were not upgraded or their baselines advanced.
