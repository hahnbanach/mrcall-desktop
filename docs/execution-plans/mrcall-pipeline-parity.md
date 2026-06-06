---
status: in-progress (Livello A landed 2026-05-20; Livello B = phone-call memory ingestion, next)
owner: cross-cutting (engine + app + IPC)
created: 2026-05-19
template: engine/docs/execution-plans/whatsapp-pipeline-parity.md
discipline: |
  Standard regole Mario. NEVER claim a feature is "fixed", "done", or
  "verified" until Mario has clicked / used it himself in the real
  Electron app and reported back. Unit tests, typecheck, RPC probes,
  log lines do NOT count. One change at a time. Tell Mario exactly
  what to test. Wait. NEVER push to origin. NEVER commit until Mario
  says "funziona". Italian register in the chat.
---

# MrCall pipeline parity + cross-channel toggle

> **Stato 2026-05-20** (live-verified by Mario, on `worktree-sprightly-floating-anchor`):
> - **Prerequisite DONE** — legacy delegated/PKCE OAuth2 + `/mrcall` command surface + `mrcall_link` removed; StarChat reached via Firebase JWT only.
> - **Livello A (read-only customer-service lookup) DONE** — MrCall tab lists + searches businesses (`mrcall.list_my_businesses`, `mrcall.search_businesses`; StarChat role-scopes admin cross-owner vs owner own-only). Onboarding unblocked for MrCall-only users + in-wizard Calendar session fix.
> - **Livello B (phone-call memory + task ingestion — the D1–D5 plan below) = NEXT.** `sync_mrcall` is currently a graceful no-op; it must be reimplemented over the **Firebase JWT path** (`{realm}/customer/conversation/search`, NOT `delegated_`) before Livello B. StarChat's `FirebaseCustomerConversationService` already hard-scopes conversation search to the caller's uid (so "only own businesses' calls" is enforced server-side), but add a defence-in-depth owner filter before ingestion anyway — Mario's hard constraint: never put another owner's contacts/calls into memory.

## Cosa Mario ha chiesto

> "Inglobare MrCall. Il tab MrCall è ancora un placeholder disabilitato.
>  Il workstream WhatsApp ha gettato le fondamenta (person_identifiers
>  con kind futura `mrcall_phone` citata in Phase 1c, pattern `*_blobs`
>  join table, F7 cross-channel). Il modello `MrcallConversation` e
>  `StarChatClient` OAuth2 esistono lato engine ma niente li processa.
>  Plan analogo a WA parity, 4 fasi: memory extraction → task creation
>  → UI MrCall tab → cross-channel toggle MrCall/email/WA nel Source
>  panel."

Due obiettivi accoppiati, identici al WhatsApp plan:

1. **Pipeline parity**: ogni `MrcallConversation` passa attraverso memory
   extraction + task creation, stessa via di email e WhatsApp oggi.
2. **Cross-channel identity**: un blob su John Smith mette insieme
   email + WA + telefonata MrCall; UN task su John indipendentemente
   da quale dei tre canali lo ha innescato.

## Stato attuale: cosa esiste vs cosa manca

### Engine — esiste ✅

| Pezzo | Dove | Note |
|---|---|---|
| `MrcallConversation` model | `storage/models.py:575` | PK text, owner_id-scoped, `memory_processed_at` già presente (mirror di Email + WhatsAppMessage), `contact_phone`/`contact_name`, `subject`/`body` JSON, `custom_values` JSON, `raw_data`, `call_duration_ms`, `call_started_at` |
| `OAuthToken` provider='mrcall' | `storage/models.py:349` | Flusso completo PKCE in `tools/mrcall/oauth.py`, refresh in `_refresh_token_if_needed` |
| `StarChatClient` | `tools/starchat.py:13` | CRUD contatti, business config, variables, `initiate_outbound_call` |
| `sync_mrcall()` | `services/sync_service.py:142` | Già funzionante: chiama `/mrcall/v1/delegated_{realm}/customer/conversation/search`, scrive in `mrcall_conversations`. Wired nel pipeline (`run()` linea 495 via `_sync_mrcall_if_connected`) |
| `InitiateCallTool` + `SendSMSTool` | `tools/call_tools.py`, `tools/sms_tools.py` | Codice esiste; **NON registrati** in `factory.create_all_tools()`. Fuori dallo scope di questo plan (vedi Out of scope). |
| RPC `mrcall.list_my_businesses` | `rpc/mrcall_actions.py:37` | Solo metodo del namespace lato server |
| `PersonIdentifier` con kind `'phone'` | `storage/models.py:314` | Già condivisibile per cross-channel match: il numero MrCall si scrive in `kind='phone'` e si aggancia al blob email/WA esistente. **Niente kind nuovo `'mrcall_phone'`** — vedi Out of scope. |

### Engine — manca ❌

- **No `MrcallBlob` join table** (analogo a EmailBlob/CalendarBlob/WhatsAppBlob).
- **No `MemoryWorker.process_mrcall_conversation()`** — `process_email` + `process_whatsapp_message` esistono; MrCall path zero.
- **No envelope MrCall nel trainer `memory_message`** — oggi il META_PROMPT menziona email + WhatsApp; manca il terzo envelope (phone call con transcript).
- **No `TaskWorker._analyze_recent_mrcall_events()`** — `_analyze_recent_email_events` + `_analyze_recent_whatsapp_events` esistono; MrCall zero.
- **`task_items.channel = 'mrcall'`** mai usato (la column accetta qualsiasi stringa, basta scriverla).
- **Storage helpers mancanti**: `add_mrcall_blob_link`, `get_blobs_for_mrcall_conversation`, `get_unprocessed_mrcall_conversations`, `mark_mrcall_task_processed`, `update_task_item(add_source_mrcall_conversation=…)`.
- **`migrate_blob_references` da estendere** con `mrcall_blobs_migrated` (analogo a `whatsapp_blobs_migrated` Phase 1c WA), così la Phase 1c reconsolidation preserva i link MrCall sui blob mergiati.
- **Pipeline wiring**: `process_pipeline.py` step [3/5] memory loop, step [4/5] task loop da estendere per MrCall.
- **RPC methods**: `mrcall.listConversations`, `mrcall.getConversation` (forma analoga a `whatsapp.listMessages`).
- **Sources schema extension**: `task_items.sources.mrcall_conversations` + `sources.mrcall_conversation_id` (analogo a `whatsapp_chat_jid`).
- **Column `mrcall_conversations.task_processed_at`** (mirror dello stesso pattern email + WA).

### App — manca ❌

- **Tab MrCall**: disabled placeholder in `App.tsx:643-646` (`disabled: true, disabledTitle: 'Not connected'`).
- **View `Mrcall.tsx`** (mirror `WhatsApp.tsx`): lista conversazioni, dettaglio con trascrizione, filtro per business_id se ne hai più di uno.
- **Connect MrCall**: oggi unico entry è CLI `zylch init`. Da aggiungere come card in Settings (mirror di `ConnectGoogleCalendar.tsx`) o come vuoto-tab CTA (mirror di `ConnectWhatsApp.tsx`).
- **ThreadPanel branch MrCall**: oggi gestisce solo `email`/`whatsapp` (`ThreadSourceType`).
- **Cross-channel pills** in ThreadPanel: oggi mostra Email/WhatsApp; aggiungere MrCall → 3 valori, conteggi paralleli, fetch parallelo, instant tab switch.
- **Preload bindings** in `app/src/preload/index.ts`: namespace `mrcall.*` esiste con `list_my_businesses` solo; aggiungere `listConversations`, `getConversation`.
- **Type extension** in `types.ts`: `ThreadSourceType = 'email' | 'whatsapp' | 'mrcall'`, `ZylchTask.sources.mrcall_conversations?`, `sources.mrcall_conversation_id?`.

### IPC contract — manca ❌

- `tasks.list` payload: `sources.mrcall_conversations?: string[]` (lista di PK `MrcallConversation.id`) + `sources.mrcall_conversation_id?: string | null` (first-touch conv id, analogo a `whatsapp_chat_jid` per email).
- `mrcall.listConversations(business_id?, limit?, offset?)` — array di conversation row dicts.
- `mrcall.getConversation(conversation_id)` — single conversation con `body` (transcript) decoded.

## Architettura proposta (D1–D5, decisioni per Mario)

Lo schema replica esattamente quello che ha funzionato per WhatsApp.

### D1 — `mrcall_blobs` join table (mirror di `whatsapp_blobs`)

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

Scritto da `process_mrcall_conversation()`. Letto da `TaskWorker` via nuovo `Storage.get_blobs_for_mrcall_conversation()`.

`migrate_blob_references(owner, dup, keeper)` esteso con un quinto step `mrcall_blobs_migrated` analogo a `whatsapp_blobs_migrated`, così la Phase 1c reconsolidation preserva i link MrCall sui blob mergiati durante `reconsolidate_now`.

### D2 — Memory extraction: estendere `memory_message` trainer

**Non** creare `memory_mrcall.py`. Il trainer `memory_message.py` è già channel-aware (post-WA Phase 2b: rinominato da `memory_email`, accetta email + WhatsApp envelope). Estendere la sua META_PROMPT per dichiarare un terzo envelope:

```
Channel: MrCall (phone call)
From: <contact_name> (<contact_phone>)
Subject: <subject>
At: <call_started_at>
Duration: <call_duration_ms / 1000>s
Transcript: <body.transcript|body.text|stringified body>
```

Il prompt istruisce il LLM a emettere `Phone:` e `Name:` in `#IDENTIFIERS`. Niente kind nuovo: il numero va in `kind='phone'`, così cross-channel match scatta naturale contro blob già esistenti dalla pipeline WA.

**Rationale per estendere invece di creare un trainer nuovo**: l'envelope è solo un wrapper testuale; il prompt di extraction è lo stesso. Un trainer in più aggiunge solo training redundancy + 3-4 punti di sincronizzazione. La Phase 2b di WA-parity ha già fatto esattamente questa scelta (`memory_email` → `memory_message`), e ha funzionato.

### D3 — `MemoryWorker.process_mrcall_conversation(conv)` (mirror `process_whatsapp_message`)

- Input: una `MrcallConversation` row.
- `_format_mrcall_data(conv)` produce l'envelope di sopra.
- Chiama lo stesso LLM con prompt `memory_message`.
- Per ogni entità: stessa pipeline `_upsert_entity` (identifier-first match → cosine fallback → MERGE/CREATE → write `person_identifiers` rows).
- Scrive `mrcall_blobs(conv_id, blob_id)` link.
- Marca `mrcall_conversations.memory_processed_at = now()`.

Wire in `process_pipeline.py` step [3/5]: loop email → loop WA → loop MrCall (sempre filtrato per `memory_processed_at IS NULL`).

`[update.summary]` log line carries `mrcall_memory=A/B` accanto a `memory=` e `wa_memory=`.

### D4 — `TaskWorker._analyze_recent_mrcall_events()` (mirror WA path)

- Itera conversations con `memory_processed_at IS NOT NULL AND task_processed_at IS NULL`.
- Dedup per `(business_id, contact_phone)` come WA dedup per `chat_jid`: se un contatto ha 3 call non processate, ne consideriamo l'evento aggregato.
- Per ogni evento aggregato: colleziona `existing_tasks_all` =
  - **thread tasks**: `Storage.get_tasks_by_mrcall_conversation_id(owner, conv_id)` (nuovo helper, prima call → null; call successive matchano via `sources.mrcall_conversation_id`);
  - **contact tasks**: `Storage.get_tasks_by_contact_phone(owner, contact_phone)` (già esistente post-WA Phase 3a; channel-agnostic);
  - **topical (F7)**: `Storage.get_blobs_for_mrcall_conversation(conv_id)` → `get_open_tasks_by_blobs(owner, blobs)` (helper già esistente, già channel-agnostic).
- LLM con system prompt task_creation, envelope MrCall, decide `task_action ∈ {create, update, close, none}` + `target_task_id`.
- CREATE: nuovo `TaskItem` con `channel='mrcall'`, `contact_phone=<phone>`, `contact_email=null`, `sources.mrcall_conversations=[conv_id]`, `sources.mrcall_conversation_id=<conv_id>` (first-touch, idempotente: subsequent UPDATE non sovrascrivono).
- UPDATE: aggiungere conv_id a `sources.mrcall_conversations` esistente; stampare `sources.mrcall_conversation_id` se ancora null (Fix-D guard mantenuto: F7 topical-blob siblings restano LLM context, MAI auto-merge una CREATE su una task di un cliente diverso).
- `_infer_task_channel` (o l'assegnazione inline corrente) impara `'mrcall'`.

F4 reanalyze sweep, F8 dedup sweep, F9 topic dedup, age-based auto-close: già channel-agnostic, ereditano gratis (come WA). Fix-D restriction (`f5196e7f`) protegge anche MrCall.

### D5 — UI MrCall tab + cross-channel toggle (Phase 3 + Phase 4)

- `views/Mrcall.tsx`: clone di `WhatsApp.tsx`. Lista conversazioni dell'attivo business_id, click → ThreadPanel con `mrcall_conversation_id`. Top bar per switchare business se `list_my_businesses` > 1.
- `components/ThreadPanel.tsx`: gain branch `source.type === 'mrcall'` che fa `mrcall.getConversation` + renderizza trascrizione (forma esatta da confermare in Phase 0 sample body — vedi Open Questions #1).
- Cross-channel pills: `ThreadPanel` header oggi mostra "Email (N) / WhatsApp (M)"; estendere a "Email (N) / WhatsApp (M) / MrCall (K)" quando una task ha ≥ 2 dei 3 canali nelle sources. Logic da `b57fcc4f` (WA cross-channel) generalizzato a 3-way.
- `views/Settings.tsx`: nuova card "Connect MrCall" che lancia il flusso OAuth PKCE — mirror di `ConnectGoogleCalendar.tsx`. Quando linkato, il tab MrCall in `App.tsx` diventa `disabled: false`.

## Phasing

### Phase 0 — preparazione e verifica baseline

- **Sample body**: chiedere a Mario di esportare 1-2 row di `mrcall_conversations` di un profilo reale (raw SQL fine: `sqlite3 ~/.zylch/profiles/<uid>/zylch.db "SELECT id, contact_name, subject, body FROM mrcall_conversations LIMIT 2;"`). Capire la forma esatta di `body` (transcript array? testo libero? markdown?) per definire `_format_mrcall_data` e il renderer.
- Re-read `engine/docs/execution-plans/whatsapp-pipeline-parity.md` Phase 1c + Phase 2 — sono il template letterale di Phase 1 di questo plan.
- Re-read this brief; rispondere alle 6 design questions sotto.

**STOP. Mario conferma sample body + risposte design questions. NON partire con Phase 1 prima.**

### Phase 1 — `mrcall_blobs` table + memory extraction (D1 + D2 + D3)

Single landing, sul modello di Phase 2 WA (che fece 2a/2b/2c in un commit unico — sono funzionalmente indivisibili):

- **1a (storage)**: `MrcallBlob` model + storage helpers (`add_mrcall_blob_link`, `get_blobs_for_mrcall_conversation`, `get_unprocessed_mrcall_conversations`). `migrate_blob_references` esteso con `mrcall_blobs_migrated`.
- **1b (trainer + worker)**: trainer `memory_message` esteso per envelope MrCall. `_format_mrcall_data` in `workers/memory.py`. `MemoryWorker.process_mrcall_conversation`.
- **1c (pipeline)**: wire in `process_pipeline.py` step [3/5]. `[update.summary]` log line carries `mrcall_memory=A/B`.
- **Test**:
  - `tests/storage/test_mrcall_blobs.py` — idempotency add, FK CASCADE da entrambi i lati, `migrate_blob_references` con `mrcall_blobs_migrated`.
  - `tests/workers/test_memory_mrcall.py` — happy path; cross-channel merge into pre-existing blob via phone identifier (un blob "Jane Doe" già esistente con `Phone: +393...` cattura il MrCall di Jane via identifier-first match); empty body skip path; identifier extraction roundtrip.

**STOP. Mario clicca Update su profilo con MrCall conversations sincronizzate. Verifica:**
- `mrcall_blobs` popolata.
- Un blob esistente di un contatto noto (es. Jane Doe che ha già blob email + WA) acquisisce il link MrCall, NON viene creato un nuovo blob duplicato.
- `[update.summary]` mostra `mrcall_memory=N/N`.

### Phase 2 — task creation da MrCall (D4)

- `mrcall_conversations.task_processed_at` column (nullable, mirror `email_blobs`/`whatsapp_blobs` watermark pattern).
- `TaskWorker._analyze_recent_mrcall_events` mirror del WA path. Dedup per `(business_id, contact_phone)`.
- `TaskItem.sources` JSON esteso con `mrcall_conversations` + `mrcall_conversation_id`. Storage helper `update_task_item(add_source_mrcall_conversation=…, mrcall_conversation_id=…)` (mirror Phase 3a WA `add_source_whatsapp_message` + `whatsapp_chat_jid`).
- `task_items.channel='mrcall'` flowed via il branch task-creation MrCall (Open Question #4 conferma `'mrcall'` vs `'phone'`).
- F4/F8/F9 sweeps ereditano (channel-agnostic).
- **IPC contract**: aggiornare `docs/ipc-contract.md` `tasks.list` payload con `sources.mrcall_conversations` + `sources.mrcall_conversation_id`.
- **Test**: `tests/workers/test_tasks_mrcall.py` — task creata da MrCall conv; seconda call sullo stesso contatto aggiorna stessa task; email + WA + MrCall sullo stesso person → UNA task con tutti e tre i source array popolati.

**STOP. Mario verifica in app:**
- Un MrCall call recente produce una `TaskItem` con `channel='mrcall'` e `sources.mrcall_conversations` non vuoto.
- Una task pre-esistente su un contatto già noto (email/WA) viene aggiornata, non duplicata.
- `sources.mrcall_conversation_id` stampato sulla prima call, idempotente sulle successive.

### Phase 3 — UI MrCall tab + Connect flow

- `views/Mrcall.tsx` clone di `WhatsApp.tsx` (lista conv + dettaglio + business selector se >1).
- Nuova card "Connect MrCall" in `views/Settings.tsx` che lancia OAuth PKCE — mirror di `ConnectGoogleCalendar.tsx`. Quando linkato → tab abilitato.
- RPC nuovi (`rpc/mrcall_actions.py`): `mrcall.listConversations(business_id?, limit=50, offset=0)`, `mrcall.getConversation(conversation_id)`. Owner-scoped come il resto del contratto.
- `app/src/preload/index.ts`: bindings tipizzati.
- IPC contract documentato.
- Tab MrCall in `App.tsx`: `disabled: !mrcallLinked` (gated su presence di OAuthToken `provider='mrcall'` per il profilo attivo — query via `account.whoAmI()` o RPC dedicato `mrcall.isLinked()`).
- ThreadPanel branch `mrcall` (fetch + render trascrizione).

**STOP. Mario verifica:**
- Click "Connect MrCall" in Settings → flusso OAuth completa → tab si abilita.
- Click tab MrCall → mostra lista conversazioni reali del business linkato.
- Click su una conv → ThreadPanel mostra trascrizione formattata.
- Open di una task con `channel='mrcall'` da Tasks view → ThreadPanel renderizza la conversazione MrCall (non email).

### Phase 4 — cross-channel toggle Email/WhatsApp/MrCall

- `ThreadPanel` header pills da 2 a 3 valori quando una task ha sources cross-canale.
- `ThreadSourceType` widened to `'email' | 'whatsapp' | 'mrcall'`.
- Generalizzare la cross-channel detection in Workspace.tsx: oggi è binary email-vs-WA; serve N-way con `available = [...]` calcolato da `sources.emails?.length`, `sources.whatsapp_messages?.length`, `sources.mrcall_conversations?.length`.
- Test sintetico (SQL) come per WA Phase 4 cross-channel: forzare una task con sources di tutti e tre i canali (Tom Lee email + Jane Doe WA + MrCall call), verificare che le 3 pill si mostrino con counter corretto e switch instant funzioni in tutte le combinazioni (E↔WA, E↔M, WA↔M, E↔WA↔M).
- **Reverter post-test** come per WA Phase 4: ripristinare sources originali una volta verificato.

**STOP. Mario verifica con test sintetico + (idealmente, ma non bloccante) con una task cross-channel naturale.**

## Files toccati

```
engine/zylch/storage/models.py            +MrcallBlob, +mrcall_conversations.task_processed_at
engine/zylch/storage/storage.py           +add_mrcall_blob_link, +get_blobs_for_mrcall_conversation,
                                          +get_unprocessed_mrcall_conversations, +mark_mrcall_task_processed,
                                          +update_task_item(add_source_mrcall_conversation=…, mrcall_conversation_id=…),
                                          +get_tasks_by_mrcall_conversation_id,
                                          migrate_blob_references += mrcall_blobs_migrated
engine/zylch/workers/memory.py            +_format_mrcall_data, +process_mrcall_conversation
engine/zylch/workers/task_creation.py     +_analyze_recent_mrcall_events, _infer_task_channel learns 'mrcall'
engine/zylch/agents/trainers/memory_message.py  envelope MrCall in META_PROMPT
engine/zylch/services/process_pipeline.py wire MrCall loops in step [3/5] e [4/5]; [update.summary] += mrcall_memory mrcall_tasks
engine/zylch/rpc/mrcall_actions.py        +listConversations, +getConversation, +isLinked (per UI gating)
engine/zylch/rpc/methods.py               dispatch entries
engine/tests/storage/test_mrcall_blobs.py NEW
engine/tests/workers/test_memory_mrcall.py NEW
engine/tests/workers/test_tasks_mrcall.py NEW
docs/ipc-contract.md                      +tasks.list sources.mrcall_*, +mrcall.listConversations, +mrcall.getConversation, +mrcall.isLinked
app/src/preload/index.ts                  +mrcall.listConversations, +mrcall.getConversation, +mrcall.isLinked
app/src/renderer/src/types.ts             ThreadSourceType += 'mrcall', ZylchTask.sources.mrcall_*
app/src/renderer/src/App.tsx              tab MrCall gated su mrcall.isLinked()
app/src/renderer/src/views/Mrcall.tsx     NEW (mirror WhatsApp.tsx)
app/src/renderer/src/views/Settings.tsx   nuova ConnectMrcallCard
app/src/renderer/src/components/ThreadPanel.tsx  branch 'mrcall' + 3-way pills (generalizzazione N-way)
app/src/renderer/src/views/Workspace.tsx  cross-channel detection N-way
```

## Open design questions per Mario (rispondere PRIMA di Phase 1)

1. **`body` shape**: la trascrizione è strutturata (es. `[{role: 'user'|'agent', text: '…', ts: …}]`) o testo libero / markdown? Determina (a) come `_format_mrcall_data` la passa al LLM (vogliamo dare `role`-tagged per chiarezza, o flat text?), (b) come `ThreadPanel.tsx` la renderizza (bubbles allineate per role come WA, o paragrafi piatti).
2. **Memoria su chiamate brevi/perse**: una call di 5 secondi (caller hangup, no transcript) genera comunque `MrcallConversation` con body vuoto/minimale? Vogliamo skipparla in memory extraction (LLM call sprecata) o lasciare che il trainer la veda? Recommend: skip se `body` vuoto o transcript-equivalent < 50 char.
3. **Granularity dei task**: una task per *conversation* (è già un evento singolo, no thread tipo email) o vogliamo raggrupparle per `contact_phone` come WA per `chat_jid`? Recommend: stessa granularity di WA — l'evento "richiamare John" può accumulare N conversation_id sulla stessa TaskItem tramite `sources.mrcall_conversations`, esattamente come WA aggrega N message_id sulla stessa task.
4. **`channel='mrcall'` vs riusare `'phone'`**: il valore `'phone'` già esiste come canale legacy (mai usato in produzione ma documentato in IPC contract). Recommend: **`'mrcall'`** nuovo per distinguere chiaramente dal "phone CRM" generico, lasciando `'phone'` ai task derivati da telefoni che NON passano da MrCall (CRM contact, future feature).
5. **Multi-business**: se un owner ha N business MrCall, syncchiamo tutti, oppure solo il business "default" (quello in `mrcall_link`)? Recommend: in Phase 1 solo il default linked (zero impact su `sync_mrcall` esistente); Phase 3 UI aggiunge un business selector se `list_my_businesses` > 1 (sync su demand del business selezionato).
6. **Connect flow**: replica del ConnectWhatsApp (CTA dentro un tab vuoto), o card in Settings come Connect Google Calendar? Recommend: **card in Settings** — più discoverable, l'OAuth è set-and-forget, e per consistency con Google Calendar che ha lo stesso pattern PKCE.

## Out of scope di questo plan

- **Outbound** (`InitiateCallTool` + `SendSMSTool` registrazione in factory + esposizione al LLM agentic solver). Separato perché tocca approval flow + agentic loop, indipendente dalla pipeline di ingestion. Sarà naturale follow-up post-Phase 4.
- **Configuratore lato server** (`mrcall-agent`): out of repo. Le settings business + variables si toccano via chat configurator esterno, già esistente.
- **Calendar** già fatta (`calendar_blobs`).
- **Nuovo kind `'mrcall_phone'`** in `person_identifiers`: scartato. Riusiamo `'phone'` esistente per cross-channel match — più semplice e più potente (un solo namespace identificatore phone-based, zero migration). Il riferimento "future kind `mrcall_phone`" in WA-parity Phase 1c era un placeholder architetturale; rivisto qui dopo aver constatato che `'phone'` basta.
- **`MrCallConfiguratorTrainer` cleanup**: dead-code removal separato in [`cleanup-mrcall-configurator-deadcode.md`](cleanup-mrcall-configurator-deadcode.md), ortogonale a questo plan.

## Come iniziare la prossima sessione

1. Apri questo file. Re-read discipline header.
2. Apri `engine/docs/execution-plans/whatsapp-pipeline-parity.md` Phase 1c (storage + migrate) + Phase 2 (single-landing memory worker) + Phase 3 (task creation) — è il template letterale.
3. **Phase 0 PRIMA di toccare codice**: chiedi a Mario (a) sample body di 1-2 `MrcallConversation` reali, (b) risposte alle 6 design questions sopra. NON partire con Phase 1 prima.
4. Phase 1 = un PR (memory pipeline complete: D1 + D2 + D3 + test storage + test memory worker). Land, Mario verifica in app, poi Phase 2.
5. NEVER claim "done" finché Mario non scrive "funziona". NEVER push to origin. NEVER commit senza ok esplicito.
