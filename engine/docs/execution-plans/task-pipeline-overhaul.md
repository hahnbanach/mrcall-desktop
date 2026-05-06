# Task pipeline overhaul

status: code complete; live Mac verification pending (single-shot review)
created: 2026-05-06

## Commit ledger

| Fase | Bug | Commit | Status |
|------|-----|--------|--------|
| 0    | F4 sweep gating | `cc66279` + `a59d42a` | shipped (pre-overhaul) |
| 1.1  | E — plural contact tasks | `3473348` | shipped |
| 1.2  | F — analyzed_at bump | `4048fd7` | shipped |
| 1.3  | B — calendar task_action | `d2aca2a` | shipped |
| 1.4  | C — silent reset trap | `01beaad` | shipped |
| 1.5  | D — F7 threshold per class | `89c9398` | shipped (later superseded by 3.1's index) |
| —    | A — auto-reply guard (regression hardening) | `b34667f` | shipped |
| 2.1  | F8 dedup sweep + reopen protection | `2491798` | shipped |
| 2.2  | manual cleanup RPCs + Settings buttons | `c8331b2` | shipped |
| 2.3  | G — identifier-based reconsolidation + diagnostic logs | `3a88e96` | shipped |
| 3.1  | email_blobs / calendar_blobs index + F7 refactor + backfill | `8af798f` | shipped |
| 3.2  | channel tag + Tasks-view filter | `ac43cbf` | shipped |
| 3.3  | age-based auto-close on phone tasks | `41f46b2` | shipped |
| 4    | UX polish + telemetry + docs | (this commit) | shipped |

## TL;DR

Il prodotto è inusabile finché 70+ task aperti restano nella lista. Il problema non è un singolo bug: è una catena di gap che si compongono. I commit `cc66279` (F4 sweep gira anche con `pending_tasks=0`) + `a59d42a` (min-age 24h → 1h) chiudono il primo anello. Ne mancano altri 7. Sotto: 4 fasi in ordine di dipendenza causale.

Ogni fase ha un criterio di done verificabile sul Mac (no unit-test = done — vedi system rules `engine/docs/system-rules.md`).

## Stato di partenza (dump live, 2026-05-06)

Profile UID `HxiZh...`, `EMAIL_ADDRESS=mario.alemi@gmail.com` (verified via `engine/scripts/diag_sent_email.py`):

- 74 open `action_required` task.
- ~30 task con `contact_email = notification@transactional.mrcall.ai` (telefonate non richiamate).
- Task del corso CNIT Salamone (`e30581f3`) ha `sent_in_thread=2` sul thread `<0BC008F8...@cnit.it>` — l'utente ha già risposto da una settimana.
- Task Omniaimpianti `cc962e54`: `sent_in_thread=4`. Task Ali Lotia `35b48cc6`: `sent_in_thread=4`. Tutti aperti nonostante user reply pre-esistente.
- Causa diretta del "non chiude mai": F4 reanalyze sweep era gated dietro `pending_tasks > 0` in `process_pipeline.py:133`. Per profili dove le sent mail recenti sono già `task_processed_at IS NOT NULL`, sweep non parte mai. Fixato in `cc66279`.

## Bug map (snapshot)

Tutti identificati durante la sessione del 2026-05-06. La fase indicata è dove vengono affrontati.

| ID | Bug | File | Fase |
|----|-----|------|------|
| A | F4 sweep gated da `pending_tasks > 0` | `process_pipeline.py:133` | **fix in `cc66279`** |
| A' | F4 min-age 24h era arbitrario | `process_pipeline.py:347-348` | **fix in `a59d42a`** |
| B | Calendar branch ignora `task_action` del LLM, crea task ogni event | `task_creation.py:854-876` | 1.3 |
| C | Reset silenzioso quando `open_tasks == 0` riprocessa 60d | `process_pipeline.py:121-132` | 1.4 |
| D | F7 skip totale per notification senders → ogni mail noreply duplica | `task_creation.py:362-453` | 1.5 |
| E | `get_task_by_contact` ritorna 1 (vs N) → LLM non vede tutti i candidati | `task_creation.py:330` + `storage.py:2570` | 1.1 |
| F | `update_task_item` non aggiorna `analyzed_at` → sweep ricicla stesso task | `storage.py:2754-2796` | 1.2 |
| G | Memory reconsolidation threshold 0.65 produce blob duplicati | `hybrid_search.py:148` + `memory.py:_upsert_entity` | 2.3 |
| H | Nessun comando manuale "dedup ora" | `rpc/methods.py` + UI Settings | 2.2 |

## Fase 0 — Verify

**Goal**: confermare che `cc66279` + `a59d42a` portano a chiusure visibili, prima di costruire altro sopra.

| Task | Done quando |
|------|-------------|
| Pull su Mac, restart app, click `Update` | sidecar.stderr stampa `[TASK] Reanalyze sweep: N of M eligible (cap=10, min_age_h=1)` |
| Conta task aperti prima/dopo | almeno il task Salamone primary `e30581f3` chiude. Idealmente Omniaimpianti `cc962e54` e Ali Lotia `35b48cc6` (entrambi `sent_in_thread=4`) anche |
| Se NESSUN task chiude pur eligible | indagare in `task_reanalyze.py:_build_user_content` — il prompt LLM non sta convincendo Sonnet a CHIUDERE. Gate per Fase 1 |

**Criterio**: numero open task scende ad almeno 71 (era 74 nel dump). Se sì, procedi. Se no, non ha senso fare altro: prima capisci perché reanalyze decide KEEP.

## Fase 1 — Stop the bleeding

**Goal**: nessun nuovo duplicato creato da `update`. A regime ogni nuova mail noreply CNIT/AIFOS NON deve generare un task in più.

### 1.1 — Bug E: `_collect` vede tutti i task del contact

`task_creation.py:330` chiama `get_task_by_contact` (singolare → ritorna `.first()`). `noreply@cnit.it` ha 5 task aperti, l'LLM ne vede 1. Decide UPDATE su quello → gli altri 4 restano duplicati eterni.

- **Change**: sostituire con `get_tasks_by_contact` (plurale, già esiste, `storage.py:2592`). Costruire `existing_tasks_all = thread_tasks + task_by_contact_list` con dedup by id.
- **Done**: nuova mail noreply CNIT entra → existing_task_context mostra TUTTI i task aperti del contact → LLM sceglie `target_task_id` corretto o NONE/UPDATE invece di CREATE.

### 1.2 — Bug F: `update_task_item` aggiorna `analyzed_at`

`storage.py:2754-2796`. Quando F4 dice UPDATE, `analyzed_at` resta vecchio. Il sweep al run successivo lo rivede come eligible (oldest first), spreca una call LLM, l'LLM dice di nuovo "no change", loop.

- **Change**: aggiungere `task.analyzed_at = datetime.now(timezone.utc)` in `update_task_item`.
- **Done**: log mostra che lo stesso task non rientra nei "candidates" del sweep al ciclo successivo entro 1h.

### 1.3 — Bug B: calendar branch onora `task_action`

`task_creation.py:854-876`. F7-calendar surface i task esistenti, ma il caller scarta `task_action`/`target_task_id` e chiama `store_task_item` ogni volta. Sui calendar event ricorrenti = task duplicato per ogni occurrence.

- **Change**: replicare la logica di `_collect`/Phase 2 dell'email branch — risolvere `target_task` da `existing_tasks_all` (cal_related), gestire i 4 casi (close/update/create/none), validare `action_required`.
- **Done**: calendar event sync con summary "Corso CNIT" e cnit-blob match → log mostra `Converting create→update on cal task=...` invece di sempre create.

### 1.4 — Bug C: rimuovere la trap del reset silenzioso

`process_pipeline.py:121-132`. Se l'utente azzera tutti i task manualmente, il prossimo `update` resetta `task_processed_at` 60 giorni → ricrea tutti i task storici. Auto-rigenerante.

- **Change**: rimuovere il blocco. Il commento dice "handles transition from old code that deleted all tasks" — quella migrazione è di mesi fa, non serve più. Se serve davvero un reset, c'è già `--force` come flag esplicito.
- **Done**: chiudo manualmente N task → click `Update` → conta task aperti = 0 (non N nuovi).

### 1.5 — Bug D: F7 sui notification senders, ma con threshold elevato

Skip totale dei `noreply/notification/etc.` è troppo grossolano: AIFOS, ISTAT, CNIT-noreply etc. mai dedupati. Ma il caso `MrCall Notification → 35 task non correlati` era reale.

- **Change**: in `task_creation.py:362-453`, rimuovere lo skip incondizionato. Aumentare la soglia per i notification senders (`TOPICAL_MIN_SCORE = 0.50` invece di 0.30 quando `_is_notification`). I task MrCall hanno blob anchor sulla piattaforma stessa con score < 0.5; CNIT/AIFOS/topical real con score > 0.5.
- **Done**: nuova mail AIFOS noreply su un corso esistente → log mostra `[TASK] F7 topical-sibling tasks added=N`. Il LLM converte create→update su task esistente.

**Esce dalla Fase 1**: i 70+ task non aumentano più di run in run.

## Fase 2 — Cleanup storico

**Goal**: i task duplicati creati prima di Fase 1 vengono chiusi automaticamente o via comando.

### 2.1 — F8: open-task dedup sweep deterministica + LLM-arbitro

- **File nuovo**: `engine/zylch/workers/task_dedup_sweep.py` (~200 righe).
- **Algoritmo**:
  1. Carica tutti gli open `action_required` task (`get_task_items(action_required=True, limit=10000)`).
  2. Cluster deterministico: union-find su (a) stesso `contact_email` (canonical lower-trim), (b) blob overlap ≥ 2 fra `task_i.sources.blobs` e `task_j.sources.blobs`.
  3. Per ogni cluster ≥2: chiamata Opus arbitro — input compatto (no body), domanda: "stesso problema? Se sì, designa keeper". Tool_use JSON `{is_duplicate_group, keeper_id?, reason}`.
  4. Chiudi i non-keeper con `complete_task_item(id, note=f"Duplicate of {keeper_id} (auto-merged by update sweep)")`.
- **Schema migration**: nuova colonna `task_items.dedup_skip_until` (Integer epoch nullable, applicata via `_apply_column_migrations` come `close_note`).
- **`tasks.reopen` set `dedup_skip_until = now + 7d`**: F8 esclude i task con skip attivo da entrambi i lati. Niente ping-pong.
- **Hook**: chiamata dopo `_reanalyze_sweep` in `process_pipeline._run_tasks` e nel nuovo `_reanalyze_only` (introdotto da `cc66279`).
- **Done**: i 30 task `notification@transactional.mrcall.ai` con call-back diversi vengono raggruppati per `contact_email` → cluster di 30 → Opus dice "tutti diversi, NESSUNO è duplicato" → restano. Cluster Salamone-email + Salamone-call con stesso topical-blob → Opus dice "stesso problema" → uno chiuso.

### 2.2 — Bug H: comandi manuali di cleanup

L'utente vuole un bottone "ripulisci ora", per non aspettare il prossimo `update`.

- **File**: `engine/zylch/rpc/methods.py` nuove RPC `tasks.dedup_now()` e `memory.reconsolidate_now()`.
- **App**: pulsante in Settings → "Clean up tasks" / "Reconsolidate memory".
- **Done**: click → notification stream → "Closed N duplicates across M groups", lista task aggiornata.

### 2.3 — Bug G: capire perché 8 blob "Salamone PERSON"

`hybrid_search.py:148` ha `RECONSOLIDATION_THRESHOLD = 0.65`. La `reconsolidation` cerca per CONTENT del nuovo blob, non per ENTITY identifier. Due "Salamone" da mail diverse hanno content diverso → score < 0.65 → blob nuovo invece di merge.

- **Indagine prima** (mezza giornata): inserire log in `_upsert_entity` (`memory.py:160-221`) che stampa per ogni nuovo blob "Salamone" i top-3 candidati con score. Capire perché quello giusto è < 0.65.
- **Fix probabile**: usare gli `IDENTIFIERS` (Email, Phone) come search query invece del content full. Una mail Salamone include `Email: c.salamone@cnit.it` — query su quello matcha esattamente il blob esistente.
- **Done**: nuova mail Salamone → log mostra match 0.85+ con blob esistente → `Reconsolidated blob ... with email ...`. Niente nuovo blob.

## Fase 3 — Strutturale

**Goal**: sostituire euristiche con index. Il sistema diventa deterministico e debuggabile.

### 3.1 — `email_blobs` association table

Già discussa nel commit di F7 (`a2d6d53`) come "the cleaner long-term architecture, NOT in this commit".

- **Schema**: `email_blobs(email_id, blob_id)` PK; index su `blob_id`. Stessa pattern per `calendar_blobs`.
- **Memory worker**: `_upsert_entity` in `workers/memory.py` scrive `(source_email_id, blob_id)` su ogni upsert.
- **Backfill**: `engine/scripts/backfill_email_blobs.py` parsing del campo strutturato `blob.event_description = "Extracted from email <id>"`. Idempotente.
- **F7 refactor in `_collect`**: usa `Storage.get_blobs_for_email(new_email_id)` → `Storage.get_open_tasks_by_blobs(blobs)`. Niente più `hybrid_search` come bridge.
- **Skip noreply rimosso completamente**: con index esatto, una mail noreply restituisce solo i SUOI blob, non un anchor di rete. Il rumore del MrCall Notification sparisce a monte.
- **Done**: esegui backfill → conta `SELECT COUNT(*) FROM email_blobs ≈ N×K` (N email × K blob/email). Su una mail Salamone nuova, log F7 mostra `matched_blobs=3 (via index, not search)`.

### 3.2 — Tag canale per i task

Oggi tutti i task vivono nello stesso flusso. Le 30+ "call-back" task da `notification@transactional.mrcall.ai` non sono e-mail-actionable: sono telefonate. Mescolarle con email-task confonde l'UX e il LLM.

- **Schema**: aggiungere `task_items.channel ENUM('email','calendar','phone','whatsapp')`.
- **Engine**: popolato in `_collect` / calendar branch / mrcall branch (quando esisterà).
- **App**: filtro nella Tasks view "Solo email / Solo phone / Tutto".
- **Done**: 30 task `phone` separati visivamente da quelli `email`. L'utente li gestisce in batch.

### 3.3 — Auto-close su age per call-back task

Una telefonata di 2 mesi fa che non hai richiamato non è più actionable.

- **File**: nuovo step nella sweep che declassa o chiude task `channel='phone'` con `created_at < 30d` ago.
- **Done**: lista call-back si riduce da 30 a quelli realmente recenti.

## Fase 4 — UX polish

### 4.1 — Diff visibile su `update`

`update.run` già ritorna `{created, closed, updated}` in `methods.py:688-820`. Verifica che la UI lo mostri (toast / status panel) — l'utente deve vedere "Closed 5 stale tasks" senza aprire stderr.

### 4.2 — Documenti

`engine/docs/active-context.md`: aggiornare la sezione "Task auto-close" con il flow nuovo (F4 sempre, F8 deterministica, channel tags). Rimuovere F1-F7 dettagli che a fine di tutto questo sono storici, lasciare il flow corrente.

### 4.3 — Telemetry minima

Log strutturato per ogni `update`: `[update.summary] sync=+12 mem=+12 tasks created=2 closed=5 dedup=3 swept=10`. Quando il prodotto è in produzione e un utente lamenta "non funziona", quel log è la prima cosa da chiedere.

## Fuori scope (orthogonal)

- Refactor LLM transport (BYOK/MrCall credits) — funzionante.
- Firebase signin / Calendar OAuth — funzionante.
- Release pipeline (Windows signing, etc.) — separato.
- Memory worker channel coverage WhatsApp / MrCall raw — esiste solo per blob extraction, non per task creation.
- F6 sibling-thread improvement — già ragionevole.

## Stima sforzo

| Fase | Giorni effettivi | Confidence |
|------|------------------|------------|
| 0 | 0.1 | alta |
| 1 (1.1-1.5) | 1.5 | alta |
| 2.1 + 2.2 | 1.5 | media |
| 2.3 | 0.5-2 | bassa (dipende dall'indagine) |
| 3.1 | 1.5 | alta |
| 3.2 + 3.3 | 1 | media |
| 4 | 0.5 | alta |
| **Totale** | **6-8 giorni** | **media** |

Calendario realistico con verifica live a ogni fase: 2-3 settimane wall-clock.

## Punti di decisione

Dopo ogni fase, gate verifica live prima di proseguire:

- Dopo Fase 0 → `cc66279` funziona davvero? Se no, indaga prima.
- Dopo Fase 1 → no nuovi duplicati arrivano in 24h di uso normale.
- Dopo Fase 2 → i 70 task scendono a una decina sostenibile.
- Dopo Fase 3 → sistema deterministico, niente più euristiche `hybrid_score >= 0.30`.

## Riferimenti

- Diagnostica: `engine/scripts/diag_sent_email.py` (commit `6255ce6`).
- Origini F1-F7: `engine/docs/execution-plans/fix-task-autoclose-stale.md` (F1-F4) + commit `20c06f5` (F5), `533b114` (F6), `a2d6d53` (F7), `955016c` (F7-calendar).
- Stato corrente engine: `engine/docs/active-context.md` "Task auto-close" + "Task creation — F7 topical-sibling".
