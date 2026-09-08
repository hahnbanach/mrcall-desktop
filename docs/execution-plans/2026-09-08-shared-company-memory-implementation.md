---
status: completed
---

# Shared company memory — milestone plan (mrcall-desktop)

<!-- doc-scope:start -->
Scope: the execution plan for the shared-company-memory workstream in this repo —
milestones, dependencies, atomicity, verification and rollback. Intent, acceptance
criteria and design decisions live in the paired brief
[`../briefs/2026-09-08-shared-company-memory-implementation.md`](../briefs/2026-09-08-shared-company-memory-implementation.md);
the binding product decision is `~/hb/docs/briefs/2026-09-05-shared-company-memory.md`.
<!-- doc-scope:end -->

## Delivered — 2026-09-08

All four milestones are implemented on `main`, **committed locally, not pushed,
not deployed** (a push is a deploy here, via the reconcile timer):

| Milestone | Commit | Gate |
|---|---|---|
| M0 runner | `efac9e7` | 9 tests incl. two-process races; full suite 853/2 |
| M1 key, scope, namespaces, family filters | `cb3bef8` | 17 tests; full suite 870/2; typecheck |
| M2 store split, provenance, join, CAS, sweep owner | `0131627` | 47 tests incl. two-process CAS/boot/index; full suite 892/2 |
| M3 app UX | `638e721` | typecheck; `test:onboarding` PASS; full suite 892/2 |

Not done, deliberately, and what each needs:

- **Deploy** to the five `zylch-server@` units — Mario's go. First boot on each
  runs `0001_company_key` (mints, backs up `zylch.db`) and `0002_memory_split`
  (moves the six tables into `~/.zylch/memory/<key>.db`).
- **The host company map** (`PROVISIOND_COMPANY_MAP`, default
  `/etc/mrcalld/company-map.json`, a JSON object of `"<uid>": "<MEMORY_KEY>"`
  pairs) — an operator action; until it exists provisiond refuses every new
  profile (403, fail closed). The five live profiles predate provisiond and are
  not affected.
- **Converging the live profiles** onto per-company keys through the Settings
  join, one at a time, after deploy; `HxiZhWEB` still has no company assigned.
- **A dev-app run** of the onboarding memory step and the Settings card against
  two local profiles — no display on this machine; `typecheck` and the
  onboarding script are what ran. The packaged-app provision check is post-go.

## What this plan executes

The brief, approved at its gate on 2026-09-08. Criteria are cited by number
(`C1`…`C20`, plus `C11b`) and never restated here; a milestone is done when its
criteria pass, not when its code is written.

Four milestones, strictly ordered: **M0 → M1 → M2 → M3**.

## Standing rules

- **Verification.** `engine/venv/bin/python -m pytest` for the named suites,
  `engine/venv/bin/ruff check zylch/` (green at HEAD, so a real signal), and
  `black --check` on the files the milestone changed. **Not `make lint`** — it runs
  `black --check zylch/` first and 29 files are already unformatted at HEAD, so the
  target fails before reaching ruff. `npm run typecheck` in `app/` for **any**
  milestone that touches `app/src` — that is M1 and M3, not M3 alone.
- **No push, no tag, no deploy, no daemon restart** without Mario's explicit go. On
  this repo a push to `origin/main` **is** a deploy: `zylch-reconcile.timer` pulls and
  restarts the units at 00:00 UTC (`engine/docs/active-context.md:13`). "No push" is
  therefore a hard wall, not caution.
- **Scope discipline.** `make format` is not run; the 29 pre-existing black diffs stay
  untouched so each milestone diff stays readable.
- **New engine surface.** Every new RPC must be declared in `zylch/rpc/param_spec.py`
  — `tests/rpc/test_contract_boundaries.py:59-62` asserts the registry matches — and
  documented in `docs/ipc-contract.md` "## Methods" (`:121`). Each milestone that adds
  an RPC owns both.
- **POSIX only.** The migration runner uses `fcntl`. The Windows build is opt-in and
  `continue-on-error` (`.github/workflows/release.yml:77-91`), and
  `services/settings_io.py:17` already imports `cli.profiles` (top-level `import
  fcntl`), so this adds no new platform regression — but the runner is POSIX-only and
  says so.

## Test infrastructure that does not exist yet

Named here so no milestone assumes it: `engine/tests/memory/` (memory tests live under
`tests/workers/` today); a deterministic `EmbeddingEngine` stub and the first test that
constructs `BlobStorage(` or `HybridSearchEngine(` at all; and a two-process harness
(only `tests/assistant/test_tool_offload_policy.py` uses `subprocess`). C2's search
half, C19, C9, C4 and C17 all depend on these. They are built by the milestone that
first needs them, and that is part of its cost.

---

## M0 — idempotent, single-owner migration runner

**Why first.** No migration mechanism exists: `create_all`
(`engine/zylch/storage/database.py:117`) plus a hardcoded ALTER list (`_apply_column_migrations`, `:130-244`),
re-run by every process at boot, with the `.sql` files under `engine/migrations/` and
`engine/zylch/migrations/` executed by nothing.

**Depends on** nothing. **Blocks** M1, M2, M3.

| # | Deliverable |
|---|---|
| M0.1 | `schema_version` table and an ordered, idempotent step registry. |
| M0.2 | **Single-owner execution keyed by the database file being migrated**, in its own lock file beside that file — *not* the per-profile lock. `zylch serve` already holds the profile flock for the life of the process (`cli/main.py:457` → `acquire_lock`), so the runner cannot take it: a second `flock` from a fresh fd conflicts with the process's own lock. |
| M0.3 | **The loser blocks, with a bound; it never skips.** An unbounded wait would hang every loser behind a hung winner, and `Restart=on-failure` never fires on a process that is merely waiting — so the wait is bounded and exits non-zero on expiry. |
| M0.3b | Why blocking rather than skipping: a daemon that skipped would keep booting and serve new code against a file the winner is still rewriting — `busy_timeout=30000` (`database.py:69`) waits on a blocked statement, not on a column nobody has added yet. The loser waits on the lock (no `LOCK_NB`) or polls `schema_version`, and serves only once the steps are recorded. |
| M0.4 | `create_all` (`database.py:117`) moves under the lock. It is the checkfirst TOCTOU this milestone exists to close; leaving it outside would defeat the runner. |
| M0.5 | Pre-migration backup. **Rule: every file a step writes to destructively — rewriting rows in place or dropping them — is backed up.** "Deletes from" would exempt M1, whose step rewrites namespaces and drops nothing, and M1 is the step whose reverse this backup exists to underwrite. For M1 that is the profile `zylch.db`; for M2 it is *also* `zylch.db` — M2's step reads and drops from it and *creates* the company store, so the company store has nothing to back up on first creation and the profile DB is the file whose loss is unrecoverable. **Mechanism: `sqlite3.Connection.backup()` or `VACUUM INTO`, never a raw file copy** — under WAL (`database.py:64`) the `-wal` pages are not in the main file, so a copy is not a backup. |
| M0.5b | One restore is exercised in the M0 suite, so "last resort" is a tested path rather than an assumption. |
| M0.6 | The boot-time data backfills move under the same lock — `_apply_data_backfills` (`database.py:245`) dispatching `:266`, `:338`, `:442`; surface `:245-476`. |
| M0.7 | The existing hardcoded ALTER list becomes the runner's first steps. |

**Verification.** `C9`, on a profile DB. Two engines booting simultaneously: exactly
one migrates, **and the loser does not serve until the steps are recorded** — assert
both, not only the first. New suite `engine/tests/storage/test_migration_runner.py`,
which builds the two-process harness. Existing `tests/storage/` stays green: same
schema out, different mechanism.

**Rollback.** `git revert`. The only schema change is additive — `schema_version`, which
reverted code ignores — so there is nothing to reverse.

**Risk.** Touches the boot path of every profile. Ships behaviour-identical.

---

## M1 — the key, per-family scope, namespace rewrite, family filters

**Depends on** M0. **Blocks** M2.

Semantically a no-op: one owner, one key, one file. The walls get built and tested with
no cross-profile blast radius; M2 makes them load-bearing.

| # | Deliverable |
|---|---|
| M1.1 | `MEMORY_KEY` in the **engine** schema (`services/settings_schema.py`), `secret: true`, **plus a one-line exclusion in `views/Settings.tsx`**. Without it the generic view renders the key as exactly what the brief forbids: `:66` loads `settings.schema`, `:85-93` groups every field, `:265` renders each as a masked editable `FieldRow`, and no exclusion set exists. From M1 to M3 that field would accept a typed key with no shape check and, post-M2, no existence check. Onboarding is unaffected (`Onboarding.tsx:231` restricts groups). The three app **mirrors** (`lib/profileSchema.ts`, `main/profileFS.ts:34`, and the exclusions at `main/index.ts:1379` / `provisionClient.ts:169`) move to M3.1 with the field that needs them. |
| M1.2 | Mint-and-validate RPC pair (shape only; existence is M2's, `C12`). **Mint runs before the migration step, inside the same boot.** `init_db()` runs inside `Storage.__init__` (`storage/storage.py:323`), before any RPC exists, so a mint living in the RPC layer lets the M1 step record itself done with no key — on all five daemons at once, since all have `MEMORY_KEY` unset. Either the step mints, or mint precedes the runner. |
| M1.3 | `company_key` column on all six memory tables, `blob_sentences` included. |
| M1.4 | Namespace constructors emit `user:<company_key>` / `facts:<company_key>`; rule families keep `template:<owner_id>` / `prefs:<owner_id>`. Fourteen sites. |
| M1.5 | The LLM-supplied namespace passthrough (`tools/create_memory_tool.py:131-134`): refuse or re-scope, never verbatim, never flattening a rule family, refusing an unrecognised family (`C15`). |
| M1.6 | Existing rows rewritten to key scope, and `company_key` **backfilled on all six tables including the rule families** — after M1.7 those are key AND owner, so a null key hides every existing rule (`C20`). |
| M1.7 | The owner→key predicate conversion on company families: ~16 sites on `Blob`/`BlobSentence`, ~28 with index tables, including all four owner-filtered SQL queries inside one `search()` (`memory/hybrid_search.py:172`, `:204`, `:287-290`, `:448-449`) plus the cache identity at `:167`. |
| M1.8 | A family filter on all nine family-blind paths. `/memory reset` (`services/command_handlers.py:649-654` → `memory/blob_storage.py:212-222`) is the one whose failure destroys rather than leaks. |
| M1.9 | Write scope moves with read scope: `update_blob` (`blob_storage.py:117`), the ignored return at `workers/memory.py:638-650`, `facts_store.py:145-152`. |

**Atomicity.** One commit: **M1.2 + M1.3 + M1.4 + M1.6 + M1.7 + M1.9**, with **M1.5 no
earlier than M1.4**. Constructors without the row rewrite re-split the store on the next
write; the rewrite without the predicate conversion makes every company-family read
miss; read scope without write scope loses knowledge silently (`C3`); M1.6 without M1.2
runs the migration step with no key on any database it meets, and without M1.3 there is
no column to write; and M1.5 ahead of M1.4 re-scopes model-supplied namespaces to
`user:<company_key>` while the constructors still emit `user:<owner_id>`, so
LLM-created memories land where nothing reads. M1.1's engine declaration and its
Settings exclusion are a separate single commit — the exclusion is what keeps the field
from being editable.

**Verification.** `C2`, `C3`, `C7`, `C11`, `C11b`, `C15`, `C19`, `C20`. The migration
test **starts from a profile with `MEMORY_KEY` unset**, which is the state all five
daemons are in; a fixture that pre-sets it never exercises M1.2. `C11b` is proven by
*running* `/memory reset`. `C2`'s search half and `C19` need the embedding stub.
`npm run typecheck` for the Settings exclusion.

**Rollback.** `git revert` alone is **not** sufficient: it leaves rows at
`user:<company_key>` under code querying `user:<owner_id>` (`facts_store.py:66-76`) —
memory silently empty. The reverse is the rollback, and decision 7's retained
`owner_id` makes it exact. Two conditions the inversion needs, neither optional:

- **`company_key` is nullable or defaulted.** Reverted code does not set it, and a
  `NOT NULL` column would fail every insert made while rolled back.
- **The reverse un-records the M1 step, and the forward step is idempotent over a
  partially-reverted database.** Otherwise rows written during the rollback window —
  namespace `user:<owner_id>`, empty key — are never rewritten on re-upgrade, because
  the step is already recorded, and they are invisible to every key-scoped read.

`forward → reverse → forward converges` belongs in the runner's suite, for M1's step
and M2's alike. The M0 backup is the last resort, and restoring it rewinds mail, tasks,
drafts, OAuth tokens and sync cursors to the migration moment — on a live mailbox that
loses everything learned since.

---

## M2 — the memory DB split, and the five cross-file references

**Depends on** M1. **Blocks** M3.

| # | Deliverable |
|---|---|
| M2.1 | Memory tables move to one DB per company: `blobs`, `blob_sentences`, `email_blobs`, `calendar_blobs`, `whatsapp_blobs`, `person_identifiers`. **The seam is the session factory in `storage/database.py` gaining per-model binds — a new mechanism, to be built.** It is not "nine `BlobStorage(` sites": those six models are referenced at 111 sites outside `BlobStorage`/`HybridSearchEngine`/`models.py` (75 in `storage/storage.py`), 27 of them direct `session.query(…)` entry points, plus 8 `HybridSearchEngine(` construction sites on the same global factory. Re-pointing only `BlobStorage` would leave search, the identifier index, the sweep and the backfill reading an empty profile table. What makes per-model binds work: **no ORM `.join(` crosses the boundary** — every access is single-table (verified by grep). `MEMORY_DB_PATH` (`memory/config.py:12`) is docstring only today. |
| M2.1b | Two transactions stop being atomic and must be stated as such, not discovered: `_reset_all_data` deletes across both files in one session (`services/command_handlers.py:3161-3172`) and `migrate_blob_references` spans them (`storage/storage.py:1214-1428`, M2.7). Each needs a defined partial-failure outcome. `create_all` also runs per engine, so M0.4's lock covers two files — and each call must
pass an explicit `tables=` list, because a shared `MetaData` would otherwise create all
tables in both files and the mis-binding would be silent rather than an error. |
| M2.1c | **The export step is crash-atomic and idempotent, because SQLite cannot make it atomic for us.** `journal_mode=WAL` is live (`storage/database.py:64`) and a transaction spanning two files is not atomic under it: a crash between "copy into the company store" and "drop from `zylch.db` + record the step" leaves the step unrecorded, and the re-run collides on the UUID primary keys (`storage/models.py:190-193`) — failing every boot until `StartLimitBurst` kills the unit. So: copy-if-absent by primary key, then drop **and** record in one `zylch.db` transaction, last. M2.1 **drops** the six tables from `zylch.db` rather than leaving frozen copies; the rollback below assumes that. |
| M2.2 | The five cross-file references: the three association tables (`storage/models.py:241,259,277`), `person_identifiers` (`:315`, uniqueness at `:334` becomes key-unique), and `task_items.sources.blobs`. |
| M2.3 | Store creation by provenance (brief decision 11). On a headless daemon "refuse" means memory disabled and reported over RPC — never a unit failure, since those units also carry mail sync. Memory-disabled mode needs a defined bind target — the memory models point at no engine
and every memory call answers the disabled report rather than raising. M2.3 names the
method that reports it: a new one enters `param_spec.py` and `ipc-contract.md` under the standing rule, and a new field on an existing method changes that method's contract entry instead. |
| M2.4 | **Write serialization by compare-and-swap, not by a long transaction.** The cycle is `get_blob` (`workers/memory.py:575`) → `llm_merge.merge` (`:629`, an LLM call taking seconds) → `update_blob` (`:638`). `BEGIN IMMEDIATE` around the whole cycle would hold the company write lock across that LLM call for every one of N daemons; around the write alone it serializes nothing and `C4`'s lost update survives. So: re-read under the write transaction and compare `updated_at` against the value read at `:575`, re-merging a bounded number of times on mismatch. `busy_timeout` (`storage/database.py:69`) is a retry budget, not serialization. Requires pysqlite's `isolation_level=None` plus an explicit `begin` event listener — SQLAlchemy's default emits no `BEGIN` where this needs one. |
| M2.5 | Vector-index invalidation: wire `on_mutation` (`memory/blob_storage.py:25-35`) to `invalidate_cache()` (`memory/hybrid_search.py:161`). Cross-process needs a mechanism, not just the wiring — a mutation counter in the company store that `_ensure_index` compares against its cached value, so a writer in one daemon invalidates the index in the others. M2.5 names it. |
| M2.6a | **A `memory.join` RPC that is the only write path for `MEMORY_KEY` from M2 on.** The gesture M3.4 copies does not exist in a usable form: Settings "apply" saves through `settings.update` then `sidecar.restart()` (`app/src/renderer/src/views/Settings.tsx:142-160`), which for a local profile boots on the new key and **orphans the old store with no merge** — `C5` fails in the real flow even if it passes in tests — and for a remote daemon returns `false` (`app/src/main/index.ts:697-699`) so the engine keeps its old bind entirely. The RPC owns the whole gesture in-process: merge, write the key, rebind the session factory, dispose the old engine, invalidate the index. The old store
is **left on disk, not deleted**, once its rows are merged into the joined one: it is
the only copy of the pre-join state and M2's rollback reads it. `settings.update` refuses `MEMORY_KEY` from M2 onward (`rpc/methods.py:2144-2186`). The post-M3 convergence of the five live daemons over `wss://` depends on this rebind — a restart is not available to them. |
| M2.6 | Join-preview/echo RPC and the merge: facts converge one row per key, the losing value retained as history in a named column or table — **and that history records the losing row's `owner_id`**, without which the rollback below cannot return merged rows to the profile they came from. |
| M2.7 | The sweep gets an owner. Its `migrate_blob_references` (`storage/storage.py:1214`) carries nine owner predicates (`:1273,1283,1308,1318,1341,1351,1374,1384,1409`) that widen with the rest — `C6` depends on it. The order **migrate references → update
the survivor → delete the duplicate last** is the invariant that keeps a crash mid-sweep
recoverable; pin it as such rather than leaving it as how the code happens to run. |
| M2.8 | The boot backfill becomes a two-session join (`database.py:353,371,383`). |
| M2.9 | **The company self-notion's home and write path.** The product brief puts it in "the shared memory's configuration", so: a row in the company store, read by the trainer at prompt build time (`agents/trainers/memory_message.py:106-111,166`). Seeded **at store creation, by whichever of decision 11's three vouched paths creates it** — not "at mint", which covers only path (a): under path (b) the mint already happened at M1 with no store to seed, and under path (c) there is no minting profile at all. Value source, in order: the creating profile's `USER_COMPANY` if set, else the trainer's inferred notion, else NULL — never the empty string, so "nobody set it" and "someone set it to nothing"
stay distinguishable — echoed to a joiner as unset. `C13`'s echo and `C14` both read this row. |
| M2.10 | provisiond: uid→company table (a fourth config accessor shaped like `provisiond/handler.py:32-46`), fail-closed on an unmapped uid, `MEMORY_KEY` deny at `:225-227`, injection at `:234`. The lookup sits **after** the already-provisioned short-circuit — `handle_provision` 409s a known uid at `:221`, before `:225-238` — so it governs new profiles only. Ships **with the mapping file in place**, never ahead of it. |
| M2.11 | `C10`: no new RPC — validate, join-preview, or M2.3's memory-disabled report — returns a filesystem path. The kernel resolver (`~/hb/cs-kernel/cs/memory_report.py:55-80`) TCP-probes `engine_ws_url` and reads no engine RPC, so the check is that the new surface stays path-free. |

**Atomicity — the critical constraint.** **M2.1 + M2.1b + M2.1c + M2.2 + M2.3 + M2.4 +
M2.5 + M2.8 are one commit**, in that logical order. **M2.10 is not in it**: provisiond
cannot receive `MEMORY_KEY` from the app until M3.1 adds it to `KNOWN_KEYS`, so it ships
on its own with its mapping file, before the first provisioned join and after this
commit. M2.1 alone breaks the engine, and this is measured,
not predicted: with `PRAGMA foreign_keys=ON` live (`database.py:65`), inserting into a
child table whose parent lives in another file fails —

```
OperationalError: no such table: main.emails
```

so every link write breaks until M2.2; the boot backfill fails until M2.8; a boot
between M2.1 and M2.3 manufactures a store for any key, violating `C12`; and without
M2.4+M2.5, `C4` cannot pass. The table numbering is deliverable order, not commit
order — nothing is pointed at a shared store until M2.3 and M2.10 are in the same
commit — M2.3 is what refuses to manufacture a store, and it is inside the set. Two
locks now exist (profile DB, company DB) and are always taken **profile first, then
company**; a fixed order is what keeps two engines migrating both files from
deadlocking.

**Verification.** `C1`, `C4`, `C5`, `C6`, `C8`, `C9` (re-proven here — see below),
`C10`, `C12`, `C14`, `C16`, `C17`, `C18` (engine clause: the body deny and the
injection), `C13` (engine clause: the preview RPC). `C4` and `C17` need two real
processes. The runner suite gains **"kill between copy and drop, re-run converges"** for
M2.1c, and `forward → reverse → forward converges` as for M1.

**`C9` is re-proven at M2, and this is where it actually bites.** At M0/M1 no two
engines ever share a file: `zylch serve` holds the per-profile flock for life
(`cli/main.py:457`), and the CLI refuses a locked profile (`main.py:239,400`). The
two-process case exists only on the company DB this milestone creates — and it is live
on every deploy after a join, because the units carry no inter-instance ordering
(`scripts/systemd/zylch-server@.service`: only `After=network-online.target`) and
`update-daemons.sh` restarts them back-to-back in a loop.

**Rollback.** Reverse the move: copy the six tables back into each participating
profile's `zylch.db`, filtered by `owner_id`, which decision 7 preserved for exactly
this. `git revert` alone leaves the tables in the company file with code looking in the
profile file. Rolling back **one** profile of a shared store is per-profile: its rows
come back, the company store keeps the rest.

**The provenance filter is exact only until the first shared tick — not until the first
sweep.** The reconsolidation sweep is manual (`rpc/maintenance.py:61-72` is its only
entry point), so it is not the mixer. The incremental merge is: it runs every update
tick, and `update_blob` (`memory/blob_storage.py:117-138`) assigns `blob.content` and
never touches `owner_id`, so the first tick after two profiles share a store already
leaves merged content under one contributor's provenance. M2.6's history records the
losing `owner_id` and the reverse copy reads it; for anything predating that history the
exact restore is **the six tables copied back out of M0.5's backup**, not a whole-file
restore — restoring the whole `zylch.db` would rewind mail, tasks and tokens as well,
which is a far larger loss than the thing being recovered.

**Risk — the highest of the four.** Two companies share the vendor host
(`engine/docs/active-context.md:47,53`), so a fault here crosses tenants. Sequencing
consequence: the first shared store is created between two profiles of the **same**
company, never as a mixed test.

---

## M3 — the app UX

**Depends on** M2 (consumes M2.6). Blocks nothing.

| # | Deliverable |
|---|---|
| M3.1 | Optional key field at the onboarding `'form'` step, acted on in a `'memory'` step between `'form'` and `'connect'` — after `finalize`, the first point a sidecar exists (`Onboarding.tsx:114-180`). Carries the three app schema mirrors and the two provision exclusions deferred from M1.1. A failed validation blocks with the refusal and offers retry or mint. |
| M3.2 | `settings.get_secret` through the preload bridge (`app/src/preload/index.ts:428-448` ships only `schema`/`get`/`update`). **Only the preload wrapper is new** — `ipcMain.handle('rpc:call')` (`main/index.ts:752-759`) already forwards any method to the sidecar with no allowlist. |
| M3.3 | Memory card in Settings beside `MaintenanceCard` (`Settings.tsx:873`), key in clear with a copy control, laid out like `AccountCard`'s uid row (`:1004-1012`). Clipboard precedent: `Logs.tsx:171-176`. Replaces M1.1's exclusion. |
| M3.4 | Join gesture copied from `BackendLocationCard` (`Settings.tsx:484`): enter → test → echo → apply. |
| M3.5 | Right-click edit menu — one `webContents.on('context-menu')` beside `buildAppMenu()` (`main/index.ts:719`; `editMenu` at `:744` already covers the keyboard; no handler exists today). |
| M3.6 | MaintenanceCard surfaces `C17`'s "another engine is sweeping" instead of a silent zero-count success. |

**Verification.** `C13` and `C18` close here (M2 proved their engine clauses); `C17`'s
UI clause. `npm run typecheck` proves none of those on its own — it proves the code
compiles. The two checks that prove something:

- **`npm run test:onboarding`** (`app/package.json:18` → `scripts/test-onboarding.mjs`)
  drives `createProfileFS` under Node and already asserts unknown-key rejection. That is
  the check for M3.1's `profileFS` mirror: `MEMORY_KEY` is accepted rather than rejected.
- **A dev-app run** (`npm run dev` against a local sidecar, two local profiles) is the
  only way to exercise mint-on-empty, paste-join-with-echo, the key in clear with its
  copy control, and M3.6's sweep message. `C13` and `C17`'s UI clause close here or not
  at all.

M3.1's five app sites — the three schema mirrors and the two provision exclusions — are
one commit, for the same reason M1.1's pair is: three of five leaves a rejected payload
or an invisible field.

**On the packaged-app check.** `main/provisionClient.ts:52-60` derives the provisiond
origin from the configured WS backend host, so a packaged-app provision necessarily
hits the VPS's live `zylch-provisiond.service`. Without a deploy it exercises the
*old* provisiond and proves nothing about `C18`; with one it needs Mario's go. `C18` is
therefore proven engine-side in M2 against a local provisiond, and the packaged-app run
is an operational check after the go — not a milestone gate.

**Note.** `app/src/renderer/src/views/Settings.tsx:130` carries a user-facing Italian
string. M3 touches this file; fixing it is in scope per the English-artifacts rule.

---

## After M3 — operational, post-go

Not a milestone: none of this is verifiable in this tree, and all of it needs a deploy.

- **Converging the five live profiles.** They predate provisiond
  (`docs/active-context.md:33`), so M2.10 does not reach them; each joins through M3.4
  over `wss://`, one at a time. **Onto per-company keys, plural** — `support@` is
  MrCall, `cafe124*` is Café 124, and `mario.alemi` and `HxiZhWEB` have no stated
  company. That assignment is decision 1 below.
- The packaged-app provision check described above.

## Open decisions for Mario

1. **Which company each of the five live profiles belongs to.** Decided 2026-09-08,
   except one:

   | Profile | Company | Joins |
   |---|---|---|
   | `support@` | MrCall | with any other MrCall profile |
   | `cafe124`, `cafe124.it` | Café 124 | with each other |
   | `mario.alemi` | private, a company of one | **never** — its own key, its own store |
   | `HxiZhWEB` | **still unassigned** | pending |

   A private profile needs no special case: M1 mints its key at first boot and no join
   ever happens, which is already the design. This gates **the join**, not
   provisioning — those five uids are already provisioned, so `handle_provision` 409s
   them at `handler.py:221` and they never reach M2.10's lookup. Everything up to and
   including M3 proceeds without the remaining assignment.
2. **Deploy timing.** The five daemons are at `8e5fa2f`; M0, M1 and M2 all change the
   boot path. Note that a push alone deploys, via the reconcile timer.
3. **Residual isolation limit, already accepted.** With two companies on one host under
   SQLite, the wall between their stores is the key's secrecy plus same-uid process
   isolation. The product brief accepts this explicitly; it closes with Postgres.
