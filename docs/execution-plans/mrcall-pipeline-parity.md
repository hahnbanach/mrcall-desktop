---
status: active
stage: Livello A landed 2026-05-20; Livello B (phone-call memory ingestion) is next
owner: cross-cutting (engine + app + IPC)
created: 2026-05-19
template: engine/docs/execution-plans/whatsapp-pipeline-parity.md
discipline: |
  Mario's standard rules. NEVER claim a feature is "fixed", "done", or
  "verified" until Mario has clicked / used it himself in the real
  Electron app and reported back. Unit tests, typecheck, RPC probes,
  log lines do NOT count. One change at a time. Tell Mario exactly
  what to test. Wait. NEVER push to origin. NEVER commit until Mario
  says it works. Italian register in the chat.
---

# MrCall pipeline parity + cross-channel toggle

> **Status 2026-05-20** (live-verified by Mario, on `worktree-sprightly-floating-anchor`):
> - **Prerequisite DONE** — legacy delegated/PKCE OAuth2 + `/mrcall` command surface + `mrcall_link` removed; StarChat reached via Firebase JWT only.
> - **Livello A (read-only customer-service lookup) DONE** — MrCall tab lists + searches businesses (`mrcall.list_my_businesses`, `mrcall.search_businesses`; StarChat role-scopes admin cross-owner vs owner own-only). Onboarding unblocked for MrCall-only users + in-wizard Calendar session fix.
> - **Livello B (phone-call memory + task ingestion — the D1–D5 plan below) = NEXT.** `sync_mrcall` is currently a graceful no-op; it must be reimplemented over the **Firebase JWT path** (`{realm}/customer/conversation/search`, NOT `delegated_`) before Livello B. StarChat's `FirebaseCustomerConversationService` already hard-scopes conversation search to the caller's uid (so "only own businesses' calls" is enforced server-side), but add a defence-in-depth owner filter before ingestion anyway — Mario's hard constraint: never put another owner's contacts/calls into memory.

## What Mario asked for

*(translated from Mario's Italian)*

> "Bring MrCall in. The MrCall tab is still a disabled placeholder. The
>  WhatsApp workstream laid the foundations (`person_identifiers` with a
>  future `mrcall_phone` kind mentioned in Phase 1c, the `*_blobs` join
>  table pattern, F7 cross-channel). The `MrcallConversation` model and
>  the OAuth2 `StarChatClient` exist engine-side but nothing processes
>  them. Plan it like WA parity, 4 phases: memory extraction → task
>  creation → MrCall tab UI → MrCall/email/WA cross-channel toggle in the
>  Source panel."

Two coupled goals, identical to the WhatsApp plan:

1. **Pipeline parity**: every `MrcallConversation` goes through memory
   extraction + task creation, the same route email and WhatsApp take today.
2. **Cross-channel identity**: one blob on John Smith brings together
   email + WA + the MrCall phone call; ONE task on John regardless of
   which of the three channels triggered it.

## Current state: what exists vs what is missing

### Engine — exists ✅

| Piece | Where | Notes |
|---|---|---|
| `MrcallConversation` model | `storage/models.py:575` | Text PK, owner_id-scoped, `memory_processed_at` already present (mirrors Email + WhatsAppMessage), `contact_phone`/`contact_name`, `subject`/`body` JSON, `custom_values` JSON, `raw_data`, `call_duration_ms`, `call_started_at` |
| `OAuthToken` provider='mrcall' | `storage/models.py:349` | Full PKCE flow in `tools/mrcall/oauth.py`, refresh in `_refresh_token_if_needed` |
| `StarChatClient` | `tools/starchat.py:13` | Contact CRUD, business config, variables, `initiate_outbound_call` |
| `sync_mrcall()` | `services/sync_service.py:142` | Already working: calls `/mrcall/v1/delegated_{realm}/customer/conversation/search`, writes into `mrcall_conversations`. Wired into the pipeline (`run()` line 495 via `_sync_mrcall_if_connected`) |
| `InitiateCallTool` + `SendSMSTool` | `tools/call_tools.py`, `tools/sms_tools.py` | Code exists; **NOT registered** in `factory.create_all_tools()`. Out of scope for this plan (see Out of scope). |
| RPC `mrcall.list_my_businesses` | `rpc/mrcall_actions.py:37` | The namespace's only server-side method |
| `PersonIdentifier` with kind `'phone'` | `storage/models.py:314` | Already shareable for cross-channel match: the MrCall number is written as `kind='phone'` and attaches to the existing email/WA blob. **No new `'mrcall_phone'` kind** — see Out of scope. |

### Engine — missing ❌

- **No `MrcallBlob` join table** (the analogue of EmailBlob/CalendarBlob/WhatsAppBlob).
- **No `MemoryWorker.process_mrcall_conversation()`** — `process_email` + `process_whatsapp_message` exist; the MrCall path is empty.
- **No MrCall envelope in the `memory_message` trainer** — today the META_PROMPT mentions email + WhatsApp; the third envelope (phone call with transcript) is missing.
- **No `TaskWorker._analyze_recent_mrcall_events()`** — `_analyze_recent_email_events` + `_analyze_recent_whatsapp_events` exist; MrCall has nothing.
- **`task_items.channel = 'mrcall'`** never used (the column accepts any string, it just has to be written).
- **Missing storage helpers**: `add_mrcall_blob_link`, `get_blobs_for_mrcall_conversation`, `get_unprocessed_mrcall_conversations`, `mark_mrcall_task_processed`, `update_task_item(add_source_mrcall_conversation=…)`.
- **`migrate_blob_references` needs extending** with `mrcall_blobs_migrated` (the analogue of WA Phase 1c's `whatsapp_blobs_migrated`), so Phase 1c reconsolidation preserves MrCall links on merged blobs.
- **Pipeline wiring**: `process_pipeline.py` step [3/5] memory loop and step [4/5] task loop both need extending for MrCall.
- **RPC methods**: `mrcall.listConversations`, `mrcall.getConversation` (shaped like `whatsapp.listMessages`).
- **Sources schema extension**: `task_items.sources.mrcall_conversations` + `sources.mrcall_conversation_id` (the analogue of `whatsapp_chat_jid`).
- **Column `mrcall_conversations.task_processed_at`** (mirrors the same email + WA pattern).

### App — missing ❌

- **MrCall tab**: disabled placeholder in `App.tsx:643-646` (`disabled: true, disabledTitle: 'Not connected'`).
- **`Mrcall.tsx` view** (mirroring `WhatsApp.tsx`): conversation list, detail with transcript, filter by business_id when there is more than one.
- **Connect MrCall**: today the only entry point is the `zylch init` CLI. To be added as a Settings card (mirroring `ConnectGoogleCalendar.tsx`) or as an empty-tab CTA (mirroring `ConnectWhatsApp.tsx`).
- **ThreadPanel MrCall branch**: today it handles only `email`/`whatsapp` (`ThreadSourceType`).
- **Cross-channel pills** in ThreadPanel: today it shows Email/WhatsApp; add MrCall → 3 values, parallel counts, parallel fetch, instant tab switch.
- **Preload bindings** in `app/src/preload/index.ts`: the `mrcall.*` namespace exists with `list_my_businesses` only; add `listConversations`, `getConversation`.
- **Type extension** in `types.ts`: `ThreadSourceType = 'email' | 'whatsapp' | 'mrcall'`, `ZylchTask.sources.mrcall_conversations?`, `sources.mrcall_conversation_id?`.

### IPC contract — missing ❌

- `tasks.list` payload: `sources.mrcall_conversations?: string[]` (list of `MrcallConversation.id` PKs) + `sources.mrcall_conversation_id?: string | null` (first-touch conv id, the analogue of `whatsapp_chat_jid` for email).
- `mrcall.listConversations(business_id?, limit?, offset?)` — array of conversation row dicts.
- `mrcall.getConversation(conversation_id)` — a single conversation with `body` (transcript) decoded.

## Proposed architecture (D1–D5, decisions for Mario)

The design replicates exactly what worked for WhatsApp.

### D1 — `mrcall_blobs` join table (mirroring `whatsapp_blobs`)

```python
class MrcallBlob(Base):
    __tablename__ = "mrcall_blobs"
    mrcall_conversation_id = Column(
        Text,
        ForeignKey("mrcall_conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    blob_id = Column(
        String(36),
        ForeignKey("blobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    owner_id = Column(Text, nullable=False, index=True)
    created_at = Column(DateTime, default=_utcnow)
```

Written by `process_mrcall_conversation()`. Read by `TaskWorker` through a new `Storage.get_blobs_for_mrcall_conversation()`.

`migrate_blob_references(owner, dup, keeper)` gains a fifth step, `mrcall_blobs_migrated`, analogous to `whatsapp_blobs_migrated`, so Phase 1c reconsolidation preserves MrCall links on blobs merged during `reconsolidate_now`.

### D2 — Memory extraction: extend the `memory_message` trainer

Do **not** create `memory_mrcall.py`. The `memory_message.py` trainer is already channel-aware (post-WA Phase 2b: renamed from `memory_email`, accepts email + WhatsApp envelopes). Extend its META_PROMPT to declare a third envelope:

```
Channel: MrCall (phone call)
From: <contact_name> (<contact_phone>)
Subject: <subject>
At: <call_started_at>
Duration: <call_duration_ms / 1000>s
Transcript: <body.transcript|body.text|stringified body>
```

The prompt instructs the LLM to emit `Phone:` and `Name:` in `#IDENTIFIERS`. No new kind: the number goes into `kind='phone'`, so cross-channel match fires naturally against blobs the WA pipeline already created.

**Rationale for extending instead of creating a new trainer**: the envelope is only a textual wrapper; the extraction prompt is the same. One more trainer adds nothing but training redundancy and 3-4 synchronisation points. WA-parity Phase 2b already made exactly this call (`memory_email` → `memory_message`), and it worked.

### D3 — `MemoryWorker.process_mrcall_conversation(conv)` (mirroring `process_whatsapp_message`)

- Input: one `MrcallConversation` row.
- `_format_mrcall_data(conv)` produces the envelope above.
- Calls the same LLM with the `memory_message` prompt.
- For each entity: the same `_upsert_entity` pipeline (identifier-first match → cosine fallback → MERGE/CREATE → write `person_identifiers` rows).
- Writes the `mrcall_blobs(conv_id, blob_id)` link.
- Marks `mrcall_conversations.memory_processed_at = now()`.

Wire into `process_pipeline.py` step [3/5]: email loop → WA loop → MrCall loop (always filtered on `memory_processed_at IS NULL`).

The `[update.summary]` log line carries `mrcall_memory=A/B` alongside `memory=` and `wa_memory=`.

### D4 — `TaskWorker._analyze_recent_mrcall_events()` (mirroring the WA path)

- Iterates conversations with `memory_processed_at IS NOT NULL AND task_processed_at IS NULL`.
- Dedups by `(business_id, contact_phone)` the way WA dedups by `chat_jid`: if one contact has 3 unprocessed calls, we consider their aggregate event.
- For each aggregate event, collect `existing_tasks_all` =
  - **thread tasks**: `Storage.get_tasks_by_mrcall_conversation_id(owner, conv_id)` (new helper; first call → null, later calls match via `sources.mrcall_conversation_id`);
  - **contact tasks**: `Storage.get_tasks_by_contact_phone(owner, contact_phone)` (already exists post-WA Phase 3a; channel-agnostic);
  - **topical (F7)**: `Storage.get_blobs_for_mrcall_conversation(conv_id)` → `get_open_tasks_by_blobs(owner, blobs)` (helper already exists, already channel-agnostic).
- LLM with the task_creation system prompt and the MrCall envelope decides `task_action ∈ {create, update, close, none}` + `target_task_id`.
- CREATE: a new `TaskItem` with `channel='mrcall'`, `contact_phone=<phone>`, `contact_email=null`, `sources.mrcall_conversations=[conv_id]`, `sources.mrcall_conversation_id=<conv_id>` (first-touch, idempotent: later UPDATEs don't overwrite it).
- UPDATE: append conv_id to the existing `sources.mrcall_conversations`; stamp `sources.mrcall_conversation_id` if still null (the Fix-D guard is kept: F7 topical-blob siblings stay LLM context, NEVER auto-merge a CREATE onto a different customer's task).
- `_infer_task_channel` (or the current inline assignment) learns `'mrcall'`.

The F4 reanalyze sweep, F8 dedup sweep, F9 topic dedup and age-based auto-close are already channel-agnostic and inherit this for free (as WA did). The Fix-D restriction (`f5196e7f`) protects MrCall too.

### D5 — MrCall tab UI + cross-channel toggle (Phase 3 + Phase 4)

- `views/Mrcall.tsx`: a clone of `WhatsApp.tsx`. Lists the active business_id's conversations, click → ThreadPanel with `mrcall_conversation_id`. Top bar to switch business when `list_my_businesses` > 1.
- `components/ThreadPanel.tsx`: gains a `source.type === 'mrcall'` branch that calls `mrcall.getConversation` and renders the transcript (exact shape to be confirmed against the Phase 0 sample body — see Open Questions #1).
- Cross-channel pills: the `ThreadPanel` header shows "Email (N) / WhatsApp (M)" today; extend it to "Email (N) / WhatsApp (M) / MrCall (K)" when a task has ≥ 2 of the 3 channels in its sources. Logic from `b57fcc4f` (WA cross-channel) generalised to 3-way.
- `views/Settings.tsx`: a new "Connect MrCall" card launching the OAuth PKCE flow — mirroring `ConnectGoogleCalendar.tsx`. Once linked, the MrCall tab in `App.tsx` becomes `disabled: false`.

## Phasing

### Phase 0 — preparation and baseline verification

- **Sample body**: ask Mario to export 1-2 `mrcall_conversations` rows from a real profile (raw SQL is fine: `sqlite3 ~/.zylch/profiles/<uid>/zylch.db "SELECT id, contact_name, subject, body FROM mrcall_conversations LIMIT 2;"`). Understand the exact shape of `body` (transcript array? free text? markdown?) in order to define `_format_mrcall_data` and the renderer.
- Re-read `engine/docs/execution-plans/whatsapp-pipeline-parity.md` Phase 1c + Phase 2 — they are the literal template for this plan's Phase 1.
- Re-read this brief; answer the 6 design questions below.

**STOP. Mario confirms the sample body + the answers to the design questions. Do NOT start Phase 1 before that.**

### Phase 1 — `mrcall_blobs` table + memory extraction (D1 + D2 + D3)

A single landing, on the model of WA Phase 2 (which did 2a/2b/2c in one commit — they are functionally indivisible):

- **1a (storage)**: `MrcallBlob` model + storage helpers (`add_mrcall_blob_link`, `get_blobs_for_mrcall_conversation`, `get_unprocessed_mrcall_conversations`). `migrate_blob_references` extended with `mrcall_blobs_migrated`.
- **1b (trainer + worker)**: the `memory_message` trainer extended for the MrCall envelope. `_format_mrcall_data` in `workers/memory.py`. `MemoryWorker.process_mrcall_conversation`.
- **1c (pipeline)**: wire into `process_pipeline.py` step [3/5]. The `[update.summary]` log line carries `mrcall_memory=A/B`.
- **Tests**:
  - `tests/storage/test_mrcall_blobs.py` — add idempotency, FK CASCADE from both sides, `migrate_blob_references` with `mrcall_blobs_migrated`.
  - `tests/workers/test_memory_mrcall.py` — happy path; cross-channel merge into a pre-existing blob via the phone identifier (an existing "Jane Doe" blob carrying `Phone: +393...` captures Jane's MrCall call through identifier-first match); empty-body skip path; identifier extraction roundtrip.

**STOP. Mario clicks Update on a profile with MrCall conversations synced. He verifies:**
- `mrcall_blobs` is populated.
- An existing blob for a known contact (e.g. Jane Doe, who already has email + WA blobs) acquires the MrCall link, and NO duplicate blob is created.
- `[update.summary]` shows `mrcall_memory=N/N`.

### Phase 2 — task creation from MrCall (D4)

- `mrcall_conversations.task_processed_at` column (nullable, mirroring the `email_blobs`/`whatsapp_blobs` watermark pattern).
- `TaskWorker._analyze_recent_mrcall_events` mirroring the WA path. Dedup by `(business_id, contact_phone)`.
- `TaskItem.sources` JSON extended with `mrcall_conversations` + `mrcall_conversation_id`. Storage helper `update_task_item(add_source_mrcall_conversation=…, mrcall_conversation_id=…)` (mirroring WA Phase 3a's `add_source_whatsapp_message` + `whatsapp_chat_jid`).
- `task_items.channel='mrcall'` flowed through the MrCall task-creation branch (Open Question #4 confirms `'mrcall'` vs `'phone'`).
- The F4/F8/F9 sweeps inherit this (channel-agnostic).
- **IPC contract**: update `docs/ipc-contract.md`'s `tasks.list` payload with `sources.mrcall_conversations` + `sources.mrcall_conversation_id`.
- **Tests**: `tests/workers/test_tasks_mrcall.py` — a task created from a MrCall conv; a second call on the same contact updates the same task; email + WA + MrCall on the same person → ONE task with all three source arrays populated.

**STOP. Mario verifies in the app:**
- A recent MrCall call produces a `TaskItem` with `channel='mrcall'` and a non-empty `sources.mrcall_conversations`.
- A pre-existing task on an already-known contact (email/WA) is updated, not duplicated.
- `sources.mrcall_conversation_id` is stamped on the first call and idempotent on later ones.

### Phase 3 — MrCall tab UI + Connect flow

- `views/Mrcall.tsx`, a clone of `WhatsApp.tsx` (conv list + detail + business selector when >1).
- A new "Connect MrCall" card in `views/Settings.tsx` launching OAuth PKCE — mirroring `ConnectGoogleCalendar.tsx`. Once linked → tab enabled.
- New RPCs (`rpc/mrcall_actions.py`): `mrcall.listConversations(business_id?, limit=50, offset=0)`, `mrcall.getConversation(conversation_id)`. Owner-scoped like the rest of the contract.
- `app/src/preload/index.ts`: typed bindings.
- IPC contract documented.
- The MrCall tab in `App.tsx`: `disabled: !mrcallLinked` (gated on the presence of an OAuthToken with `provider='mrcall'` for the active profile — queried via `account.whoAmI()` or a dedicated `mrcall.isLinked()` RPC).
- ThreadPanel `mrcall` branch (fetch + transcript render).

**STOP. Mario verifies:**
- Clicking "Connect MrCall" in Settings → the OAuth flow completes → the tab enables.
- Clicking the MrCall tab → shows the linked business's real conversation list.
- Clicking a conv → ThreadPanel shows the formatted transcript.
- Opening a task with `channel='mrcall'` from the Tasks view → ThreadPanel renders the MrCall conversation (not email).

### Phase 4 — Email/WhatsApp/MrCall cross-channel toggle

- `ThreadPanel` header pills go from 2 to 3 values when a task has cross-channel sources.
- `ThreadSourceType` widened to `'email' | 'whatsapp' | 'mrcall'`.
- Generalise cross-channel detection in `Workspace.tsx`: today it is binary email-vs-WA; it needs to be N-way with `available = [...]` computed from `sources.emails?.length`, `sources.whatsapp_messages?.length`, `sources.mrcall_conversations?.length`.
- A synthetic (SQL) test as for WA Phase 4 cross-channel: force a task with sources from all three channels (Tom Lee email + Jane Doe WA + a MrCall call), verify the 3 pills show with the right counters and that instant switching works in every combination (E↔WA, E↔M, WA↔M, E↔WA↔M).
- **Revert after the test**, as for WA Phase 4: restore the original sources once verified.

**STOP. Mario verifies with the synthetic test + (ideally, but not blocking) with a naturally-occurring cross-channel task.**

## Files touched

```
engine/zylch/storage/models.py            +MrcallBlob, +mrcall_conversations.task_processed_at
engine/zylch/storage/storage.py           +add_mrcall_blob_link, +get_blobs_for_mrcall_conversation,
                                          +get_unprocessed_mrcall_conversations, +mark_mrcall_task_processed,
                                          +update_task_item(add_source_mrcall_conversation=…, mrcall_conversation_id=…),
                                          +get_tasks_by_mrcall_conversation_id,
                                          migrate_blob_references += mrcall_blobs_migrated
engine/zylch/workers/memory.py            +_format_mrcall_data, +process_mrcall_conversation
engine/zylch/workers/task_creation.py     +_analyze_recent_mrcall_events, _infer_task_channel learns 'mrcall'
engine/zylch/agents/trainers/memory_message.py  MrCall envelope in META_PROMPT
engine/zylch/services/process_pipeline.py wire the MrCall loops into steps [3/5] and [4/5]; [update.summary] += mrcall_memory mrcall_tasks
engine/zylch/rpc/mrcall_actions.py        +listConversations, +getConversation, +isLinked (for UI gating)
engine/zylch/rpc/methods.py               dispatch entries
engine/tests/storage/test_mrcall_blobs.py NEW
engine/tests/workers/test_memory_mrcall.py NEW
engine/tests/workers/test_tasks_mrcall.py NEW
docs/ipc-contract.md                      +tasks.list sources.mrcall_*, +mrcall.listConversations, +mrcall.getConversation, +mrcall.isLinked
app/src/preload/index.ts                  +mrcall.listConversations, +mrcall.getConversation, +mrcall.isLinked
app/src/renderer/src/types.ts             ThreadSourceType += 'mrcall', ZylchTask.sources.mrcall_*
app/src/renderer/src/App.tsx              MrCall tab gated on mrcall.isLinked()
app/src/renderer/src/views/Mrcall.tsx     NEW (mirrors WhatsApp.tsx)
app/src/renderer/src/views/Settings.tsx   new ConnectMrcallCard
app/src/renderer/src/components/ThreadPanel.tsx  'mrcall' branch + 3-way pills (N-way generalisation)
app/src/renderer/src/views/Workspace.tsx  N-way cross-channel detection
```

## Open design questions for Mario (answer BEFORE Phase 1)

1. **`body` shape**: is the transcript structured (e.g. `[{role: 'user'|'agent', text: '…', ts: …}]`) or free text / markdown? This determines (a) how `_format_mrcall_data` passes it to the LLM (do we want it `role`-tagged for clarity, or flat text?), and (b) how `ThreadPanel.tsx` renders it (bubbles aligned by role as in WA, or flat paragraphs).
2. **Memory for short / missed calls**: does a 5-second call (caller hangs up, no transcript) still produce a `MrcallConversation` with an empty or minimal body? Do we want to skip it in memory extraction (a wasted LLM call) or let the trainer see it? Recommend: skip when `body` is empty or the transcript-equivalent is < 50 chars.
3. **Task granularity**: one task per *conversation* (it is already a single event, no email-style thread) or do we group by `contact_phone` as WA groups by `chat_jid`? Recommend: the same granularity as WA — the "call John back" event can accumulate N conversation_ids on the same TaskItem through `sources.mrcall_conversations`, exactly as WA aggregates N message_ids onto the same task.
4. **`channel='mrcall'` vs reusing `'phone'`**: the value `'phone'` already exists as a legacy channel (never used in production but documented in the IPC contract). Recommend: a new **`'mrcall'`**, to distinguish it clearly from the generic "phone CRM", leaving `'phone'` for tasks derived from phone calls that do NOT go through MrCall (CRM contact, future feature).
5. **Multi-business**: if an owner has N MrCall businesses, do we sync all of them or only the "default" business (the one in `mrcall_link`)? Recommend: in Phase 1, only the default linked one (zero impact on the existing `sync_mrcall`); the Phase 3 UI adds a business selector when `list_my_businesses` > 1 (on-demand sync of the selected business).
6. **Connect flow**: replicate ConnectWhatsApp (a CTA inside an empty tab), or a Settings card like Connect Google Calendar? Recommend: **a Settings card** — more discoverable, the OAuth is set-and-forget, and it is consistent with Google Calendar, which uses the same PKCE pattern.

## Out of scope for this plan

- **Outbound** (`InitiateCallTool` + `SendSMSTool` registration in the factory + exposure to the agentic LLM solver). Kept separate because it touches the approval flow + agentic loop, independently of the ingestion pipeline. It will be the natural follow-up after Phase 4.
- **Server-side configurator** (`mrcall-agent`): out of repo. Business settings + variables are edited through the existing external chat configurator.
- **Calendar**, already done (`calendar_blobs`).
- **A new `'mrcall_phone'` kind** in `person_identifiers`: discarded. We reuse the existing `'phone'` for cross-channel match — simpler and more powerful (a single phone-based identifier namespace, zero migration). The "future kind `mrcall_phone`" reference in WA-parity Phase 1c was an architectural placeholder; revised here after establishing that `'phone'` suffices.
- **`MrCallConfiguratorTrainer` cleanup**: already done, orthogonal to this plan. The dead-code removal landed in `e5b2c2be`; the separate `cleanup-mrcall-configurator-deadcode.md` plan was deleted as obsolete in `0bec32e`.

## How to start the next session

1. Open this file. Re-read the discipline header.
2. Open `engine/docs/execution-plans/whatsapp-pipeline-parity.md` Phase 1c (storage + migrate) + Phase 2 (single-landing memory worker) + Phase 3 (task creation) — it is the literal template.
3. **Phase 0 BEFORE touching code**: ask Mario for (a) a sample body from 1-2 real `MrcallConversation` rows, (b) answers to the 6 design questions above. Do NOT start Phase 1 first.
4. Phase 1 = one PR (the complete memory pipeline: D1 + D2 + D3 + storage tests + memory-worker tests). Land it, Mario verifies in the app, then Phase 2.
5. NEVER claim "done" until Mario writes that it works. NEVER push to origin. NEVER commit without an explicit go-ahead.
