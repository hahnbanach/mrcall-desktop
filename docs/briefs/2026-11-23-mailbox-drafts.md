# One mailbox draft for every Desktop client

The governing cross-repository brief is HB's
`docs/briefs/2026-11-23-drafts-live-in-the-mailbox.md`, available in this workspace
at `/home/mal/hb/docs/briefs/2026-11-23-drafts-live-in-the-mailbox.md`.
Its November 23 execution plan governs delivery through installed acceptance.
This leaf trace records the Desktop-owned implementation boundary. The current
IMAP transport amendment is HB `docs/briefs/2026-11-24-mailbox-drafts-imap-transport.md`;
it supersedes this trace's original provider/container assumptions.

The engine owns native mailbox draft creation, listing, editing, recoverable
Trash and sending. Gmail, Desktop and MCP refer to the same current mailbox
draft through its exact IMAP handle. Internal editable draft rows and review-copy synchronization
are retired. The kernel requests effects from the engine.

The engine preserves saved Gmail edits and never recreates a draft externally
sent or deleted. A durable receipt binds each request to its mailbox, operation
and generated Message-ID. An uncertain send only rechecks Sent, across process
restart and across every caller. A later automatic path cannot retransmit while
the original source's send remains unconfirmed.

Scheduled composition checks conversation, Sent, assignments and existing drafts
before generation. Human answers hold the thread until a newer eligible inbound.
An existing draft stays for review in either mode. Send mode dispatches directly
without an intermediate draft. Manual deletion does not persist a suppression.

Acceptance includes public MCP and Desktop paths, saved Gmail recipient/body
changes, independent receipt and Sent confirmation, same-request replay,
delayed Sent across an actual process restart, two Café draft-mode ticks and
one MrCall send-mode tick through ordinary launchers, and one installed release
on seven engines. The separate 17-draft Trash order is exactly identified and
excludes later arrivals. Production evidence contains no customer content.

The original platform requirement uses IMAP/SMTP with app passwords. Exact
owner/mailbox/folder UIDVALIDITY/UID handles identify current messages. A saved
external edit can replace its handle; a fresh explicit send names the freshly
listed draft. A stale handle never reattaches heuristically. Existing Firebase
identity and Calendar OAuth remain separate from mailbox access.
