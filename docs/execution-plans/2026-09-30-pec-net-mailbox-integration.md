---
status: active
date: 2026-09-30
---

# Additional mailboxes on an existing profile — execution plan

<!-- doc-scope:start -->
Scope: milestone plan for Delivery 1 of the approved additional-mailboxes
brief: N IMAP mailboxes on one engine profile, synced, stored and processed
like the primary, with PEC envelopes unwrapped. Deliveries 2 and 3 (PEC flag,
`certified`/`delivered`) get their own plan after this one is accepted.
<!-- doc-scope:end -->

The [brief](../briefs/2026-09-30-pec-net-mailbox-integration.md) was
APPROVED at the brief gate on 2026-09-30 after an adversarial review. This
plan resolves its four decisions and sequences the work into seven
milestones. Engine milestones belong to the engine specialist, the app
milestone to the app specialist; every milestone that changes a JSON-RPC
method or result gets the IPC contract reviewer before the next milestone
starts.

## Decisions

**D1 — Configuration and secret store.** A new profile-DB table
`mailboxes` holds one row per mailbox: `id` (UUID text), `owner_id`,
`address`, `imap_host`, `imap_port`, `smtp_host`, `smtp_port`, `preset`,
`is_primary`, `secret` (nullable), `created_at`, `last_sync_at`,
`last_error`, `removed_at`. The primary row is materialised from `.env` by
the migration and on every boot when missing; its `secret` is NULL and its
password keeps living in `EMAIL_PASSWORD`, so `settings.get`,
`settings.get_secret` and cs-kernel see no change. Additional mailboxes keep
their password in `secret`, Fernet-encrypted under a per-profile key
`MAILBOX_SECRET_KEY` that the engine writes into `.env` through
`settings_io` on the first add. The key is deliberately not a Settings
schema key: that keeps it out of the Settings form, out of
`settings.get_secret`, out of remote provisioning and out of the app's
`KNOWN_KEYS`, and `settings.update` refuses it as unknown. Mailbox secrets
build `Fernet(MAILBOX_SECRET_KEY)` directly and fail closed; they never go
through `utils/encryption.py`, whose global fails open without
`ENCRYPTION_KEY`. The OS keychain is rejected because the hosted daemon has
none; a plaintext column is rejected because destructive migrations copy
the DB into `backups/`. The primary mailbox is the one entered at
sign-up (Onboarding), and it does not change: `emails.owner_id` is its
address, and the CTO decided on 2026-09-30 that this stays as it is.

Migration rule for existing rows: the migration creates one `mailboxes`
row per distinct `emails.owner_id` found in the table plus the current
`EMAIL_ADDRESS`. The row matching the current address is primary; every
other one (a former address, or `local-user` for a profile that had no
address) is created hidden with `removed_at` set, so rows of a former
address stay invisible as they are today. A profile whose current owner is
`local-user` keeps that row active, so its rows stay visible. A profile
with no `EMAIL_ADDRESS` gets no primary row and an empty mailbox list; sync
stays gated as it is.

**D2 — Identity in storage, cursors and results.** `emails` gains
`mailbox_id` (NOT NULL), `original_message_id` and `pec_markers` (JSON,
nullable); its unique constraint becomes
`(owner_id, mailbox_id, gmail_id)` and both `ON CONFLICT` targets follow.
The sync cursor table is rebuilt as `email_sync_cursor_v2` keyed
`(owner_id, mailbox_id, folder)`; existing cursors migrate to the primary
id. Thread ids stay profile-wide. Thread summaries gain `mailbox_ids`
(list); message rows gain `mailbox_id` and `mailbox_address`. One message
delivered to two mailboxes is processed once: when `store_emails_batch`
stores a row whose `message_id_header` already exists under another
mailbox of the same owner, the new row's `memory_processed_at` and
`task_processed_at` are set to the store time, so memory extraction and
task detection see only the first stored copy. The rule runs on insert
only, never on the upsert's update path, so a first copy stored again
before processing is not marked done. The copy of sent mail
written by `insert_sent_email` is stamped with the primary mailbox id, and
its dedup and parent lookup are scoped to that mailbox. cs-kernel
sees additional-mailbox rows in `emails.search` and `emails.list_by_thread`
because the operator sees all of the user's mail; the fields it reads do not
change. Every mailbox address joins the user identity set, including
`emails.needs_reply` and `is_user_sent`: a mailbox address is verified by
its connection, unlike a declared alias, so the safety reason for excluding
aliases from `needs_reply` does not apply.

**D3 — Archive and removal.** `emails.archive` groups the thread's rows by
`mailbox_id`, opens each mailbox's own client and moves that mailbox's
Message-IDs; a Message-ID the source mailbox does not hold is a named
failure, not a success. Rows whose copy moved get `archived_at`; rows that
failed stay visible and the result names them. The result becomes
`{ok, archived, mailboxes: [{mailbox_id, attempted, moved, error}]}`.
Attachment fetch and `get_message` use the row's mailbox client. Removing a
mailbox sets `removed_at`, stops its sync, and hides its rows from every
list, search and processing query; rows and memory already extracted are
kept, because the memory is company knowledge that was legitimately
extracted. Hiding is one storage helper, `active_mailbox_ids(owner_id)`,
applied by every owner-scoped list, search and processing query. Adding an
address that matches a removed row revives that row with its id and clears
`removed_at`, so a re-added mailbox keeps its rows and cursors; the
duplicate-address refusal applies only to active rows.

**D4 — PEC envelope.** A helper `pec_original(msg)` fires only when the
transport markers of the PEC rules are present (`X-Trasporto`,
`X-Ricevuta`, `X-Riferimento-Message-ID`; list finalised in M4 from a
privately captured live header sample, never from content) and returns the
`message/rfc822` original plus the markers. Sender, subject, body,
attachments, `In-Reply-To`, `References` and thread id come from the
original; `gmail_id` and `message_id_header` both stay the envelope's
Message-ID, because archive and attachment fetch find the message on the
server by `message_id_header`; the original's id goes to
`original_message_id`; markers go to `pec_markers`. Auto-reply detection
reads the original's headers. Forward-as-attachment mail never fires the
helper.

## Non-negotiable boundaries

No password in logs, RPC errors, notifications or test fixtures; no live
message content in committed fixtures; `MAILBOX_SECRET_KEY` follows the
`MEMORY_KEY` rules. The primary mailbox's `.env` keys keep their meaning.
`owner_id` is never re-keyed. No send from an additional mailbox. The
Firebase UID and profile directory are not mailbox identifiers.

## M1 — Storage, migration and secrets (engine)

**Dependency:** none. Add the `Mailbox` ORM model and `mailboxes` table;
change the `Email` model (`mailbox_id`, `original_message_id`,
`pec_markers`, new unique constraint); add profile step
`0003_emails_mailbox`, `destructive=True`, on the
`step_identifiers_company_unique` template: create `mailboxes`, insert the
primary row from `.env`, rebuild `emails` preserving `id` and stamping the
primary id, hidden rows for former owners, recreate its indexes, rebuild
the cursor table as v2. Stamp `insert_sent_email` with the primary id and
scope its dedup and parent lookup. Add
`Mailbox` loading (`mailboxes.for_owner`, `primary`, `by_id`, `by_address`)
and `build_imap_client(mailbox)` that resolves the password from `.env` or
the encrypted column. Add the fail-closed secret wrapper and key generation.
Update `ON CONFLICT` targets and every storage signature listed in the
session facts (`store_email`, `store_emails_batch`,
`get_existing_email_ids`, `get_newest/oldest_email_date`,
`get_thread_message_id_headers`) to take a mailbox.

**Verification:** migration test on a legacy DB fixture (rows keep ids,
primary stamped, rows of a former address get a hidden mailbox, a profile
without `EMAIL_ADDRESS` migrates with no primary, second run idempotent,
backup created); fresh DB creates the new shape; `insert_sent_email` test
(none exists today); secret round-trip and fail-closed tests; `make lint`
and `pytest tests/storage tests/email`.

**Rollback:** the destructive step backs up `zylch.db` before running.
Restore procedure: stop the app or daemon, delete any `zylch.db-wal` and
`zylch.db-shm` beside the file, restore with `restore_sqlite` (the
runner's documented reverse) or copy the backup over `zylch.db`, install
the previous release, start. The previous release's `ON CONFLICT`
target does not match the new index, so running it on a migrated DB is not
an option. Data-loss window: everything written after the migration that
is not on the IMAP server (pins, read flags, archive flags, tasks, memory
extracted in the meantime); mail itself re-syncs from the server. The
hosted daemons take this step in M7, one at a time, supervised.

**M1 integration review (2026-09-30): APPROVED** on the second pass. The
first pass found two defects, both repaired: the migration and the
resolver now take the current owner from the same raw value the runtime
uses, and a hidden owner-keyed row is revived instead of duplicated, with
`UNIQUE (owner_id, address)` on `mailboxes`. Focused suites: storage and
email 189 passed; rpc and workers 334 passed with one pre-existing
`llm.models` failure. Open for M5: `mailboxes.list` must not show a
primary row whose address is empty as a configured mailbox; the first-key
race on concurrent adds.

## M2 — Sync per mailbox (engine)

**Dependency:** M1. `_run_sync`, `_execute_sync`, `_sync_emails_direct`
and the factory iterate the owner's non-removed mailboxes, build one
`EmailArchiveManager` per mailbox and aggregate results. The date floor,
dedup set and cursors are mailbox-scoped, so an added mailbox's first sync
covers the `days_back` window regardless of other mailboxes.
`_convert_message` stamps `mailbox_id`. Per-mailbox errors carry the
mailbox address in `sync.run` `errors[]` and `sync.progress` messages;
one mailbox's failure never stops the others. `last_sync_at` and
`last_error` are written per mailbox. Add `active_mailbox_ids` and apply
it to every owner-scoped list, search and processing query named in the
session facts (`storage.py` thread lists and searches, unprocessed-row
pickers at `storage.py:2782,3252`, `rpc/methods.py:1157-1175`).

**Verification:** fake-IMAP tests with two mailboxes: same Message-ID in
both stored as two rows, only the first copy is picked by the memory
and task pickers, and re-storing the first copy before processing leaves
it unprocessed; second mailbox's first sync reaches its own `days_back`
floor while the primary has newer mail; one mailbox failing leaves the
other's cursor advanced; rows of a mailbox with `removed_at` set are absent
from every list, search and picker; `pytest tests/email tests/storage`.

**M2 integration review (2026-09-30): APPROVED** on the third pass. The
loop lives in `SyncService`, used by all three entry points. Fixed on the
way: a total failure now keeps the classified per-mailbox exception, the
"processed once" rule is a structural first-copy predicate that survives
the reset paths, and `(owner_id, message_id_header)` is indexed so the
pickers stay linear (20,000 rows: 0.2 s instead of 60 s). Suites: 794
passed, one pre-existing `llm.models` failure. Left to M5 as planned:
`get_email_by_id` across mailboxes and the `setup.state` counts.

## M3 — User identity across mailboxes (engine)

**Dependency:** M1. Add `email/identity.py:user_addresses(owner_id)` =
primary address ∪ `EMAIL_ALIASES` ∪ non-removed mailbox addresses, and
route every primary-only and alias site through it (the session facts list
them: task creation, reply queries, `is_user_sent`, inbox/sent/search
`is_user` checks, `is:unread`, sibling threads, flat search, thread
presenter, hygiene, task prompt). The memory worker skips contact creation
when `from_email` is a user address. The domain-substring trainer sites
keep the primary's domain rule and add exact matching for other mailbox
addresses; a PEC provider domain is never treated as the user's domain.
`TaskWorker` derives `user_email` from the owner when the caller passes
none, closing the empty-identity defect in the chat and command sync jobs.

**Verification:** tests that a message sent from an additional mailbox is
`is_user_sent`, creates no task and no contact entity, and does not count
as needing a reply; `pytest tests/workers tests/rpc`. The IPC contract
reviewer reviews this milestone too, because it changes what
`emails.needs_reply` and `is_user_sent` mean for cs-kernel.

**M3 integration review (2026-09-30): APPROVED** on the second pass; IPC
contract review APPROVED. `identity.user_addresses` (primary, aliases,
active mailboxes) feeds lists, search, tasks, trainers and memory;
`identity.verified_user_addresses` (primary and active mailboxes, no
aliases) feeds `emails.needs_reply` and `is_user_sent`, because a
declared alias is not verified by a connection. `is_user_sender` is one
shared function for the trainers and the CLI. Suites: 802 passed, one
pre-existing `llm.models` failure. Recorded for later: the memory worker
now skips body extraction of the user's own sent mail (a lossless
follow-up adds to/cc to the picker and uses the first non-user recipient
as the contact); cs-kernel clones must list aliases and additional
mailbox addresses in `config.self_emails`; the IPC contract doc gets a
"the user's message" definition in M7.

## M4 — PEC envelope unwrap (engine)

**Dependency:** M2 (both milestones edit `_convert_message` and
`store_emails_batch`) and read access to the supervised live PEC.net
account. Before writing the marker list, capture the headers of one
received PEC and one receipt from that account into a private note under
the profile directory, mode 0600, outside the repository (headers only,
no body, no address of a third party). Implement `pec_original`, wire it
after `message_from_bytes` in the parser, pass `original_message_id` and
`pec_markers` through `_convert_message` and `store_emails_batch`, and
switch auto-reply detection to the original's headers.

**Verification:** fixtures built with `build_raw_message`: a synthetic PEC
envelope stores the inner sender, subject and body, keeps the outer
Message-ID as both `gmail_id` and `message_id_header`, and threads by the
inner References; a
forward-as-attachment keeps its forwarder; a receipt without an inner
message stores the envelope as is; `pytest tests/email`.

## M5 — RPC surface (engine + IPC contract)

**Dependency:** M2, M3. New methods: `mailboxes.list` (rows without
secrets, with state), `mailboxes.presets` (engine table with
`PEC.net (Register.it)` added), `mailboxes.test` (IMAP login, LIST, SELECT
INBOX read-only plus the Sent and archive folders when folder discovery
finds them, absent ones counting as absent as `sync_folders` does;
returns one of `ok`, `auth`, `unreachable`, `tls`, `folder` where `folder`
means a found folder that cannot be selected, with a message that never
echoes the password), `mailboxes.add` (runs the test first, refuses an
active duplicate address, revives a removed one), `mailboxes.update`
(hosts, ports, password), `mailboxes.remove` (sets `removed_at`). The
archive change replaces the "missing message counts as moved" branch of
`move_message_by_message_id` with a named failure. `emails.list_inbox`,
`list_sent`, `search` gain `mailbox_ids` per thread and accept an optional
`mailbox_id` filter; `emails.list_by_thread` rows gain `mailbox_id` and
`mailbox_address`; `emails.archive` takes the D3 shape; attachment tools
and `get_message` resolve the client from the row's mailbox. Document all
of it in `docs/ipc-contract.md`. The IPC contract reviewer reviews this
milestone before M6.

**Verification:** RPC tests for each new method including the four error
classes against the fake IMAP; remove then re-add keeps the mailbox id and
its rows; fake-IMAP archive tests with two mailboxes: a thread spanning
both moves each copy on its own server, the same Message-ID in both moves
both copies, a PEC envelope moves by its envelope id, a missing message
gives a named failure and leaves the row unarchived, and the primary's
connection is never used for the other mailbox's messages;
contract-boundary test for the archive result; `pytest tests/rpc
tests/email`; docstring signatures pass the param-spec dispatcher.

## M6 — App (Electron)

**Dependency:** M5. `MailboxesCard` in Settings on the `MemoryCard`
pattern: list with state and last error, Add (preset select, address,
password with a label that names the provider's credential, hosts, Test
before Save), Edit, Remove. Preload bindings and
`types.ts` entries for `mailboxes.*` and the changed `emails.*` shapes.
Email view: per-message mailbox chip in the reading pane, mailbox filter in
the toolbar, archive result handling that shows a named per-mailbox
refusal. `StageErrors` titles name the mailbox. `ApprovalCard` shows a
read-only From line for `send_email`/`send_draft` with the primary
address.

**Verification:** `npm run typecheck && npm run build && npm run
test:onboarding`; `node scripts/test-settings-recovery.mjs` with the fake
bridge extended for `mailboxes.*`; a react-test-renderer script for the
Email view chip and filter modelled on `test-spending-ui.mjs`.

## M7 — Live acceptance and docs

**Dependency:** M6. Run the brief's acceptance list on the supervised
PEC.net account and on a fixture profile: add through the GUI with the
preset, test, restart, sync twice, attribution, history older than the
overlap window, memory and task processing ran, PEC message stored
unwrapped, sent-from-added-mailbox creates nothing, primary still syncs
and sends, migration of an existing single-mailbox profile without
password re-entry, shared Message-ID as two rows, archive across mailboxes
and of a PEC envelope, forward-as-attachment keeps forwarder, cs-kernel
mailbox read returns the primary. Hosted rollout: pin the release, then
for each hosted daemon in turn stop it, confirm the migration backup was
written, start it and check `mailboxes.list` and one sync; the Café 124
production voice daemon stays on its pinned release until the pilot plan
releases it. Record results in this plan. Then write
`engine/docs/features/mailboxes.md`, update `engine/CLAUDE.md`,
`app/CLAUDE.md` and `docs/README.md`, and set this plan `completed` or
record what remains.

## Risks

- The hosted daemon reads `.env` at start; the generated
  `MAILBOX_SECRET_KEY` is hot-patched into the running process by
  `update_env`, and a daemon restarted before the key is written cannot
  decrypt the added mailbox. `mailboxes.add` writes the key before the row.
- `factory._create_imap_client` caches clients by credential tuple; the
  cache key must include the mailbox id or the "interactive" client will
  serve the wrong account.
- The PEC marker list is standard-derived until M4 captures a live sample.
