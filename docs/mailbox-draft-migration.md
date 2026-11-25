# Retiring legacy internal drafts

The mailbox-only engine stores editable drafts in Gmail. The profile's old
`drafts` rows and generated reply snapshots are discarded without publishing,
copying, restoring or sending their contents. Existing mailbox drafts are not
part of this migration.

Model-composed campaign material in `campaign_contacts.draft_subject` and
`draft_body` is discarded too. The migration sets only those two fields to
null. It preserves each campaign, contact, state, timestamp and complete dossier,
including an existing `dossier.mailbox_draft_id`. It never publishes campaign
text to Gmail or reconstructs it after migration. Preview reports
`legacy_campaign_drafts`; apply separately reports `cleared_campaign_draft_contacts`
and `cleared_campaign_draft_fields`. The snapshot digest includes complete
campaign and contact row sets, including contacts without draft text. Foreign
campaign or contact owners refuse the entire transaction before destruction.

The implementation is `engine/zylch/storage/mailbox_draft_migration.py`.
`MailboxDraftMigration(engine, owner=mailbox_address, profile_uid=firebase_uid)`
operates on one explicitly identified profile database. `preview()` reads the
complete legacy state and returns status counts and a snapshot digest. It
returns no message text, addresses of correspondents, subjects or credentials.
An unknown schema, foreign mailbox row or foreign profile journal refuses the
migration rather than attributing its sends to another mailbox.

## Applying the migration

Before `apply(preview_digest, writer_fence=assert_stopped,
sent_lookup=read_exact_sent)`:

1. Keep both recurring operator schedules paused. Inspect the actual crontab
   and launcher state. Wait for any existing operator processes to finish.
2. Stop every engine writer for the selected database, including hosted units,
   temporary candidate services and local sidecars. Verify each unit's stopped
   state and absence of an owning process. Respect the host's switching window.
3. Bind `assert_stopped` to those actual observations. It must return exactly
   true for both `writers_stopped` and `schedules_paused`. The migration checks
   the assertion before work, under its SQLite write transaction, and before
   deletion. A lost assertion rolls back receipt imports and deletions.
4. Bind `read_exact_sent` to a read-only exact provider lookup. It receives one
   RFC Message-ID and returns complete native message records with raw MIME,
   native message identity and labels. It must not generate mail, create a
   draft, send, delete, move or append anything.
5. Review a fresh preview and pass its exact digest. A change to legacy rows,
   canonical receipt rows or the archive records used to identify a reply source
   invalidates the preview. The digest does not include
   `mailbox_operation_request_aliases`. Apply independently checks the shared
   request-key namespace inside its transaction: an alias colliding with an
   imported legacy key refuses with `legacy_receipt_identity_conflict`, while
   an independent alias is preserved. Only the receipt schema is created before
   the transaction. Receipt rows are imported in the same atomic transaction
   that discards the legacy rows.

The transaction imports each old send journal entry under
`request_key = "legacy-send:" + old_operation_id`, with kind `send`, target
`"legacy-internal:" + old_draft_id`, source equal to the exact original
`in_reply_to`, and the originally claimed RFC Message-ID. Its owner is the
explicit profile mailbox. Its executor is empty and its native draft ID is
null. It contains no draft text or recipients. Unjournaled legacy send claims
use the stable key `"legacy-send:draft:" + old_draft_id`.

Some unjournaled sends store the source header with literal `&lt;` and `&gt;`
as its outer delimiters. The migration replaces just those delimiters and
validates the resulting Message-ID. It preserves every interior character,
including letter case and ampersands. It requires one active primary mailbox
with the exact owner ID and a matching mailbox address, and exactly one
`emails.message_id_header` equal byte for byte in that owner's primary mailbox.
The archived message may have been sent by the owner. Preview binds the
primary mailbox and matching archive row identities to the digest. Apply
repeats the lookup inside its write transaction before discarding any rows.
The receipt uses the archived RFC header to fence future replies, while its
payload digest retains the original escaped source. The claimed outgoing
Message-ID stays exactly as stored. A standalone send retains its empty
reply source and its own outgoing identity.

During migration and repeated migration, exactly one matching provider Sent
record, with the claimed RFC Message-ID and mailbox sender, establishes
completion. Missing, ambiguous, malformed or unavailable Sent remains
unconfirmed. An unknown legacy Message-ID stays empty
and fenced; the migration never invents a replacement identity. A locally
`sent` draft or `completed` journal is insufficient. Repeating the migration
preserves an existing uncertain receipt and its evidence until exact Sent proof
completes it. Discarded local rows cannot become evidence that dispatch never
occurred, even when the retained old journal says `reserved` or `inventoried`. A provably pre-dispatch
journal remains not dispatched unless provider Sent proves otherwise.

The new engine checks imported, unresolved legacy receipts by mailbox and exact
RFC source before preparing or sending a reply. Ordinary recovery of an
imported send receipt checks for one unique exact Message-ID in provider Sent.
The migration's sender and raw-MIME proof decoder applies during migration.
Repeating an old request performs read-only Sent reconciliation and cannot
reconstruct an internal draft. The new receipts retain confirmed old Sent
membership after legacy draft rows are removed. Every old provider-journal
row remains unchanged as recovery evidence.

Generated snapshots in `operator_reply_operations.result` become an immutable
`legacy_draft_id`, snapshot hash, body hash and `status: "discarded"`. The
obsolete `draft_id` and editable `snapshot` are absent, so native recovery cannot
interpret an internal UUID as a current mailbox draft. Original source context
and instruction provenance are not generated editable drafts and remain intact.

## Compatible rollback

Pause writers before any rollback and preserve the complete profile database,
including canonical send receipts, `mailbox_operation_request_aliases` and old
provider journals. A compatible release retains both receipt tables, resolves
every accepted secondary request key to its original canonical operation and
uses read-only Sent recovery for uncertain sends. It neither restores discarded
draft rows nor repeats a possible dispatch. Dev12 cannot read these aliases and
is incompatible once an alias is accepted. Dev13 supports aliases but cannot
recover an uncertain generation that has no mailbox receipt. Dev14 supports both alias and pre-mailbox-generation recovery contracts.
The current policy-only review state additionally requires dev15 as below.
Preserve generation IDs, reservations and usage as well as mailbox receipts.
Dev15 also accepts a policy-only review with a nonblank reason and an empty
`missing_facts` list. Once such a review is recorded, dev14 cannot recover it
through its older constructor. Keep dev15 or a forward reader with that contract.
The installed database already contains a policy-only review with zero missing
facts. Its compatible rollback target is dev15 or a verified forward reader.
The earlier pre-review dev14 rollback condition no longer applies. No rollback
restores an old database or rewrites a review to satisfy an older reader.
Verify compatibility by reopening the database and replaying the original send
key, an accepted alias, the retained pre-mailbox uncertain generation and a
policy-only review with zero missing facts. Each returns its original identity
without another inference or transmission;
uncertainty does not authorize a new attempt.

`rollback_check(writer_fence=assert_stopped)` refuses an old writer whenever the
legacy journal is nonempty or unknown, any mailbox operation receipt exists, or
legacy draft rows or campaign draft fields remain. An absent legacy journal cannot establish compatibility.
Even a permitted old restart restores zero discarded drafts. Never restore an
old database backup over active receipt state to make a rollback pass.

## Rehearsed checks

The focused synthetic SQLite suite is
`engine/tests/storage/test_mailbox_draft_migration.py`. It checks complete
internal-row removal, unchanged old journal and mailbox drafts, zero provider
mutations, snapshot stripping, stale previews, loss of the writer fence,
mailbox/profile isolation, complete campaign/contact snapshots, campaign text
clearing with dossier preservation, exact Sent proof, unavailable Sent, and unknown send
identity. After reopening SQLite with the compatible mailbox service, a repeated
legacy request remains unconfirmed while Sent is empty and completes when the
original Message-ID appears; its provider mutation count remains zero.

These checks do not assert that production has migrated. The deployment owner
records actual per-profile counts, stopped processes, paused schedules and
provider observations before applying this module to live data.
