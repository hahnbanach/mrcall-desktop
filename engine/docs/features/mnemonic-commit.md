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

`allow_actions` narrows what a caller admits: `/memory store --force` passes
`(CREATE,)`, and a proposal outside the set is refused as review, never written
another way. `parent_event_id` files the event as one child of a source
operation ([children of a source](#children-of-a-source)).

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
   `semantic_update` / `semantic_merge` under a `CommitPermit`.
5. The identifier index and the source link — for a MERGE, every source link
   of the donor, and the alias — through `zylch/memory/associations.py`, in
   this same session.
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

## A merge

A MERGE drops a memory, and consolidation is the only operation that drops
one: `commit.py` admits a MERGE only for a consolidation pair
(`pairs.admits_merge`) — `allow_actions` includes it, the event's source kind is
`consolidation`, the keeper and donor are exactly the two ids its `source_id`
names, and the current preparation item is the admitted `memory:consolidate`
item for that pair. Every other MERGE, and every reclassification, is
`review_needed` with the proposal recorded.

`mnemonic/writes.py` writes it, inside the one transaction:

1. keeper and donor re-read visibly under the lock; either missing is a
   conflict;
2. the donor's source links read (email, calendar, WhatsApp);
3. `BlobStorage.semantic_merge` (`memory/blob_commits.py`): the permit checked
   for MERGE with both (id, version) pairs in its write set and both rows in
   its namespace, each version compared with the row just re-read — a stale
   keeper and a stale donor each raise a `ConflictError` naming which — then
   the keeper rewritten through `_rewrite(reason="consolidate")` and the donor
   dropped through `delete_blob(retain=True, session=…)`, both under the
   operation's id; a drop that removes nothing is a conflict;
4. every donor link re-created on the keeper, each with its own `owner_id`;
5. the keeper's identifier rows replaced from the merged text's
   `#IDENTIFIERS` block, so an index row neither text states does not spread;
6. `associations.record_alias(donor → keeper)`.

The receipt records one pending effect, `task_references` /
`"<donor>-><keeper>"`: the committing profile's task ledger
(`task_items.sources["blobs"]`) lives in another file and cannot join the
company transaction. `mnemonic/references.py` applies it right after the
commit — only for the committing account, only while this profile is bound to
the merge's company, only in this process's own profile file, only the
`sources["blobs"]` lists that name the donor, which is re-pointed to the
keeper's survivor (a later merge may have folded the keeper too). The effect is
removed from the receipt once applied. A follow-up that fails or cannot read
its receipt leaves the effect recorded and the result `committed` with
`pending_effects`; every consolidation run replays this account's recorded
effects first (`replay_pending`), and a journal that cannot list them is an
error, never "none pending". Other profiles sharing the store never have their
file opened: they resolve the donor through the alias, and
`scope.resolve_aliases` follows alias chains in both directions, bounded at 32
hops.

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

The commit runs on a worker thread (`asyncio.to_thread` in the two tools, in
`/memory store` and in the tools' rule paths) so the paid decision round does
not block the event loop, and under a `revocable_turn`: `chat.send`,
`tasks.solve`, the interactive CLI solve and the background memory job each
open one, so cancelling the turn revokes a dispatch grant already copied into
that thread. Correction learning's thread is spawned inside the solve's turn,
so the same revocation reaches it.

## Retention

Nothing an append does is destructive. Every rewrite of a blob's content goes
through `BlobStorage._rewrite`, and the first thing `_rewrite` does is copy the
row it is about to replace into `blob_versions` (`memory/blob_versions.py`,
`retain_version`) in the same session, stamped with a `reason` — `append` for
an update, `consolidate` for consolidation's keeper rewrite, `restore` for the
owner's restore — and, for a semantic write, the `operation_id` of the event
that caused it. Consolidation's donor drop is `delete_blob(retain=True,
session=…)` inside the MERGE's own transaction: the donor's final text is
retained with reason `consolidate` before the row goes, and a retaining drop
without the caller's session is refused. The owner's own `/memory delete` and
`/memory reset` retain nothing and prune the versions of exactly the blobs they
remove — consolidation is the only *semantic* operation that removes memory,
and it keeps what it removes. The one raw delete in the estate,
`scripts/compact_learned_prefs.py`'s `DELETE FROM blobs`, is a maintenance
script the frozen inventory names (`sql:DELETE:blobs`, milestone 8); it
retains nothing and stays until milestone 8 converts it.

`blob_versions.blob_id` is indexed and deliberately **not** a foreign key: a
cascade would delete a retained donor inside the very transaction that retains
it. Pruning is explicit, by blob id, and never by `owner_id` — on a shared
store a version's `owner_id` is the writer's provenance, and filtering on it
would let one key holder's reset erase the history of another's rows.
`list_versions` and `get_version` read versions back.

**How long a version is kept.** Consolidation applies the retention policy and
nothing else does (`expire_versions`; a static test pins its only caller). The
settings come from the sweeping engine's profile and act on the whole shared
store: `MEMORY_VERSION_RETENTION_DAYS` (90), `MEMORY_VERSION_FLOOR` (10) and
`MEMORY_VERSION_SINK_THRESHOLD` (25). A value below 1 is refused and named in
the run's `retention_refused`: nothing is pruned, and a refused threshold also
decides no pair.

- A blob's **count** is its `append` versions superseded after its latest
  `restore` version. `consolidate` and `restore` versions never count.
- A **sink** is a live blob whose count exceeds the threshold. None of its
  versions is pruned, consolidation never pairs it, and every run reports it
  until its owner restores a version or deletes the blob.
- Every other blob's version is pruned when it is older than the window
  (`superseded_at`) and not among the blob's floor newest. A dropped donor has
  no live blob and is never a sink: the window and the floor alone decide, and
  the floor keeps its final text.

Every run reports, before pruning, `blobs_versions_max` (the largest count of
any live blob), `version_sinks_total` (every sink in the store) and
`version_sinks` — the sinks this account can see, each with its count, largest
first, at most 100.

A version is restorable, mechanically, by any key holder who can see the
blob. `restore_version` rewrites the blob from the version's text through
`_rewrite` — so the restore retains the text it replaces and is itself
reversible — and asks no model. It is reachable as
`memory.restore_version(blob_id, version_id)` (`rpc/maintenance.py`) and as
`/memory restore <blob_id> <version_id>` in chat, with `/memory versions
<blob_id>` listing the ids, and it is gated on every route a mutation has:
`restore_memory` in `APPROVAL_TOOLS` and in the slash gate, `memory_write`
under a read-only turn, and `memory.restore_version` in the scheduled
operator's raw-RPC deny list. A headless operator cannot roll a shared memory
back by any door.

## The permit

`zylch/memory/commit_permit.py` holds the single-use authority for one
semantic write, bound to company, owner, event, proposal digest, namespace, the
exact content digest, and the write set with its expected versions. It is
opaque: no session, no engine, no callable.

`BlobStorage.semantic_create` / `semantic_update` / `semantic_merge` (the
committed writers, `memory/blob_commits.py`) refuse a missing, forged or
already-spent permit **at the storage boundary** — forgery by object identity,
so a value-identical copy is not the permit that was issued. The compare-and-
swap lives there too: the version is compared against the row re-read inside
the transaction, not against what a caller remembered. A MERGE permit names
both members with their versions; a donor it does not name, or one outside its
namespace, is refused and nothing is dropped.

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

### Children of a source

An ingested source — a mail, a WhatsApp message, a calendar event, a MrCall
conversation — is one **parent** operation whose id is derived from owner,
company, kind, source id and the digest of the rendered text, so an edited
source is a new revision and never reuses an old digest. Extraction runs under
the parent's own grant; `mnemonic/manifest.py` then records the bounded
manifest (at most `MAX_EXTRACTED_ENTITIES`, 16 — more is a review) and one
pending child row per entity, with stable ids `<parent>:<n>`, in a single
transaction under the parent's lease. Each child is submitted with
`parent_event_id` and settles on its own: committed, skipped, review or failed.
The parent is terminal only when every child is. Committed or skipped children
advance the source's checkpoint; a child in review parks the source visibly; a
failed child keeps its retry evidence; an empty valid extraction is an explicit
skip. A resume after a crash re-reads the manifest and decides only the
children that are not yet terminal, and a source already terminal replays its
receipt without a paid call. A review may also record `restrictions` — the
exact ids and versions of FACT candidates the role named as one customer's
knowledge rather than the company's — which `memory/eligibility.py` excludes
from every ordinary fact read ([what the validator
refuses](mnemonic-decisions.md#what-the-validator-refuses)). `mnemonic/ingestion.py`
is the loop; the journal stays a record, not a queue — admission, retries and
batches remain preparation's.

Sizes are bounded by the contracts, not by a second check here: `MemoryEvent`
refuses an oversized observation or suggestion and `Proposal` an oversized
content or write set. Refusal, never truncation — a trimmed observation is a
different observation, and the operation would then be idempotent against
something nobody submitted.

## Runbook: sinks, restores and pending follow-ups

**Reading a sink report.** `zylch memory-sweep` prints one line per sink
(`<blob_id>: <n> versions`) and says how many more exist that this profile
cannot see or the list leaves out; the Settings button's result carries the
same `version_sinks`. A sink is most often a busy contact — rewritten more than
25 times since its last restore — and occasionally the thing the report exists
for: a memory that absorbed other subjects. Read its versions
(`/memory versions <blob_id>`, oldest first) and decide which.

**What a restore does to a sink.** A restore retains the text it replaces with
reason `restore`, and the count starts again after it, so the blob is no longer
a sink and, from the next run, its versions older than the window and beyond
the floor are pruned like any other blob's — including the texts it absorbed.
Copy out what an absorbed text holds before restoring. When the current text is
already right (the busy contact), acknowledge the sink with two restores: the
current text is not a version, so restore the newest version, then restore the
version that first restore retained — the text is back and the count is zero.
Deleting the blob ends a sink too, with its versions.

**A pending task-reference follow-up.** A merge whose ledger follow-up could
not run is `committed` with `pending_effects` (`task_references`,
`<donor>-><keeper>`), and the operation row keeps the effect. The next
consolidation run by the same account on the same company replays it first and
reports `references_resolved` / `references_pending`. Until then the donor's id
still resolves to the keeper through the alias for every reader.

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

- **Reclassification returns `review_needed`**, and so does a MERGE anywhere
  but a consolidation pair's own admitted item. The proposal is recorded,
  nothing is written. Approximating a merge with an update is the failure this
  harness exists to remove.
- **Join, the storage migrations and the repair scripts are still direct**
  (milestone 8). The frozen inventory names every one; no setting selects a
  writer anywhere, and a proposal the harness cannot admit is refused, never
  written another way.
- **A review parks its source.** A child in review leaves its parent pending
  and its source unprocessed, visibly; nothing resolves it yet (milestone 8's
  tooling).
- **Calendar extraction is prose**, so a calendar child carries no typed
  identifiers and cannot corroborate: the duplicate-CREATE gate is off on that
  path. Consolidation folds a calendar-born PERSON into its mail-born twin only
  when both headers state the same email, or the same phone or lid and the same
  name; one whose address sits only in its prose, or that states only a name,
  stays a duplicate. The gate comes back by making that extraction structured,
  not by mining the message for identity.
- **A headerless legacy row anchors an UPDATE on the hint's name**, so an
  UPDATE against such a row commits without identity evidence; the replaced
  text is retained.

## The adapters

`zylch/tools/memory_events.py` turns a `create_memory` or `update_memory` call
into an authenticated event (its `create_event` also serves `/memory store`),
and `zylch/services/solve_memory.py` does the same for the task solve's
`update_memory`. Two things are kept apart:

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
either: a name hint drives the retrieval query (`candidates.retrieval_query`)
but never reaches the identity index, and it makes `names_entity_subject` true,
which forbids a company FACT outright, so a solve could not store "from Monday
we open at 8". Because the caller names no blob,
every solve proposal writes to a subject it did not choose, and the departure
says so (`unnamed_subject`). The origin stays `interactive` in both cases: a
human pressed Solve, so the dispatch rides their turn and leaves bounded
preparation untouched. The interactive CLI solve (`services/task_interactive.py`)
installs the same solve context, built from the task row and whatever the
operator typed, around each of its three executor runs.

The tool reports success only after a committed receipt **and** an actual
read-back through the ordinary scoped read path. A decision is never reported
as a save.

**Ingestion** (`workers/memory.py` over `mnemonic/ingestion.py`). Each channel
worker collects the original source — the mail, the WhatsApp message, the
rendered calendar event or MrCall conversation — and hands it to `ingest` as a
`Source`; the worker writes no blob. Extraction stays on the owner's trained
extraction prompt and the extract-routed client, under the parent's grant;
each extracted entity becomes one child event whose observation is a bounded
view of the source (`MAX_OBSERVATION_CHARS`, marked when cut) and whose
`SubjectHint` carries the entity's own header — type, name, and the
`identifiers` its `#IDENTIFIERS` block states, in the index's canonical form.
The sender is never injected: an automatic event's observation is the whole
message and is never mined for identity, so a name-only entity reaches the
role with no identity at all rather than with the sender's. The caller class is
`automatic_observation`, the origin `automatic` with the admitted item's stage,
the decision client the merge-routed model. The merge-gate brake
(`merge_enabled` off) keeps its meaning as an empty candidate set: search and
identifier lookups return nothing, exact reads stay, and every entity becomes a
fresh blob. `process_pipeline.py` reaches the mail and WhatsApp batches
only; a calendar event and a MrCall conversation are ingested per item through
the worker's own coroutines and the job facade, and both are tested there.

**Background jobs** (`services/job_executor.py`). `memory_process` is a facade
over the worker's own admitted path: `run_source_sync` runs the worker's
bounded coroutine for one item in a private loop, on a thread that carries the
job's context (`contextvars.copy_context().run`), under one `preparation_run`
and one `revocable_turn` for the whole job. A source through the job and the
same source through the pipeline is one parent operation with the same
children. A `BudgetError` leaves the channel loop and fails the job visibly; a
stop lands between sources and, through the turn, before the next child's
dispatch. The job has no entity decision of its own.

**Helper writers** (`services/facts_store.upsert_fact`,
`prefs_store.store_rule` / `refine_rule`, `services/correction_learning.py`).
Each is an adapter over `submit()` and asks no human. A FACT hint pins the
exact `(Category, Key)` row; a rule pins its supersession candidate; a shape
refusal and an exact duplicate are decided without a paid call; the outcome is
reported as itself (`created`, `superseded`, `refined`, `duplicate`, `review`,
`refused`, `error`). STYLE files in the canonical `template` namespace, and the
rule body — the pure STYLE control header stripped — is what rendering, dedup,
ranking and the read-side cap measure. Where a helper is called decides its contract
(`mnemonic/entry.py`): inside an admitted preparation item it is automatic with
that item's stage and source; inside a run but outside an item it is refused,
so a trainer or a maintenance RPC cannot buy the interactive contract by
omission; otherwise it is interactive on the current turn, with the turn's
observation or the text it was handed. Correction learning builds one entry per
approved send — the drafted and sent texts with their recipients, keyed by their
digest, source kind `correction` — on the solve turn that produced it; that
observation is an envelope and is never mined for identity.

**`/memory store`** (`services/command_handlers.py`). The verb submits one
explicit interactive event on the chat turn: the turn's words are the
observation (the typed content when no turn stands behind the verb), the
content is the labelled suggestion, and `explicit_request` is set so a silent
SKIP is refused. The role may answer with an UPDATE of memory it was shown; that
is committed and recorded as a departure from the create that was asked for.
`--force` admits CREATE only. The answer is read back from the committed row;
the verb writes no blob itself.

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

Ingestion, the jobs, the helper writers and the verb have their own, on real
split databases with the role scripted at the transport:
`tests/workers/test_mnemonic_ingestion.py` (what one source commits, links
and indexes; the sender never inherited; the candidates the role is shown; an
empty extraction as a recorded skip), `tests/workers/test_mnemonic_replay.py`
(the replay contract — real fault injection before the manifest, between
children, after the company commit and before the checkpoint, on a resume; a
source edit as a new revision; a budget refusal that consumes no retry; a
refusal a later run can satisfy kept retryable),
`tests/services/test_mnemonic_jobs.py` (one source, one operation through
either entry; the restart; the stop; the read-only origin; the tag and the turn
read inside the thread), `tests/memory/test_mnemonic_children.py` (the
manifest and the restrictions), `tests/services/test_helper_writer_events.py`
(the three entry states, the adapters' outcomes, the spawn inside the solve
turn asserted structurally), `tests/services/test_memory_verb_events.py`
(`/memory store`, `--force` and a read-only turn) and
`tests/memory/test_fact_eligibility.py` (a customer-shaped FACT leaves every
read). `tests/workers/ingestion_env.py` is the shared bench.

The merge and consolidation have their own, on the same real split databases:
`tests/memory/test_mnemonic_merge.py` (one transaction, the stale keeper and
donor, an undeclared third memory, a failure at each company write, the door),
`tests/memory/test_mnemonic_merge_boundary.py` (the permit at the storage
boundary), `tests/memory/test_mnemonic_reference_recovery.py` (the follow-up:
only this account's ledger, a crash after the commit, an unavailable second
profile, a company switch, alias chains), `tests/memory/test_mnemonic_pairs.py`
(the pair event, the hint, the pre-checks, admission),
`tests/memory/test_consolidation_retention.py` (the policy, sinks, restores,
the caller pins), `tests/memory/test_consolidation.py` (the three triggers,
the order, the gates, the stops) and `tests/memory/test_consolidation_pairs.py`
(what folds, what costs no call, what is left out).
