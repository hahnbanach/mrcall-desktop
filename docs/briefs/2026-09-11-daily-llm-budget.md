# Enforced daily LLM budget and runaway memory cost

## Intent

Prevent another uncontrolled API-spend incident while retaining LLM judgement
for semantic classification. The CTO reports about USD200 of overnight
Anthropic charges and has blocked payments. Existing account budgets are USD5,
but the implementation checks only before the pipeline and records successful
calls after dispatch. Chat/solve and direct SDK bypasses also need coverage.

## Scope and constraints

Repair the existing LLM_DAILY_BUDGET_USD control rather than add a competing
setting. Preserve configured limits. Enforce per active immutable account,
across processes/restarts, at every billable engine dispatch. Reserve a
conservative request bound atomically before transport; reconcile verified
usage afterward. Uncertain outcomes keep reservations; database/pricing errors
must refuse paid work. Include output, cache and server-side tool costs;
unknown model pricing must refuse rather than assume a cheaper tier. Bound or
disable hidden retries. UTC day boundaries must be explicit. No claim that
local estimates control provider invoices, taxes, external processes or other
hosts sharing a key. No API calls to test the new limiter against real billing.

Investigate configured models, costs by call site and repeated processing for
the two reported mailboxes. Separate recorded estimates from invoice evidence.
Find why historical OpenRouter/GLM choices no longer route engine calls and
assess cheaper LLMs using existing evidence and current official references.
No regex-based semantic labelling, automatic loss of source records, or
unvalidated broad model-quality claims. Preserve auth and memory capabilities.

## Acceptance

1. Concurrent calls cannot reserve beyond the account's daily cap. Every
   normal engine LLM path and discovered SDK bypass is covered; zero means
   pause, invalid/nonfinite limits cannot disable protection.
2. A failed/unavailable ledger blocks calls. Ambiguous failures/restarts retain
   reservations; UTC rollover and stale in-flight calls cannot reopen spend.
3. Budget stop is actionable and leaves unfinished work pending, never marked
   as successfully analysed. Settings/usage show limit, settled/reserved usage,
   reset time and cause. Existing configured limits persist.
4. Tests cover real dispatch with fake upstream, independent SQLite connections,
   concurrency, retries/errors and large requests; no live paid acceptance.
5. Incident and provider-routing reports cite verifiable aggregates/source and
   identify remaining uncertainty. Prioritize fixing merge amplification and
   model defaults only where safe evidence supports the change.
6. Review implementation and document operational rollout/rollback limits.
   Reversible containment may pause affected background workers to stop loss.

## Material decisions

The existing pipeline-entry gate is insufficient. Central enforcement owns the
safety guarantee; stage checks improve UX only. A conservative pause is preferable
to unexpected charges. Provider subscriptions used by the human in Codex/Claude
Code remain separate. The current reported USD5 account setting is retained.
