# The semantic commit and its operation journal

<!-- doc-scope:start -->
Scope: the write half of the mnemonic harness — how a validated proposal
becomes committed memory, what one transaction contains, and what the operation
journal remembers. The decision half is
[mnemonic-decisions.md](mnemonic-decisions.md); the writers not yet routed
through here are [mnemonic-writer-inventory.md](mnemonic-writer-inventory.md).
<!-- doc-scope:end -->

`zylch/memory/mnemonic/commit.py` is the only production module that writes
company memory through the harness. `submit(event)` is its whole public
surface: hand it an event, get one `MnemonicResult`. It returns a result and
does not raise — its callers are tools that owe their own caller an answer, and
an exception escaping would say nothing about whether memory changed. The one
thing that still propagates is `KeyboardInterrupt`: that is the process going
away, not an outcome. A caller never receives a session, a permit, a writer or
a commit function.

`wiring.py` holds the composition — which store, which account, which
retrieval — and `session.py` the one company transaction both the commit and
the journal open.

```
submit(event)
  └─ journal.open_operation  → a recorded terminal result replays here
     journal.claim           → a fenced lease, not an in-process mutex
     agent.decide            → the bounded, paid decision round
     _commit                 → one transaction on the company store
```

## One transaction

Embeddings are computed **before** the transaction: encoding is seconds of CPU
and can fail, and doing it under the company write lock would queue every other
writer behind a model. An embedding failure is therefore a `retryable_failure`
that never opened a transaction.

Inside, in this order:

1. `memory.store.take_write_lock` — a no-op write on `memory_meta`, so SQLite
   grants the RESERVED lock as the transaction's first statement.
2. `journal.owns` — this process still holds the lease, or it stops here.
3. `authorize_request` — re-checked under the lock. A turn cancelled, or a
   policy flipped, while the model was thinking stops the write, not merely the
   next dispatch.
4. The blob and its sentences, through `BlobStorage.semantic_create` /
   `semantic_update` under a `CommitPermit`.
5. The identifier index and the source link, through
   `zylch/memory/associations.py`, in this same session.
6. The mutation sequence, bumped once for the whole commit.
7. The operation receipt.

The session is bound to the company store **alone** —
`mnemonic/session.py` binds one engine rather than reusing the per-table binds
— so a stray profile-table statement has nowhere to go instead of quietly
committing a second transaction inside an operation that calls itself atomic.

Every journal transaction that reads a row and then updates it takes the same
lock first, for the same reason the commit does. Under WAL, SQLite refuses to
upgrade a deferred read transaction whose snapshot has gone stale, and it
refuses *immediately*: `busy_timeout` never applies, because there is nothing
to wait for. Without the lock up front, two engines on one company store both
fail and neither writes.

An UPDATE **replaces** its blob's identifier rows. The old writer only
appended, so correcting an email address left the wrong one in the index and
the next cross-channel lookup still matched it.

## The permit

`zylch/memory/commit_permit.py` holds the single-use authority for one
semantic write, bound to company, owner, event, proposal digest, namespace, the
exact content digest, and the write set with its expected versions. It is
opaque: no session, no engine, no callable.

`BlobStorage.semantic_create` / `semantic_update` refuse a missing, forged or
already-spent permit **at the storage boundary** — forgery by object identity,
so a value-identical copy is not the permit that was issued. The compare-and-
swap lives there too: the version is compared against the row re-read inside
the transaction, not against what a caller remembered.

`issue_commit_permit` is imported by `mnemonic/commit.py` and by nothing else.
That is asserted statically in `tests/memory/test_mnemonic_commit.py`, because
Python privacy is not a sandbox against code in the same process: a runtime
guard stops a forger, not a future adapter that politely asks the factory for a
real permit.

## The operation journal

One row per submitted event in `memory_operations`, in the **company** store
beside the blobs it writes. Profile-local `WorkerState` cannot coordinate two
profiles sharing a company and swallows persistence errors; `Blob.events`
cannot either, since a donor's receipts vanish with the donor. Admission,
source-stage retry limits, backoff and status stay with `preparation_state` /
`preparation_attempts`.

It answers three questions a stateless decision layer cannot:

- **Was this done?** `event_id` is the idempotency key. A replayed event
  returns its recorded result and pays for nothing; the same id arriving with a
  different `input_digest`, owner or company is refused rather than re-pointed.
  `committed`, `skipped` and `review` replay; `failed` is meant to be retried.
- **How much may it still spend?** `allowance` is the durable form of the
  per-event dispatch allowance. `mnemonic/authorization.py`'s in-process table
  is now a cache over it: the grant reads it, and every dispatch decrements it
  **before** the request goes out. A crash mid-dispatch leaves the call counted
  rather than free — deliberately, so a crash loop converges.
- **Who holds it?** `claim` writes a durable, unguessable lease into the row;
  `owns` re-checks it inside the commit's transaction, so an attempt superseded
  while a model was thinking finds out instead of overwriting the winner.

Persistence fails closed: every function raises `JournalError` and `submit`
turns that into a `retryable_failure`. Recording a commit that may not have
happened is the one outcome it must never produce.

**Who may read a row.** The journal is in a store every key holder can open, so
visibility is hung the opposite way round from a blob's. A blob defaults to
visible and rule namespaces are carved out; an operation defaults to **private
to its submitter**, and only a decided company-family `target_family` opens it
to the rest of the company. The asymmetry is the payload: a blob's content is
already the committed memory, while an operation carries the raw observation
that produced it, and until the role has answered nobody knows whether that
text is company knowledge or one account's private correction.

**What a payload holds.** The suggestion, the explicit-request flag, the
proposal and its write set — plus the original instruction only when the source
cannot be referenced durably (a chat turn the engine does not keep). An email
or a task has a row of its own; copying its body here would give the same text
two retention policies. On a terminal state the bodies are dropped and the
digests stay, which is exactly enough to recognize a replay.

Sizes are bounded by the contracts, not by a second check here: `MemoryEvent`
refuses an oversized observation or suggestion and `Proposal` an oversized
content or write set. Refusal, never truncation — a trimmed observation is a
different observation, and the operation would then be idempotent against
something nobody submitted.

## Migration

`memory_operations` is registered in `MEMORY_TABLE_NAMES`
(`zylch/storage/database.py`). That single registration is the install: the
name puts the table on the memory bind, so every statement naming it reaches
the company store, and inside `memory.store.prepare_store`'s ensure pass, so
`create_all` adds it and its two indexes to every store under that file's
migration lock. Additive: no existing row is read or rewritten, and
`tests/storage/test_mnemonic_journal_migration.py` hashes every durable column
of every blob row before and after to prove it.

## What this does not do yet

- **MERGE and reclassification return `review_needed`.** The proposal is
  recorded, nothing is written. Approximating a merge with an update is the
  failure this harness exists to remove.
- **Only `create_memory`'s entity path is routed here**, and only when
  `MNEMONIC_WRITE_PATH=create`. The default is `off`, which is the direct write
  the tool has always done — the approval that must guard a change to existing
  memory does not exist yet, so the slice stays unreleased outside a test or an
  explicitly selected cohort.
- **A proposal to change existing memory is refused, never written the old
  way.** A harness that writes around itself when it disagrees is not a
  boundary.
- **`entry_type='behavioral_rule'` still goes to `prefs_store.store_rule`**, in
  both modes. Account rules keep their own dedup and supersession logic.
- **Every other writer in the inventory is still direct.** There is no
  single-writer claim.

## The supervised slice

`zylch/tools/memory_events.py` turns one `create_memory` call into an
authenticated event. Two things are kept apart:

- **what the human said** — captured into `assistant/turn_context` by
  `ChatService.process_message` as its first statement, upstream of the
  semantic command matcher (which replaces the message with a slash command)
  and of the TASK CONTEXT prefix a task conversation adds. That is the
  `observation`, and its digest is the chat turn's source revision — so the
  same sentence is the same event wherever it was typed.
- **what the model made of it** — the `content` argument, carried as a
  *suggestion* through `MemoryEvent.with_model_arguments`, which can set
  nothing else.

A call with no turn behind it is refused rather than promoting the model's
rewrite to the status of something that was said. The caller class is
`operator_delegated`: a tool call during a human's turn is the model acting on
the human's behalf, not an authenticated human instruction.

The tool reports success only after a committed receipt **and** an actual
read-back through the ordinary scoped read path. A decision is never reported
as a save.

## Tests

`tests/memory/test_mnemonic_commit.py`, `tests/memory/test_mnemonic_journal.py`
and `tests/storage/test_mnemonic_journal_migration.py`, against real split
profile and company databases — two owners sharing a key, a second company, and
two independent OS processes committing one event id once. The vertical slice
runs the real tool, the real role, the real `LLMClient` and the real
reservation ledger with only the provider transport replaced: no test-supplied
preparation context, no stubbed `check_dispatch`, no faked reservation.
