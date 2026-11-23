# One mailbox draft for every Desktop client

The governing cross-repository brief is HB's
`docs/briefs/2026-11-23-drafts-live-in-the-mailbox.md`, available in this workspace
at `/home/mal/hb/docs/briefs/2026-11-23-drafts-live-in-the-mailbox.md`.
Its November 23 execution plan governs delivery through installed acceptance.
This leaf trace records the Desktop-owned implementation boundary.

The engine owns native mailbox draft creation, listing, editing, recoverable
Trash and sending. Gmail, Desktop and MCP refer to the same immutable Gmail
draft container. Internal editable draft rows and review-copy synchronization
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

Native Gmail draft identity is required because saved external edits replace
message identifiers. IMAP identifiers and thread matching cannot safely adopt
that replacement. Existing application OAuth configuration is reused; mailbox
consent remains an explicit provider authorization dependency. Calendar grants
and app passwords do not acquire Gmail scopes implicitly.
