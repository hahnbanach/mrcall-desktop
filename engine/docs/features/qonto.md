# Native Qonto connection

<!-- doc-scope:start -->
Scope: the engine's native Qonto credentials, private sources, managed chat,
task preparation and consented company-publication boundaries;
verification and hosted rollout state belong to the cross-cutting execution plan.
<!-- doc-scope:end -->

Qonto is an explicit profile-private source in the Python engine. Settings and
managed Qonto chats use the same RPC services on local and hosted engines. The
adapter sends bounded GET requests to `thirdparty.qonto.com`; it offers no payment
or bank mutation tool. A Business API key can nevertheless grant bank-side writes.

Development and verification state: [native delivery plan](../../../docs/execution-plans/2026-10-04-qonto-connection.md).
Source and UI fixtures do not certify a live bank connection or installed Desktop.
Engine preparation/publication and native Desktop browser integration have
fixture acceptance. Support-only authenticated banking, synchronization across
restart, source reads
and a managed assistant answer have live acceptance. Installed Desktop and
provider-UI comparison remain unverified; exact state belongs to the plan.

## Credentials and authority

Test receives request-only credentials and returns the legal organization,
accounts, the current MrCall company label (or null if unnamed), and an expiring
challenge. The label and challenge share the same company authority. Save requires that challenge, a nonempty
tested account subset, authority confirmation and the consent version. The
engine probes again before saving a direct-Fernet encrypted credential copy.
Login and key never appear in Settings readback, provisioning, logs or model tools.

Credentials have one source: the `login` and `api_key` arguments of
`qonto.test` and `qonto.connect`, which the Desktop card fills from its typed
fields. The key argument also accepts a strictly validated combined `login:key`
value; a bare key without a login returns `login_required`. `credential_source`
is optional and `input` is its only accepted value. The retired `bootstrap`
value is refused with `credentials_required`, after the authority checks and
before any provider request; any other value is refused with
`invalid_credentials`.

A Qonto request carries only credentials that arrived in those request
arguments or come from the engine's own encrypted stored copy. That copy is
decrypted with the profile's private `qonto.key` file on a local engine and
with the tenant's injected `ENCRYPTION_KEY` on a hosted one. No engine code
looks up a Qonto credential anywhere else: not in a profile `.env`, not in
another file, not in the process environment. Credential lines left in a
profile `.env` are never used as Qonto
credentials, and every `QONTO_`-prefixed profile key is refused by Settings,
`settings.get_secret` and provisioning. Profile activation loads such lines
into the engine process environment like every other profile line; deleting
them is operator work.

Every bank operation binds the signed, unexpired Firebase UID to its immutable
profile, engine installation, current company, organization, selected accounts
and connection generation. Hosted setup requires a private `QONTO_HOST_ID_FILE`
outside transferable profile data, a writable private parent for its lock,
and the tenant's injected encryption key. Hosted startup validates every saved
Qonto envelope before opening the server; undecodable credentials fail closed.
Company changes, sign-out and revocation fence old work. Profile-only Qonto tables
are created by the serialized migration runner; company databases contain none.

## Sync and reads

Connect starts an initial source-only sync covering 30 days. Manual sync fairly
shares bounded work among initial history, updated movements, recent history and
pending repairs. Pages commit independently; incomplete windows retain progress
without advancing their watermark. Retry eligibility and coverage survive restarts.
No periodic scheduler or mail preparation hook syncs Qonto.

Money retains exact integer minor units, scale and decimal text. Current and
authorized balances come from the provider independently of transaction flow.
All four statuses are requested explicitly; timestamps can be null. Summaries
group by account, currency, status and debit/credit side. They require an explicit
date basis, dates and statuses, and refuse unqualified totals for incomplete,
stale or undated evidence. Traversed windows do not imply a provider snapshot.

Read limits are 31 days, 50 rows per page and 500 summary rows. A source older than
24 hours is stale. Results include opaque source IDs/revisions, retrieval time
and coverage. Read results retain numeric `retrieved_at` and add engine-formatted
`retrieved_at_utc`; finance tools instruct literal UTC citation without model
conversion. Both volatile fields are excluded from balance source revisions.
Bounded drill-down labels bank narratives as untrusted evidence.
Reads re-probe organization/account authority and create no paid reservation.

## Managed assistant history

`system.capabilities.chat_history_binding = 1` enables a separately labelled,
empty Qonto context. Ordinary chats retain the legacy raw-history contract and
have no Qonto tools. Managed chats use engine-issued handles and revisions;
renderer transcripts are display-only. Every managed turn revalidates live bank
authority before loading canonical history or calling a model.

Tool evidence, model history and compaction retain monotonic binding provenance.
Checks run before reservations, provider dispatch and late delivery. Disconnect
keeps conversation tombstones and evidence digests so stripping binding metadata
cannot revive prior evidence through an ordinary chat. Generic acknowledgements
are excluded from assistant-text receipts; structured bank evidence is retained.

Generic memory tools cannot publish retained finance evidence, including before
company journaling. Finance chat, direct read and narration logs expose metadata
only. Progress and separate narration contain no bank payload. Model processing
in a managed chat still sends its authorized evidence to the selected LLM.

## Private preparation and tasks

`qonto.prepare` runs one bounded finance batch. Its deterministic declined-debit
rule creates a private review task without a model call or paid reservation.
It respects the saved pause and shared batch/busy/retry state; `resume=true`
starts one explicit batch without clearing the pause or enabling automatic work.
Source revision and rule checkpoints commit with task changes in one profile
transaction. `preparation.status` adds current-binding `qonto:task` counts.

Task list, count, detail and actions apply the finance predicate before SQL
limits. Desktop finance disclosure and managed `get_tasks` require fresh provider
authority. Generic assistant, voice and mail task processing exclude finance
rows. Public task copies omit the private `_qonto` binding metadata.

Re-evaluation preserves user edits. Disconnect hides source-backed tasks;
imported-data deletion removes generated-only tasks and retains edited private
shells with an unavailable source. These shells remain bound to the original
signed UID, engine installation and company, including after disconnect.

## Explicit company publication

Preview contains only the fact that the company uses Qonto and the selected
business-account currencies. Its 15-minute intent binds the exact fact, source
revision, generation, selected accounts and company. Confirmation discloses
current and future company-key holders and potential selected-LLM processing.

Publication uses one bounded automatic mnemonic item and central pricing. Its
proposal guard rejects expanded facts, targets and model-authored reasons before
company journaling. Real concurrent pause, disconnect and socket cancellation
prevent later commits; already dispatched model charges remain accounted.
Terminal receipt replay recovers a completed company commit without paying twice.

Committed journal provenance and retained versions/alias closure prevent these
facts from following a company join, including one made by another colleague.
Shared reads identify them as historical snapshots with an unavailable private
source. This annotation does not inspect another profile's bank database; use
authorized Qonto reads for current evidence or `/memory delete <blob_id>` to
remove the shared memory.

## Disconnect and deletion

Disconnect removes the encrypted application credential copy and hides bank
reads; reconnecting takes typed credentials and a new Test. Delete imported
data separately removes private source rows and sync/preparation records. It
retains tombstones and historical published facts. Neither action revokes or
regenerates the provider-side key.

RPC details: [Qonto IPC](../../../docs/qonto-ipc.md).
