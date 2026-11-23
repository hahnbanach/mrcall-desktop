# Mailbox draft contract

This contract describes the mailbox draft candidate. Hosted dev7 retains the
previous internal-draft behavior until the reviewed cutover and installed
acceptance are complete.

## Identity and ownership

The engine's `services/mailbox_drafts.py:MailboxDrafts` is the shared draft
surface for Desktop, chat, MCP and kernel RPC callers. Editable content lives
in the authenticated primary Gmail mailbox. Additional IMAP/PEC archive sources
continue to sync; their drafts are outside this Gmail-only provider scope.
The engine's `mailbox_operation_receipts` contains immutable effect
identity and hashes, without editable message bodies.

An opaque handle combines the configured mailbox identity with Gmail's stable
native draft container ID. IMAP UID, Gmail message ID and RFC Message-ID can
change during a saved edit. Conversation headers find existing work before
composition; they never reattach a missing named draft to another draft.

The native adapter is `email/gmail_mailbox.py:GmailMailbox`. Its reads exhaust
pagination. It verifies the authenticated mailbox, reads current raw MIME,
uses native draft create/update/send, and moves drafts with `messages.trash`.
Permanent `drafts.delete` is not used. Existing drafts with attachments remain
visible and recoverably deletable; unsupported editing or sending refuses
before dispatch. Sparse header changes preserve omitted MIME alternatives.

## Public paths

| Surface | Operations |
| --- | --- |
| Native RPC | `drafts.list`, `drafts.get`, `drafts.create`, `drafts.update`, `drafts.trash`, `drafts.send`, `drafts.send_status`, `drafts.compose_reply` |
| MCP | `list_drafts`, `prepare_reply`, `recover_reply`, `send_reply`, `delete_draft` |
| Desktop | Email → Drafts; current content, sparse edits, send, Trash and pending-operation recovery |
| Existing tools | Storage draft adapters, chat, task approval and slash commands call the same engine service |

`drafts.list` returns the complete current draft array. `drafts.get` returns
`{ok, draft, cause}`. Mutations use opaque full draft IDs and stable request keys.
A technical failure remains explicit and never appears as an empty mailbox.
The MCP verifies its grant and exact mailbox on every effect. A person's
explicit request retains exact source binding while scheduled callers retain
assignment and eligibility holds. An explicit reply target wins over a shared
conversation root: a draft for an older inbound remains untouched and does not
replace a reply to a newer inbound.

`drafts.compose_reply` accepts `source_email_id`, `thread_key`, `request_key`,
`mode` (`draft` or `send`), optional request text and instruction versions, and
`recover_only`. A recovery-only request without an engine admission refuses
before generation. Direct `mode=send` requires a scheduled origin; interactive
sending names an existing draft.
Scheduled calls carry `operator_origin: "scheduled_operator"` and
`operator_origin_version: 1`. The engine checks current conversation, Sent,
existing drafts and assignment eligibility before generation. Existing drafts
remain for human review in either mode. Draft mode creates one mailbox draft;
send mode composes and dispatches without creating a draft resource.

## Campaign preparation

`campaign.add_contact` and `campaign.update_contact` preserve ordinary campaign
metadata. Supplying a string `draft_subject` or `draft_body` prepares the only
editable draft in the mailbox and requires a stable `draft_request_key`.
A new contact without a native draft creates one; a contact with
`dossier.mailbox_draft_id` updates only the explicitly supplied subject/body
fields of that named container. An externally sent or deleted container is
never recreated. Null legacy fields only clear internal housekeeping values;
they never clear native message content.

The old `CampaignContact.draft_subject` and `draft_body` fields stay null.
The dossier holds the opaque native handle and a protected, body-free
`mailbox_draft_request` record with the request key, receipt key, input digest,
operation kind and recovery state. Clients cannot replace those bindings.
The profile writer reserves each contact's preparation before releasing the
transaction for provider I/O. Concurrent calls and a crash after provider receipt
completion recover that original operation before another effect. Repeating a
completed key reads the current mailbox object without overwriting later Gmail
edits. Replaying an older create or edit key preserves a later contact claim
and does not block a fresh subsequent edit. Provider authorization failures remain explicit and retain no generated
text in the contact. Closed campaigns refuse new draft preparation.

Campaign sends use `drafts.send` with the named native handle. The fixed-template
bulk sender remains a separate existing path and does not adopt a draft store.

Fixed-template campaign queueing uses the same producer with explicit
`draft_body_format=html` and `draft_cc`, preserving the rendered MIME and copy
recipients. The engine writes its protected native handle; a caller cannot adopt
an arbitrary draft through dossier replacement. Fixed-template direct SMTP sends
remain separate and unchanged.

## Sending and replay

A send reads the current named native draft, including saved recipient and
body changes. Native `drafts.send` consumes that container with its current MIME
and an engine-generated Message-ID. A draft externally sent or deleted is not
recreated. Direct replies use `messages.send`.

The engine commits dispatch-possible state before the provider mutation. A
network timeout, lost acknowledgement, unavailable Sent or empty search leaves
the operation unconfirmed. Recovery only observes Sent for the original
Message-ID; it never retransmits. A canonical mailbox plus exact RFC source
fence spans preparation, named-draft sends and direct sends while delivery is
unconfirmed. Confirmation ends that fence, while the original request key
permanently identifies its original operation and message.

Authoritative provider rejections establish non-dispatch only when the failed
mailbox mutation itself is rejected, or authorization fails before it starts.
A failed readback after a successful mutation remains uncertain. A new explicit
attempt after definite non-dispatch receives a new key. Approval cards apply
only explicit changes, so unchanged hydrated fields cannot replace later Gmail
edits. A failed update prevents the subsequent send. Atomic native-handle reservations
exclude simultaneous send/update and update/update effects while an operation is
reserved, dispatch-possible or unconfirmed. Elapsed time never releases that fence.
A saved update can settle through a read-only check of the same native container,
its unique per-update MIME marker and the digest of the requested normalized
fields. Matching old content alone is insufficient. Missing proof stays fenced;
no update is repeated. These receipts contain hashes and field names, never text.
`drafts.send_status` reads only the requested key and named handle, then checks
Sent. An absent request returns `named_send_operation_not_found` without a provider
draft read or a new reservation. Another client's key is a separate operation.

## Authorization and migration

Gmail uses mailbox-bound encrypted `google_gmail` credentials with
`gmail.modify` scope. Calendar read-only credentials and app passwords do not
grant this access. The dedicated OAuth RPCs are `google.gmail.begin`,
`google.gmail.complete`, `google.gmail.status` and `google.gmail.disconnect`.
PKCE state persists encrypted; callbacks use an exact configured allowlist.
The host supplies `GOOGLE_GMAIL_CLIENT_ID`, `GOOGLE_GMAIL_CLIENT_SECRET` and optional
JSON `GOOGLE_GMAIL_REDIRECT_URIS`; the client must match the stored grant. The
prepared `/etc/mrcalld/gmail-oauth-client.env` is root-owned mode 0600. Candidate
cutover loads it with an explicit service `EnvironmentFile`; current units do not
load it. No staged secret or encrypted grant is stored in Git.

The [migration contract](mailbox-draft-migration.md) discards legacy internal
rows and editable reply snapshots without provider mutations. Original uncertain
send identities remain fenced and recoverable from Sent. Unsafe old-writer
rollback is refused. Existing mailbox drafts remain separate from that cleanup.

## Verification boundary

Synthetic provider-wire, public MCP/RPC, actual task/approval, subprocess-restart,
migration and Chromium UI checks exercise this candidate. They do not establish
native Gmail authorization, installed Desktop acceptance, real operator ticks
or a completed production release. Those obligations remain in the governing
HB plan `docs/execution-plans/2026-11-23-drafts-live-in-the-mailbox.md`.
