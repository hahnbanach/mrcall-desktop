---
description: |
  Entity-centric memory: everything about an entity stored in a single natural-language blob.
  New info triggers reconsolidation (update, not duplicate). Hybrid search: SQLite text LIKE +
  fastembed cosine similarity (384-dim, numpy). No pgvector, no HNSW — in-memory brute-force.
---

# Entity-Centric Memory System

## Overview

The Memory System stores persistent, entity-centric knowledge for AI agents with semantic search and memory reconsolidation. Unlike traditional databases, it **updates existing memories** when new information arrives, preventing fragmentation.

Everything about an entity is in a single natural-language "blob" — no structured fields, no categories. Properties live in free-form text.

**The thesis**: Professional relationships exist in language. LLMs don't need physics — they need memory. This system provides persistent memory that accumulates relational understanding over time.

## Scope: one memory per company

Memory belongs to the company, not to the account that read the mail. A
profile's `MEMORY_KEY` selects the store, `~/.zylch/memory/<MEMORY_KEY>.db`,
and every profile on the host holding that key shares it. Inside the store
the namespace family decides who sees a row:

| Family | Namespace | Visible to | Holds |
|--------|-----------|------------|-------|
| `user` | `user:<key>` | every key holder | PERSON / COMPANY entities |
| `facts` | `facts:<key>` | every key holder | company facts, one row per (category, key) |
| `template` | `template:<owner>` | its owner only | the account's reply templates |
| `prefs` | `prefs:<owner>` | its owner only | the account's operating rules |

`owner_id` stays on every row as provenance — which account contributed
it — and decides nothing for the company families. One predicate,
`zylch/memory/scope.py:blob_visible(owner_id, company_key)`, is applied on
every read, write, update, delete and list; no call site filters on
`owner_id` alone. Sentences, link tables and `person_identifiers` are
scoped by the company key; an identifier is unique per
`(company_key, kind, value, blob_id)`.

Joining (`memory.join`, `zylch memory-join`, the Settings card) imports
what the profile can see of its current store into the target key's store,
as a fenced, crash-safe cutover: entities are all kept and consolidation
folds afterwards the duplicates whose headers prove one subject, facts
converge to one row per key with the losing value in `fact_history`, the
joining account's rules keep their owner and another account's stay behind,
versions and restrictions travel with their rows. A join is refused while the
account's own memory work in the current company is unsettled, and names what
settles each operation. The old store file stays on disk. Contract:
[company-memory-join.md](company-memory-join.md).
Several daemons write one store: updates compare-and-swap on `updated_at`,
the in-process vector index is keyed on the store's `mutation_seq`, and
consolidation runs after each update only when the store changed since the
last sweep started, once per company (`<store>.sweep.lock`).

## The semantic write path

Memory is changed through one semantic writer, the **mnemonic harness**
(the direct `store_blob` and `update_blob` left production with milestone 8
and live only in the test seeding module): a caller submits an observation, a
bounded role decides what the memory should become, and a small validator
rejects unsupported decisions. One transaction on the company store writes the
blob, its sentences, its identifier index, its source link, the mutation
sequence and an operation receipt together. Which callers are converted is
[mnemonic-writer-inventory.md](mnemonic-writer-inventory.md); the decision
contract is [mnemonic-decisions.md](mnemonic-decisions.md) and the commit
contract [mnemonic-commit.md](mnemonic-commit.md).
The old `store_blob` and `update_blob` methods remain defined in
`blob_storage.py` but have no production callers. Join, migrations and repair
scripts still have their separate direct paths.

### The installed-client journey (milestone 9)

The write path above is exercised end to end by the *installed* kernel: the
real `cs` entry point of a `cs-kernel` installed in its own interpreter, the
real `rpc.chat` / `EngineClient` over a real WebSocket served by the engine's
own connection handler (`server_ws._handle_connection`), `dispatch_raw`, the
real adapters, harness, journal and stores, two accounts on one company key
with real profile and company SQLite files, the real `LLMClient` and
reservation ledger. Only the provider transport and the bearer token are
fixture-controlled. Every case asserts the committed content, the retained
versions, the namespaces, the operation row's state and `departure`, read
visibility from each account (the tools' scoped read-back,
`search_local_memory`, `get_facts_by_category`, hybrid search) and that no
unrelated blob, version or operation row moved. What it does **not** prove:
Firebase verification is not in the loop — the handler asserts a fixture
bearer and sets the claims itself, so nothing in it is a claim about the
production `server_ws` handshake — nor anything about a deployed host.

The seventeen cases: (1) `cs memory` dispatches nothing; (2) `cs ask` refuses
every memory-writing verb and "remember that" with zero rows, zero
reservations and no agent, while a search still answers; (3) `cs chat
--allow` commits the Acme forwarding correction as one `operator_delegated`
UPDATE with both numbers retained and the preparation ledger untouched;
(4) global hours commit a company FACT the second account reads; (5) an
account rule commits a STYLE the second account cannot see; (6) a task-solve
correction through `cs rpc tasks.solve` with the typed instruction as
observation; (7) a changed final proposal recorded as `departure.changed_action`
on both sides; (8) a tool outside `--allow` is declined, nothing written;
(9) a dropped socket during a held role decision revokes the grant and commits
nothing; (10) the second account finds the entity and the FACT, not the STYLE;
(11) a correction under a paused preparation commits and the pause survives;
(12) an automatic event outside an admitted item is refused before any
reservation; (13) a review-restricted legacy FACT is absent from reads while a
valid one stays; (14) one mail source through `preparation.resume` and then
the `memory_process` job: one parent, the same children, one checkpoint;
(15) a crash between two children in a second process, the resume deciding
only the non-terminal child with one payment each; (16) a join refused with
`blocking`, settled by a dismiss and a drain, then cut over with the fence
completed; (17) a consolidation MERGE whose deferred references land on the
committing profile's ledger only.

Files: `tests/rpc/kernel_journey_env.py` (the server, the kernel bootstrap,
the profiles, the transports, the unrelated-memory digest),
`test_mnemonic_kernel_journey.py` / `_b.py` (cases 1–10) and
`test_mnemonic_engine_journey.py` / `_b.py` (cases 11–17). Locally, from
`engine/`, with a kernel installed in any interpreter:

```bash
CS_PROJECT_KERNEL_PYTHON=/path/to/kernel-venv/bin/python \
  python -m pytest tests/rpc/test_mnemonic_kernel_journey.py tests/rpc/test_mnemonic_kernel_journey_b.py \
    tests/rpc/test_mnemonic_engine_journey.py tests/rpc/test_mnemonic_engine_journey_b.py
```

Without the variable the four files skip; with `MNEMONIC_JOURNEY_REQUIRED=1`
a missing kernel is an error. CI runs them in
`.github/workflows/mnemonic-journey.yml` on every push or pull request that
touches `engine/`: it checks out `malemi/cs-kernel` at the commit pinned in
the file (`KERNEL_REF`, `ba79cc1` today), installs it in its own venv, links
it as the sibling `../cs-kernel` the audit resolves, sets both variables and
also runs `test_project_kernel_journey.py`, `test_memory_readonly.py` and
`test_mnemonic_kernel_inventory.py`; the pytest log is uploaded on failure. A
kernel change turns this evidence red or green only through a reviewed bump
of that one line. The priced corpus of the same milestone is the opt-in
`tests/memory/test_mnemonic_corpus_live.py`, described under
[bounded preparation](bounded-preparation.md#the-priced-corpus-inside-one-explicit-run)
and [spending protection](daily-llm-budget.md#the-corpus-runners-second-bound).

## Key Concepts

### Hybrid Search

Blobs contain free-form text, so pure vector search dilutes the signal. Solution: combine text matching with semantic similarity.

| Query Pattern | Strategy | Rationale |
|---------------|----------|-----------|
| Named entity ("John Smith") | Text LIKE weighted higher | Exact match critical |
| Conceptual ("communication style") | Semantic weighted higher | Meaning matters more |
| Mixed ("John's email preferences") | Balanced | Both signals useful |

**Implementation** (standalone):
- **Text search**: SQLite LIKE queries on blob content
- **Semantic search**: fastembed (ONNX, 384-dim) embeddings stored as BLOB in SQLite, loaded into numpy arrays, cosine similarity computed in-memory
- **No pgvector, no HNSW**: brute-force cosine similarity via numpy (fast enough for single-user scale)

### Entity Types

**PERSON**: Individual contact information
- `#IDENTIFIERS`: Name, email, phone
- `#ABOUT`: Role, company, relationship
- `#HISTORY`: Interaction timeline

**COMPANY**: Organization information
- `#IDENTIFIERS`: Name, domain
- `#ABOUT`: Industry, services
- `#HISTORY`: Business interactions

**TEMPLATE**: Reusable response pattern — how the user typically responds to recurring inquiry types. Enables the assistant to draft similar responses for new inquiries.

## Reconsolidation Flow

```
New info arrives (an ingested source, a chat or solve correction)
     │
     ▼
Candidates: identity-index matches + hybrid search (text LIKE + cosine), at most 3
     │
     ▼
The mnemonic role decides; the validator checks the identity evidence
     │
     ├── proven same subject ──► UPDATE it: one transaction, sentences re-embedded
     ├── new subject ────────► CREATE a new blob + embed sentences
     └── unsupported or uncertain ──► SKIP or REVIEW without a write
```

### Consolidation

Duplicates that ingestion still creates — a calendar-born person beside its
mail-born twin, two blobs a join brought together — are folded by
consolidation (`zylch/memory/consolidation.py`), the only ordinary semantic
operation that merges and removes duplicate memory. It runs from the Settings
button (`memory.reconsolidate_now`),
`zylch memory-sweep` and after every update. Each run replays this account's
pending task-reference follow-ups, applies the version-retention policy and
reports the sinks, then clusters the entity family by shared identity-index
rows and the stated `Name:` (`zylch/memory/clusters.py`). Each pair is decided
by the mnemonic role and committed as one MERGE through the harness, which
keeps the replaced and the dropped text as versions
([a merge](mnemonic-commit.md#a-merge), [retention](mnemonic-commit.md#retention),
[consolidation pairs](mnemonic-decisions.md#consolidation-pairs)).

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MEMORY_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | FastEmbed model (ONNX) |
| `MEMORY_EMBEDDING_DIM` | 384 | Vector size |

`MemoryConfig` still declares `MEMORY_RECONSOLIDATION_THRESHOLD`, but the
current consolidation path does not use it to decide a MERGE. The mnemonic
role and validator control that decision.

## Files

| File | Purpose |
|------|---------|
| `zylch/memory/company_key.py` | `MEMORY_KEY` mint/validate, namespace families |
| `zylch/memory/scope.py` | `blob_visible` and the other scope predicates |
| `zylch/memory/store.py` | The per-company store file, `memory_meta`, sweep gating |
| `zylch/memory/join.py` | Joining a company memory: drain, fence, evaluation, key switch, rebind |
| `zylch/memory/join_import.py` | The join import: one mechanical transaction per store, idempotent by row |
| `zylch/memory/join_recover.py` | The join's crash states, told apart at boot and at every join |
| `zylch/memory/rebuilds.py` | The identifier reindex and the source-link rebuild, inside a digest guard |
| `zylch/memory/blob_storage.py` | Blob CRUD (embeddings as BLOB in SQLite), compare-and-swap updates |
| `zylch/memory/blob_commits.py` | The permit-guarded `semantic_create` / `semantic_update` / `semantic_merge` |
| `zylch/memory/blob_versions.py` | Retained versions, the restore, the retention policy and the sink report |
| `zylch/memory/consolidation.py` | Consolidation, the one removing operation, and its summary |
| `zylch/memory/clusters.py` | The entity family clustered by identity, sinks and restricted rows left out |
| `zylch/memory/commit_permit.py` | The single-use authority for one semantic write |
| `zylch/memory/associations.py` | Identifier, source-link and alias writes, inside the caller's transaction |
| `zylch/memory/mnemonic/` | The semantic write boundary: events, role, validator, admission, journal, commit |
| `zylch/memory/embeddings.py` | fastembed wrapper (ONNX, 384-dim) |
| `zylch/memory/hybrid_search.py` | InMemoryVectorIndex + text search |
| `zylch/memory/llm_merge.py` | The merge-routed client consolidation decides pairs with, and the merge-gate canary |
| `zylch/memory/text_processing.py` | Sentence splitting, text normalization |
| `zylch/memory/pattern_detection.py` | Pattern extraction |
| `zylch/memory/config.py` | Memory configuration |
