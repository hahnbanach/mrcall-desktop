---
status: active
---
# Predictable AI spending — delivery plan

Brief: [approved intent](../briefs/2026-09-11-predictable-ai-spending.md).
Brief review APPROVED by independent spending_brief_review. No paid testing;
retain the four existing account pauses and USD5 limits throughout rollout.

## M1 — Bounded credits protocol (billing server)

Owner: billing implementation agent, isolated mrcall-agent worktree.
Add a versioned, additive bounded JSON endpoint alongside the legacy SSE API.
A free quote binds normalized text/function request hash, exact model, tariff
version, credit unit USD value, markup and upward credit rounding. Frozen
pricing includes conservative input bytes, full output and maximum supported
cache-write cost. Refuse unknown features, nonstandard tiers and stale quotes.
The execute request supplies request ID, quote version/hash and maximum debit.
Validate independently server-side before provider dispatch. Never trust a
client's claimed token counts or price. Actual debit cannot exceed that maximum.

Persist account/request-ID admission and canonical payload hash in PostgreSQL
before upstream dispatch, with a unique constraint handling concurrent replays.
Store only hashes, accounting metadata and final charge receipt, not tokens or
mail content. State transitions: admitted -> dispatched -> debit_pending ->
settled. All pre-dispatch transitions commit before external effects. Existing
or ambiguous IDs never redispatch or consume again. Credit backend presently
has no proven idempotency: commit debit_pending before calling consume, and
leave ambiguous mutation unresolved instead of retrying. Missing receipt means
client retains its hold. A status endpoint may recover a known settled receipt,
but never regenerate message content. Do not claim distributed exactly-once.

Use existing Firebase auth and established credit service; no changes to phone,
SMS or configurator billing. New tables/migration are additive; absent migration
refuses bounded API. Legacy endpoint remains compatible during engine rollout.
Tests use real SQL transactions and fake Anthropic/credit services: concurrent
replay, conflicting account/payload, stale tariff, malformed usage, provider
failure, max debit, crash boundaries, timeout after consume, receipt recovery.
Independent M1 integration review before engine credits adapter integration.

## M2 — Engine transports and explicit model policy

Owner: lead; may delegate independent provider implementation after plan review.
Keep the existing SQLite admission ledger as the sole dispatch authority.
Add durable transport price/receipt metadata additively; quote is free, reserve
its maximum account debit atomically, then execute once using reservation ID.
Validate receipt against account/request/hash/tariff/maximum before atomic
settlement. Missing/mismatched receipts retain holds, including across UTC and
restart. Known settled receipt reconciliation only; no automatic hold expiry.
Unknown/legacy proxy refuses with upgrade guidance, never a fallback.

Add explicit OpenRouter provider/key selection using supported API semantics,
checked model prices and server-enforced provider price caps where supported.
Disable hidden retries/fallbacks. If upstream cannot enforce a demonstrable
bound for a feature, refuse it rather than advertise budget coverage. Validate
current official API/pricing docs before implementation. Decimal micro-USD
rounding covers fractional rates. Provider changes do not reset the ledger.

Central role presets: economy, balanced, custom. Economy uses an explicitly
priced inexpensive model; preserve existing explicit models and credentials.
GLM availability is not evidence of memory quality. Expose exact role mappings;
no implicit promotion to premium models on errors. New configuration defaults
must be inexpensive. Keep existing direct Anthropic tests and add factory,
actual HTTP adapter + SQLite tests, cancellation, live settings, model switches,
unknown pricing, bounded proxy end-to-end receipt and crash cases.
Independent M2 integration review before dependent UI integration.

## M3 — Bounded preparation and progress

Owner: independent engine worker agent; independent of transport implementation.
Saved per-run item limit (default 25) bounds backlog work across memory/task
stages; existing per-call budget remains authoritative. Add durable per-source
failure attempt/backoff metadata so restarting or pressing resume cannot reset
retry allowance. Three failed attempts suspend that item until explicit reset;
budget refusal does not consume semantic attempts. Keep existing checkpoints:
failed/incomplete extraction is pending, never complete. Stop scheduling new
paid work on pause while accounting for already dispatched requests.

Expose preparation status and explicit pause/resume through existing RPC flows:
pending/completed/failed, current run progress, limits and actionable stop reason.
Separate sync-only from paid analysis. Preserve company scoping and repaired
three-candidate merge shortlist. Bound chat tool turns as another paid-loop
limit. No semantic regex replacements or destructive cleanup. Verify actual
worker/RPC paths with local stores, fake LLMs, repeated runs, restart, cancellation,
multiple channels, manual/automatic triggers and checkpoint integrity.
Independent M3 integration review before dependent UI integration.

## M4 — Settings, preparation UX and evaluation

Owner: lead/UI implementation agent after M2/M3 approval.
Settings display provider, effective models, editable daily allowance, spent,
uncertain holds, remaining capacity and UTC reset. Preserve top-up link to
MrCall dashboard; never send credit users to API-key entry as error recovery.
Preparation offers sync, bounded analyze, pause/resume with persistent status;
disabled actions explain the remedy. Account switching refreshes status.
Support old engines explicitly rather than treating missing RPCs as success.
Add reproducible offline task fixtures/evaluation runner for extraction, merge
and task decisions; live evaluations require opt-in and explicit max spend.
Document semantic quality as unmeasured until paid evaluation is authorized.
Verify app types/build and actual RPC-contract journeys with fake paid upstream.
Independent M4 integration review plus a separate final user-path review.

## M5 — Delivery and rollback

Reconcile living docs, status and tested protocol; run harness checks and semantic
review. Commit and push isolated branches with reviewable PRs. Inspect actual
server production deployment workflow before rollout. Apply additive migration
and deploy reviewed server first; verify read-only quote/health without invoking
paid execute. Deploy engine isolated release on paused accounts, preserving
profile caps and backups, verify paths and RPC. Never merge desktop main early:
host reconciliation automatically pulls it. Release desktop installer only once
compatible server/engine and release checks pass. Report source versus installed
UI accurately. Rollback uses prior guarded release with automation still off;
never drop accounting tables or revert to unguarded spending. No paid benchmarks,
customer credit debits or automatic backlog resumption during acceptance.

## Gates

- [x] Brief independently approved.
- [x] Plan independently approved (spending_plan_review).
- [x] M1 implementation and review (bounded_billing_review APPROVED; 47 independent tests).
- [x] M2 implementation and review (spending_brief_review APPROVED; 97 tests incl cross-repo journeys).
- [x] M3 implementation and review (bounded_billing_review APPROVED; 17 independent cases).
- [x] M4 implementation and review (spending_ux_review APPROVED; real React/RPC simulations and evaluator checks).
- [x] Fresh final end-to-end implementation review (54 engine, 45 PostgreSQL endpoint, 4 cross-repository journeys and both React scripts).
- [ ] Final documentation review.
- [ ] Compatible delivery, read-only verification and final report.

Plan review requires account + resolved business quote binding, durable receipt metadata, one allowance across channels/stages, pause coverage for training/canaries/reconsolidation, and explicit legacy-client limits.

## Deployment acceptance

- Server production pipeline 2841302220 passed; image `prod-c238edf8` is ready.
  Independent read-only SQL verifies Alembic `20260911_bounded_billing` and the
  accounting table. Authenticated public capabilities and free Haiku quote
  return 200; no execute or credit consumption is used for acceptance.
- Four affected engine units run isolated `83075a0`, with private profile/override
  backups. Saved provider matches previous billing; economy Haiku replaces the
  previous default Opus for these profiles. Caps remain USD5, batch size 25,
  automation off and durable preparation pause on. Two configured operator
  accounts pass public authenticated RPC; two additional accounts pass local
  production RPC handlers. All four services are active; read-only SQLite checks
  find no usage since 12:25 UTC containment and no outstanding holds.
- Root regression suite: 331 engine tests passed. Full server suite: 196 passed;
  CI lint/format/test passed. App component journeys, typecheck and build pass.
- Desktop v0.1.48 release artifact remains the final delivery step. Rollback keeps
  the prior guarded engine override and all accounting data; never restore
  automation or an unguarded build.
