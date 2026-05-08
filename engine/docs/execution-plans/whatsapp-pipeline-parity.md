---
status: in-progress (Phase 1 a/b/c landed; Phase 2 onwards pending)
owner: next-session
discipline: Mario's standard rules apply. NEVER claim a feature is "fixed"
  or "done" or "verified" until Mario has clicked / used it himself in the
  real Electron app and reported back. Unit tests, typecheck, RPC probes,
  log lines do NOT count. One change at a time. Tell Mario exactly what
  to test. Wait. NEVER push to origin. NEVER commit until Mario says
  "funziona". Italian register in the chat.
created: 2026-05-07
last_updated: 2026-05-08
---

# WhatsApp pipeline parity + cross-channel person identity

## What Mario asked for

> "Replicate for WhatsApp the same flow we have for email. And not only:
>  they must be seen as the same thing. If I have a blob on PERSON X, if X
>  writes me via email or via WA, it's the same thing — I update the blob,
>  and the (one) task."

Two coupled goals:

1. **Pipeline parity**: every WhatsApp message goes through memory
   extraction + task creation, the same way email does today.
2. **Cross-channel identity**: a memory blob about Carmine Salamone
   merges email + WhatsApp records, and a task about Carmine has ONE
   row in `task_items` regardless of how Carmine wrote in.

## How the email side works today (must mirror this)

References checked: `engine/zylch/workers/memory.py`, `workers/task_creation.py`,
`services/process_pipeline.py`, `storage/models.py`, `storage/storage.py`,
`engine/docs/active-context.md` (2026-05-06 entry: Fase 1.1–4, Fase 2.3
identifier-based reconsolidation, Fase 3.1 `email_blobs`).

### Memory extraction — `MemoryWorker.process_email()` (`workers/memory.py:71-343`)

- Input: one `Email` row.
- LLM (custom user prompt + Anthropic prompt cache) emits a list of
  entities delimited by `---ENTITY---`. Each entity has `#IDENTIFIERS`,
  `#ABOUT`, `#HISTORY` blocks.
- For each entity:
  - `_extract_identifier_query()` (lines 26–68) pulls just the
    `#IDENTIFIERS` block. This is the dedup key.
  - `hybrid_search.search(query=identifiers)` against existing blobs in
    `namespace=user:<owner_id>`. Score ≥ 0.65 → candidate match.
  - If candidate exists, LLM verifies "same entity?" → MERGE
    (`llm_merge.merge_blob_content`) and update.
  - Otherwise CREATE new blob with `event_description="Extracted from
    email <id> (<date>)"`.
  - Either way, write `email_blobs(email_id, blob_id)` join row
    (`storage.add_email_blob_link`, models 240–256).

### Task creation — `TaskWorker._collect()` (`workers/task_creation.py:328-527`)

- For each new email:
  - **Thread tasks**: `Storage.get_tasks_by_thread(owner_id, thread_id)`.
  - **Contact tasks**: `Storage.get_tasks_by_contact(owner_id, from_email)`
    (plural, post-Fase 1.1).
  - **Topical sibling tasks (F7)**: 
    `blobs = Storage.get_blobs_for_email(email_id)` →
    `Storage.get_open_tasks_by_blobs(owner_id, blobs)` (storage 783–833).
- Builds `existing_tasks_all = thread + contact + topical`, deduped by id.
- LLM analyser decides `task_action ∈ {create, update, close, none}` +
  `target_task_id`. The new row goes through `_infer_task_channel`
  → `task_items.channel ∈ {email, phone, calendar, whatsapp?}`.
- After `process_batch`: F4 reanalyze sweep, F8 dedup sweep, age-based
  phone auto-close.

### TaskItem.sources shape (`storage/models.py`)

```jsonc
{
  "emails": ["<email_id>", ...],
  "blobs": ["<blob_id>", ...],
  "calendar_events": ["<event_id>", ...],
  "thread_id": "<thread_id>" | null
}
```

No `whatsapp_messages` slot today.

## What WhatsApp has today

- `WhatsAppMessage` rows in `whatsapp_messages` (sync.py / models 568–601)
  with `chat_jid`, `sender_jid`, `sender_name`, `text`, `timestamp`,
  `is_from_me`, `is_group`. Columns are channel-canonical, no FK to
  `Contact` or `WhatsAppContact`.
- `WhatsAppContact` (post-`9eee73c2`) carries `jid` + resolved
  `phone_number` + `name`, derived from neonize's `whatsmeow_lid_map`
  and `whatsmeow_contacts`.
- **Zero downstream processing.** `services/process_pipeline.py` step
  [2/5] syncs WA, then steps [3/5] memory and [4/5] tasks operate on
  emails only. `MemoryWorker.process_whatsapp_message()` exists at
  `memory.py:856-946` but is NEVER called.
- `task_items.channel` column already supports `'whatsapp'` as a value;
  no row carries it today.

## What's missing to unify identity

There is NO `Person` table and NO `BlobIdentifier` table. A blob's
`#IDENTIFIERS` block is free text inside `Blob.content`. Reconsolidation
matches via embedding cosine on that block — works for e.g.
`Name: Carmine Salamone\nEmail: carmine@cnit.it` matching a second blob
with the same email, but does NOT cross-match an email blob to a
WhatsApp blob unless the LLM happened to emit the same identifier on
both sides.

This is the load-bearing question of the whole feature.

## Proposed architecture (decisions for Mario to confirm)

### D1 — Identifier-keyed person index (NEW)

New table `person_identifiers`:
```
person_identifiers
  id            uuid pk
  owner_id      str index
  blob_id       fk Blob.id
  kind          str          # 'email' | 'phone' | 'lid' | 'name_norm'
  value         str          # 'carmine@cnit.it', '+393395040816', '19095575629933@lid', 'carmine salamone'
  created_at    datetime
  unique (owner_id, kind, value, blob_id)
```

Filled by the memory worker after it parses `#IDENTIFIERS`. Memory
worker's match logic becomes:
1. Parse `#IDENTIFIERS` from new entity into `(kind, value)` tuples
   (regex: `Email: …`, `Phone: …`, `LID: …`, `Name: …` → `name_norm`
   = lowercased + whitespace-collapsed).
2. Query `person_identifiers WHERE owner_id=? AND (kind,value) IN (…)`
   → set of candidate `blob_id`s.
3. If exactly one candidate, MERGE into it.
4. If multiple candidates, MERGE the new entity into the OLDEST and
   write a `person_identifiers` row pointing every other candidate's
   identifiers to the keeper too — explicit person-merge audit. (Or
   simpler: pick highest-cardinality candidate.)
5. If none, CREATE blob + write all `(kind,value)` rows for it.

Cosine similarity on identifier text becomes a fallback (typo
tolerance), not the primary key.

**Why this and not an explicit `Person` table**: blobs already are
the per-person aggregate. Adding a Person table forces a second
migration of every existing blob. Identifier rows are additive.

### D2 — `whatsapp_blobs` join table (mirror of `email_blobs`)

```
whatsapp_blobs
  whatsapp_message_id  fk WhatsAppMessage.id  pk
  blob_id              fk Blob.id              pk
  owner_id             str
  created_at           datetime
```

Written by the new `MemoryWorker.process_whatsapp_message()` path.
Read by `TaskWorker` via a new `Storage.get_blobs_for_whatsapp_message()`
mirror of `get_blobs_for_email()`.

### D3 — `TaskItem.sources` extended

```jsonc
{
  "emails": [...],
  "whatsapp_messages": [...],   // NEW
  "blobs": [...],
  "calendar_events": [...],
  "thread_id": ... | null
}
```

`get_open_tasks_by_blobs` is already shape-agnostic about which channel
populates `sources.blobs` — so the cross-channel topical lookup
(`task created from email about X` matched by `WA message about X`)
**falls out for free** once `whatsapp_blobs` is written.

`task_items.channel = 'whatsapp'` for tasks whose primary trigger was
a WA message; `_infer_task_channel` learns to read the channel of the
trigger.

### D4 — Memory worker: process WhatsApp

Add `MemoryWorker.process_whatsapp_message(msg)` (skeleton already
exists at `memory.py:856-946`, never called). It feeds the same LLM
prompt the email path uses, but with a WA-shaped envelope:

```
Channel: WhatsApp
From: <sender_name> (<sender_jid resolved to phone>) [GROUP <name>]
At: <timestamp>
Text: <text>
```

Wire it into `services/process_pipeline.py` step [3/5] right after
`MemoryWorker.process_email` loop. Iterate over WA messages newer than
`memory_processed_at` watermark (new column on `WhatsAppMessage`,
mirror of `Email.memory_processed`).

### D5 — Task worker: process WhatsApp

Add `TaskWorker.process_whatsapp_message_batch()` mirroring
`process_batch()`:

- Same `_collect`-style aggregation: thread (= chat_jid) tasks +
  contact (= resolved phone) tasks + topical (via blobs of this msg).
- Same LLM prompt with `Channel: WhatsApp` envelope.
- Same `task_action` decision logic, then UPSERT a `TaskItem` whose
  `sources.whatsapp_messages` carries the message id and `channel =
  'whatsapp'`.

Cross-channel sharing emerges naturally: an email task about Carmine
already has `sources.blobs = [carmine_blob]`. A WA message from
Carmine extracts into the same blob (D1 identifier match). The WA
task path queries `get_open_tasks_by_blobs` with `[carmine_blob]` →
finds the existing task → LLM picks `update`/`close` instead of
`create`. ONE task on Carmine across channels.

## Phasing

### Phase 0 — preparation

- Read `engine/docs/active-context.md` (2026-05-06 task-pipeline-overhaul
  entry) end-to-end so naming + numbering is consistent with what's
  shipped.
- Re-read this brief.

### Phase 1 — schema + identifier index (D1) ✅ DONE

Split into three landings:

**1a — additive write** (commit `d0baa6b1`, 2026-05-07).
- ✅ `PersonIdentifier` model (FK CASCADE on `Blob.id`, UNIQUE
  on `(owner_id, kind, value, blob_id)`). Indexed kinds: `email`,
  `phone`, `lid`. Names deliberately not indexed.
- ✅ Storage helpers `add_person_identifiers`,
  `find_blobs_by_identifiers`, `get_identifiers_for_blob`.
- ✅ Module-level parser `_parse_identifiers_block` and normaliser
  `_normalise_phone` in `workers/memory.py`. Multi-value comma split,
  bullet markers, placeholder rejection, deduplication.
- ✅ `MemoryWorker._upsert_entity` writes rows post-upsert (merge
  AND create branches).
- ✅ Opt-in backfill script
  `engine/scripts/backfill_person_identifiers.py` (idempotent via
  UNIQUE). Live populated 1745 rows across 3 profiles.

**1b — identifier-first match** (commit `315c56d1`, 2026-05-07).
- ✅ `_upsert_entity` candidate list now: identifier-matched first,
  cosine fallback, LLM merge gate unchanged. Each candidate carries
  a `source` label visible in logs (`identifier-only`,
  `identifier+cosine`, `cosine=0.78`).
- ✅ Tests: `tests/workers/test_person_identifiers.py` — 34 cases
  including 3 mock-based end-to-end Phase 1b scenarios (priority,
  fallback on LLM-INSERT, no-match → create).
- ✅ Live verification 2026-05-08 update on gmail profile: 1 of 8
  emails captured an identifier match (FeFarma `5491bb51` +
  `5b6075e3` — two duplicate company blobs cosine alone would have
  missed).

**1c — identifier-clustered `reconsolidate_now`** (commit `6ae8a5fa`,
2026-05-08).
- ✅ `Storage.migrate_blob_references(owner, dup, keeper)` — moves
  per-table references (`person_identifiers`, `email_blobs`,
  `calendar_blobs`, `task_items.sources.blobs`) from dup to keeper,
  idempotent.
- ✅ `reconsolidate_now` rewritten with `_build_dedup_clusters`
  (union-find on identifier tuples + canonical Name fallback).
  Migrate before delete so CASCADE doesn't drop linked rows.
- ✅ Tests: 13 new tests covering migrate per-table semantics,
  cluster builder edge cases, end-to-end mock-based scenarios.
- ✅ Live impact:
   - `support@mrcall.ai`: 805 → 307 (-62%, 498 dups merged across 10 cap-50 runs).
   - `mario.alemi@cafe124.it`: 731 → 315 (-57%, 416 dups merged across 9 runs).
   - `mario.alemi@gmail.com`: pending — Mario clicks Settings → Maintenance → "Reconsolidate memory" (Firebase session needed).

**What 1c does NOT do**: pure name-only typos (`Salomone` vs `Salamone`)
remain — same as before, no regression. The `groups_examined` counter
hit 0 on both BYOK profiles, so the sweep is exhaustive on
identifier-shared dups.

Discrepancies vs. the original brief:
- The brief mentioned `tests/workers/test_memory_identifiers.py` —
  actual file is `tests/workers/test_person_identifiers.py` (47
  tests covering parser + normaliser + storage helpers + FK CASCADE
  + Phase 1b match + Phase 1c migrate + cluster builder + 4 end-to-end
  reconsolidate scenarios).
- The brief's `_find_match` rewrite is implemented in `_upsert_entity`
  itself (no separate `_find_match` helper extracted).

### Phase 2 — `whatsapp_blobs` table + WA memory extraction (D2 + D4)

- New table.
- `MemoryWorker.process_whatsapp_message` wired + called from
  process_pipeline step [3/5] WA loop.
- New `Storage.get_blobs_for_whatsapp_message` mirror.
- `WhatsAppMessage.memory_processed_at` column.
- Tests: `tests/workers/test_memory_whatsapp.py` — message extracted
  into a person blob, second message merges, identifier overlap with
  existing email-derived blob merges (cross-channel happy path).
- **STOP. Mario tests in app: send/receive a few WA messages, observe
  blobs created; verify a blob about a contact who also emails him is
  ONE blob, not two.**

### Phase 3 — task creation from WhatsApp (D3 + D5)

- Extend `TaskItem.sources` JSON to include `whatsapp_messages`.
- `TaskWorker.process_whatsapp_message_batch`.
- `task_items.channel = 'whatsapp'` flowed via `_infer_task_channel`.
- F4 reanalyze sweep, F8 dedup sweep, channel filter UI dropdown
  already exist — just need the new channel value to flow through.
- Tests: `tests/workers/test_tasks_whatsapp.py` — task created from
  WA message, second WA message updates same task, email + WA on same
  person → ONE task.
- **STOP. Mario tests in app: trigger a real-life WA conversation
  with someone he also emails; verify ONE task surfaces, with sources
  showing both channels.**

### Phase 4 — UI surfacing (renderer)

- Tasks view: `sources.whatsapp_messages.length` shown next to
  `emails.length`.
- Task detail panel: link "WhatsApp message" alongside "Email".
- Channel filter dropdown already supports `'whatsapp'`.
- **STOP. Mario tests in app.**

### Phase 5 — telemetry + docs

- Extend `[update.summary]` log line with `wa_memory=A/B
  wa_tasks=C/D`.
- Update `engine/docs/active-context.md` "What Is Built and Working"
  with Phases 1–4 outcome (only AFTER Mario confirms live).
- Mark this plan `status: completed` (only after live confirmation).

## Open design questions for Mario (ask BEFORE coding)

1. **Group messages**: do we extract memory + create tasks from group
   chats (`is_group=True`), or only 1-on-1? Group chats have many
   participants and identifier resolution is per-`participant`.
   Recommend: 1-on-1 only in v1, group later.
2. **Self-sent WA (`is_from_me=True`)**: same rule as email
   (LLM-driven, can create tasks from things Mario writes to himself
   or to a contact)?
3. **`task_items.contact_email`**: today this column is `email_address`.
   For WhatsApp tasks, what do we put — phone? LID? Or rename to
   `contact_id` and overload? Recommend: keep `contact_email` for the
   email value when known, add `contact_phone` (nullable) for the
   phone, populate whichever is the trigger channel's primary
   identifier.
4. **Memory cost**: every WA message → an LLM call (memory) and
   another (task). On a busy WA day this could be hundreds of calls.
   Should we batch (group N messages from same chat into one prompt)?
   Recommend: same per-message granularity as email; the prompt cache
   makes the marginal cost small. Revisit if Mario sees a credit
   spike.
5. **Identifier kinds**: do we also index `name_norm` (lowercased
   name)? Risk: false merges between two "Mario Rossi". Recommend
   YES with a confidence flag — name match alone is "weak", needs
   embedding ≥ 0.50 to confirm; email/phone/lid match is "strong".

## Files the next agent will touch

```
engine/zylch/storage/models.py            +PersonIdentifier, +WhatsAppBlob, +memory_processed_at on WhatsAppMessage
engine/zylch/storage/storage.py           +add_person_identifier, +find_blobs_by_identifiers, +add_whatsapp_blob_link, +get_blobs_for_whatsapp_message
engine/zylch/workers/memory.py            _find_match() rewrite, +process_whatsapp_message wiring
engine/zylch/workers/task_creation.py     +process_whatsapp_message_batch, _infer_task_channel learns 'whatsapp'
engine/zylch/services/process_pipeline.py wire WA loops in steps [3/5] and [4/5]
engine/scripts/backfill_person_identifiers.py NEW
engine/scripts/backfill_whatsapp_blobs.py     NEW (no-op if table fresh)
engine/tests/workers/test_memory_identifiers.py
engine/tests/workers/test_memory_whatsapp.py
engine/tests/workers/test_tasks_whatsapp.py
app/src/renderer/src/views/Tasks.tsx      sources.whatsapp_messages display
```

## Out of scope

- Calendar already has its own join table (`calendar_blobs`).
- MrCall raw conversations: still TODO. Keep in mind the same
  identifier index (D1) will subsume them when their pipeline lands —
  identifier kind `'mrcall_phone'`.
- LLM provider choice: stays as today (Anthropic, BYOK or proxy via
  `make_llm_client()`).

## How to start the next session

1. Open this file. Re-read the discipline header at the top.
2. Open `engine/docs/active-context.md`, "task-pipeline-overhaul"
   entry — confirm the current state of `email_blobs` and
   identifier-based reconsolidation matches what this brief assumes.
3. Ask Mario the 5 open design questions above. Wait for his
   answers. Do NOT start Phase 1 before he answers them.
4. Phase 1 is one PR (one logical change). Land it, get Mario to
   verify in app, then move to Phase 2.
