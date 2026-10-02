# Daily engine AI spending protection

This is an **engine-profile budget**, not a cap on all AI used by a company or
operator. Claude Code headless reasoning and direct cs-kernel classifiers use
separate clients outside this ledger. An operator-triggered engine request is
inside the cap. Preparation pause does not disable clone cron ticks; see
[execution and controls](../../../docs/operator-setup.md#ai-execution-and-controls).

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
restart releases possibly incurred liability, and no hold is ever deleted.
Settled spending resets at UTC midnight; a late result settles on its completion
day. Existing in-flight charges remain committed if the limit is reduced.

A reservation is taken immediately before dispatch and covers one call while it
is in flight. It therefore gates admission only while that call could still be
running: holds younger than `IN_FLIGHT_HORIZON` (one hour) count in full,
including one taken minutes before midnight. An older unsettled hold is
unresolved liability, not live exposure — it is reported as `stale_holds` /
`stale_holds_usd` in `usage.today` and no longer consumes the current
allowance. Without that horizon a hold nothing can settle — a direct-provider
call has no receipt path, so `usage.reconcile` cannot close one — shrank every
following day permanently.
An observed actual-cost bound breach is recorded in full and blocks future
admission across midnight/restarts until explicit pricing reconciliation.

The installed-client journey's replay case (case 15,
`tests/rpc/test_mnemonic_engine_journey_b.py`) asserts this behaviour after a
process death: a worker killed while the second child's decision call is in
flight leaves that reservation unsettled, and nothing releases it — not the
crash, not the restart, not the resumed run. It counts in full until the
one-hour horizon; the case advances the clock past it, and the resume then
re-extracts nothing, reserves afresh for the one undecided child and settles
it. The profile ledger ends with three mnemonic rows — settled, unsettled,
settled — one settled payment per decided child and the crashed hold still
open, reported as stale.

### The corpus runner's second bound

The milestone 9 corpus runner (`tests/memory/corpus_live_env.py`, class
`Ledger`) adds a **cumulative cap** on top of the per-UTC-day budget. Before
every dispatch, and once at start before anything is seeded, it sums every
settled `llm_usage` row of the disposable profile since its first run — not
since midnight — plus every unsettled `llm_reservations` hold regardless of
age (no in-flight horizon: a stale hold counts here forever) plus the bound of
every intent still open in the profile's `corpus-intents.jsonl`, adds the
request's own bound, and refuses (`CapExceeded`, nothing dispatched) when the
total would pass the milestone's USD 10. A settled row dated yesterday counts:
the guard test inserts one for USD 9.99 and the next case is refused. The
daily budget in the profile's `.env` (`LLM_DAILY_BUDGET_USD=10`) is the second
bound underneath, applied by the ordinary admission above; the runner never
resets, deletes or relabels anything in either ledger.

Amounts are rounded upward to integer micro-USD. Cache creation is conservatively
settled at the one-hour rate when using the aggregate token count, so displayed
completed spending can exceed the actual provider charge. Valid five-minute/one-hour cache usage detail is settled at its respective rate. Historical usage uses
its previously recorded estimates. Neither value should be described as an invoice.

## Supported billing surface

The guard uses an exact Anthropic standard-tier model-price allowlist, UTF-8
text size plus protocol allowance, full maximum output, and conservative cache
creation costs. Admission and pricing read that size differently: the hold
prices one token per payload byte, which no tokenizer exceeds, while the
context check converts bytes to tokens at the densest measured ratio and
refuses a combined input and output above 200,000 tokens — the smallest
window among the priced models. Unknown models, premium options, multimodal and
provider-side tools refuse before dispatch. Ordinary client-executed function
tools remain supported and each subsequent LLM request gets its own reservation.

MrCall accounts with several businesses can select the billed business using the
saved `SMS_BUSINESS_ID`. The engine forwards it on bounded quote/execute requests,
rejects a quote for another business, and invalidates existing clients when the
saved selection changes. An unset selection leaves the server's existing sole-
business resolution in force; it refuses an ambiguous account.

MrCall credits use the additive `mrcall-bounded-v1` server contract. A free quote
binds the account, business, request and frozen tariff, including markup and
credit rounding. Its maximum debit is reserved atomically with the quote in
`llm_billing_authorizations` before execute. Only a matching receipt of actual
committed credit consumption can settle the reservation. Legacy proxy servers
refuse with upgrade guidance. Lost answers can recover their billing receipt
through read-only status without repeating inference or consumption.

OpenRouter supports the models the resolved table picks plus the allowlisted
GLM 5.2, Kimi K3 and namespaced Claude Opus 5, Sonnet 5 and Haiku 4.5
([model selection](model-selection.md)), and since milestone 10 (slice S3)
any model the model snapshot prices, so an explicit choice keeps running. Legacy requests use the Messages API
with thinking disabled where the model allows it (per-model request rules);
[K3 max](k3-reasoning.md) uses Chat completions with maximum reasoning. Both
adapters send decimal price caps, disable fallbacks and validate the
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
selects economy (output-price ceiling USD 10 per million tokens), balanced
(USD 20) or custom; each role's model under a ceiling comes from the resolved
table ([model selection](model-selection.md)). Saved explicit
role models take priority; the Desktop preset gesture clears individual overrides
when saved. Existing explicit models are preserved until such a deliberate edit.
No model is a default in code: a custom profile with no saved model resolves
each role under economy. Model choice never
changes billing provider. Long-lived clients refuse dispatch after relevant
saved settings change; start a new run or conversation to create fresh clients.

Choose a role by the work it performs, then resolve its saved model through
the normal role override and provider policy. `MODEL_MEMORY_EXTRACT` is for
turning source text into a bounded, structured representation while preserving
source/entity boundaries, exact identifiers and explicit missing information.
`MODEL_MEMORY_MERGE` decides how an extracted item changes existing memory;
`MODEL_TASK_DETECTION` decides whether source text contains an actionable task.
The offline telephone-note converter is implemented in the checkout and uses
`MODEL_MEMORY_EXTRACT` for source-to-structured extraction, rather than a
hard-coded model ID or the merge/task role. The checkout and Café 124 production
read the stored `phone.md` instructions through the operator-instructions
reader. Model-role selection does not establish telephone disclosure quality. The
[voice knowledge plan](../../../docs/execution-plans/2026-09-28-voice-company-knowledge.md)
defines source, refresh, independent output review and activation gates.

See [bounded preparation](bounded-preparation.md) for batch/retry controls and
[model evaluation](../qa/preparation-model-evaluation.md) for offline comparisons.
A small blinded Claude/K3 [comparison](../../../docs/evaluations/2026-09-13-openrouter-models.md)
found consequential Haiku errors; it does not certify production replacements. GLM's prior classifier
results do not establish extraction or merge quality for these workloads.

## Model catalog and payment selection

`llm.models(provider?)` is read-only and free. For `mrcall` it returns the
billing server's authenticated capability catalog; absent or malformed catalogs
return `available=false`, never a fabricated local credit-model list. For BYOK
it returns the engine's supported provider models, without needing a personal
key or contacting a paid endpoint. Entries contain `id`, `label`, `provider`.
The OpenRouter rates frozen on 2026-09-13 were GLM 0.6/2, Kimi K3
2.648138063/13.28272425, Opus 5/25, Sonnet 2/10 and Haiku 1/5 USD per
million input/output tokens. Since milestone 10 (slice S3) no rate is frozen:
each request is capped at, and reserved at, its model's price in the model
snapshot × the margin 1.25 (K3: its pinned DigitalOcean endpoint's price ×
1.25), so GLM 5.2's ceiling follows the catalogue's 0.41/3.99 and K3's its
endpoint's 2.55/12.95 as read on 2026-10-02. Each request enforces these
provider ceilings; actual accounting still uses `usage.cost`. Anthropic models
reserve twice the input ceiling to cover possible upstream one-hour cache writes.

### Where prices come from (since milestone 10a)

One price source, `zylch/llm/roles/prices.py`. In milestone 10a it read two
committed files: the resolved table (`roles/resolved.json`, every pick,
Anthropic fallback and MrCall id at the price the resolver recorded) and the
allowlist of `roles/requirements.json` (every model billed before the table
existed, at the rate above and the eleven direct rates), the allowlist's
billed price winning where an id was in both.

Since milestone 10 (slice S3, brief D5) it reads the model snapshot
(`roles/catalogue.py`: the snapshot layers in force, the build copy
`roles/snapshot.json` last) at every call: a catalogue id at its snapshot
price on OpenRouter (its reference price: the lower median of its eligible
endpoints by Artificial Analysis's blended price, or its model-level price
when its endpoints were not read or none is eligible), a direct id at its
`anthropic` endpoint's price
(Anthropic's list price), a dated id `<alias>-YYYYMMDD` at its alias's. The
allowlist answers only for an id no snapshot prices, until the switch-over;
the resolved table prices nothing. `budget_pricing.PRICES` (direct) and
`openrouter_pricing.RATES` are views over it, so a snapshot installed later
reaches every request. OpenRouter holds and `max_price` are the price × the
margin of `requirements.json` (1.25; K3 from its pinned endpoint's price),
with the provider policy (no fallbacks, parameters required, price sorting,
`requirements.json`'s quantizations, and `only` the endpoints the snapshot
admitted); the direct transport reserves at the list price. The hand-written
snapshot-id map is gone: a response may name the requested id or
`<requested>-YYYYMMDD`. Tests hold the direct rates equal to the `anthropic`
endpoint's. `usage.py`'s estimate prices an id at its snapshot rate (so a GLM
or MiMo pick is not counted at Opus rates); an unpriced one, which admission
refuses anyway, at the dearest direct rate the snapshot holds, with no family
matched by name. The reservation, settlement, unpriced refusal and corpus cap
contracts above are unchanged; only the source of the numbers and the
OpenRouter margin moved. See [model selection](model-selection.md).

Settings exposes `ANTHROPIC_MODEL`, `OPENROUTER_MODEL` and
`MRCALL_CREDITS_MODEL` separately. Selecting a default model explicitly sets
custom policy while preserving job overrides and other providers' keys/models.
No migration changes existing models. The existing preset selector remains an
explicit action which can replace job overrides as indicated before Save.
