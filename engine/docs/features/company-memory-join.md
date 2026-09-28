# Joining a company memory, resolving parked work, and maintenance

Scope: the join cutover (`memory.join`, `zylch memory-join`), the tooling that
settles operations the harness parked (`zylch memory-reviews`), and the
mechanical maintenance routes (`zylch memory-reindex-identifiers`,
`scripts/compact_learned_prefs.py`, the boot link rebuild). Milestone 8 of the
mnemonic harness; the semantic write path itself is
[mnemonic-commit.md](mnemonic-commit.md), the sealed writer boundary
[mnemonic-writer-inventory.md](mnemonic-writer-inventory.md). Built and
tested on branch `mariocc/loving-fermi-5xde8j`; **not merged, not deployed**.

## A join is a fenced, crash-safe cutover

A profile that holds a company memory and enters another key joins that
company: its memory is imported into the other store and its `MEMORY_KEY`
moves. `zylch/memory/join.py` orchestrates, `join_import.py` copies,
`join_recover.py` tells the crash states apart. A profile with no store of its
own only switches the key.

**The fence.** `memory_join_fences` (`storage/join_fence_model.py`) is a table
in the *source* company store: the join attempt's id, the company, the joining
profile's identities, the sha256 of the destination key (never the key), a
phase and the snapshot digest. Phases: `fenced` → `accepted` → `completed`,
or `fenced` → `released`; `accepted` → `released` only by the joining
profile's own recovery. A partial unique index admits one active (`fenced` or
`accepted`) fence per company. `mnemonic/fence.py` holds the reads, the phase
moves (compare-and-set under the source's write lock) and
`refuse_if_fenced`.

**What an active fence refuses.** Every journal writer runs
`refuse_if_fenced` inside its write transaction, after the write lock:
`open_operation` (creating or reopening a row), `claim`, `spend_allowance`,
`record_attempt`, `receipt` (so `record_result`, `_settle`, `_settle_parent`
and the commit's own receipt), `manifest.record_manifest` and
`references._record_remaining`. While a company is fenced, no account's
semantic write or journal write lands in it, the joining account's included;
a terminal row still replays. The refusal, `CompanyFenced` ("company memory is
being joined"), is a `JournalError`: `submit` answers `retryable_failure` and
the row keeps its state and allowance. It is not a failure of the item:
preparation's `bounded_item` finishes the item as refused whether or not it had
already paid, ends the run with the fence as its stop reason and suspends
nothing; a fenced dispatch gives its budget reservation back; consolidation
answers skipped (or, met mid-run, stopped), which the Settings button and
`zylch memory-sweep` read as a rest. The owner's `/memory delete`, `/memory reset`,
`memory.restore_version` and retention pruning are not semantic writers and
are not fenced; the import holds the source's write lock and re-checks its
snapshot, so they cannot slip between the snapshot and the acceptance.
`memory.status` reports `joining` and `joining_reason` for an active fence on
the bound company, never the destination.

**The binding check.** The same check refuses a write to a company the
profile's `.env` on disk no longer names as `MEMORY_KEY`: a second process of
the joining profile (a Desktop engine beside a CLI join, or the reverse) still
holding the old key in its environment. It answers "this profile has joined
another company memory; restart the engine", retryable, no failure counted.
The `.env` is cached on its inode, `st_mtime_ns` and size. A process with no
active profile, or whose `.env` names no key, is not checked. Nothing is keyed
to an identity: a fresh profile of the same account, or the same profile
joining back, names the company again and writes normally.

**Drain, then evaluate under the fence.** `zylch memory-join --drain` first
runs one ordinary memory pass of this profile inside a preparation run — it
resumes pending children, lands the checkpoints of settled sources and replays
recorded task-reference follow-ups, and costs what one pass costs; a paused or
busy preparation refuses the join with its own reason and pays nothing.
`memory.join` never drains. Then the fence is placed and this profile's rows
in the source journal (either identity) are read under it. The cutover is
refused, the fence released and the `.env` left untouched when any of these
holds: a row `pending` or `failed`; a row in `review`; a `committed` or
`skipped` ingestion parent whose source row in this profile has no
`memory_processed_at`; a `committed` row with a pending effect. The answer
lists each blocking row with its `event_id`, `state`, `source_ref` and the
command that settles it (`--drain`, `zylch memory-reviews --retry` or
`--dismiss`). Other accounts' rows never block and stay in the source.

**The import** is one transaction per store, source under its write lock
first. It compares-and-sets the fence (this attempt, `fenced`, this
destination's digest) and hashes what it will copy — each blob's id and
`updated_at` and the restriction set. It copies only what the joining account
can see (`scope.blob_visible` for either identity): every company-family row
and that account's own rules, never another account's. Company-family
namespaces move to the destination key. Facts converge: the destination's
fact wins and the loser goes to `fact_history` under its own owner. A blob id
the destination already holds with other text keeps the destination's row and
sentences; the source's text is retained on it as a `join` version. Versions,
sentences, links, identifiers and aliases travel with their blob. Every copy
is keyed so a second import of the same source writes nothing twice: rows by
their own ids (`INSERT OR IGNORE`), a history row by the losing blob's id and
`updated_at` and the winner's id, a `join` version by the blob id and the
source's `updated_at`. Every restriction the source records against a copied
blob is written on the import's receipt (`join-<fence id>`, state
`committed`), so a restricted FACT is ineligible in the destination before
anything can read it; when the blob id already existed there, the restriction
therefore also hides the destination's own row. `merge_projects` runs
unchanged in the same destination transaction. The destination commits first,
then the fence moves to `accepted` with the digest: an acceptance never exists
without its import. An ordinary failure anywhere in the import releases the
fence and clears `MEMORY_JOIN_TO`.

**The key switch and the three crash states.** The `.env` carries what a
restart needs: `MEMORY_JOIN_TO=<destination>` once the evaluation passes; then
the import and acceptance; then one write of `MEMORY_KEY=<destination>`,
`MEMORY_KEY_SOURCE=join`, `MEMORY_JOIN_FROM=<source>`, `MEMORY_JOIN_TO=`; then
the in-process rebind; then the source fence `completed` and
`MEMORY_JOIN_FROM=` cleared. `join_recover.recover()` runs at every engine boot
once the store is attached, and a join runs its body first:

- *before the key* (`MEMORY_JOIN_TO` set): an `accepted` fence of this profile
  for that destination finishes the switch; a `fenced` one whose receipt is in
  the destination with a digest the source still matches is accepted without
  a second import; anything else releases the fence and clears the setting.
  A source that changed since the receipt refuses the switch visibly.
- *after the key* (`MEMORY_JOIN_FROM` set): the process is bound to the
  destination (a live process is rebound), the source fence becomes
  `completed`, the setting is cleared.
- *completed*: a `fenced` fence of this profile left by a crash before the
  evaluation is released.

One lock serialises a join and its recovery: the profile's join lock
(`<zylch.db>.join.lock`). Boot recovery takes it without waiting and does
nothing when another process holds it. A fence never expires by time.
`zylch memory-join --release-fence` releases a `fenced` fence on the bound
company for any profile bound to it (acceptance is a compare-and-set, so a
released fence is never accepted); an `accepted` one is finished only by its
own profile's recovery. "This profile's" fence is one whose recorded
identities meet the profile's: a second profile of the same account booting on
the same company can release a live join's `fenced` fence, and that join then
refuses at its compare-and-set, writing nothing.

## Resolving parked work: `zylch memory-reviews`

`mnemonic/reviews.py`, on the engine CLI only — no RPC method, so the
scheduled operator has no route to it:

- `zylch memory-reviews` lists this profile's rows (either identity) in the
  bound company in `review`, `failed` or `pending`, with parent, reason,
  restrictions and the actions each admits.
- `--dismiss <id>` settles any such row `skipped` ("dismissed by owner") and
  clears its `proposal_digest`, so a dismissed pair settles nothing for other
  accounts. A child's parent is re-aggregated in the same transaction by the
  rule ingestion uses (`ingestion.parent_settlement`); the next worker run
  replays the parent and lands the source's checkpoint without a paid call.
- `--retry <id>` reopens a `review` row the next submission can decide again:
  an ingestion parent reviewed before it had children (it extracts again,
  paid), a consolidation pair, a child whose parent kept its manifest. The row
  and its parent become `failed` with the allowance reset. A chat, CLI or RPC
  event, and a child whose parent's manifest was pruned, are refused: dismiss
  them.

A parent keeps its manifest while it is in `review` and prunes it when it
settles. `receipt` and `record_attempt` refuse a terminal row, so an attempt
still in flight cannot overwrite a dismissal. A restriction stays on its row
whatever the row becomes, and `eligibility.restricted_ids` reads restrictions
from rows in any state. Both resolutions are refused while a fence is active.
This settles the refusal reviews recorded by milestone 5–7 builds on
app-created profiles: a parent or a pair is retried, a chat event dismissed.

## Maintenance routes

- **`zylch memory-reindex-identifiers [--apply]`** (`memory/rebuilds.py`)
  indexes the exact `#IDENTIFIERS` entries of the PERSON and COMPANY rows this
  profile can see, parsed by the parser a commit uses, through
  `associations.add_identifiers`. Dry run by default.
- **The boot link rebuild** (`rebuilds.rebuild_source_links`, called from
  `storage/database._backfill_email_blobs_index`) rebuilds `email_blobs` /
  `calendar_blobs` from legacy `blob.events` descriptions once per profile; a
  calendar summary is linked only when exactly one of this profile's events
  carries it, and an ambiguous one is counted and left unlinked.
- Both rebuilds run inside a digest guard over `id`, `owner_id`, `namespace`,
  `company_key` and `content` of the company's blobs; a change rolls the
  transaction back (`RebuildTampered`).
- **`scripts/compact_learned_prefs.py --profile <uid> [--apply] [--llm]`**
  boots the profile through the engine and reads only its own `template:` /
  `prefs:` rows. `--apply` drops exact duplicates and strictly contained rules
  through `delete_blob(retain=True, reason="maintenance")` in one company
  transaction with one mutation-sequence bump; each dropped text is kept in
  `blob_versions`. An entity-shaped rule is reported as needing review and
  never moved; `--llm` only reports. Dry run by default.

## Schema

`storage/step_memory_operations_drop_approval.py` (memory-store step
`0002_memory_operations_drop_approval`, destructive, so the runner backs the
store up first) removes the inert `memory_operations.approval` column by a
table rebuild, guarded by `sqlite_master`; a second run and a partially
reverted store are no-ops. A store it migrated cannot be opened by a
milestone 5–7 build.

## Tests

`tests/memory/test_mnemonic_fence.py`, `test_mnemonic_fence_items.py`,
`test_mnemonic_reviews.py`, `test_mnemonic_reviews_known_issue.py`,
`test_mnemonic_reviews_cli.py`, `test_mnemonic_join_cutover.py`,
`test_mnemonic_join_crashes.py`, `test_mnemonic_join_guards.py`,
`test_join.py`, `test_mnemonic_maintenance.py`,
`tests/storage/test_memory_operations_drop_approval.py`. Each guard named here
has a mutation that fails a named test.
