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
submit(event, requested=…)
  └─ journal.open_operation  → a recorded terminal result replays here
     journal.claim           → a fenced lease, not an in-process mutex
     agent.decide            → the bounded, paid decision round
     authorize_mutation      → a human accepts a CHANGED final mutation
     _commit                 → one transaction on the company store
```

`requested` is what the calling tool's own arguments asked for. An adapter that
supplies none is treated as having changed everything: the harness cannot tell a
faithful proposal from a rewritten one without being told what was asked, and it
resolves that in the direction that asks a human.

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

## The acceptance

A validated proposal is not yet an authorized one. Between `agent.decide` and
the transaction, `mnemonic/approval.py` compares the proposal against the
`RequestedWrite` the adapter declared. A proposal that does what was asked
proceeds on the approval the caller's own tool call already needed
(`APPROVAL_TOOLS` gates every memory tool, and `assistant/core.py` refuses with
no approval channel). A proposal that **changed** something is presented in full
and written only on an acceptance naming it:

- a different action (`CREATE` where an overwrite was asked for, or the reverse);
- a different subject — a blob other than the one the call named, or, when the
  call named none, any target at all, since nothing the caller said picked it;
- a different entity type or scope;
- an effect that absorbs, re-points or removes another memory, a
  reclassification, or a donor.

**What makes an acceptance exact.** Three name-keyed shortcuts auto-approve in
production: `cs --allow` answers every notification for an allowed tool name,
the engine remembers `chat.approve(mode="session")` per conversation and tool
name, and the Desktop card offers "Allow for session". A new tool name defeats
none of them, because all three key on whatever name is used. So an acceptance
is not a boolean: the card carries a single-use nonce and the digest of the
proposal, and the accepting surface must echo both back in `edited_input`. Every
standing grant answers `(True, None)` and therefore fails structurally, with no
list of trusted surfaces to maintain.

`proposal_digest` covers the write set's expected versions, so a CAS re-read
that lands on a different version — or a re-decision that revises the prose — no
longer matches the acceptance a human gave, and the next round asks again. The
gate is inside the decision loop for exactly that reason. A denial, a timeout, a
cancelled turn and an edited card are all refusals; an edit means the accepted
text is no longer the decided one, and the revision has to be submitted as its
own instruction.

A caller with no channel — a headless run, a scheduled operator, an RPC client
offering no approval route — gets `review_needed` and no write.

**Where the channel comes from.** `zylch/services/mnemonic_approval.py` is the
one bridge from the engine's async `approval_callback` to this synchronous path,
and the driver that owns the turn installs it: `chat.send` and `tasks.solve` do,
each also opening a `revocable_turn` so cancelling the turn revokes a dispatch
grant already copied into a worker thread. The commit runs on a worker thread
precisely so the bridge can reach the loop; asked from the loop thread it
refuses rather than deadlocking the loop that would deliver the answer.

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
- **Only the interactive chat tools and the task solve are routed here.**
  `MNEMONIC_WRITE_PATH` is a ladder: `off` (the shipped default) is the legacy
  direct writes, `create` is `create_memory`'s entity path alone, and
  `supervised` adds `update_memory` and the solve — which is what the acceptance
  above exists to guard. Widening the slice past a test or an explicitly
  selected cohort is a separate decision; nothing about the acceptance existing
  makes it the default.
- **A proposal this mode does not admit is refused, never written the old
  way.** Under `create`, a proposal to change existing memory returns for
  review. A harness that writes around itself when it disagrees is not a
  boundary.
- **`entry_type='behavioral_rule'` still goes to `prefs_store.store_rule`**, in
  both modes. Account rules keep their own dedup and supersession logic.
- **No adapter populates a `SubjectHint`'s `name`, `email`, `phone` or
  `company`.** `create_memory` passes at most a bare `FACT` hint, `update_memory`
  passes a `target_blob_id`, and the solve passes none. Three rules in
  [mnemonic-decisions.md](mnemonic-decisions.md) therefore describe branches
  nothing currently reaches: the caller-named-subject anchor an UPDATE falls back
  to for a legacy row stating neither `Name` nor `Key` (so such a row cannot be
  updated through the harness at all — it returns review), and the PERSON
  corroboration arm that needs "a shared identifier plus the same stated name",
  which leaves PERSON corroboration effectively email-only for
  `_check_duplicate_create`. Both fail visibly rather than silently, and a
  populated hint is what a converting adapter supplies when it has one — the
  rules are not dead, they are unused.
- **Every other writer in the inventory is still direct.** There is no
  single-writer claim.

## The supervised slice

`zylch/tools/memory_events.py` turns a `create_memory` or `update_memory` call
into an authenticated event, and `zylch/services/solve_memory.py` does the same
for the task solve's `update_memory`. Two things are kept apart:

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

`update_memory`'s `blob_id` is a **hint**, not a target. It pins that row first
among the candidates and it is the `RequestedWrite` baseline the acceptance gate
measures the proposal against — so a proposal that writes elsewhere is a changed
subject and needs a human. It never becomes the write target by having been
named.

The **solve** has no chat turn, and `zylch/services/solve_context.py` carries
what it has instead: the instruction the human typed into the solve box this
run, and the task's own text, kept separate. A typed instruction is the
observation and the caller class is `operator_delegated`; with nothing typed,
the task's text is the observation and the class is `automatic_observation`.
Extracted content cannot acquire an instruction's authority by being passed to
the tool a human also uses, and nothing a model writes changes either — the
authority fields are `MODEL_SEALED`. The solve's `query` reaches the decision as
nothing at all — it is what the model searched with, and it was briefly passed as
a `SubjectHint(name=…)` on the theory that a name hint widens retrieval, which it
does not: `candidates.gather` searches the observation and the identifier index
stores no names. What it did do is make `names_entity_subject` true, which forbids
a company FACT outright, so a solve could not store "from Monday we open at 8".
There is no retrieval-only field to put it in, so it is passed nowhere. Because
the caller therefore names no blob, every solve proposal writes to a subject it
did not choose and is always shown before anything is written. The origin
stays `interactive` in both cases: a human pressed Solve, so the dispatch rides
their turn and leaves bounded preparation untouched.

The tool reports success only after a committed receipt **and** an actual
read-back through the ordinary scoped read path. A decision is never reported
as a save — including a change the human was shown and declined, which is a
review with a reason.

## Tests

`tests/memory/test_mnemonic_commit.py`, `tests/memory/test_mnemonic_journal.py`
and `tests/storage/test_mnemonic_journal_migration.py`, against real split
profile and company databases — two owners sharing a key, a second company, and
two independent OS processes committing one event id once. The vertical slice
runs the real tool, the real role, the real `LLMClient` and the real
reservation ledger with only the provider transport replaced: no test-supplied
preparation context, no stubbed `check_dispatch`, no faked reservation.

The acceptance and the adapters have their own:
`tests/services/test_mnemonic_approval.py` (what counts as a change, what counts
as an acceptance, and the gate end to end against real rows),
`tests/tools/test_mnemonic_adapters.py` (the observation/suggestion split, the
sealed authority fields, the mode ladder) and
`tests/services/test_mnemonic_solve.py` (the query's lost authority, the two
caller classes, and the real `TaskExecutor` driven across both of its thread
boundaries). The Desktop card's half of the contract is
`app/scripts/test-memory-approval.mjs`, which drives the real `StdioRpcClient`
against a fixture sidecar and asserts the `chat.approve` frame that arrives.
