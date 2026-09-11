# Daily engine AI spending protection

The saved `LLM_DAILY_BUDGET_USD` applies to every engine LLM request, including
chat, compaction, extraction, merge, task judgement and maintenance. Default USD10;
zero pauses paid AI. Negative, non-finite or unreadable settings refuse calls.
Existing profiles retain their saved limits. It is an estimate-based engine
allowance, not a bank-payment limit or a provider invoice reconciliation.

## Admission and accounting

`llm/budget.py` reserves a conservative maximum before dispatch, using an
additive `llm_reservations` table in the profile SQLite database. `BEGIN IMMEDIATE`
serializes competing processes. Saved policy is read during admission so another
process cannot use its stale environment after the limit is lowered.

Each reservation records immutable `OWNER_ID`, model, transport and call site,
never prompts or credentials. All usage rows in the profile database count,
including historical rows keyed by old email addresses. Changing the display
email therefore cannot reset the allowance. SDK automatic retries are disabled.

Successful validated usage is recorded and the hold closed atomically. Failed,
missing-usage or uncertain responses retain their reservation; no timeout or
restart releases possibly incurred liability. Settled spending resets at UTC
midnight. Unsettled holds survive midnight; a late result settles on its completion
day. Existing in-flight charges remain committed if the limit is reduced.
An observed actual-cost bound breach is recorded in full and blocks future
admission across midnight/restarts until explicit pricing reconciliation.

Amounts are rounded upward to integer micro-USD. Cache creation is conservatively
settled at the one-hour rate when using the aggregate token count, so displayed
completed spending can exceed the actual provider charge. Valid five-minute/one-hour cache usage detail is settled at its respective rate. Historical usage uses
its previously recorded estimates. Neither value should be described as an invoice.

## Supported billing surface

The guard uses an exact Anthropic standard-tier model-price allowlist, UTF-8
text size plus protocol allowance, full maximum output, and conservative cache
creation costs. Combined input/output bounds over 200,000 tokens refuse to avoid
unpriced long-context premiums. Unknown models, premium options, multimodal and
provider-side tools refuse before dispatch. Ordinary client-executed function
tools remain supported and each subsequent LLM request gets its own reservation.

MrCall credits use the additive `mrcall-bounded-v1` server contract. A free quote
binds the account, business, request and frozen tariff, including markup and
credit rounding. Its maximum debit is reserved atomically with the quote in
`llm_billing_authorizations` before execute. Only a matching receipt of actual
committed credit consumption can settle the reservation. Legacy proxy servers
refuse with upgrade guidance. Lost answers can recover their billing receipt
through read-only status without repeating inference or consumption.

OpenRouter currently supports `z-ai/glm-5.2` through its Messages API. The adapter
sends decimal price caps, disables fallbacks and thinking, and validates the
actual charge returned in `usage.cost`. Missing or invalid receipts keep holds.
Explicit model/feature allowlists apply; this is not unlimited model routing.

The limit covers this engine/profile store. Other hosts, copied databases,
external scripts, kernel direct API calls and Codex/Claude Code subscriptions
are outside its accounting. Prices are a dated catalog, not an upstream guarantee.

## User surface and recovery

Settings retains its existing limit field. The new spending readout shows
completed, reserved, available and maximum amounts through `usage.today`.
`usage.today` also exposes effective provider/model policy and billing availability.
`usage.reconcile(cursor?)` checks ten pending credit receipts per page and returns
`next_cursor`; permanent uncertain holds cannot hide later known settlements.
The Settings action follows those pages without invoking inference. Direct
provider holds require provider evidence; the MrCall action cannot release them.
A budget refusal is an AI spending-protection error, not a request for a new API
key. Sync/read-only access remains possible when AI is paused.

Unfinished extraction remains pending on provider/budget failure or truncated
output. Explicit semantic `SKIP` is a completed empty extraction. Memory merge
comparisons share a three-candidate shortlist corroborated against explicit
LLM-authored identifiers; message provenance is never injected as entity identity.
Already-polluted index rows remain untouched but no longer create unbounded paid
comparisons. Final merge decisions remain semantic LLM judgements.

Uncertain holds require reconciliation with provider evidence before any manual
release. Do not delete holds or reset spending to make a failed run proceed.
The affected backlogs remain paused until deliberate resumption; checkpoint
repair only restores confirmed failed memory extraction to pending and must not
reset independent task processing.

Implementation evidence: [incident](../investigations/2026-09-11-llm-spend-incident.md),
[model routing](../investigations/2026-09-11-model-routing-audit.md),
[delivery plan](../../../docs/execution-plans/2026-09-11-daily-llm-budget.md).

## Explicit model policy

`LLM_PROVIDER` selects `anthropic`, `openrouter` or `mrcall`, even when more than
one credential is stored. Only an unset selector uses legacy saved-Anthropic-key
routing; an ambient key cannot override an active profile. `LLM_MODEL_PRESET`
selects economy (Haiku/GLM), balanced (Sonnet5/GLM) or custom. Saved explicit
role models take priority; the Desktop preset gesture clears individual overrides
when saved. Existing explicit models are preserved until such a deliberate edit.
Unconfigured models default to inexpensive Haiku or GLM. Model choice never
changes billing provider. Long-lived clients refuse dispatch after relevant
saved settings change; start a new run or conversation to create fresh clients.

See [bounded preparation](bounded-preparation.md) for batch/retry controls and
[model evaluation](../qa/preparation-model-evaluation.md) for offline comparisons.
No new paid semantic-quality benchmark has been run; GLM's prior classifier
results do not establish extraction or merge quality for these workloads.
