# Qonto IPC

<!-- doc-scope:start -->
Scope: native Qonto RPC, managed history, finance task and publication contracts shared by the engine and
Desktop; engine behavior is documented in its Qonto feature document.
<!-- doc-scope:end -->

These methods use the existing authenticated JSON-RPC transport. Authority comes
from the selected engine's verified Firebase session and active profile; no
method accepts an owner, company key, host or arbitrary provider URL override.
See [engine behavior](../engine/docs/features/qonto.md) and
[delivery state](execution-plans/2026-10-04-qonto-connection.md).

| Method | Parameters | Result |
|---|---|---|
| `qonto.status` | none | connection state, generation, bootstrap availability, stored-copy flag and persisted coverage |
| `qonto.test` | `credential_source`, input `login`/`api_key` when applicable; optional `account_ids` | organization/accounts, challenge, expiry, consent version and `company_name: string|null` |
| `qonto.connect` | same credential source, `challenge_id`, `account_ids`, `authority_confirmed=true`, `consent_version` | saved state and bounded initial sync |
| `qonto.sync` | none | bounded source-only sync outcome and coverage |
| `qonto.accounts` | optional `account_ids` | authorized provider balances with source metadata |
| `qonto.transactions` | date basis/from/to, statuses; optional accounts/currency/side/page/page size | bounded source rows, pagination and coverage |
| `qonto.transaction` | `source_id` | authorized bounded transaction detail |
| `qonto.summary` | date basis/from/to, statuses; optional accounts/currency/side | exact grouped flows with source/coverage metadata |
| `qonto.prepare` | optional `resume=false` | bounded private task preparation status, counters and safe errors |
| `qonto.publication_preview` | none | `preview_id`, exact `fact_text`, audience disclosure, generation and expiry |
| `qonto.publish` | engine-issued `preview_id`, `confirmed=true`; optional `resume=false` | committed/skipped/review_needed/refused status and safe reason |
| `qonto.disconnect` | none | application-copy removal and independent bootstrap availability |
| `qonto.delete_imported_data` | `confirmed=true` | private-source deletion; bootstrap and historical facts retained |

`credential_source` is `input` or `bootstrap`. Input credentials are secret
arguments. Test does not save them: Desktop retains a short-lived request-only
copy until Save, edit, expiry, error or context change. Save consumes the exact
tested context and account selection. A key without an organization API login
returns the safe `login_required` outcome.

`company_name` describes the MrCall company bound to the issued challenge;
`null` means unnamed. Desktop requires this field and uses it for confirmation.
Company joins clear consent state, block new operations during cutover and
invalidate pending replies; fresh memory checks also reject stale Save requests.

`date_basis` is `emitted_at`, `settled_at` or `updated_at`; dates are UTC bounds. Statuses
must be explicit. Money objects carry `minor`, `scale` and exact `decimal` text.
Read responses distinguish partial/stale windows and provider balances from
period totals. Narratives are untrusted source text, never instructions.

Retrieval metadata preserves numeric `retrieved_at` and adds `retrieved_at_utc`, an
engine-formatted ISO 8601 UTC string. Both are null for an unknown retrieval
time. The pair is present on read envelopes, account balances, movement records
and per-account read coverage. Finance tools cite the UTC string literally;
both retrieval fields are excluded from account source-revision hashes.

## Managed chat

`system.capabilities` advertises `chat_history_binding=1`. A new Qonto chat sends
`chat.send` with `history_mode="managed_finance"`, a unique conversation ID and
empty/omitted client history, without a handle or revision. Its result adds
`history_mode`, `history_handle` and `history_revision`.

Follow-ups send the same mode and ID with the exact returned handle/revision and
empty client history. The engine loads canonical history after fresh live bank
authorization. Missing/stale binding, UID/host/company/generation changes and
known evidence replay refuse before model reservation. Client context cannot
grant finance access. Old engines and ordinary chats keep the existing contract;
choosing finance starts a separate empty context and preserves old transcripts.

## Preparation, tasks and publication

Preparation respects saved pause; explicit resume starts one batch. Results carry
`attempted`, `completed`, `failed`, `limit`, `paused`, `stop_reason`, and safe
`errors` with `stage`, `detail` and optional error code. Ordinary preparation
status adds `channels["qonto:task"]` for the authorized current binding.

Finance tasks use `channel/event_type="qonto"` and public
`sources.qonto={source_id,source_revision}`. Existing task actions retain engine
authorization; source review calls `qonto.transaction`. Private binding fields
are absent from public copies. Deleted edited tasks remain private unavailable
shells; no email source fallback is available.

Publish without the exact preview or confirmation returns a safe refusal.
Successful publication is limited to the previewed company-use/currency fact.
Pause/revocation prevents later mutation while preserving incurred charges.
Published shared-memory reads add `source_kind="qonto"`,
`source_available=false`, `historical_finance_snapshot=true` and removal guidance.

Engine integration and native Desktop browser fixtures pass. Packaged Desktop,
hosted and live bank acceptance are tracked separately in the delivery plan.
