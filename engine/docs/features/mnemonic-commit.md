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
     departure_for           → how the proposal differs from what was asked
     _commit                 → one transaction on the company store
```

`requested` is what the calling tool's own arguments asked for. The proposal is
measured against it and the difference is recorded; the write itself is never
conditioned on it ([the departure](#the-departure)). An adapter that supplies
none records nothing: there is no baseline to differ from.

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

## The departure

A validated proposal is written. Nobody is asked: the caller's tool call already
carried the one permission a memory write needs (`APPROVAL_TOOLS` gates every
memory tool, and `assistant/core.py` refuses with no approval channel), and the
role's decision is the point of routing the write through it. What the harness
owes the caller instead is the difference between what was asked and what was
decided. `mnemonic/approval.py` compares the proposal against the
`RequestedWrite` the adapter declared and names each way it departs:

- `changed_action` — `CREATE` where an overwrite was asked for, or the reverse;
- `changed_subject` — a blob other than the one the call named;
- `unnamed_subject` — the call named no blob, so nothing the caller said picked
  the target;
- `changed_scope` — a different entity type or scope;
- `destructive_effects` — an effect that absorbs, re-points or removes another
  memory, a reclassification, or a donor.

`departure_for` returns `None` for a faithful proposal and otherwise the flags,
one sentence per flag, the requested baseline and the proposed action, entity
type, scope and targets. It is computed per decision round against that round's
proposal, and it rides three places: the `departure` column of the operation
row, written by `journal.receipt` inside the commit's transaction, so a
departing rewrite and the record that it departed cannot disagree; the
`MnemonicResult`, so `create_memory` and `update_memory` return it in
`data["departure"]`; and the solve's text answer, as one `Note:` line the model
reads. A human who sees that the role chose differently corrects it as a new
observation — a correction is an append, not a permission — and the text the
departing write replaced is retained ([retention](#retention)).

The three standing grants in the estate — `cs --allow`, the engine's
`chat.approve(mode="session")` and the Desktop "Allow for session" button —
grant the tool. That is the whole of what they grant, and it is enough.

The commit runs on a worker thread (`asyncio.to_thread` in both tools) so the
paid decision round does not block the event loop, and under a `revocable_turn`:
`chat.send`, `tasks.solve` and the interactive CLI solve each open one, so
cancelling the turn revokes a dispatch grant already copied into that thread.

## Retention

Nothing an append does is destructive. Every rewrite of a blob's content goes
through `BlobStorage._rewrite`, and the first thing `_rewrite` does is copy the
row it is about to replace into `blob_versions` (`memory/blob_versions.py`,
`retain_version`) in the same session, stamped with a `reason` — `append` for
an update, `consolidate` for the sweep's keeper rewrite — and, for a semantic
write, the `operation_id` of the event that caused it. The sweep's donor delete
is `delete_blob(retain=True)`: the donor's final text is retained with reason
`consolidate` before the row goes. The owner's own `/memory delete` and
`/memory reset` retain nothing and prune the versions of exactly the blobs they
remove — consolidation is the only remover of memory, and it keeps what it
removes.

`blob_versions.blob_id` is indexed and deliberately **not** a foreign key: a
cascade would delete a retained donor inside the very transaction that retains
it. Pruning is explicit, by blob id, and never by `owner_id` — on a shared
store a version's `owner_id` is the writer's provenance, and filtering on it
would let one key holder's reset erase the history of another's rows.
`list_versions` and `get_version` read versions back.

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

`memory_operations` and `blob_versions` are registered in `MEMORY_TABLE_NAMES`
(`zylch/storage/database.py`). That single registration is the install: the
name puts the table on the memory bind, so every statement naming it reaches
the company store, and inside `memory.store.prepare_store`'s ensure pass, so
`create_all` adds it and its indexes to every store under that file's
migration lock. `memory_operations.departure` is added by
`_apply_column_migrations` in the same pass, which can only add a column and
skips a store that lacks the table. Additive: no existing row is read or
rewritten, and `tests/storage/test_mnemonic_journal_migration.py` and
`tests/storage/test_blob_versions_migration.py` hash every durable column of
every blob row before and after to prove it.

## What this does not do yet

- **MERGE and reclassification return `review_needed`.** The proposal is
  recorded, nothing is written. Approximating a merge with an update is the
  failure this harness exists to remove.
- **Only `create_memory`, `update_memory` and the task solve are routed here.**
  They have no other path: no setting selects a writer, and the direct writes
  they replaced are gone rather than parked behind configuration. What guards
  the change is the tests below and the priced corpus of milestone 9. A
  proposal the harness cannot admit is refused, never written another way.
- **`entry_type='behavioral_rule'` still goes to `prefs_store.store_rule`.**
  Account rules keep their own dedup and supersession logic.
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

## The adapters

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
among the candidates and it is the `RequestedWrite` baseline the departure is
measured against — so a proposal that writes elsewhere is recorded as a changed
subject. It never becomes the write target by having been named.

The **solve** has no chat turn, and `zylch/services/solve_context.py` carries
what it has instead: the instruction the human typed into the solve box this
run, and the task's own text, kept separate. A typed instruction is the
observation and the caller class is `operator_delegated`; with nothing typed,
the task's text is the observation and the class is `automatic_observation`.
Extracted content cannot acquire an instruction's authority by being passed to
the tool a human also uses, and nothing a model writes changes either — the
authority fields are `MODEL_SEALED`. The solve's `query` reaches the decision as
nothing at all: it is what the model searched with. It is not a `SubjectHint`
either — a name hint does not widen retrieval (`candidates.gather` searches the
observation, and the identifier index stores no names) and it makes
`names_entity_subject` true, which forbids a company FACT outright, so a solve
could not store "from Monday we open at 8". Because the caller names no blob,
every solve proposal writes to a subject it did not choose, and the departure
says so (`unnamed_subject`). The origin stays `interactive` in both cases: a
human pressed Solve, so the dispatch rides their turn and leaves bounded
preparation untouched. The interactive CLI solve (`services/task_interactive.py`)
installs the same solve context, built from the task row and whatever the
operator typed, around each of its three executor runs.

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

Retention, the departure and the adapters have their own:
`tests/memory/test_blob_versions.py` and
`tests/storage/test_blob_versions_migration.py` (every rewrite and consolidation
path retains, the owner's delete prunes by blob and never by owner, foreign
keys on), `tests/memory/test_mnemonic_departures.py` (what counts as a
departure, that a departing proposal is written and recorded in the row and in
the response, that a faithful one records nothing, and that a headless caller
writes), `tests/tools/test_mnemonic_adapters.py` (the observation/suggestion
split and the sealed authority fields), `tests/services/test_mnemonic_solve.py`
(the query's lost authority, the two caller classes, the read-back, and the
real `TaskExecutor` driven across both of its thread boundaries and through
its cancellation handler) and `tests/services/test_task_interactive_memory.py`
(the CLI solve carries its context).
