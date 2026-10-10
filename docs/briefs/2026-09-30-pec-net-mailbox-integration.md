---
status: draft
date: 2026-09-30
---

# Additional mailboxes on an existing profile, with PEC as a later flag

<!-- doc-scope:start -->
Scope: product and architecture brief for letting a signed-in MrCall Desktop
user add further IMAP mailboxes (the driving case is a Register.it PEC.net
address) to the existing engine profile, and for the two PEC-specific
increments that follow. It frames the work; the reviewed execution plan owns
storage and API shape.
<!-- doc-scope:end -->

## Intent

An existing MrCall Desktop user adds another mailbox address and its password
in the GUI, verifies that the connection works, and from then on that
mailbox is synchronized, stored, searched, read and processed exactly like
the ordinary one. Its messages enter memory extraction and task detection
like every other message. The only differences are the per-row source
mailbox, which the UI shows, and, for PEC envelopes, storing the original
message instead of the provider's wrapper.

PEC is ordinary email plus Italian bureaucracy: spam arrives, newsletters
arrive, and every certified exchange adds acceptance and delivery receipts as
separate messages. Nothing about PEC content needs a separate privacy or
processing rule. What PEC needs, later, is a way to keep the bureaucratic
noise out of the store and a way to record what a receipt proves.

A manual read-only IMAP connection to one PEC.net mailbox succeeded on
2026-09-29. That proves authentication and mailbox access for that account,
nothing about Desktop sync or outgoing SMTP. No credentials or
account-specific paths belong in this brief.

## Existing product boundary

- The engine has one generic IMAP client and a profile-scoped sync. Desktop
  Onboarding and Settings expose `EMAIL_ADDRESS`, `EMAIL_PASSWORD`,
  `IMAP_HOST`/`IMAP_PORT` and `SMTP_HOST`/`SMTP_PORT` as single values. Every
  sync and RPC entry point reads that one mailbox from the process
  environment. Replacing the values with a PEC mailbox disconnects the
  ordinary one, so a provider preset alone does not deliver "also download
  PEC mail".
- Two preset tables exist, both falling back to Gmail hosts on an unknown
  domain: Onboarding's `PRESETS` (Gmail, Outlook, Yahoo, iCloud) and the
  engine's `IMAP_PRESETS`/`SMTP_PRESETS`. The password field is labelled
  "App password", which is wrong for a PEC mailbox password.
- The engine knows the user by one address. Task detection compares senders
  against `EMAIL_ADDRESS` only and ignores `EMAIL_ALIASES`; reply detection
  and the memory and task trainers compare against the address plus aliases
  at most. Mail sent from any other address the user owns is read as a
  contact's mail.
- Sync covers INBOX, the `\Sent` folder and the `\All`/`\Archive` folder,
  with a persisted per-folder cursor (UIDVALIDITY plus last UID) keyed by
  owner and folder name. A folder with no cursor seeds its floor from the
  newest email stored in the whole profile minus an overlap window, not from
  the history window of a new profile. Fetches use `BODY.PEEK[]` on a
  read-only SELECT, so sync never marks server mail as read. Per-message UID
  and raw message bytes are not stored; parsed bodies and attachment
  filenames are.
- Threads are keyed by `References`/`In-Reply-To` across the whole profile.
  The `emails` table is unique on `(owner_id, gmail_id)`, and on the IMAP
  path `gmail_id` is the RFC 5322 `Message-ID`. Two mailboxes receiving the
  same message (a copy to both addresses, a forward that keeps the header)
  collide today. This is the load-bearing schema decision of the plan.
- Server-touching actions all use the primary mailbox's credentials.
  `emails.archive(thread_id)` moves every Message-ID of the thread on the
  server, and a Message-ID the server does not hold counts as moved.
  `emails.delete(thread_id)` is a local soft delete and never touches IMAP.
  Attachment download re-fetches the message live by Message-ID.
- Sending uses `smtplib.SMTP` with STARTTLS only. Register.it documents
  implicit SSL on port 465 for PEC SMTP, so `SMTP_PORT=465` in today's fields
  does not send.
- A received PEC is an envelope under the PEC technical rules: the outer
  `From` is the provider's certified address "on behalf of" the sender, the
  outer body is boilerplate, and the original message travels as an attached
  `postacert.eml`. The parser stores the outer `From` and the first text
  part. This shape is taken from the standard, not yet from a live sample.
- cs-kernel, the separate operator repo that drives this engine, reads the
  profile's mailbox through `settings.get` (`EMAIL_ADDRESS`) and
  `settings.get_secret` (`EMAIL_PASSWORD`), and calls `emails.search`,
  `emails.list_by_thread` and `emails.needs_reply`.
- Register.it's [PEC configuration guide](https://www.register.it/assistenza/configura-la-pec-su-dispositivo/)
  gives the full address as username, IMAP SSL on `imap.pec-email.com:993`
  and SMTP SSL on `smtp.pec-email.com:465`. These are a provider preset that
  can be updated, not an account type hard-coded into sync logic.

## Delivery 1 — additional mailboxes, nothing PEC-specific

Add a mailbox to the signed-in user's existing profile. The GUI offers
provider presets, including `PEC.net (Register.it)` with the official hosts
prefilled, plus a custom IMAP/SMTP path. The password label says what it is
for the chosen provider. A connection test runs before saving and
distinguishes wrong password, unreachable server, certificate failure and an
unreadable folder. The password stays masked in the renderer and out of logs
and errors, under the profile's existing private credential boundary. The
Firebase UID and profile directory do not become a mailbox identifier.

The profile holds a list of mailboxes, not a second slot: adding the third
mailbox costs nothing beyond the second, and no `*_2` environment variable
exists. Exactly one mailbox is primary, and it is the one that sends. The
engine gets mailbox-scoped configuration, credentials, sync cursors and
source attribution. Every email row, search hit and attachment retrieval
carries its source mailbox, and attachments are fetched from that mailbox.
A thread can span mailboxes; its rows keep their own attribution. Two
different mailboxes holding the same `Message-ID` are two rows. Every
mailbox address is a user identity wherever the engine decides whether a
message is the user's: task detection, reply detection, memory extraction.
The first sync of an added mailbox covers the same history window as a new
profile, independent of mail stored from other mailboxes.

Existing single-mailbox profiles migrate without re-entering the password or
re-importing history. The additional mailbox uses the same folder policy and
the same post-sync chain (memory extraction, task detection, LLM budget) as
the primary one. Archive of a thread moves each message on its own source
mailbox, or is refused with a named error for the messages it cannot reach;
a mailbox missing the message never counts as success. Delete stays local.
A PEC transport envelope, recognised by the envelope markers the PEC standard
defines and never by the mere presence of an attached message, is stored
with the original's sender, subject and body, so memory learns the
correspondent and
not the provider. The row keeps the envelope's `Message-ID` as its server
identity for sync and archive, uses the original's `Message-ID` and
`References` for threading, and retains the envelope markers so a later
delivery can derive `certified` from stored rows. A message forwarded as an
attachment keeps its forwarder as sender, in every mailbox.

The primary mailbox keeps answering `EMAIL_ADDRESS`/`EMAIL_PASSWORD` through
`settings.get`/`settings.get_secret`. Existing email RPC results stay
backward compatible and gain a source-mailbox field. Whether cs-kernel
threads include additional-mailbox rows is stated in the plan.

Onboarding keeps creating one mailbox. Settings lists the profile's
mailboxes with their sync state, an "Add mailbox" action, editing of an
added mailbox's credentials, and removal. Removal stops sync and hides the
mailbox's rows; the plan states what happens to memory already extracted
from them.

Sending from an additional mailbox is outside this delivery. Replies and new
mail keep going out through the primary mailbox as today, and the composer
shows the From address, because a PEC recipient may reject ordinary mail.
Adding SMTP for additional mailboxes, including implicit SSL on 465, is its
own later milestone with its own approval and dedup bookkeeping.

**Acceptance** (isolated fixtures plus one supervised live PEC.net account):
add the mailbox through the GUI with the PEC.net preset; test the connection;
add a third mailbox in a fixture and confirm it syncs with its own cursors;
restart; sync twice without duplicates; see both mailboxes listed with their
state and each message attributed to the right one; find a known message
older than the overlap window, its attachments and a known receipt in the
second mailbox; confirm memory and task processing ran on its messages, and
that a known PEC message is stored with the original sender and body rather
than the provider envelope; confirm a message sent from the additional
mailbox creates no task and no contact entity for the user; confirm the
primary mailbox still syncs and sends; migrate an existing single-mailbox
profile without re-entering the password; store the same `Message-ID`
delivered to both mailboxes as two rows; archive a thread spanning two
mailboxes and a thread whose `Message-ID` exists in both, and confirm each
copy moved on its own server or was refused with a named error, and the
primary was not touched for the other's messages; archive a PEC envelope
fixture and confirm it moved on its own server; confirm a forward-as-
attachment fixture in the primary mailbox keeps its forwarder as sender;
confirm cs-kernel's mailbox read still returns the primary. No live message
content in committed fixtures.

## Delivery 2 — flag a mailbox as PEC and drop the bureaucracy

A mailbox setting marks it as PEC. For a PEC mailbox the sync recognizes the
provider-generated bureaucratic messages (acceptance, delivery and
non-delivery receipts, daily notices) and does not store them as mail, so
they never reach search, memory or tasks. The recognition rule must be
provider-grounded (headers and sender patterns that the PEC standard
defines), listed in one place, and testable against captured receipt
headers. Human correspondence in the same mailbox is untouched. A user can
see how many messages were dropped and why, and can turn the filter off.

## Delivery 3 — record what the receipts prove

Add two fields to the mail store so the product does what the Italian public
administration cannot: `certified` (the received message is a PEC, derived
from the envelope markers Delivery 1 retains on the row) and
`delivered` (a delivery receipt for a message
we sent has been matched to it). The match uses the receipt's reference to
the original message identifier, never the subject. Both fields show in the
email view and are queryable. This delivery needs Delivery 2's receipt
recognition and, for `delivered`, sending from the PEC mailbox.

## Out of scope for all three

Legal classification of receipts, a claim of compliant long-term
conservation, raw `.eml` export with manifests, and broad provider
certification. The local database is a working copy; the provider's PEC
records remain the certified ones.

## Decisions for the execution plan

1. Mailbox configuration and secret store, and the migration path from the
   single `.env` mailbox, including a profile whose `EMAIL_ADDRESS` changed
   in the past and whose older rows came from a different account.
2. Mailbox identity in storage, sync cursors and RPC/UI results, the new
   uniqueness constraint on `emails`, and whether cs-kernel threads include
   additional-mailbox rows.
3. How archive reaches each message's source mailbox, and what removal of a
   mailbox does to memory already extracted from it.
4. The PEC recognition rule and its test corpus (Delivery 2), then the
   `certified`/`delivered` derivation and the SMTP-SSL send milestone
   (Delivery 3).
