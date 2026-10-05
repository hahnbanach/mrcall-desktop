---
status: approved
date: 2026-10-04
---

# Qonto company connection in MrCall Desktop — brief

<!-- doc-scope:start -->
Scope: product and architecture for a read-only Qonto source configured inside
MrCall Desktop, owned by its local or hosted Python engine, and available to
its assistant, selected company knowledge and private tasks. This approved
brief neither implements nor authorizes a bank connection.
<!-- doc-scope:end -->

## Intent and first delivery

An existing Desktop user connects their company's Qonto account in Settings,
tests and confirms the company, then asks MrCall about balances and movements
using synchronized, attributable records. The engine owns authentication,
reads, storage and processing on the selected host. The boundary follows the mailbox pattern: GUI setup, engine source, assistant access.

Propose one Qonto organization per profile initially, with explicitly selected
bank accounts, a 30-day initial transaction history and subsequent updates.
Account balances and pending/completed/declined/reversed movements are in scope.
The proposal includes source-grounded assistant reads, private review tasks and
selective publication of useful company facts. Payments, bank-side edits,
automatic invoice reconciliation and claims that an invoice is paid are excluded.

## Existing architecture and PEC precedent

The engine's [sync service](../../engine/zylch/services/sync_service.py),
[tool factory](../../engine/zylch/tools/factory.py),
[memory worker](../../engine/zylch/workers/memory.py) and
[task worker](../../engine/zylch/workers/task_creation.py) are integration
surfaces, not an existing generic banking connector. Qonto needs a dedicated
source adapter and finance-specific processing; a transaction is not an email
or automatically a durable entity fact. [Company visibility](../../engine/zylch/memory/scope.py)
shares company-family facts with every memory-key holder; profile provenance
alone does not make a financial fact private.

The [PEC brief](2026-09-30-pec-net-mailbox-integration.md) and
[plan](../execution-plans/2026-09-30-pec-net-mailbox-integration.md) describe
Settings `MailboxesCard`, `mailboxes.*` RPC, encrypted credentials and
mailbox-specific rows/cursors feeding memory/tasks. At this brief's authoring,
that implementation lived on `feat/additional-mailboxes` in a separate
worktree. The [next-release integration](../execution-plans/2026-10-05-mailboxes-qonto-release-integration.md)
now combines it with Qonto; live PEC acceptance and hosted rollout remain
open. Its mail extraction policy does not establish a policy for publishing
banking data.

## Transport and authentication decision

**Proposed first delivery: direct Business API with the connecting company's
API login/key, scoped to an own-company pilot.** Qonto documents this method
for automating one's own business. It works with either engine location and
requires no shared application secret in a distributed binary. This is a proposal, not a user-mandated credential choice. The adapter permits
only fixed GET routes for organization/accounts and transactions on
`https://thirdparty.qonto.com/v2`; no arbitrary URL, method, redirects carrying
credentials, or bank mutation is exposed to a model. The key itself has write
capabilities: the GUI must distinguish read-only MrCall behavior from a
provider-enforced read-only credential. [Authentication/access table](https://docs.qonto.com/get-started/business-api/authentication/introduction),
[API login/key](https://docs.qonto.com/get-started/business-api/authentication/api-key).

Qonto's official [read-only MCP endpoint](https://docs.qonto.com/mcp/multi-organization)
`https://mcp.qonto.com/multi-organization/mcp` is a credible **engine-side**
alternative: select one organization at OAuth consent, and enforce its exact
`organization_id` on every call. Its OAuth can maintain a client connection;
it is not inherently tied to an external chat app. An engine implementation
would need remote-HTTP OAuth discovery, registration/callback support, protected
token persistence and unattended refresh/restart acceptance. The reviewed
[authentication page](https://docs.qonto.com/mcp/authentication) does not specify
that full custom-engine lifecycle; an unauthenticated metadata probe returned
HTTP 403, which proves neither incompatibility nor working support. Crucially,
its [transaction tools](https://docs.qonto.com/mcp/tools/transactions-and-statements)
exclude pending movements. Direct API is selected for complete intended status
coverage and explicit synchronization controls; Qonto also recommends it for
[embedded/backend integrations](https://docs.qonto.com/mcp/overview).

A general customer OAuth offering is outside this pilot. That path requires a
registered MrCall application and confidential backend exchange/refresh service
with `organization.read` and `offline_access`, serialized rotating refresh
tokens, and authenticated delivery to the correct engine/profile. Electron and
a distributed local engine cannot hold a shared client secret. No such service
is assumed to exist. [Business API OAuth](https://docs.qonto.com/get-started/business-api/authentication/oauth/oauth-flow).

## Desktop connection and authorization

Settings gains a proposed Qonto card: enter login/masked key → Test → inspect
returned legal company identity and account list → select accounts → confirm
binding to the displayed MrCall company → Save and initial sync. Test does not
persist credentials or start ingestion; Save revalidates identity server-side.
Editing credentials invalidates the test. Show host location, read-only behavior,
private financial storage, optional company publication, last successful sync,
coverage and actionable authentication/TLS/network/rate-limit errors. Clear secret
form state after use; never return credentials in Settings/RPC/logs or diagnostics.

Proposed `qonto.test/connect/status/sync/disconnect`, account and transaction read
RPCs belong behind existing authenticated IPC; these names and UI are not current
features. Credentials stay engine-owned, encrypted before persistence, with a
persisted private local key or the hosted tenant key. Missing/invalid keys fail
closed. The [current helper](../../engine/zylch/utils/encryption.py) permits local
plaintext fallback and cannot be reused unchanged. Preserve Firebase UID profile
identity and the in-memory-only Firebase token contract.

Record consent by the connecting Firebase UID, exact Qonto organization ID,
selected account IDs and bound company scope. Successful key access establishes
provider access, not a personal Qonto role: the user explicitly confirms authority
to connect that company. Never infer identity from names or email domains.
Raw bank reads belong only to that profile in this delivery; another colleague
needs their own authorized connection. `MEMORY_KEY` grants no bank access.
A company change suspends sync, financial reads and publication until explicit
rebinding; existing bank-derived material must not silently migrate through
`memory.join`. Switching engine host requires a separately confirmed connection;
credentials and finance records are not silently copied by provisioning.

## Source correctness and useful processing

Store financial source records in profile SQLite, separate from company memory,
with organization/account/provider transaction identity, source revision and
retrieval time. Preserve exact minor-unit/decimal amounts, debit/credit side,
account/original currencies, raw statuses, nullable emission/settlement/update
timestamps and account balance timestamps. Never sum currencies together or
present calculated period cash flow as the account balance. Request all intended
statuses explicitly: API transaction listing defaults to completed only.
[Transaction contract](https://docs.qonto.com/api-reference/business-api/transactions-statements/transactions/list-transactions).

Initial sync covers the declared emitted-date window; incremental reads use
bounded update-time windows, overlap and every returned page. Provider-ID upserts
must survive retries/restarts and update pending-to-completed/reversed records,
including older rows updated later. Commit a cursor only after its entire window
succeeds. Persist per-account coverage and partial progress; interrupted/paged
results cannot support completeness claims. Re-scan overlapping history to handle
moving pagination and stale pending rows; do not assume snapshot isolation.
Back off on throttling and distinguish authorization failure from temporary
outage. Connection performs source reads without paid extraction; subsequent
sync is manual initially. [Qonto synchronization guidance](https://docs.qonto.com/get-started/business-api/use-cases/sync-transactions).

Assistant tools query this authorized source with bounded filters and drill-down
by source ID. Answers state account, currency, status, date basis, retrieval time
and coverage; failed/stale reads are explicit. Financial calculations are
mechanical. Notes and counterparties are untrusted source text, never instructions.
Only the records needed for an authorized answer go to the configured LLM, under
existing engine billing/budget controls; setup discloses that processing boundary.

**Proposed sharing policy:** raw rows, balances, personal counterparties, account
numbers and transaction narratives never enter ordinary shared memory or voice
context automatically. The owner may publish a previewed, minimal durable company
fact, such as the company's use of Qonto with an EUR business account. Supplier
identity/relationships require corroborating identity evidence; a matching payment
label alone is insufficient. Publication explicitly authorizes visibility to all
current/future holders of that company's key. Use the existing mnemonic commit
path with source/revision attribution and idempotent ingestion, not direct writes.
This selective policy is a proposal; the user specified integration, not unrestricted
financial disclosure. [Memory contract](../../engine/docs/features/mnemonic-commit.md).

A dedicated finance stage can feed the existing private task workflow with a
source-linked suggestion such as “Review this declined outgoing transaction”,
when the owner explicitly runs preparation. Deduplicate by source and rule,
re-evaluate on source revisions and preserve user edits; no task executes a
payment or declares an invoice settled. Financial task evidence obeys the same
profile access boundary. Both processing paths retain preparation pause, batch
limits, paid admission and completion guards; raw transactions never pass wholesale
through the mail/entity prompt. [Preparation contract](../../engine/docs/features/bounded-preparation.md).
## Hosted operation and removal

Hosted requests run under the profile's Unix identity. Allow only the required
Qonto API hostname in that tenant's egress policy, with TLS validation and existing
resolver enforcement; no other tenant's policy changes. The pilot downloads no
attachments and needs no presigned-file hosts. [Hosted boundary](../remote-backend.md).

Disconnect fences running jobs/late writes, erases credentials and disables all
financial tools and processing; revoked keys cause the same access refusal.
Retain raw rows privately but hidden until same-company reconnection or explicit
Delete imported data, which removes rows/cursors and source-only task evidence.
Published company facts remain explicitly shared historical knowledge, with source
unavailable after deletion; the confirmation explains this and offers their
ordinary memory removal flow without claiming to retract already disclosed data.
Qonto-side key regeneration is a separate user action that can affect other
integrations; removing MrCall's copy does not revoke the provider key.
## Acceptance and remaining limits

- Fixtures exercise GUI test/save/restart, wrong-company/account/UID refusal,
  company joins and host switches, encryption failure, secret redaction, denied
  non-GET requests, duplicate/replayed pages, partial failures, throttling,
  status changes, date/currency arithmetic, coverage and disconnect races.
- Through actual assistant/task/memory entry points, verify useful grounded
  answers, private deduplicated review tasks, explicit selective publication,
  no raw financial leakage to another key holder or voice, paused/budget-refused
  processing, deletion and same-company reconnect. Existing mail still works.
- Supervised Desktop acceptance runs against both local and isolated hosted
  engines: connect one authorized company, select accounts, sync twice with a
  restart, compare a balance and sampled movements/statuses to Qonto's UI, ask
  a bounded question, exercise a task/publication fixture and disconnect.
  Record coverage, engine identity and results without bank content in git.

No Qonto account, eligibility, key, product OAuth registration, MCP engine
refresh flow or live Desktop connection has been verified. This rewrite used
repository evidence and official public documentation only; it changes no code,
configuration, bank state or credentials. Fresh brief review precedes planning.
