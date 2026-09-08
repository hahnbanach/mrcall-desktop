# Shared company memory — implementation brief (mrcall-desktop)

## Intent

Implement the product decision in `~/hb/docs/briefs/2026-09-05-shared-company-memory.md`
(commit `37d3080`, review-approved, binding) inside this repository: one memory per
company, addressed by a capability key, replacing the per-profile memory that the
engine has today.

That brief is the **what** and the **why**, and this brief does not restate or
re-decide it. This one is the **how** for `engine/` and `app/`: what gets built, in
what order, under what constraints, and what has to be true before the work is
called done.

## Sources, and the baseline they were verified against

- Product decision: `~/hb/docs/briefs/2026-09-05-shared-company-memory.md` @ `37d3080`.
- File:line evidence, already verified against engine code — do not re-derive it:
  `~/hb/cs-kernel/docs/sessions/f1bfd7e1-d81f-42cf-9205-60aeefece296.md`, sections
  "Findings — shared-company-memory brief vs engine code", "Adversarial review
  (fable)", "Findings — settings GUI as host for the memory key".
- Evidence baselines: engine findings at `8e5fa2f`, GUI findings at `bd48d34`.
  Every anchor was re-read at `2af67a5` (this repo's HEAD) while writing this brief.
  **One file drifted**: `engine/zylch/tools/contact_tools.py`
  (`git diff --stat 8e5fa2f..HEAD` → 21 insertions). The contact-search tool is now
  `:168-210`; its deliberate absence of a namespace filter is stated in a code
  comment at `:201-205` and the owner-scoped call is `:206-210`. Everything else is
  byte-identical to the evidence baseline — in particular
  `services/command_handlers.py` did not move, and `_reset_all_data` is
  `:3144-3179` (table list `:3161-3171`, owner-only delete `:3173-3179`), a wider
  span than the evidence's `:3162-3177` but the same code.

## Scope

Four milestones, in this order. The order is the operator's and it is load-bearing:
see "Why M1 precedes M2" below.

- **M0 — an idempotent, single-owner migration runner, with a backup.** No migration
  mechanism exists today: schema is `create_all` (`storage/database.py:117`) plus a
  hardcoded ALTER list (`_apply_column_migrations`, `:130-244`), re-run by every process at boot, and the `.sql`
  files under `engine/migrations/` and `engine/zylch/migrations/` are executed by
  nothing (verified: no Python references them). Two processes on one file race on
  `create_all`'s checkfirst TOCTOU. The runner owns a `schema_version` table (none
  exists anywhere today), single-owner execution, the pre-migration backup that every
  later milestone's rollback depends on, and — the same single-owner problem wearing
  different clothes — the boot-time data backfills at `storage/database.py:245-476` —
  `_apply_data_backfills` at `:245` dispatching the three at `:266`, `:338` and
  `:442` — which today every process re-runs unserialized. Prerequisite to build, not a rule to
  observe.
- **M1 — the key, per-family scope, namespace rewrite, family filters.** The key
  becomes a settings field, a mint-and-validate RPC pair, and a column on every
  memory table; scope is decided per namespace family; the namespace constructors
  emit key-scoped namespaces for the company families and existing rows are rewritten
  to match; every path that filters by owner with no family filter gains one.
- **M2 — the memory DB split, and the five cross-file references.** Memory tables
  move out of the per-profile `zylch.db` into one memory DB per company, with the
  join-merge and its echo, write serialization, vector-index invalidation, the
  identifier index, the dangling task-ledger references, the company-scoped
  reconsolidation sweep, and the shared company self-notion. The boot backfill also
  becomes a two-session join: `_backfill_email_blobs_index` reads `Blob`, `Email` and
  `CalendarEvent` from one session today (`storage/database.py:353,371,383`), and
  after the split those live in different files.
- **M3 — the app UX.** Optional key field in onboarding, join with echo, a Settings
  card with a copy control, `settings.get_secret` through the preload bridge, a
  right-click edit menu, the field declared in all three schema lists, and the
  MaintenanceCard surfacing criterion 17's "another engine is sweeping" outcome
  instead of reporting a silent zero-count success. M3 also owns the only path by
  which the five profiles already live on the vendor host reach a shared key: they
  predate provisiond (`docs/active-context.md:33`), so they converge through the
  Settings join over `wss://`, one profile at a time.

### The family-blind paths M1 must fix — the full set

Every path that filters by `owner_id` with no namespace filter leaks rule blobs
between accounts the moment owner scope widens. There are **nine**, not four:

1. Contact search — `tools/contact_tools.py:206-210`, the absence documented in its
   own comment at `:201-205`.
2. The memory update tool — `tools/update_memory_tool.py:93,126` →
   `memory/blob_storage.py:117` (`update_blob`).
3. The memory delete path — `memory/blob_storage.py:188` (`delete_blob`).
4. Blob listing — `memory/blob_storage.py:196-204`, serving
   `services/command_handlers.py:635`.
5. **The solve agent's memory search** — `services/solve_tools.py:164-168`
   (`_search_memory`) calls `HybridSearchEngine.search(owner_id=…, query=…, limit=3)`
   with no namespace. Live: dispatched at `solve_tools.py:23-24`, declared to the
   model at `services/solve_constants.py:95,162`, reached through
   `services/task_executor.py:167` ← `rpc/methods.py:682`.
6. **The solve agent's memory update** — `services/solve_tools.py:215-219` runs the
   same unfiltered search with `limit=1` and then calls `update_blob` on the top hit
   (`:213,215`). This one both reads *and edits* another account's rules.
7. The per-account hard reset — `services/command_handlers.py:3144`
   (`_reset_all_data`), whose delete at `:3173-3179` filters
   `model_cls.owner_id == owner_id` across a table list that includes `blobs` and
   `blob_sentences` (`:3161-3171`). Named explicitly by the product brief alongside
   the other four. This is the "delete all my data" verb; item 8 is a different one.
8. **`/memory reset` — the destructive one.** `command_handlers.py:649` dispatches
   `cmd == "reset"` to `blob_storage.delete_all_blobs(owner_id)` at `:651`, and
   `delete_all_blobs` (`memory/blob_storage.py:212-222`) runs
   `session.query(Blob).filter(Blob.owner_id == owner_id).delete(...)` at `:217-218`
   with no namespace filter, cascading to sentences. This is not the hard reset of
   item 7: it is the memory-only wipe that lets a profile rebuild, sixteen lines below
   the `list` branch item 4 already cites. After the owner→key conversion, one account
   typing `/memory reset` deletes **the whole company's** blobs, every other account's
   `template:`/`prefs:` rules included — and the paired
   `reset_memory_processing_timestamps(owner_id)` at `:654` resets only *that*
   account's timestamps, so the other accounts' memory is destroyed and does not even
   rebuild. A one-command company-memory wipe is the single worst outcome available in
   this work.
9. `/memory stats` — `command_handlers.py:607-620` calls `get_stats(owner_id)` and
   prints `stats["namespaces"]` one per line; `get_stats`
   (`memory/blob_storage.py:224-248`) filters on owner alone (`:229,235`) and returns
   the namespace set (`:240,246`). Also live at `cli/chat.py:180`. Under key scope it
   lists `template:<other>` / `prefs:<other>` to any account, and criterion 11
   requires rules to be neither readable **nor listable**.

Four more owner-scoped blob queries are *not* on this list, checked rather than
assumed: `BaseTrainer._get_blobs` (`agents/trainers/base.py:71-90`) has zero callers;
`emailer_agent._get_blobs_by_ids` (`:234-241`) and `command_handlers.py:1852` hydrate
ids a `user:`-namespaced search already produced; and `storage.py:913/973/1033`
(`get_blobs_for_email` / `_event` / `_whatsapp_message`) are entity reads that are
*meant* to widen to the company.

`get_blob` (`memory/blob_storage.py:176`) deserves its own note. Its third caller,
`workers/memory.py:575`, receives ids from `find_blobs_by_identifiers`
(`:509-512`) — the `person_identifiers` index, not a namespaced search — so it is
cleared for a different reason: identifier rows point only at `user:` blobs. But it
must still convert, because a foreign-owner miss is skipped silently at `:576-579`,
and an identifier-matched merge that cannot load its blob degrades into creating a
duplicate entity instead. Criterion 3 catches it.

Plus one unfiltered read that is not owner-scoped at all: the boot backfill at
`storage/database.py:338-440`, reached from `init_db()` (`:125`) ←
`Storage.__init__` (`storage/storage.py:323`). It iterates `session.query(Blob).all()`
at `:383` across every owner, joins against this profile's `Email.id` set (`:371`),
and writes `EmailBlob` (`:406`) / `CalendarBlob` (`:419`) rows — two of M2's five
cross-file references. Its "already populated" guard (`:355-360`) degrades under a
shared store to "only whichever profile boots first is ever backfilled".

### The namespace constructors M1 must change

Fourteen live sites emit a family-scoped namespace: `workers/memory.py:251`,
`agents/base_agent.py:101`, `agents/emailer_agent.py:196,921`,
`agents/trainers/task_email.py:328`, `workers/task_creation.py:530`,
`memory/llm_merge.py:344`, `services/command_handlers.py:480`,
`services/facts_store.py:29`, `services/prefs_store.py:76,321`,
`tools/create_memory_tool.py:100,112,132`.

One of them is not a constructor but a passthrough, and it is the dangerous one:
`tools/create_memory_tool.py:131-134` scopes a bare category to the owner but takes
the model's namespace **verbatim** when it already contains a `:`. Under key scope an
LLM-supplied `user:<anything>` writes outside the company namespace — silent
knowledge loss that no namespace rewrite repairs afterwards.

### The predicate conversion M1 must make, and where it hides

For the company families the read and write predicate moves from `Blob.owner_id` to
`company_key`. This is the change; everything else in M1 serves it. The surface is
the ~16/~28 sites given under Material assumptions, and it is not evenly distributed:
**one `HybridSearchEngine.search()` call carries four owner-filtered SQL queries plus
the cache identity that decides whether the first of them runs at all**. Leaving any
one behind returns nothing across accounts while looking correct.

1. `memory/hybrid_search.py:167` — the in-process index cache key
   (`self._index._owner_id == owner_id`), which decides whether the index is reloaded
   at all.
2. `:172` — the index load itself, `filter(Blob.owner_id == owner_id)`.
3. `:204` — `_text_search`, `filter(Blob.owner_id == owner_id)`, with the namespace
   filter applied only when a namespace is passed.
4. `:448-449` — `_get_matching_sentences`, called per top result at `:330`, filtering
   `BlobSentence.owner_id`. Converting it changes nothing observable today:
   `result.matching_sentences` has no reader anywhere in the engine, so the field is
   written and dropped. It converts with the rest rather than being left as the one
   owner-scoped query in a key-scoped path.
5. `:287-290` — candidate hydration, `filter(Blob.id.in_(…), Blob.owner_id == owner_id)`,
   whose misses are silently skipped at `:300`. A row that survives ranking and fails
   hydration simply vanishes from the result with no error.

This is why criterion 2 and criterion 19 pin retrieval to the search path. The direct
fact query at `services/facts_store.py:66-76` reads
`filter(Blob.owner_id == owner_id, Blob.namespace == ns)` and never touches
`HybridSearchEngine` at all, so an implementation that converts the fact store and
forgets hybrid search satisfies "a fact learned from A is returned to B" while
entity retrieval — the feature's main path — is dead.

### Why M1 precedes M2

M1 lands the whole mechanism inside the per-profile database, where it is
semantically a no-op — one owner, one key, one file — and therefore fully testable
without any cross-profile blast radius. M2 then flips the deployment so several
profiles open one file, which is what makes M1's walls load-bearing. Building the
walls first and the sharing second means no window exists in which accounts share a
file while still being separated only by `owner_id`.

M1 rewrites existing rows, so it depends on M0. M2 depends on M1's walls. M3
consumes RPCs that M1 (mint, validate) and M2 (join preview/echo) introduce.

Between M1 and M3 there is no key UX, and that is deliberate rather than a gap: M1's
engine mints a key on first boot when `MEMORY_KEY` is unset. A key set by hand before
M3 — through `settings.update` or by editing the profile `.env` — is a typed key under
decision 11, so it joins an existing store and never creates one. M3 is what makes the
gesture reachable from the GUI, with the echo that makes it safe.

## Out of scope

Named here so no reviewer or later session treats their absence as an oversight:

- The Postgres layer that makes the key a verified capability. Deferred by the
  product brief; under SQLite the wall is the key's secrecy plus host isolation.
- Key rotation, one-time invite codes, selective visibility — all explicitly
  deferred by the product brief.
- The `cs-kernel` doc-truth line at `cs/memory_report.py:149-160`. It rides a normal
  kernel release once this ships; it is not this repo's change.
- The `amministrazione@cafe124.it` dunning loop. It ships on today's mechanisms and
  does not wait for this.
- The `NewProfileWizard`. It is dead code — three surviving comments, no component
  (`App.tsx:315`, `lib/profileSchema.ts:4`, `components/ProfileFormFields.tsx:5`).
  It stays dead; the key step goes in `Onboarding.tsx`, the only account-creation
  surface.

## Constraints

- **No push, tag, or deploy without the operator's explicit go.** Committing locally
  is in scope; publishing is not. This includes the five `zylch-server@` profile
  engines on the vendor host and any `v*` tag.
- **The engine stays the sole authority for what it owns** (charter invariant). The
  kernel↔engine contract does not change: `cs memory` reports an RPC endpoint plus a
  reachability verdict, never a path, and that shape survives this work untouched.
- **Symlinking the whole profile DB stays forbidden** (product brief): it would merge
  inboxes and OAuth tokens with no lock protecting the file. M2 moves the memory
  tables, never the file.
- **Extend, do not build parallel.** Four surfaces already exist and must be driven
  rather than re-implemented: the `fcntl.flock` acquire/stale-clean pattern in
  `cli/profiles.py:49-108` (M0's single-owner lock), the `BlobStorage.on_mutation`
  hook at `memory/blob_storage.py:25-35` together with
  `HybridSearchEngine.invalidate_cache()` at `memory/hybrid_search.py:161` (M2's
  index invalidation — the hook exists and is passed at none of its 9 construction
  sites), the provision-path injection at `provisiond/handler.py:234` (M2's
  provisioned key), and `BackendLocationCard` at
  `app/src/renderer/src/views/Settings.tsx:484-594` (M3's enter → test → echo → apply
  join gesture).
- **The public desktop app keeps its on-device promise.** Shared memory is a
  configuration of MrCall-operated engines, not a second product.
- **Everything durable is in English** — code, comments, tests, docs, log lines, and
  every user-facing string this work adds.
- Verification runs against `engine/venv` (pytest 9.1.1, Python 3.12.3) and
  `npm run typecheck` in `app/` (`package.json:14`, passing at HEAD). **`make lint`
  is not a usable gate**: the target is `black --check zylch/` then
  `ruff check zylch/` (`Makefile:11-13`), and black wants to reformat 29 files under
  `zylch/` at HEAD on a clean tree, so the target fails before reaching ruff.
  Reformatting 29 unrelated files would bury this work's diff, so each milestone
  gates on `ruff check zylch/` (green at HEAD) plus `black --check` on the files it
  changed. The only workflow is `.github/workflows/release.yml`, which has no test or
  lint step: nothing runs any of this unless a person does.

## Design decisions taken here

The product brief leaves these open; they are engineering choices, recorded so the
plan and its reviewer work from one set.

1. **The key is a settings field named `MEMORY_KEY`,** minted engine-side as
   `secrets.token_urlsafe(16)` — 128 bits, the brief's floor — and stored in the
   profile `.env` like every other setting.
2. **It is declared `secret: true`, and the preload bridge gains `settings.get_secret`.**
   The evidence offers a cheaper alternative — declare the key non-secret so the
   existing `settings.get` returns it verbatim — and the product brief rejects it:
   "at rest it is a secret … and the app reads it back through the engine's
   one-secret-per-call read, which the preload bridge exposes for this key". This
   brief follows the product brief. `settings.get` keeps masking it to `"<set>"`
   (`rpc/methods.py:1951-1962`); the Settings card reads it through
   `settings.get_secret` (`:1969-2002`), which already refuses any key not in
   `SECRET_KEYS` (derived at `services/settings_schema.py:424`).
3. **On the provisiond path the key is injected, never accepted — and this needs new
   code, not an existing pattern.** `provisiond/handler.py:225` tests every body key
   against `KNOWN_KEYS` and `:227` raises on the offenders, while
   `values["OWNER_ID"] = uid` at `:234` injects the uid
   outside that validation. It is tempting to say `MEMORY_KEY` "follows `OWNER_ID`",
   and it does not: `OWNER_ID` is not in `settings_schema.py` at all
   (`grep -c OWNER_ID` -> 0), so it is not a `KNOWN_KEY` and `:225-227` rejects it *by
   absence*, with no exclusion code anywhere. `MEMORY_KEY` **is** a settings field, so
   it lands inside `KNOWN_KEYS` and would be **accepted** from the request body. An
   explicit deny for `MEMORY_KEY` on the provision path has to be written; only the
   injection half at `:234` is reusable.

   That deny is a backstop, not the mechanism, because **the app would otherwise send
   the key on every provision**. `app/src/main/index.ts:1378-1382` builds the
   provision payload by iterating `KNOWN_KEYS` imported from `profileFS` (`:19`) and
   reading each key out of the profile `.env`, skipping exactly one — `OWNER_ID`, at
   `:1379` — with `provisionClient.ts:169` stripping it a second time defensively.
   Put `MEMORY_KEY` in `KNOWN_KEYS` and leave those two untouched, and the engine-side
   deny turns every provision into a 400. `MEMORY_KEY` is therefore excluded app-side
   at both points exactly as `OWNER_ID` is.
4. **provisiond resolves uid -> company from an explicit mapping, and fails closed.**
   The product brief has mrcalld "hold the company key and inject it into every
   account it creates for that company", which presumes a uid->company mapping. None
   exists: `grep -rniE "company_key|company_registry|uid_to_company|COMPANY_ID"` over
   `zylch/` returns nothing, and `entitlement_allows` (`provisiond/handler.py:98-106`)
   is a permissive stub returning `True` with a TODO.

   **A host-level key is not an acceptable stand-in, because the vendor host is
   multi-tenant today.** `engine/docs/active-context.md:47` names the profile set on
   that daemon host — `support@` beside "the proxy/credits profiles (cafe124,
   cafe124.it, mario.alemi)" — and `:53` reads "all 6 profile daemons (BYOK today:
   `support@`, `cafe124`)"; the newest entry (`:13`, 2026-09-08) works on
   `production@cafe124.it`. `support@` is MrCall's own identity; `cafe124*` is Café
   124, whose `amministrazione@cafe124.it` is the product brief's named first
   consumer. One host-wide key would put MrCall's memory and a customer's into one
   store — the exact inverse of "one memory per company".

   So the mapping gets built: mrcalld's configuration carries an explicit company
   table, provisiond resolves the verified uid through it, and a uid that resolves to
   no company is **refused, never defaulted**. provisiond's configuration today is
   three env-var-backed accessors (`provisiond/handler.py:32-46`), so the table is a
   fourth of the same shape: a file path from a new env var, read per request, mapping
   uid to company key; an absent file or an absent uid refuses. Adding a row is an
   operator action on the vendor host, not something any client can trigger.

   No **automatic** fallback key exists anywhere in the design, because a fallback is
   precisely how two tenants end up in one store. An operator editing a profile's
   `.env` by hand can still put two companies in one store; that is the same
   unverified-key limit the product brief already accepts under SQLite, not a
   mechanism this design provides.
5. **Column name `company_key`, on every memory table,** `blob_sentences` included
   (it already carries `owner_id` at `storage/models.py:217`, and the product brief
   already requires "every memory table gets the key column, the sentence-level table
   included").
6. **Namespace shapes.** Company families become `user:<company_key>` and
   `facts:<company_key>`. Rule families keep `template:<owner_id>` and
   `prefs:<owner_id>` — the owner is already the wall inside that string — and gain
   the key column plus a key predicate, so they are scoped key AND owner as the
   product brief requires.
7. **`owner_id` is never overwritten.** It stays on every row, migrated or new, as
   provenance: which account contributed the fact.
8. **M0's single owner is an `fcntl.flock` holder,** extending `cli/profiles.py:49-108`'s
   pattern rather than inventing one, plus a `schema_version` table. That pattern is
   `LOCK_EX | LOCK_NB` (`:86`) returning `False` on contention (`:91-96`): it fails
   rather than waits, so the loser of a race skips the work **this boot** and finds it
   already done on the next one. Every criterion below that says "cannot both" means
   that, not "only ever once". The
   read-merge-write serialization M2 needs is `BEGIN IMMEDIATE`, because
   `with_for_update()` compiles to nothing on SQLite — verified — and
   `PRAGMA busy_timeout=30000` (`storage/database.py:69`) serializes statements, not
   cycles.
9. **The reconsolidation sweep gets an owner, exactly as the migration does.**
   `memory/llm_merge.py:344,365` is per-owner today, and it is not only a merge: on
   each merged pair it calls `Storage.migrate_blob_references`
   (`memory/llm_merge.py:479-486` -> `storage/storage.py:1214`, task-ledger rewrite
   at `:1409-1428`), which is the machinery criterion 6 rests on. That method carries
   nine owner predicates of its own — `PersonIdentifier` (`storage/storage.py:1273,1283`),
   `EmailBlob` (`:1308,1318`), `CalendarBlob` (`:1341,1351`), `WhatsAppBlob`
   (`:1374,1384`) and `TaskItem` (`:1409`) — and they widen with the rest: left owner-scoped, the company-wide sweep cannot
   rewrite another account's references, which is exactly what criterion 6 forbids. The four
   `*_migrated` counters at `llm_merge.py:346-359` are the no-LLM early-return stub,
   hardcoded to `0` — not the migration. Key-scoped
   without an owner, five profile engines would each run a company-wide LLM sweep
   over the same store. It runs once per company (product brief), elected the same
   way M0 elects its migrator, and stays reachable at `rpc/maintenance.py:88`.
10. **The key step is collected at the onboarding form step and acted on after
    `finalize`.** No sidecar exists while the form renders — `Onboarding.tsx:114-180`
    reaches a live engine only at `finalize` — and minting, validation and the join
    echo are all engine calls. The product brief already places minting there ("the
    engine mints a key at finalize"), so the optional field lives in the form and a
    `'memory'` step between `'form'` and `'connect'` performs mint-or-join.
    `createProfileForFirebaseUser` (`Onboarding.tsx:149`) has already written a pasted
    key to `.env` by then, so the `'memory'` step states an outcome when validation
    fails: it blocks with the refusal and offers retry or mint, and the profile holds
    no usable memory key until one of the two succeeds. A key pasted *after* one was
    auto-minted abandons the minted store **only when that store is provably empty**,
    which is the onboarding `'memory'` step and nowhere else: M1 auto-mints on first
    boot and no key UX exists before M3, so a key pasted later — in M3's Settings
    card — meets a store holding everything the profile has learned since. That case
    is a merge, as the product brief requires ("entering an existing key from a
    profile that already holds a memory merges two memories") and as criterion 5
    proves; deleting it there would destroy accumulated memory.
11. **A company store is created only by a vouched-for key; a typed key opens
    existing-only.** Store opening is unconditionally create-if-missing today:
    `get_engine()` runs `os.makedirs` then `create_engine("sqlite:///…")`
    (`storage/database.py:52-56`), SQLite creates the file on first connect, and
    `init_db()`'s `create_all` (`:117`) furnishes it. Under M2 the key selects the
    file, so a boot carrying an unvalidated key would silently manufacture a fresh
    empty company store — exactly what criterion 12 forbids, and it would do it
    before the `'memory'` step ever ran.

    The rule is not "only minting creates", because three paths legitimately create a
    store and two of them are unavoidable:
    (a) **minting** — the engine generated the key itself, at M1 first boot or at the
    onboarding `'memory'` step;
    (b) **M2's own migration** — every profile alive at the first post-M2 boot carries
    an M1-minted key that names no store yet, because M2 is what creates stores. The
    voucher here is M0's `schema_version`, not "the profile still holds blobs": a
    sync-only profile can hold an M1-minted key and zero blobs
    (`engine/docs/active-context.md:53`) and could never re-mint, since minting fires
    only when `MEMORY_KEY` is unset;
    (c) **provisiond's first profile for a company** — the injected key comes from
    mrcalld's mapping table, so an authority on the host has already vouched for it.

    What separates these from the case criterion 12 forbids is not novelty but
    **provenance**: in all three the key is vouched for by something the host already
    holds — the engine minted it, or the profile's `zylch.db` is pre-M2 by its
    `schema_version` and the key is the one M1 wrote there, or the operator's mapping
    table names it for this uid. A key a *human typed in* — the onboarding paste, the Settings join —
    has none of that, and it is precisely the case the product brief means by "a key
    the host does not know is refused, never silently turned into a fresh empty
    memory". So: a typed key opens existing-only; a vouched-for key may create.
    "Refuse", on a headless `zylch-server@` daemon, means memory is disabled and the
    condition is reported through the RPC surface — never a unit failure, because five
    live daemons also carry mail sync, and taking those down to reject a memory key
    would be a far larger outage than the fault.
12. **The shared company self-notion is M2, not M1.** It is a property of the shared
    memory's configuration, and a shared configuration only exists once a store is
    shared. It is injected into the extraction prompt at build time
    (`agents/trainers/memory_message.py:106-111,166`), because the trainer's LLM
    infers the company from each profile's own sampled mail and the `USER_COMPANY`
    setting is never read by the trainer — it is read at runtime by other agents
    (`services/solve_constants.py:432-440`).

## Acceptance criteria

The product brief's criteria, made executable here. Each names where it is proven.

1. A fact learned from one profile's mailbox is returned to another profile's agent
   on the same host, with no `cs --account` bridge.
2. Every `user:`/`facts:` row that existed per profile before the change is
   retrievable through the key after it — proven on both retrieval paths, the direct
   fact query (`services/facts_store.py:66-76`) and `HybridSearchEngine.search()`,
   because only the second exercises the owner-filtered queries inside search. The
   `search()` half uses an identifier-overlapping query, the only kind that reaches
   `_text_search` at all (`memory/hybrid_search.py:213` needs `matched > 0`), which is
   what covers `:204` and `:287-290`; criterion 19 covers the vector half. A
   start-empty implementation fails this.
3. An entity written by A and later updated by B is actually updated — the merged
   content comes back, not an ignored empty result. This is the criterion that fails
   today's write path: `BlobStorage.update_blob` filters on owner
   (`memory/blob_storage.py:117`) and returns `{}` for a foreign owner, while
   `workers/memory.py:638-650` ignores that return and reports success, and
   `services/facts_store.py:145-152` returns the blob id as if it had written.
4. Two engine processes writing the same entity into the shared file converge on one
   blob: no lost update, no vector-index duplicate.
5. Two pre-existing memories joined under one key converge — one row per fact key,
   no value silently dropped, entity blobs united by the reconsolidation sweep.
6. A blob merged away by one account leaves no dangling reference in another
   account's `task_items.sources.blobs` or in `person_identifiers`.
7. Every row, migrated or new, carries the contributing account as `owner_id`.
8. One account's "delete all my data" leaves company knowledge intact, provenance
   included, while that account's own rule rows are gone.
9. Whichever process boots first migrates the shared file; the second boot is an
   idempotent no-op, and two simultaneous boots do not both migrate.
10. `cs memory`'s output shape is unchanged — no filesystem path reaches any clone.
11. A's operating rules are neither readable, listable, editable nor deletable from
    B. Proven on eight of the nine owner-scoped, namespace-unfiltered paths
    enumerated above — the ninth, `/memory reset`, is criterion 11b because its
    failure destroys rather than leaks. They are: contact search, the memory update tool, the delete path, blob listing,
    both solve-agent paths (`services/solve_tools.py:164-168` and `:215-219`, the
    second of which edits the top hit), the per-account hard reset
    (`services/command_handlers.py:3144`, delete at `:3173-3179`) and `/memory stats`
    (`:607-620` → `memory/blob_storage.py:224-248`, which lists namespaces) — not only
    on the namespace-scoped stores, where isolation is trivial and the test passes
    without the fix.
11b. `/memory reset` from account B destroys nothing of account A's and nothing of the
    company's: it removes B's own contributions and B's rule rows, leaving company
    knowledge and every other account's rules intact
    (`services/command_handlers.py:649-654` → `memory/blob_storage.py:212-222`).
    Proven by running it, not by reading the filter — this is the one path whose
    failure is unrecoverable, because `reset_memory_processing_timestamps` at `:654`
    would not rebuild what it deleted.
12. An unknown key is refused, never silently turned into a fresh empty memory.
    Existence cannot be checked before M2: under M1 the memory still lives in the
    per-profile `zylch.db`, so the only key a profile can know is its own. M1's
    validate RPC therefore checks **shape** — well-formed, full entropy — and M2's
    checks **existence** against the company stores on the host; M3 surfaces both
    refusals. Proven at the store layer, not only at the RPC: a boot whose `.env`
    carries a **typed** key naming no store opens nothing and creates nothing
    (`storage/database.py:52-56,117`), so no empty store appears on disk to be joined
    later. The three vouched-for creating paths of decision 11 — mint, M2 migration,
    provisiond injection — are the complement of this criterion, not exceptions to
    it, and criterion 9 exercises the migration one.
13. Joining echoes the company's self-notion and the memory's size before committing
    (M2's preview RPC, M3's echo control), and after account creation the profile
    owner reads the key in clear in Settings and copies it in one gesture; a key
    pasted at creation joins; an empty field yields a freshly minted key, shown once.
14. No profile sharing a key stores an entity about the company named in the shared
    self-notion, whatever its own trainer inferred.
15. A namespace supplied by the model to `create_memory_tool` cannot write outside
    the company's namespace: a crafted `user:<other>` is refused or re-scoped to this
    company, never stored verbatim (`tools/create_memory_tool.py:131-134`). The
    re-scoping must not flatten families — a `template:`/`prefs:` namespace still
    resolves to `template:<owner_id>`/`prefs:<owner_id>`, never to the company key —
    and a family the engine does not recognise is refused rather than stored, which
    `:133-134` currently accepts verbatim.
16. The boot backfill indexes every profile's mail against the company store, not
    only whichever profile boots first (`storage/database.py:338-440`; the "already
    populated" guard is `:355-360`, the unfiltered blob scan `:383`, the `EmailBlob`
    and `CalendarBlob` writes `:406` and `:419`). It scans the company's blobs — that
    is the point of the shared store — but joins them only against the booting
    profile's own `Email`/`CalendarEvent` rows, and it runs under M0's single-owner
    lock so two booting engines cannot both backfill.
17. The reconsolidation sweep runs once per company, not once per profile: with N
    engines up, one sweep executes and the other N-1 return a distinguishable
    "another engine is sweeping" result rather than a silent zero-count success, so
    the Settings MaintenanceCard can say which happened
    (`memory/llm_merge.py:344,365`, `rpc/maintenance.py:88`).
18. A `MEMORY_KEY` supplied in a provision request body is refused, and the profile
    provisiond creates carries the key from mrcalld's own configuration instead
    (`provisiond/handler.py:225-227` for the deny, `:234` for the injection), while a
    normal provision from the packaged app still succeeds rather than 400-ing —
    `MEMORY_KEY` is skipped app-side at `app/src/main/index.ts:1379` and
    `provisionClient.ts:169` the way `OWNER_ID` already is. The five profiles live on
    the vendor host today predate provisiond (`docs/active-context.md:33`), so they
    converge onto a company key through M3's Settings join over `wss://`, not through
    this path. Two
    profiles of different companies on one host never resolve to the same key, and a
    uid that maps to no company is refused rather than given a default — the vendor
    host runs `support@` and `cafe124*` side by side, so a shared fallback key would
    merge MrCall's memory with a customer's.
19. Cross-account **entity** retrieval works through `HybridSearchEngine.search()`,
    and specifically through its **vector** half. `search()` merges two independent
    retrievers — the index at `memory/hybrid_search.py:269-271` and `_text_search` at
    `:276` — so a query that overlaps the entity's identifiers is served by FTS alone
    and proves nothing about the index: `_text_search` scores on identifier-term
    overlap (`:211-215`) and `extract_identifiers_section` falls back to the **whole
    blob content** when the `#IDENTIFIERS…#ABOUT` header is absent (`:18-31`, the bare
    `return content` at `:31`), so a plain name or address matches. The criterion is
    therefore: B retrieves A's entity through `search()` using a semantic query
    sharing no term with that entity's identifiers, which only the vector half can
    serve — `_text_search` needs `matched > 0` (`:213`) and contributes nothing — so
    it proves `:172`, the index load filter, on top of `:204` and `:287-290`. The
    cache identity at `:167` is not covered by that query: it lives inside one process
    serving one uid and only bites when a single engine instance is asked for two
    scopes. That is its own criterion: one engine process that answers for two
    scopes in turn returns each scope's own entities, rather than serving the second
    from the index it cached for the first (`memory/hybrid_search.py:167`).

20. Every existing `template:`/`prefs:` rule row survives the M1 conversion and stays
    readable by its owner. C2 covers the company families only; once rule families are
    scoped key AND owner, a row whose `company_key` was never backfilled is invisible
    to everyone, so the backfill covers all six memory tables and not just the two
    company ones. (Added after the plan gate exposed the gap; the brief passed its own
    gate at 19 criteria plus C11b.)

## Material assumptions

- The five `zylch-server@` profile engines and provisiond on the vendor host run as
  the same system user (`mrcalld`), so under SQLite the key selects a file that
  nothing verifies. Asserted by the evidence, not checkable from this tree. The
  product brief accepts this and bounds it; the criteria above do not claim a wall
  the deployment does not have.
- Blob ids are UUIDs (`storage/models.py:190-193`), so merging two memory files
  cannot collide on primary keys.
- No *third* scope wall exists beyond `owner_id` and the namespace string: the index
  cache key (`memory/hybrid_search.py:167`) and `agent_prompts` both derive from those
  two. This was checked, not assumed — and it does not make them free: `:167` and
  `:172` are conversion sites, listed as such above.
- `MEMORY_DB_PATH` (`memory/config.py:12`) is docstring only — no field, not wired.
  M2 builds that plumbing rather than configuring something that already works.
- The memory-side tables are `blobs`, `blob_sentences`, `email_blobs`,
  `calendar_blobs`, `whatsapp_blobs`, `person_identifiers`
  (`storage/models.py:187-349`). The split is **not** "nine `BlobStorage(` sites on the
  global `get_session`" — that undercounts by an order of magnitude. Those six models
  are referenced at 111 sites outside `BlobStorage`/`HybridSearchEngine`/`models.py`
  (75 in `storage/storage.py` alone), of which 27 are direct `session.query(…)` entry
  points, and there are 8 `HybridSearchEngine(` construction sites on the same global
  factory. What makes the split tractable is that **no ORM `.join(` crosses the
  boundary** — every access is single-table — so the seam is the session factory in
  `storage/database.py` gaining per-model binds, which routes all 111 transparently.
- The owner-scoped read surface is ~16 sites on `Blob`/`BlobSentence` and ~28 once
  the memory-side index tables are counted.
- Onboarding rejects unknown keys at `app/src/main/profileFS.ts:261-270`, so the
  field must land in all three hand-synced *schema* lists —
  `services/settings_schema.py:427`, `app/src/renderer/src/lib/profileSchema.ts:25`,
  and `profileFS.ts:34 KNOWN_KEYS`. Two of three yields either a rejected payload or
  an invisible field. Those mirrors have already drifted by two fields, which is why
  M3 treats the triplication as a trap. Two further sites are exclusions rather than
  declarations, and decision 3 covers them: the provision-payload skip at
  `app/src/main/index.ts:1379` and the defensive strip at `provisionClient.ts:169`.
  Five hand-synced places in total.

## Risks

- **The write path loses knowledge if read scope widens before write scope.** This is
  the single most dangerous ordering error available in this work, and criterion 3
  exists to catch it. Both moves land together in M1.
- **The vector index is never invalidated today** — `invalidate_cache()` has no
  callers and `on_mutation` is passed at none of the 9 `BlobStorage` construction
  sites. It is a live single-process defect; sharing a file makes it cross-process
  and lets accounts create duplicate entities in parallel. M2 fixes it as a
  correctness prerequisite, not as opportunistic cleanup.
- **Rewriting rows without changing the constructors re-splits the store on the next
  write.** The two halves of M1 are one change, never two commits.
- **The per-account reset changes meaning under a shared store.** Left as is, it
  erases the account's provenance rows from company knowledge.
- **Migration is destructive by nature.** Every milestone that migrates data is
  reversible only from the backup M0's runner takes.
- **Fail-closed provisioning changes a live endpoint.** `zylch-provisiond.service` is
  enabled and active on the VPS, and refusing a uid that maps to no company is a
  behaviour change on it. Blast radius is small — no fresh profile has ever been
  provisioned end-to-end through the packaged app
  (`docs/active-context.md:33`) — but the endpoint is live, so the change ships with
  the mapping file in place rather than ahead of it.
