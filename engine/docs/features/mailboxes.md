# Additional mailboxes

<!-- doc-scope:start -->
Scope: the engine runtime contract for a profile that holds more than one
IMAP mailbox — the `mailboxes` table, secrets, row identity, per-mailbox
sync, removal, user identity, PEC envelopes, archive, the migration step and
its restore, and the limits that bind. The RPC surface is specified in
[docs/ipc-contract.md](../../../docs/ipc-contract.md); the app surface in
[app/CLAUDE.md](../../../app/CLAUDE.md).
<!-- doc-scope:end -->

A profile holds N IMAP mailboxes. Exactly one is primary: the sign-up
address, whose `.env` keys `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `IMAP_HOST`,
`IMAP_PORT`, `SMTP_HOST` and `SMTP_PORT` keep their meaning, and whose
address is the profile's `owner_id`. The primary does not change. Every
other mailbox is added at runtime through `mailboxes.add`, holds its own
hosts and an encrypted password, and is synced, stored, searched, read and
processed like the primary. Only the primary sends. Design and delivery
record: the
[brief](../../../docs/briefs/2026-09-30-pec-net-mailbox-integration.md)
and its
[plan](../../../docs/execution-plans/2026-09-30-pec-net-mailbox-integration.md).

## The `mailboxes` table and the primary row

`mailboxes` (model `Mailbox`, `zylch/storage/models.py`) has one row per
mailbox: `id` (UUID text), `owner_id`, `address` (stored lower-cased and
trimmed), `imap_host`, `imap_port`, `smtp_host`, `smtp_port`, `preset`,
`is_primary`, `secret` (nullable), `created_at`, `last_sync_at`,
`last_error`, `removed_at`. `(owner_id, address)` is unique. `secret` is
excluded from every serialisation.

The primary row is materialised from `.env`: `zylch/email/mailboxes.py:
ensure_primary_mailbox` runs at every boot, creates the row when
`EMAIL_ADDRESS` is set and none exists, and mirrors the environment's
hosts and ports onto it, so a Settings edit of `IMAP_HOST` reaches the row
after the restart the app performs. Its `secret` is NULL; its password is
`EMAIL_PASSWORD`. A profile without `EMAIL_ADDRESS` has no primary row and
sync stays gated as it is. A profile whose runtime owner is `local-user`
gets an active row keyed by that owner.

`for_owner(owner_id)` lists the active rows, `primary`, `by_id` and
`by_address` (case-insensitive) find one, `active_mailbox_ids` feeds the
storage filter. `build_imap_client(mailbox)` produces the IMAP client for
one row: the primary from `EMAIL_PASSWORD` and the environment's hosts,
any other from its decrypted `secret` and the row's hosts; both fail closed
with `MailboxSecretError` when no password can be produced. The client
factory caches one client per `(mailbox.id, credential_fingerprint)`, so a
password change rebuilds the client.

## Secrets

The password of every non-primary mailbox lives in `mailboxes.secret`,
Fernet-encrypted under the profile's `MAILBOX_SECRET_KEY`
(`zylch/email/mailbox_secrets.py`). The key is minted with
`Fernet.generate_key()` and written into the profile `.env` through
`settings_io.update_env` (atomic 0600 write, hot-patched into
`os.environ`) the first time a secret is encrypted; `mailboxes.add`
writes the key before the row. `ensure_secret_key` re-reads `.env` before
minting, so a key another process persisted meanwhile is adopted, never
overwritten.

The key is outside the settings schema: it is not in `KNOWN_KEYS`, not in
the Settings form, not readable through `settings.get_secret`, not part of
remote provisioning, and `settings.update` refuses it as unknown. It is
never logged and never in git. The module builds `Fernet(MAILBOX_SECRET_KEY)`
directly and never uses `utils/encryption.py`: a missing key, an empty
column or a token the key does not verify raise `MailboxSecretError`, and
no path returns a ciphertext as if it were a password. No error message
carries the key, a token or a password. Login failures raised by
`IMAPClient.connect` carry only a classification; the server text stays on
the exception chain for the classifier, and every message that could echo
a credential is scrubbed in plain, escaped-`str` and escaped-`bytes` form.

## Row identity in `emails`

Every `emails` row names its mailbox: `mailbox_id` is NOT NULL and the
unique constraint is `emails_owner_mailbox_gmail_unique`
`(owner_id, mailbox_id, gmail_id)`; both `ON CONFLICT` targets follow it.
On the IMAP path `gmail_id` is the RFC 5322 Message-ID, so one message
delivered to two mailboxes is two rows. Rows also carry
`original_message_id` and `pec_markers` (JSON, SQL NULL when absent),
both non-null only on PEC rows. `ix_emails_owner_message_id_header`
`(owner_id, message_id_header)` supports the first-copy rule below and is
declared on the model, created by the migration step and ensured at boot.

Thread ids stay profile-wide: a thread can span mailboxes and its rows
keep their own attribution. The copy of sent mail written by
`insert_sent_email` is stamped with the primary's id, and its dedup and
parent lookup are scoped to the primary. `Storage.get_email_by_id` is
exact with a `mailbox_id`; without one it returns the unique match, the
first stored copy when the rows are copies of one message, and raises
`ValueError` when they differ.

## Sync per mailbox

`SyncService.sync_emails` (`zylch/services/sync_service.py`) is the one
sync path for `sync.run`, `update.run`, the background job and the CLI.
It iterates the owner's active mailboxes, builds one client and one
`EmailArchiveManager(mailbox=...)` per mailbox, and aggregates
`{success, new_messages, mailboxes[], errors[]}`. Per mailbox, in a
`finally`: the client is disconnected and `record_sync_result` writes
`last_sync_at` (success) or `last_error` (the exception's message, never
a credential; the address is the row's own). One mailbox's failure never stops the others;
`success` is false only when no mailbox synced, in which case
`MailboxSyncFailed` carries the per-mailbox result and is chained from the
first mailbox's exception, so the error classifier still names an IMAP,
DNS, TLS or timeout cause. `sync.run` `errors[]` entries and
`sync.progress` messages carry the mailbox address.

The date floor, the dedup set and the cursors are mailbox-scoped:
`email_sync_cursor_v2` is keyed `(owner_id, mailbox_id, folder)` with the
folder's UIDVALIDITY and last UID, so the first sync of an added mailbox
covers the `days_back` window regardless of what other mailboxes hold.
Folder policy is the primary's: INBOX, the `\Sent` folder and the
`\All`/`\Archive` folder, read-only SELECT, `BODY.PEEK[]`. The post-sync
chain (memory extraction, task detection, budget admission) treats an
added mailbox's rows like any other.

## One message in two mailboxes

A message delivered to two mailboxes is two rows and is processed once.
At insert time, `store_emails_batch` stamps `memory_processed_at` and
`task_processed_at` on a row whose `message_id_header` is already held by
another active mailbox of the same owner (the upsert's update path never
touches the marks). The rule itself is the structural predicate
`Storage.first_copy_filter`: a row is a later copy when another row of the
same owner with the same `message_id_header` sits in a different active
mailbox and was stored earlier (`created_at`, then `id`). Both unprocessed
pickers and the `update.run` ETA counts apply it, so a reset of the marks
(force mode) cannot bring the second copy back. A twin in a removed mailbox
does not count. Thread history shown to the task model carries one copy
per `message_id_header`.

## Removal and re-add

`mailboxes.remove` sets `removed_at`. A removed mailbox is out of the
sync loop and its rows are absent from every list, search, picker, count,
thread history and identity set: the one predicate is
`Storage.active_mailbox_filter` over `active_mailbox_ids(owner_id)`. Rows,
cursors and the memory extracted from them are kept: that memory is
company knowledge. The attachment tools refuse a removed mailbox. Adding
an address that matches a removed row revives that row with its id, rows
and cursors; the duplicate refusal applies to active rows and to the
primary's address, compared case-insensitively. The primary cannot be
removed or edited through `mailboxes.*`.

## Identity: who the user is

`zylch/email/identity.py` is the one answer to "is this message ours".

- `user_addresses(owner_id)` = primary ∪ `EMAIL_ALIASES` ∪ active mailbox
  addresses, lower-cased, exact match. Lists (`emails.list_inbox`,
  `emails.list_sent`, `emails.search`, `is:unread`, sibling threads, flat
  search), task detection, thread history, hygiene, the trainers and the
  memory worker use it.
- `verified_user_addresses(owner_id)` = primary ∪ active mailbox
  addresses, no aliases. `emails.needs_reply` and
  `emails.list_by_thread.is_user_sent` use it: a mailbox address is
  verified by its connection, a declared alias is not, and counting an
  unverified alias as ours could mark a customer's thread as answered.
- `is_user_sender(owner_id, address, user_email)` is the trainers' and the
  CLI's rule: the primary's domain counts as the user's, then exact match
  on `user_addresses`. Another mailbox's domain — a PEC provider's — is
  never the user's domain, so a third party on that provider is a contact.
- A removed mailbox no longer identifies the user. `TaskWorker` derives
  `user_email` from the primary when the caller passes none. The module
  never raises; what cannot be read contributes nothing.

## PEC envelopes

`zylch/email/pec.py` recognises a PEC message by its marker headers only,
never by an attached message: `X-Trasporto: posta-certificata` (transport
envelope), `X-Trasporto: errore` (anomaly wrapper), `X-Ricevuta: <type>`
(receipt) and `X-Riferimento-Message-ID` (the message a receipt refers
to). `X-TipoRicevuta`, `X-VerificaSicurezza` and `X-Mittente` are kept
verbatim when present. Receipt types follow the standard's list
(`accettazione`, `non-accettazione`, `presa-in-carico`,
`avvenuta-consegna`, `errore-consegna`, `preavviso-errore-consegna`,
`rilevazione-virus`); an unknown value is still a receipt and its raw
value is kept. The marker list and the signed-envelope layout are derived
from the PEC technical rules (DPCM 2 November 2005, AgID); whether a live
PEC.net envelope matches them is unconfirmed.

`pec_original(msg)` runs in `_parse_message_bytes` right after
`message_from_bytes`. For a transport envelope it descends through every
`multipart/*` container (the provider's S/MIME-signed layout included),
never into a `message/rfc822` payload, and takes `postacert.eml` — else
the first `message/rfc822` part — as the original. Sender, recipients,
subject, date, body, attachments, `In-Reply-To`, `References`, the thread
id and the auto-reply headers come from the original; `gmail_id` and
`message_id_header` stay the envelope's Message-ID, because sync, archive
and attachment fetch find the message on the server by that id; the
original's id goes to `original_message_id`; the markers go to
`pec_markers` as `{kind: transport|receipt|anomaly, receipt_type,
reference_message_id, headers}`. A reply to a PEC row uses
`original_message_id` for `In-Reply-To` and `References`, because the
correspondent threads on the original.

An anomaly wrapper (`X-Trasporto: errore`, the "busta di anomalia" that
delivers every ordinary, non-certified message to a PEC mailbox accepting
ordinary mail) unwraps the same way, its markers keeping `kind: anomaly`
so a later delivery can derive that the message was not certified.
Receipts, and an envelope or wrapper without an rfc822 part, are stored
as they are, provider sender included, with their markers.
`postacert.eml`, `daticert.xml` and `smime.p7s` are never user attachments
on a PEC-marked message; `fetch_attachments` reads the original's parts.
A message forwarded as an attachment carries no marker and keeps its
forwarder as sender, in every mailbox.

## Archive

`emails.archive(thread_id)` groups the thread's rows by mailbox, opens each
mailbox's own client and moves that mailbox's Message-IDs from INBOX to
its archive folder; the primary's connection is never used for another
mailbox's messages. A Message-ID not in INBOX but held by the archive or
Sent folder is already where it belongs and counts as moved; one absent
from all three is a named failure whose row stays visible; a non-OK SEARCH
is a protocol failure; a connection or login failure is the mailbox's
`error` with nothing moved. `archived_at` is stamped only on rows whose
copy moved, and `ok` is true only when every mailbox moved everything.
A PEC row is moved by its envelope id. `emails.delete` stays a local soft
delete on every row.

## RPC surface

`mailboxes.list`, `mailboxes.presets`, `mailboxes.test`, `mailboxes.add`,
`mailboxes.update` and `mailboxes.remove` (`zylch/rpc/mailboxes.py`), the
`mailbox_id` filter and `mailbox_ids` on the three listers, the per-row
fields of `emails.list_by_thread`, the `emails.archive` result and the
`setup.state` per-mailbox breakdown are specified under `**mailboxes.***`
and `**emails.***` in [docs/ipc-contract.md](../../../docs/ipc-contract.md).
Refusals are answers (`{ok: false, status, message}`), never error
envelopes, and no result carries a secret. `mailboxes.test` is
`zylch/email/mailbox_probe.py`: login, LIST, read-only EXAMINE of INBOX and
of the Sent and archive folders discovery finds, classified as `ok`,
`auth`, `tls`, `unreachable`, `folder` or `invalid`.

## Migration step `0003_emails_mailbox`

`zylch/storage/step_emails_mailbox.py`, `destructive=True`, runs once per
profile store under the runner's lock. Before it runs, the runner writes
`<profile>/backups/zylch.db.0003_emails_mailbox.<UTC stamp>.bak` through
the SQLite backup API (WAL pages included). The step then creates
`mailboxes` with one row per distinct `emails.owner_id` plus the current
`EMAIL_ADDRESS` (the current address primary and active, every other owner
hidden with `removed_at`, a current `local-user` active, no address → no
primary); rebuilds `emails` in the model shape preserving every `id` and
stamping each row with its owner's mailbox; recreates the indexes; carries
the cursors into `email_sync_cursor_v2` joined on their owner's row, drops
orphans and the v1 table. A file already in the new shape is left alone.

Restore, when the migrated store must go back:

1. Stop the app or the daemon (`systemctl stop zylch-server@<uid>`).
2. Delete `zylch.db-wal` and `zylch.db-shm` beside the file.
3. `zylch.storage.migrations.restore_sqlite(backup_path, db_path)`, or
   copy the `.bak` over `zylch.db`.
4. Install the previous release and start. The previous release's
   `ON CONFLICT` target does not match the migrated index, so it cannot
   run on a migrated store.

Data-loss window: everything written to `zylch.db` after the migration
that is not on the IMAP server — pins, read flags, archive flags, tasks.
Mail itself re-syncs from the server. The company memory store is a
separate file that a `zylch.db` restore does not touch: rows restored to
their pre-migration state are unprocessed again and are re-extracted on
the next run, which merges into the memory already there. Hosted rollout
steps are in [remote-backend.md](../../../docs/remote-backend.md).

## Known limitations

- A PEC original in one mailbox and a plain copy of the same message in
  another have different server identities (the envelope's Message-ID
  against the original's), so the first-copy rule does not pair them and
  both are processed.
- Sending stays on the primary: replies and new mail go out through
  `EMAIL_ADDRESS`, and the composer shows that From address. SMTP for an
  additional mailbox, including implicit SSL on port 465, is not
  implemented; the PEC.net preset's `smtp.pec-email.com:465` is stored
  on the row and unused.
- The primary cannot change: `mailboxes.update` and `mailboxes.remove`
  refuse it, and `owner_id` is never re-keyed.
- The memory worker marks the user's own sent mail processed without
  extracting from its body and without creating a contact entity for the
  user; the picker hands over no recipients, so there is no other party to
  extract for.
- Live PEC.net acceptance (the brief's acceptance list on the supervised
  account) has not run; the marker list is unconfirmed on a live sample.
