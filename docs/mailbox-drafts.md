# Mailbox draft contract

This contract describes shared mailbox draft operations. See the
[Desktop delivery plan](execution-plans/2026-11-23-mailbox-drafts.md) for
installed evidence and remaining acceptance.

## Identity and ownership

The engine's `services/mailbox_drafts.py:MailboxDrafts` is the shared draft
surface for Desktop, chat, MCP and kernel RPC callers. Editable content lives
in the authenticated primary mailbox, accessed with its existing IMAP app password.
Additional IMAP/PEC archive sources continue to sync; draft mutations are scoped
to the primary mailbox.
The engine's `mailbox_operation_receipts` contains immutable effect
identity and hashes, without editable message bodies.

An opaque `imap:` handle binds the owner, exact primary mailbox/server, Drafts
folder, UIDVALIDITY and UID. A saved external edit can replace the message and
therefore its handle. Clients list and read current drafts before an explicit
mutation. A missing old handle refuses without heuristic rebinding by thread,
subject, body or recipient. Conversation headers find existing work before
composition; they never adopt another message for an old operation.

The adapter is `email/imap_mailbox.py:IMAPMailbox`, extending the existing primary
mailbox selection, IMAP client, complete ReviewMailbox inventories and exact
RetirementMailbox MOVE/COPYUID helpers. Each facade owns a separate connection
and a bounded lock/deadline scope. Folder reads require complete observations.
Quoted and atom Gmail labels are parsed as structured IMAP attributes; reserved
Sent and Draft/Drafts labels retain their meaning. Malformed metadata refuses.
Trash uses exact UID and UIDVALIDITY proof plus recoverable destination evidence;
COPY/global EXPUNGE is never a fallback.

Existing drafts with attachments remain visible and recoverably deletable;
unsupported editing or sending refuses before dispatch. Sparse header changes
preserve omitted MIME alternatives. An edit moves the exact old message to
recoverable Trash before one replacement APPEND. It uses a distinct generated
Message-ID and an operation marker, verifies content and returns a new handle.
A lost APPEND acknowledgement is reconciled without another APPEND. Body-free
progress proof and source reservations retain uncertainty through an empty-Drafts
gap. Desktop, task/chat approval and campaigns adopt the returned new handle.

## Public paths

| Surface | Operations |
| --- | --- |
| Native RPC | `drafts.list`, `drafts.get`, `drafts.create`, `drafts.update`, `drafts.trash`, `drafts.send`, `drafts.send_status`, `drafts.compose_reply` |
| MCP | `list_drafts`, `prepare_reply`, `recover_reply`, `send_reply`, `delete_draft` |
| Desktop | Email → Drafts; current content, sparse edits, send, Trash and pending-operation recovery |
| Existing tools | Storage draft adapters, chat, task approval and slash commands call the same engine service |

`drafts.list` returns the complete current draft array or JSON-RPC error
`-32030` with a safe cause when the inventory fails. `drafts.get` returns
`{ok, draft, cause, draft_id}` on a successful lookup or an absent draft.
Get and mutation handlers return safe refusal or receipt results for mailbox
service failures. Mutations use opaque full draft IDs and stable request keys.
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
Full-MIME source matching normalizes surrounding header whitespace and requires
one nondefective Message-ID header on exactly one source message. Missing or
ambiguous source identity refuses before generation.

## Campaign preparation

`campaign.add_contact` and `campaign.update_contact` preserve ordinary campaign
metadata. A non-null `draft_subject`, `draft_body`, `draft_body_format` or
`draft_cc` requests a mailbox mutation, including when format or Cc is the
only draft field supplied. This requires a stable `draft_request_key` of
16–128 characters. A contact without a native draft creates one. A contact
with `dossier.mailbox_draft_id` patches only the supplied fields of that exact
message and adopts the returned replacement handle. An externally sent or
deleted container is never recreated. Null legacy fields only clear internal
housekeeping values.

The old `CampaignContact.draft_subject` and `draft_body` fields stay null.
The dossier holds the current opaque handle and protected, body-free replacement lineage plus a
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

A send reads the current named draft, including saved recipient and body changes.
`email/imap_mailbox_smtp.py` submits its raw MIME with an engine-generated
Message-ID through the existing mailbox SMTP credentials and timeout. MIME
alternatives remain intact; Bcc recipients are envelope-only. Every recipient
must be accepted before DATA. The transaction never retries DATA. A draft
externally sent or deleted is not recreated. Direct scheduled replies use the
same raw SMTP path without any intermediate APPEND.

SMTP does not consume the draft. Only exact Sent confirmation permits retiring
the original sent UID and snapshot. Receipt progress survives restart. A changed
or missing original never authorizes moving a newer draft. `drafts.send_status`
is read-only toward the mailbox, including after Sent confirmation. If cleanup
remains pending, Desktop offers Remove sent draft. That explicit action repeats
the original send key to finish retirement without another SMTP submission.

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
A saved update can settle through a read-only check of its distinct replacement
Message-ID, unique per-update MIME marker and normalized requested-field digest. Matching old content alone is insufficient. Missing proof stays fenced;
no update is repeated. These receipts contain hashes and field names, never text.

Accepted send and Trash keys are durably bound to the exact operation. When a
new key resolves to an existing named send or in-flight Trash, the engine
binds it before recovery or cleanup in the same serialized writer that checks
for conflicting identity. The body-free `mailbox_operation_request_aliases`
table binds the owner and secondary key to the original receipt. Canonical
keys and aliases share one namespace per owner. A key bound to a different
draft or operation refuses. Recovery and status return the canonical operation,
Message-ID and original `request_key`, including when looked up by an alias.

`drafts.send_status` resolves the supplied key and exact named handle, observes
Sent when applicable, and may record the observation in the existing receipt.
It creates no new reservation or alias and performs no mailbox mutation. An
absent request returns `named_send_operation_not_found` without a provider
draft read. MCP can recover with the original key or an accepted alias. A new,
unbound key presented to MCP for an already retired handle fails the current
draft lookup with `draft_not_found` before any binding.

## Authorization and migration

Primary mailbox access uses the existing IMAP/SMTP app password from the
profile's `EMAIL_PASSWORD`. Additional IMAP mailboxes decrypt their stored
secrets for synchronization. The six `mailboxes.*` management methods and
owner-only `settings.get_secret` have their own
[credential contracts](ipc-contract.md#historical-method-index). Draft RPCs
accept and return no credentials. Firebase authenticates Desktop and remote
engine sessions. Google Calendar uses its own read-only OAuth grant. Drafts
require no Gmail OAuth client, scope or consent. There are no `google.gmail.*`
RPCs. Public draft failure reasons exclude provider exception text and message
content.

The [migration contract](mailbox-draft-migration.md) discards legacy internal
rows and editable reply snapshots without provider mutations. Original uncertain
send identities remain fenced and recoverable from Sent. Unsafe old-writer
rollback is refused. Existing mailbox drafts remain separate from that cleanup.
Receipt and alias tables use `CREATE TABLE IF NOT EXISTS` so concurrent first
opens of an existing profile can create the missing schema safely. Legacy
imports check the shared key namespace inside the same serialized transaction
as draft deletion. An alias collision rolls back the import and deletions.

## Verification boundary

Synthetic provider-wire, public MCP/RPC, task/approval, subprocess-restart,
migration and Chromium UI checks exercise the source. Installed evidence covers
a saved Gmail IMAP edit, MCP send and lookup of the same send after an actual
Café service restart with the original key and an alias accepted through RPC.
Packaged Linux Desktop restores authentication after restart and opens the
exact draft produced by the first ordinary Café tick. The
[Desktop delivery plan](execution-plans/2026-11-23-mailbox-drafts.md) records
that evidence and the outstanding ordinary outcomes, both normal-clone FULL
checks, public release provenance, Gmail web verification and final review.
