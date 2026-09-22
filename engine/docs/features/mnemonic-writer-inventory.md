# Mnemonic writer inventory

This is the Milestone 0 freeze for the mnemonic harness plan. It describes the
current production write graph; it does not claim that the single-writer seam
exists yet. The executable source of truth is
`tests/fixtures/mnemonic/legacy_writer_inventory.json`, checked by
`tests/memory/test_mnemonic_inventory.py` and
`tests/memory/test_mnemonic_kernel_inventory.py`. Every temporary entry names
the milestone that must remove or constrain it. Adding a direct writer without
updating that reviewed inventory fails the test.

## Current call graph

```mermaid
flowchart LR
    K[cs ask / cs chat / raw RPC] --> C[chat and command dispatch]
    C --> I[interactive tools and task solve]
    C --> H[slash memory handlers]
    A[mail / WhatsApp / calendar / MrCall] --> W[MemoryWorker]
    A --> J[JobExecutor sync facades]
    E[approved edits] --> L[correction learning]
    I --> P[prefs_store]
    H --> B[BlobStorage]
    I --> B
    W --> F[facts_store]
    W --> B
    J --> B
    L --> P
    L --> F
    P --> B
    F --> B
    R[reconsolidation] --> B
    R --> X[references, identifiers and aliases]
    B --> T[blobs and blob_sentences]
    W --> X
    J --> X
    O[join, migrations and repair scripts] --> T
    O --> X
```

The graph has both asynchronous and synchronous semantic loops. The automatic
`MemoryWorker` path is async, while the job executor repeats entity decisions
in synchronous helpers. Calendar and MrCall each have their own variants in
both paths. Interactive `create_memory`, `update_memory`, slash memory storage
and task solve also reach persistence independently. Correction learning can
write through both `prefs_store.store_rule` and `facts_store.upsert_fact`.

`BlobStorage.store_blob` and `update_blob` are the common low-level blob
writers, but they are not yet capability protected. Associations and identity
meaning can also change through `Storage.add_*_blob_link`,
`add_person_identifiers`, `migrate_blob_references` and the reconsolidation
alias writer. Join, company-key/split/identifier migrations and three repair
scripts contain direct SQL or fixed ORM writes outside those methods. The
manifest distinguishes these mechanical or migration candidates from runtime
semantic adapters so Milestone 8 can review each one rather than granting a
general offline exemption.

## Finite legacy allowlist

The JSON inventory freezes six independently scanned sets:

- calls to semantic writer helpers, including nested aliases and their exact
  enclosing symbol, count, execution mode and owning milestone;
- direct ORM construction of blob, sentence, association, identifier and alias
  rows;
- ORM `update`/`delete` operations on those models;
- direct assignments to a queried or constructed ORM row, independent of the
  local variable name (the current four are `Blob.content`, `embedding`,
  `events` and `updated_at` in `BlobStorage.update_blob`); `setattr` on a bound
  row, imported model aliases and inline query-result assignments are treated
  as the same write;
- SQLAlchemy Core `insert`/`update`/`delete` operations on tracked models,
  including the two `MemoryMeta` lock/mutation-sequence updates;
- literal `INSERT`, `UPDATE` and `DELETE` statements against mnemonic tables.

`memory_meta` is included because the eventual commit must carry the mutation
sequence atomically. Its fixed seed, self-notion, sweep and join writes are now
listed alongside blob sinks rather than hidden as coordination detail.

Six fixed dynamic-SQL implementations are recorded separately because a plain
literal matcher cannot represent their table construction honestly. They cover
the join helper's association/index/alias copies, company-key stamping, the
identifier-table rebuild, and the memory split's forward copy, profile-table
drop and rollback restore. Every one is bounded to an explicit table tuple and
belongs to Milestone 8 review; there is no generic offline-write exemption.

Two aliases are explicit beyond the plan's grouped table:
`handle_reset._reset_all_data` reaches
`BlobStorage.delete_all_blobs`, and
`Storage.delete_whatsapp_message_by_message_id` directly deletes semantic
association rows while enforcing source retention. The first belongs to the
Milestone 1 reset gate; the second is a fixed deletion/retention path for
Milestone 8 review.

The ownership sequence is:

| Milestone | Temporary owners |
|---|---|
| 1 | mutation authorization before slash/reset routing and kernel request policy |
| 3 | guarded `BlobStorage` commit primitives and transaction-scoped sinks |
| 4 | interactive create/update and task-solve adapters |
| 5 | facts, rules, correction learning and memory command writers |
| 6 | async workers, synchronous job facades, associations and identifiers |
| 7 | reconsolidation, reference migration, donor deletion and aliases |
| 8 | join, storage migrations, backfills and semantic repair scripts |

## Kernel and permission edges

`cs-kernel` has no memory persistence and remains an RPC client. Its current
edges are nevertheless part of the freeze:

- `cmd_ask` calls `rpc.chat` with an empty tool allowlist. That controls pending
  tool approvals but is not a server-enforced read-only request policy.
- `cmd_chat` accepts caller-selected tool names; `rpc.chat` approves pending
  calls by matching those names.
- `cmd_draft_reply` also passes an empty allowlist but intentionally creates an
  engine draft, while `cmd_draft_send` permits only `send_draft` through an
  exact-input predicate. The executable inventory keeps both callers visible
  so Milestone 1 cannot infer read-only meaning from an empty set alone.
- `rpc.chat` currently normalizes missing permissions with `allow_tools or
  set()`, sends `chat.send`, observes `chat.pending_approval`, and answers via
  `chat.approve`; the method names and payload keys are frozen by AST.
- the scheduled/headless `cmd_catchup` path calls `sync.run` followed by
  `update.run`, so the paid memory/task pipeline remains an explicit effect.
- the scheduled template broadly allows `cs rpc`; the cron deny set includes
  raw `rpc chat`, but does not enumerate all memory, update, reconsolidation,
  join/reset and preparation-resume RPC effects identified by the plan.

The template audit counts every current spelling for `cs memory`, `catchup
--check`, `ask`, `draft-reply`, broad `rpc`, and the cron denials for
`draft-send`, `chat` and `rpc chat`. It also verifies that the engine really
registers `update.run`, `memory.reconsolidate_now`, `memory.join` and
`preparation.resume`, while recording that none has an explicit raw-RPC cron
denial today. The normalized chat-effect inventory covers memory store/force,
delete/reset, agent memory run/process, jobs resume, update and hard reset;
each entry is tied to its current slash-command route and engine handler.

Those are audit findings for Milestone 1 and later approval binding. Milestone
0 intentionally does not change routing or permissions.

## Behavioral fixtures

`tests/fixtures/mnemonic/incidents.json` is the bounded semantic corpus. Each
case retains the original observation separately from hints and candidates and
states semantic invariants rather than formatter text. It covers unrelated
same-name people, a shared switchboard, corroborated identity, customer number
and price corrections, company hours, account feedback, planned work,
contradictory legacy representations, malformed/truncated output and a
multi-entity source with stable child keys.

`current_behavior.json` and `test_mnemonic_fixtures.py` capture the starting
storage behavior with actual temporary profile and company SQLite databases:
company entities and FACTs are visible across owners sharing the key, account
rules are private, a known customer-shaped legacy FACT is still returned by an
ordinary category read, and the email memory checkpoint is owner-scoped but
source-grained. Later milestones must change an expectation only alongside the
corresponding production boundary.
