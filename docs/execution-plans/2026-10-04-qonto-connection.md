---
status: active
brief: ../briefs/2026-10-04-qonto-connection.md
date: 2026-10-04
base_commit: d30e5680f42117516c58333ed01b84050bdc3694
---

# Qonto native company connection — execution plan

<!-- doc-scope:start -->
Scope: implementation milestones for the native MrCall Desktop Qonto company connection, including the explicitly authorized support-only deployment and its verification and rollback boundaries.
<!-- doc-scope:end -->

## Delivery state

- Approved brief and plan: native engine-owned Qonto source and Desktop setup.
- M1–M5: APPROVED for identity, source sync/reads, managed history, private task/publication boundaries and native browser fixtures.
- M6 and separate final review: APPROVED for support-only deployment and actual authenticated banking/RPC/assistant acceptance, including Firebase and UTC timestamp corrections.
- M7 integration and separate final review: APPROVED on main above 0.1.53, including the combined logout/finance correction. The scoped local integration retains the published authentication repair; no new installer is published.
- Verification: original focused engine suite 518 passed; timestamp correction suite 96 passed plus one stricter RPC regression. Focused Ruff/Black and the documentation mechanical gate pass. Native browser and company-change/history journeys pass.
- Scope of approval: installed/packaged Desktop and Qonto-provider UI comparison remain unverified. Finance preparation, publication and deletion have fixture acceptance; they were not executed against the live bank.
- Plan status stays `active` for the remaining installed Desktop/provider-UI checks. Historical gate revisions and diagnostic evidence are in the [archive](../active-context-archive.md#2026-10-05--qonto-rollout-and-correction-evidence-before-reconciliation).

## Classification and authority

Substantial work: new persisted financial data, authenticated RPC, bank credentials, company isolation and user behavior rule out the direct fast path. M1–M6 were implemented in `feat/qonto-company-connection`, `/home/mal/worktrees/mrcall-desktop-qonto`; M7 integrates that reviewed delta into main. Do not import the additional-mailboxes branch. Its encrypted credential pattern is a reference only.
The approved brief governs M1–M5. The subsequent operator instruction authorizes updating and testing **support@mrcall.ai's existing remote-engine profile on this machine**, whose profile `.env` already contains `QONTO_API_KEY`; M6 incorporates that narrower live authority. It does not authorize payments, arbitrary company publication, other tenants' changes or changes to preparation/billing settings.
The lead owns integration and rollout. Engine and app work belong to this repository. A fresh reviewer approves this plan before execution; every milestone receives a fresh integration review before dependent work starts. Repair and re-review with the same reviewer for that gate. A separate fresh reviewer handles final end-to-end acceptance.

## Decided architecture

- Implement `engine/zylch/qonto/` as small provider, identity, secrets, connection, repository, sync, reads, preparation and publication modules, each below 500 lines. Extend existing storage, RPC, assistant and Settings entry points; no MCP client, OAuth application, generic connector framework or parallel task ledger.
- `SyncService.run_full_sync()` is mail-specific today. Qonto therefore has its own `qonto.sync` service/RPC and explicit Settings action; connect starts one initial source-only sync. Ordinary update/auto-update must neither sync Qonto nor analyze financial rows. Finance preparation/publication are explicit actions sharing the existing preparation admission machinery.
- Finance identity is the active profile's immutable `OWNER_ID`, matching the active profile directory/identity and nonexpired Firebase session UID. Never use `cli.utils.get_owner_id()` as bank authority: it currently returns an email. Reject missing UID, UID disagreement, unavailable company memory and pending company join. Derive company binding inside the engine from the current memory key; persist only its domain-separated digest in profile finance tables and never return/log the capability or digest.
- A connection binds `(profile UID, host identity, Qonto organization ID, company scope, selected account IDs, generation)`. User-supplied IDs only narrow this binding. No RPC accepts an owner/company capability override. A live organization GET revalidates identity/accounts before connect, sync and financial read admission; network/auth failure refuses new source access with actionable status rather than serving a silently authorized cache. Already delivered answers cannot be retracted.
- Host identity is a private generated engine-installation UUID outside transferable profile data: local engine home, or a tenant-owned private file configured during hosted setup. It is never provisioned from Desktop. A different instance/mode requires a fresh test/confirmation; Qonto credentials, keys, records and bootstrap inputs are absent from provisioning payloads. The UI invalidates state on transport/profile changes.
- Persist connection state/generation before revocation returns. A per-profile cross-process guard plus transactional generation comparison fences sync, task and publication writes. Hold that guard only around short commits/state changes, never network/LLM waits. All Qonto commit paths use guard → company transaction (when needed) → profile transaction in one documented order; do not claim two databases commit atomically. Cancel in-process handles too, but persisted fencing remains authoritative after restart.
- On company join, suspend/fence finance before cutover and retain the suspension after a failed/abandoned transition until deliberate reconfirmation. Boot/read guards also compare bindings, covering hosted operator joins and crashes. Published Qonto-derived blobs and their dependent versions/links/aliases must remain in their original company, not follow `join_import`; M4 implements durable provenance exclusion.
- Disconnect erases encrypted credentials, increments generation, cancels work and hides raw reads/tasks. A detected 401/403 likewise fences access and erases unusable credentials. Retain hidden source rows for reconnection to the exact original company and organization; a different binding starts fresh and does not relabel retained rows. Delete imported data removes rows, accounts/cursors/preparation checkpoints and generated source-only task evidence; preserve user-authored task edits as a private source-unavailable shell. Published facts remain historical shared knowledge with unavailable source and an ordinary memory-removal link.

## Credential bootstrap contract

Qonto requires organization login and secret in `Authorization: <login>:<key>`; this is not Base64 Basic authentication. [Official authentication](https://docs.qonto.com/get-started/business-api/authentication/api-key).
- Preferred bootstrap variables: `QONTO_API_LOGIN` and `QONTO_API_KEY`. Read only on an explicit `qonto.test(credential_source="bootstrap")` or matching connect. No automatic connection/ingestion at boot. A key alone produces `login_required`; do not guess the login from company/email names.
- Support's existing profile `.env` is an authorized bootstrap source. If its key field contains exactly a valid combined `login:key` header value, split it in memory with strict validation; reject malformed/ambiguous values and conflicting separate login. Report only availability/classification, never values or lengths. A bare key still needs login.
- Development file is `/home/mal/worktrees/mrcall-desktop-qonto/.env.qonto`, explicitly ignored and selected using `QONTO_BOOTSTRAP_ENV_FILE` at local engine launch. Only the two credential fields are parsed, with dotenv interpolation disabled; never source the file as shell code. This developer override is disabled on hosted engines. Hosted bootstrap reads only that daemon's active profile `.env`.
- Keep bootstrap/key fields out of all three Settings/onboarding allowlists, `settings.get_secret`, config diagnostics and provisioning. Add explicit deny/redaction guards so future schema edits cannot expose them. `qonto.status` returns bootstrap availability only. Dedicated RPC credential arguments are both treated as secrets; safe exception mapping strips provider bodies, SQL parameters and HTTP headers.
- Test holds credentials in request memory only and returns company/accounts plus an opaque expiring confirmation challenge bound to the context and credential fingerprint. Connect consumes that challenge, re-probes, checks authority/account confirmation and encrypts both login/key before writing. Editing credentials invalidates the challenge. Save clears renderer secret state.
- Use direct Fernet, never the locally fail-open `utils/encryption.py` encrypt/decrypt functions. Local key: atomic exclusive creation of a 0600 file in the private profile, persisted/fsynced before ciphertext; serialize first creation and reject symlinks/unsafe permissions. Hosted key: existing tenant-injected `ENCRYPTION_KEY`, never generate/read root secrets as an application fallback. Missing/invalid/wrong key fails closed. Extend hosted rekey enumeration for the new ciphertext column.
- Bootstrap credentials remain user-managed configuration. Read them only for explicit test/connect; never erase, consume or rewrite `QONTO_API_LOGIN`/`QONTO_API_KEY` in the support profile `.env` or development bootstrap file. Disconnect removes the encrypted application connection copy and reports independently retained bootstrap availability without secret readback. It must not claim every credential copy was erased, and must never auto-reimport a disconnected source. Clear request/renderer credential state after use. Do not regenerate/revoke the Qonto-side key.

## M1 — Private storage, authority and credential lifecycle

**Dependencies:** approved plan. **Owner:** engine connection/storage owner; lead reviews cross-cutting hooks.
- Add profile-only models in `qonto/models.py`, imported during `storage/database.py` initialization: connection (one active organization per UID), selected accounts, transactions, per-account sync windows, finance processing checkpoints and publication intents. Keep these out of `MEMORY_TABLE_NAMES`; store no raw provider JSON/attachments beyond the declared source fields.
- Connection stores encrypted credential envelope, status, immutable authority/binding fields, generation and consent timestamps/version. Transactions uniquely key UID + organization + account + provider `transaction_id`; keep opaque `id` separately if supplied. Store normalized source revision hash and retrieval time. A stable source identifier contains opaque IDs, never labels/account numbers.
- Verify Firebase JWTs before session admission in both token-update RPCs and headless refresh, derive UID/email/expiry from signed claims, and enforce the selected profile owner. Keep valid verified local pre-profile sign-in available for onboarding. Regression includes real WS dispatch within expiry grace and refusal of forged future-expiry updates.
- Add strict context/secrets/bootstrap services and `rpc/qonto.py`, registered in `rpc/methods.py` with complete parameter declarations; extend `rpc/dispatch.py` secret/error handling. Implement test/connect/status/disconnect/delete lifecycle first against provider fixtures; M2 supplies real transport. Status must remain callable for disconnected/auth-failed states without revealing bank rows.
- Add common generation guard, crash recovery and company-mismatch suspension. Hook `memory/join.py` before cutover and `join_recover.py` recovery; no write to `MEMORY_KEY` outside existing join. Guard settings/provisioning readback and `storage/rekey.py` for Qonto.
- Expose additive migrations through the existing serialized migration runner and actual `init_db()`. On first deployment back up the profile database using SQLite backup, preserving WAL, plus private config/key files. Repeating migration must preserve existing mail/task/token rows and create no finance tables in company storage.
**Verification to implement/run:** `tests/qonto/test_identity.py`, `test_secrets.py`, `test_lifecycle.py`, `test_schema.py`; use real split databases and dispatch handlers. Assert wrong UID/company/host/account, expired session, missing key, corrupted ciphertext, concurrent first key creation, bootstrap redaction/preservation and no automatic reimport after disconnect, restart, duplicate connect, disconnect late writes and migration replay. Fixture spies must fail on any LLM call or budget reservation during test/connect/status/disconnect.
**Gate/rollback:** independent M1 integration review includes raw RPC rejection and encryption inspection. Additive tables can remain after code rollback; disconnect/fence before rollback, retain private key for restoration, never downgrade into plaintext. No dependent code before approval.

## M2 — Fixed provider GETs and resumable source sync

**Dependencies:** M1 approved. **Owner:** engine provider/sync owner.
- Implement fixed `https://thirdparty.qonto.com/v2/organization` and `/transactions` requests in `qonto/provider.py`; account selection comes from returned organization accounts. Fixed GET only, verified TLS, redirects disabled, bounded connect/read/overall deadlines, response/page size caps and no caller-defined URL/path/proxy override. Provider errors become enumerated safe outcomes (`auth`, `tls`, `network`, `rate_limited`, `invalid_response`).
- Query `status[]=pending,completed,declined,reversed` explicitly and use `bank_account_id`; the provider defaults to completed otherwise. Preserve raw status, debit/credit side, account/original currencies and nullable emitted/settled/updated timestamps. Parse JSON decimals exactly, retain provider cents as integers with scale metadata, and reject inconsistent representations. [Transaction contract](https://docs.qonto.com/api-reference/business-api/transactions-statements/transactions/list-transactions).
- Initial history is `[run_started_utc - 30 days, run_started_utc]` on emitted time, split into bounded daily windows. Incremental windows are update-time ranges from the last completed watermark minus 48 hours to fixed run start, without emitted-date restriction, so old movements revised now arrive. Explicit ascending sort for that window's date basis, `per_page=100`, follow validated numeric `meta.next_page` until exhausted; refuse loops/inconsistent metadata.
- Per-account durable window state records bounds, page progress, observed count, status/error and completion. Upsert each page under generation guard; a partial window does not advance the account watermark. Restart the interrupted window from page one, allowing duplicate pages. Store source changes only when normalized revisions differ; an older provider update never overwrites a newer version. Equal timestamps with changed content are re-read rather than silently discarded.
- Allocate bounded window/request work fairly across initial, incremental, recent and pending purposes and selected accounts, retaining durable scheduling progress. Repeated successful manual runs must reduce unfinished initial history even when maintenance work alone exceeds the global batch bound; the converse must not starve current updates or pending repair.
- Every manual sync also revisits the recent emitted window and bounded windows containing unresolved pending records, with all statuses; track remaining backfill work. Moving pagination cannot prove snapshot completeness: flag changed page totals/inconsistent scans, retry within a finite allowance and report partial coverage on exhaustion. Watermarks represent fully traversed windows, not permanent provider completeness.
- Refresh provider balances independently from transaction totals and store provider timestamp when supplied plus retrieval time always. Show current/authorized balance distinctly; never infer balance from period flow. Honor `Retry-After`, persist retry eligibility, cap retry budget and resume manually; zero cursor advancement after failed window. No bank payload in progress notifications/logs.
- Implement `qonto.sync` single-flight per connection and connect's initial sync, reporting persisted partial state. Cleanup/disconnect can cancel while a GET is blocked, and its response must fail the generation check. No periodic scheduler or mail pipeline hook.
**Verification to implement/run:** `tests/qonto/test_provider.py`, `test_sync.py`, `test_amounts.py`: non-GET/redirect/untrusted-host refusal, all-status query, 2+ pages/replay/restart, partial page failure, 429/backoff, older revised transaction, pending→completed/reversed, null timestamps, UTC boundaries, multi-currency, stale pending repair, moving pagination and concurrent disconnect. Invoke through real `dispatch_raw` plus injected HTTP transport, not only adapter methods.
**Gate/rollback:** M2 review checks persisted coverage against fixture ground truth and unchanged paid ledger. On rollback retain cursors/rows hidden; do not attempt to reverse provider activity because none was performed.

## M3 — Grounded assistant access and source privacy

**Dependencies:** M2 approved. **Owner:** engine assistant/read owner.
- Add bounded `qonto.accounts`, `qonto.transactions`, `qonto.transaction` and mechanical `qonto.summary` RPCs backed by the same authorization/read service. Require explicit date basis and status filters for aggregates; cap date windows/page size and return pagination. Group totals by account/currency/status/side and label signed net flow separately from balance.
- Add corresponding read-only tools in `tools/qonto_tools.py`; register them in `ToolFactory.create_all_tools()` and document discovery/use in `assistant/prompts.py`. `_get_tool_schemas()` already enumerates registered tools; assert schemas reach the actual assistant and no separate hard-coded routing list hides them. Finance setup/sync/deletion/publication are not model tools.
- Each result carries source IDs/revisions, account/currency/status/date basis, retrieval time and coverage/partial/stale flags. Preserve narrative/counterparty text only for bounded requested drill-down and mark it untrusted. Refuse external instructions embedded in provider labels. No bank rows in ordinary memory extraction, shared context, voice tool schema or source-less automatic summaries.
- **M3 history ownership:** add `qonto/history.py` and one profile-private conversation table holding an opaque engine-issued history handle, revision, canonical model history and monotonic finance provenance `(UID, engine instance, company, connection generation, source references)`. `rpc/methods.py:chat_send` resolves this record before calling `ChatService.process_message`; do not use the existing ephemeral `chat_session.py` manager as durable authority. Create the record only on a new explicitly finance-capable empty-history chat, persist provenance before a finance tool result is appended/returned, and persist subsequent model history/compacted summaries with that provenance. Client `context` cannot set or clear it. Unknown/stale handles, revision mismatch or an existing conversation whose handle was stripped fail closed before routing, compaction or any model call.
- **Actual client contract, owned in M3:** advertise `chat_history_binding=1` in `system.capabilities`; extend preload/types and `views/Workspace.tsx` plus `store/conversations.ts` to negotiate an explicitly finance-capable managed context and retain its opaque handle/revision. Require a managed context before exposing Qonto tools. Within that context renderer history is display-only; the engine loads canonical history and rejects nonempty client-supplied `conversation_history`, unknown/stale handles and stripped binding metadata, including a different conversation ID. Preserve the existing raw-history contract and follow-up behavior for ordinary nonfinance conversations and old Desktop/direct callers; Qonto tools and evidence are unavailable on that path. Do not reset or migrate ordinary email transcripts. A legacy conversation chosen for finance starts a separately labelled empty managed context while its old transcript remains displayable. Retain finance-managed binding/tombstone and engine-owned rendered-evidence receipt/digest records after disconnect so stripping handles or replaying known engine-produced finance messages cannot downgrade them to the legacy path; this matches known evidence, not semantic detection of arbitrary user text. Capability negotiation must permit an engine-only support rollout with the old Desktop still working. M3 owns these minimal client changes before its review, rather than deferring the privacy contract to M5.
- **Before every disclosure:** authorize the engine record at `chat.send` entry, before `chat_service.py` calls `compact_if_needed`, immediately before the compactor's `client.create_message`, and in `assistant/core.py:_create_message_within_budget` before every initial/tool-loop `client.create_message`. Pass an engine-owned history guard through turn context into all descendant paid calls; `llm/client.py` checks it at the existing pre-reservation/dispatch boundary, covering auxiliary summarization and a scope change between prompt construction and dispatch. Finance access refusal must propagate out of `chat_compaction.py`'s broad fallback catch rather than returning the original forbidden history. Compacted summaries retain the same provenance; never infer safety from the absence of a tool-result block. Verify UID, active nonexpired session, host/company and current connected generation each time. Invalid history is retained privately but unavailable; reconnect does not revive old-generation history. A fresh empty conversation is allowed, and bank facts a human newly authors are outside this provenance guarantee.
- Enforce the same engine-owned finance provenance in `memory/mnemonic/authorization.py`: generic create/update/correction paths cannot publish retained finance evidence; only M4's consented minimal projection is eligible. Recheck before source results and answer completion, suppressing late output after disconnect/signout/host change. An already dispatched authorized call cannot be withdrawn; changed authority blocks every later dispatch and delivery. Existing central pricing/reservations remain authoritative; add no synthetic paid holds to reads.
- **M3 logging ownership:** update `assistant/core.py:_execute_tools` so finance tools and every later tool in a finance-marked turn log only registered tool name, turn/step, status/error code and safe counts. Suppress `full_input`, `tool_result.message` and formatted results at the current lines 531/642/676, including errors and direct-response tools. Redact `chat.send` message/history/context at `rpc/dispatch.py` before debug logging, and replace `chat_service.py` raw user-message/context logs with metadata on this path before provenance admission. Progress/narration may consume only these safe metadata events, never bank labels, amounts, narratives, account numbers or full tool payloads. Do not rely on disabling DEBUG or the voice-only logging condition.
**Verification to implement/run:** `tests/qonto/test_reads.py`, `test_assistant.py`, `test_privacy.py` through `chat.send`/real tool schemas with deterministic LLM responses: correct summary/source citation, omitted/stale coverage refusal, malformed filters, second profile with same memory key denied, adversarial narrative ignored, generic memory write blocked now and after conversation replay, voice absent, expired/revoked credentials and late-answer cancellation. Use real billing refusal test doubles to prove no answer dispatch when budget admission refuses. Add `tests/qonto/test_history_authorization.py` through real `dispatch_raw`/`chat.send` and `app/scripts/test-qonto-history.mjs` through the Workspace/preload contract: old Desktop/nonfinance raw-history follow-ups remain unchanged with no Qonto tools; managed finance follow-up/restart with a valid handle works; force compaction, then replay after disconnect/company join/host or session change; strip/forge metadata, reuse another conversation ID, submit nonempty unreceipted history, and invalidate authority between tool result, compaction and the next model call. Assert zero compactor/LLM reservations and provider dispatches after refusal, with no forbidden original-history fallback. Add `tests/qonto/test_chat_logging.py` with DEBUG enabled and distinctive bank-label/narrative/IBAN/amount fixtures; capture Python logs, RPC progress and narration inputs across successful tools, errors, generic follow-up tools and replay. Assert fixture content absent while safe tool/status/count progress remains present. Actual authorized answer delivery is checked separately from metadata progress.
**Gate/rollback:** fresh M3 review asks an account-bounded question via real RPC/assistant entry, not a direct service call. Disable tool registration on rollback while retaining private storage; verify existing email search still reaches its tool.

## M4 — Explicit finance preparation and consented company facts

**Dependencies:** M3 approved. **Owner:** engine preparation/memory/task owner.
- Implement `qonto.prepare` as a dedicated bounded run, not general email analysis. Default respects saved pause; `resume=true` is the explicitly labelled one-batch action, uses `preparation_run(uid, explicit=True)` and never clears saved pause or enables auto-update. Shared busy/batch/retry counters come from `services/preparation.py`; check run/generation both before work and before commit. Add finance pending/checkpoint counts to `rpc/preparation.py` without counting transaction rows twice.
- The first deterministic rule is “Review this declined outgoing transaction.” `bounded_item("task:qonto")` admits `(source ID, source revision, rule version)` attempts; task mutation plus finance checkpoint commit in one profile transaction before completion is counted. No LLM is needed to classify an explicit declined debit; budget exhaustion does not prohibit this free rule and must create zero paid reservations. User pause and batch exhaustion still stop it. Never declare invoice settlement or initiate payment.
- Use actual `TaskItem` rows with `event_type/channel="qonto"`, UID owner, stable source+rule event key and source reference/revision in `sources`. Add one storage predicate that retains legacy email ownership for nonfinance tasks and selects Qonto tasks only for current authorized UID/binding; use it across task lists/counts/direct lookup/prefix/actions, including source enrichment. This keeps existing Tasks UI/RPC useful after email rename without granting email-based bank access.
- Ordinary model task tools and voice exclude Qonto task rows/counts/details unless the turn has the M3 engine-managed finance guard. Finance-enabled task tools mark source provenance and recheck before delivery; Desktop task RPC/UI remains privately authorized through the same UID/binding predicate. This prevents generic task tools from bypassing the managed-history boundary.
- Qonto task re-evaluation updates machine-owned source status/evidence separately from user title/body/completion/snooze/pin changes. Exclude Qonto from mail/contact dedup, hygiene and email reanalysis; show a dedicated Review source action instead of generic email Solve. Disconnect/joins hide these tasks, and deletion removes only generated source-only material. Test ordinary task behavior unchanged.
- `qonto.publication_preview` produces only an engine-built minimal fact: company uses Qonto and selected business-account currencies. No balances, IBAN, personal names, narratives or arbitrary text. Supplier relationships are not inferred; adding one requires a separately evidenced identity workflow, outside this first whitelist. Preview discloses all current/future company-key holders and potential selected-LLM processing.
- `qonto.publish(preview_id, confirmed=true, resume?)` checks exact preview/source revision/company/generation and records a private consent intent. It runs one `bounded_item("memory:qonto")` in the same preparation machinery, builds an AUTOMATIC `MemoryEvent` with deterministic event ID and opaque `qonto` source/revision, then calls existing `mnemonic.commit.submit`. Do not use `facts_store.upsert_fact`'s exception-swallowing facade or direct blob writes. Surface committed/skipped/review/refused and propagate paid/pause refusal without marking processed.
- Restrict mnemonic output to the previewed minimal FACT/company scope; any semantic expansion or other target/content becomes `review_needed`. Keep central model pricing/reservations, origin-bound grant and completion guards. Add an engine-only commit guard to `CommitContext` (default no-op) wrapping commit, plus a cancellation/binding check before every paid dispatch; Qonto supplies the persisted generation guard. Receipt replay recovers a crash after company commit before private publication checkpoint, without paying twice.
- Use committed journal `source_ref=qonto:…` plus `committed_ids`, retained versions and alias closure as durable bank provenance. `join_import._snapshot()` excludes all such blobs and their dependents before copying, including merged keepers; exclusion must work when the joining colleague is not the publisher and after original profile deletion. A later ordinary edit must not erase provenance. Show excluded count in join result. Keep original-company facts accessible as historical knowledge after raw deletion, with source-unavailable status; ordinary memory deletion remains available.
**Verification to implement/run:** `tests/qonto/test_preparation.py`, `test_tasks.py`, `test_publication.py`, `test_join.py`: real preparation→TaskItem→tasks.list/get/close/UI path; source revision and user edits; pause/batch/busy/retry/restart; free rules at zero budget; paid publication refused before dispatch at zero budget; preview mismatch/no consent denied; mnemonic commit/replay/CAS/cancellation; raw payload absent from company DB/journal/voice; join by publisher and colleague, alias/version leakage, disconnect/delete races. Re-run focused preparation, mnemonic admission/write-boundary and join-cutover suites.
**Gate/rollback:** fresh M4 reviewer checks actual tasks and mnemonic receipts in split databases. Remove pending intents on disconnect; a historical shared fact cannot be undisclosed by rollback. No migration or rollback may reinterpret it as permission in another company.

## M5 — Desktop Settings and private source review

**Dependencies:** M2 contract approved for independent UI fixture work; final M5 integration depends on M3/M4 approval. **Owner:** app owner; lead owns any shared engine contract changes.
- Add `components/QontoCard.tsx` to `views/Settings.tsx`, typed bindings in `preload/index.ts` and `renderer/src/types.ts` (prefer a focused finance types module). Use existing per-window `rpc:call`; do not expose arbitrary transport or engine paths.
- Flow: masked login/key or “Use engine bootstrap” → Test → returned legal company/account list → selected accounts + current MrCall company/host + authority confirmation → Save and initial sync. Editing inputs invalidates Test. Display no existing secret value; clear secret state after use/unmount/signout/transport change and ignore late responses from prior contexts.
- Show private-storage/selected-LLM boundary, read-only application versus write-capable provider key, sync/coverage/status/errors, manual sync, explicit one-batch preparation, previewed publication confirmation, disconnect and distinct Delete imported data. Explain historical shared facts and provider-key regeneration separately. Missing/old engine fails closed with an update message.
- Extend Tasks channel/filter/source detail types for Qonto and render a bounded finance evidence detail using `qonto.transaction`; source unavailable does not fall back to email. Existing close/snooze/pin remain in the private task workflow under engine predicates. Publication stays in the explicit card preview flow.
- Add engine/app feature docs and IPC contracts describing implemented behavior; update relevant thin indexes/current snapshots without rewriting unrelated stale documentation. Add credential-free `.env.qonto.example` under engine docs/examples and ignore only the real development bootstrap path.
**Verification to implement/run:** `app/scripts/test-qonto.mjs` follows existing React fixture journeys and exercises test/edit/retest/save/restart, bad account/authority, bootstrap-only setup, manual sync, task review, publication preview, disconnect/delete, old engine and account/host-switch late replies. Add a browser fixture check of the complete Settings+Tasks user path; fixture transport must preserve the same contract as real RPC. Run `npm run typecheck`, `npm run build`, `node scripts/test-preparation.mjs`, `npm run test:onboarding`; no screenshots containing bank data in git.
**Gate/rollback:** fresh M5 review includes an interactive fixture browser journey and actual preload method names. UI can be reverted independently after disabling pending operations; engine authority must remain sufficient without UI checks.

## M6 — Support-only hosted rollout and separate final acceptance

**Dependencies:** M1–M5 approved. **Owner:** lead for host operations; engine/app owner for fixes; fresh final reviewer.
- Before any deployment, identify support's exact Firebase UID, tenant Unix user/unit/socket, current executable/source release, private profile/config/key paths and active egress policy using metadata only. Confirm session/profile UID/company binding and credential availability without printing values. If `QONTO_API_LOGIN` is absent and key is not validated combined form, finish all fixture work and report live login acceptance unavailable; do not guess or use another account.
- Stage an isolated support release from the current serving tree and apply only the reviewed Qonto patch with conflict checks; retain its existing `llm/bounded_proxy.py` and billing behavior. Use the freshly verified serving commit regardless of ancestry; do not replace it with the whole development branch. Rehearse the patched release against disposable profile/store copies before switching the unit; retain the active release and unit configuration. Do not update a checkout imported by other daemons. Back up support profile DB via SQLite backup plus private config/key files with 0600 protection, record preparation pause/auto-update/billing limits, and verify restoration on a disposable copy. Shared company schema must remain unchanged; M4's provenance reads use existing journal tables.
- Extend existing `engine/scripts/server/egress_policy.py` usage with an opt-in support policy entry for `thirdparty.qonto.com`, TCP443 only, preserving every other endpoint and tenant. The compiler currently matches DNS suffixes; use the most specific hostname, retain provider exact-host enforcement and do not claim firewall hostname equality. Add fixture tests proving no global flush/other-tenant changes. No attachment/presigned-file domains are needed.
- Record previous support egress artifacts and atomically install only its reviewed delta; verify DNS/TLS/API reachability as that tenant. Retain policy rollback. Extend hosted rekey/startup validation to include Qonto ciphertext and confirm provider login is never attempted with undecodable material. Do not expose the tenant key in output or copy it into a release.
- Switch/restart support's unit only, confirm process identity/socket/health/current release and unchanged other-tenant unit states. Verify pause/batch/provider/budget/automatic-update readback against before-state. On health/auth/encryption/regression failure stop Qonto work, restore its previous unit/release/policy/config and SQLite backup only if incompatible writes require it; never restore shared company memory from a profile backup.
- Using the operator's scoped authorization, execute test→company/account selection→connect→manual sync twice across a support-daemon restart→bounded source question→disconnect/same-company reconnect. Record account IDs/coverage privately and compare provider balances and sampled statuses/movements with Qonto's UI when that UI is available. Selection binds only the provider organization returned by support's key to support's existing MrCall company; do not change company membership. A material identity contradiction stops live work.
- Do not publish real financial facts or start paid preparation merely because connection testing was authorized. Exercise task/publication/pause/budget/deletion through disposable fixtures; use a real support publication only if the operator explicitly confirms its preview. Keep bank payloads and protected backups outside git. Do not make Qonto key regeneration part of cleanup.
- Run the real Desktop against a disposable local fixture engine and the selected hosted support engine when a GUI is available. If this environment lacks a signed-in Desktop or Qonto UI, authenticated hosted RPC acceptance can complete but GUI/provider-UI comparison remains explicitly pending; never substitute unit tests for that claim.
**Focused regression/acceptance commands:** engine `venv/bin/python -m pytest -q tests/qonto tests/services/test_preparation.py tests/memory/test_mnemonic_join_cutover.py tests/memory/test_mnemonic_write_boundary.py tests/llm/test_mnemonic_admission.py tests/email/test_sync_cursor.py`; hosted policy `venv/bin/python -m unittest discover -s tests/server -p test_egress_policy.py`; app M5 commands plus `ZYLCH_BINARY=<tested-sidecar> npm run dev` for actual GUI acceptance. Run `make lint` as required, distinguish baseline failures, and run Black/Ruff on changed Python files without bulk formatting.
**Gate:** first a fresh M6 rollout integration review; then a separate fresh end-to-end review against every brief criterion and current live limitations. Reconcile docs/status and report code completion, support deployment, live RPC acceptance and Desktop/Qonto-UI acceptance separately. No commits unless separately instructed.

## Current support deployment and acceptance

The implementation originated in `feat/qonto-company-connection` at
`/home/mal/worktrees/mrcall-desktop-qonto`. M7 integrates its reviewed source into
the main working checkout on top of `1198a6b` (published app version 0.1.53),
including the Firebase default correction. The operator's M7 integration
instruction authorizes a scoped local commit after final review; no push,
release publication or further host deployment is included.

Support imports
`/home/mrcalld/releases/mrcall-qonto-support-20261005-utc-c5d2585d4140/engine`
through its own `90-qonto-native.conf`. The 365-entry source manifest matches
that immutable release. The installation identity is outside the profile at
`/var/lib/mrcall-qonto/mc-16d5836d57be/engine-instance`. The tenant policy permits
`thirdparty.qonto.com` TCP443. Both bootstrap login and key are available;
Firebase refresh and signed socket admission work without a public-key override.
The engine default matches Desktop, with a cross-tree regression check.

The account remains connected to its existing MrCall company. Captured acceptance
contains 285 private transactions from the initial 30-day source sync and 79
transactions in the tested seven-day interval. Initial/manual sync, persisted
connection across restart, disconnect/reconnect, detail and summary reads pass.
Independent provider reads match current/authorized balances, ten sampled
movement records and period aggregates. Old managed history is refused after
reconnect before any new paid reservation. The accepted managed answer matches
its live source balance, account, currency, source citation, coverage and literal
`retrieved_at_utc`; the earlier timestamp-conversion answer is superseded.

Captured preservation checks retain six other daemon identities/configurations,
the shared serving checkout, billing sources, egress policies, private settings
and keys, installation identity, saved budget/provider and preparation controls.
All 1,684 reservation hashes present before the final source switch are unchanged.
The complete captured test window adds seven settled reservations with recorded
usage USD 0.196353: four assistant calls and three separate `reply-need`
classifications. No finance preparation checkpoints or publication intents exist
in that acceptance snapshot. These are dated verification results, not live
counters to assume unchanged during future operations.

Rollback artifacts retain the preceding Firebase-corrected source release and
exact unit drop-in. Protected original profile/config/key/policy backups are in
`/home/mrcalld/qonto-support-backups/20261004-qonto-native`. The additional initial
migration backup is retained losslessly compressed in the profile's `backups/`;
older and protected uncompressed backups remain available. Apply M6's rollback
conditions; do not restore shared company memory from a profile backup.

Evidence is under `/tmp/mrcall-ai-kit/qonto-live-20261005/`, including its `utc/`
correction logs, canonical-answer checks and before/after snapshots. Earlier
Firebase-default evidence is under `/tmp/mrcall-ai-kit/firebase-default-fix/`.
The final review evidence is under `/tmp/mrcall-ai-kit/qonto-final-review/`.
These local artifacts support this acceptance record and are not bank payloads
committed to the repository.

## Remaining acceptance

- Verify the installed/packaged Desktop Settings, Tasks and managed-chat journey against support's hosted engine.
- Compare the displayed bank data with Qonto's authenticated provider UI.

This environment has no display or signed-in provider UI. Native browser
fixtures and raw-provider API comparisons cover their stated paths only.
The accepted hosted bank connection remains usable while these UI checks are open.

## M7 — Integrate with the published Desktop authentication repair

The operator now authorizes integrating Qonto into the main checkout before
the next Desktop delivery. This supersedes the unmerged-checkout constraint
above for source integration and its local commit; it does not start a release
or host rollout.
The approved product brief and M1–M6 contracts remain unchanged.

**Owner:** lead. **Plan gate:** `qonto_main_plan_review`, APPROVED before source edits.

1. Capture the feature delta from `d30e568` and main's current tracked and
   untracked state. Check the remote main head without overwriting local work.
   Three-way merge only the Qonto implementation, tests and documentation into
   current main; retain 0.1.53 package metadata and every session-recovery change.
   Preserve unrelated dirty files. Keep recoverable copies and content hashes
   outside the repository; recheck a destination before each write.
2. Resolve overlapping preload, renderer types and living documentation by
   retaining both features. Inspect the actual auth/Qonto boundary (logout,
   relogin, late callbacks, profile/host/company changes). Run existing auth,
   onboarding, Qonto credential/history/browser/native-sidecar journeys,
   TypeScript and production build; run focused Qonto/Firebase/affected engine
   regressions. Add a regression only if integration exposes an uncovered bug.
3. A fresh integration reviewer checks merged behavior and preservation against
   this plan. Correct findings before a separate final reviewer checks source,
   evidence and documentation. Record the exact integrated main base and checks,
   then commit only the reviewed integration paths locally, preserving unrelated
   staged/working changes. No push or release tag is part of M7.
   Keep installed Desktop/provider-UI acceptance open and published 0.1.53
   accurately distinguished from integrated, unreleased Qonto source.

Rollback restores only this integration's touched files from captured content,
after checking for subsequent edits; never reset the checkout or restore a live
profile database. No service, credentials, policies, billing or release tags are
changed. Local integration is completed before any publication decision.

### M7 integration evidence

- At integration start, `origin/main` and local HEAD both resolved to `1198a6b162ad233a98e72ace5ed53392821d7fd7`.
  The 139-path feature inventory was merged with captured destination hashes;
  135 paths changed relative to the initial checkout. Only two additive doc
  conflicts needed resolution. The auth repair survives in preload/types;
  its main process, App component and 0.1.53 package/lock files remain
  byte-identical to the published source. The renderer auth helper receives the
  additive invalidation correction below. Unrelated dirty work is retained.
- All five Qonto component/credential/history/browser/native-sidecar suites,
  both auth suites (12 main and 13 renderer checks), onboarding, TypeScript
  and production build pass on integrated main. Ruff passes 99 Python files;
  the documentation mechanical gate is clean. The focused engine run reports
  499 passed and two setup errors: the server policy unittest class inherited
  an obsolete global Supabase fixture under pytest. Running that standalone
  unittest file through its own entry point passes both policy checks; no
  application failure or host policy change was involved.
- Integration reviewer `qonto_main_integration_review` returned REVISE after
  reproducing a deferred private source rendered following actual App logout
  with failed Firebase signout and no status/auth callback. Authentication now
  notifies finance views synchronously before either logout call. The finance
  context clears credentials, tested consent, sources and publication previews,
  rejects revoked captures, and discards prior replies. Workspace hides on
  revocation and fences late chat/start completions, including same-UID relogin.
  `app/scripts/test-qonto-auth-lifecycle.mjs` exercises actual App/authUtils,
  preload, Qonto components and Workspace against deferred fixture responses.
  Its reproduction regression and all five corrected Qonto suites pass.
  Both auth suites, TypeScript and production build pass again after the fix.
  The first rereview closed source/chat but found private Tasks still visible
  after failed Firebase logout. The auth listener now immediately moves the
  actual App gate to signed-out, unmounting its entire private shell. The
  regression covers populated Tasks, a deferred task list resolved after a new
  same-UID shell mounts, and a fresh authorized reload. Integration rereview
  returned APPROVED after independently running that regression and proving
  Tasks unmounts while the main logout call is still pending, before Firebase
  logout begins. Separate reviewer `qonto_main_final_review` returned APPROVED
  after independently rerunning the actual auth/finance lifecycle and native
  Settings/preload/Python journey. It verified all 105 engine paths against the
  approved feature and preservation of the unrelated source. M7 is complete
  for local source integration; packaged/provider-UI acceptance remains open.
- Snapshots, hashes, merge candidates and check logs are under
  `/tmp/mrcall-ai-kit/qonto-main-integration/`. This source-only step neither
  changes support's pinned engine nor publishes an installer.
- During final review, another session committed `0ab1849` with 22 R5 sandbox
  documentation lines. It changes no code and is preserved as the integration
  parent. The preservation check accounts for that exact committed document
  separately; the other 829 files outside integration/correction are unchanged.
