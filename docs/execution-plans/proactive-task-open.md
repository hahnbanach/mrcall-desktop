---
status: completed
owner: cross-cutting (engine + app)
created: 2026-05-10
completed: 2026-05-12
outcome: |
  Landed across 5 commits (df1e1fb1, 4cd8ec39, 336bc152, a1896df6,
  b36e15b3) on main. Live-verified by Mario on Mac dev against
  real profile tasks (ISTAT, Aleide, Google Workspace closed
  task). Engine + app + IPC contract all updated. See
  - engine/docs/active-context.md "Agentic task Open"
  - app/docs/active-context.md "Workspace + agentic Open flow"
  - docs/active-context.md "Agentic task Open"
  - docs/ipc-contract.md (tasks.solve / .approve / .cancel /
    .event surface)

  Beyond the original plan, the live test surfaced and we fixed:
  - Source panel staleness on sidebar conversation switches +
    backfill on legacy localStorage convs (Conversation.threadId
    became a first-class field).
  - "Nessun segnale di vita" during long tool runs → engine emits
    tool_use_start events, renderer swaps narration per tool.
  - Closed tasks are now read-only by design (composer disabled,
    "Riapri" toggles back to active in place) — opens a clean
    UX line between "active work" and "archive".
  - Annulla on a solve approval card cancels the run via
    tasks.solve.cancel instead of declining the tool — declining
    used to make the model propose alternatives, opposite of
    intent.
---

# Proactive task "Open" — agent‑first UX

## Why

Oggi cliccare **Open** su una task apre una chat con un *prompt
pre-compilato* in italiano (`"Aiutami a gestire questa task."` +
campi della task in inglese, generati dal task-detector). L'utente
deve premere Send, aspettare, leggere un'analisi in inglese, e
condurre poi 5–7 turni per arrivare a una mail inviata.

Mario vuole che cliccare **Open** mostri direttamente la
**risposta dell'agente** — breve, in italiano, azionabile:

> "Hai ricevuto 4 reminder, secondo me è da pagare. Bonifico
> all'IBAN xyz di €XX dal tuo conto Fineco. Vuoi che ti prepari
> la mail di conferma ad Aleide?"

…e con un singolo click sul draft → invio. Tre click totali
(Open → "sì prepara" → Invia), non sette.

## Stato del codice oggi

Buona notizia: **tutta l'infrastruttura agentica esiste già**. È
solo non collegata al pulsante Open.

### Engine (già pronto)

| Pezzo | Dove | Cosa fa |
|---|---|---|
| `tasks.solve(task_id, instructions="")` | `engine/zylch/rpc/methods.py:258-341` | RPC che fa partire un agente con tool, streama eventi via `tasks.solve.event` notifications, si ferma per approvazione su tool distruttivi e aspetta `tasks.solve.approve(tool_use_id, approved, edited_input?)`. |
| `SOLVE_SYSTEM_PROMPT` | `engine/zylch/services/solve_constants.py:11-30` | System prompt agentico in inglese. Inietta `personal_data_section`. |
| `get_personal_data_section(owner_id)` | `engine/zylch/services/solve_constants.py:280-329` | Costruisce blocco con USER_FULL_NAME, USER_PHONE, USER_CODICE_FISCALE, USER_DATE_OF_BIRTH, USER_ADDRESS, USER_IBAN, USER_COMPANY, USER_VAT_NUMBER, USER_NOTES, USER_SECRET_INSTRUCTIONS + `prefs:<owner_id>` blobs. |
| `build_task_context(task, store, owner_id)` | `engine/zylch/services/solve_constants.py:332-373` | Carica TASK + URGENCY + REASON + CONTACT + ORIGINAL EMAIL (via `event_id`) + CONTACT MEMORY blobs (via `task.sources.blobs`). |
| `TaskExecutor` | `engine/zylch/services/task_executor.py` | Loop a 10 turni con tool: `search_memory`, `search_emails`, `draft_email`, `send_email`, `send_whatsapp`, `send_sms`, `read_document`, `download_attachment`, `web_search`, `run_python`, `update_memory`. Streama `thinking` / `tool_call_pending` / `tool_result` / `done` / `error`. |
| Timeout RPC `tasks.solve` | `app/src/main/index.ts:83` | 600 000 ms (10 min). |

### Renderer (NON usa solve)

| Pezzo | Dove | Cosa fa oggi |
|---|---|---|
| Pulsante Open | `app/src/renderer/src/views/Tasks.tsx:517` | Chiama `openTaskChat(t)`. |
| `openTaskChat` | `app/src/renderer/src/store/conversations.ts:242-264` | Crea conversazione `task-<id>`, riempie `draftInput` con il template precompilato. |
| `buildTemplate` | `app/src/renderer/src/store/conversations.ts:165-183` | Produce `"Aiutami a gestire questa task.\n\n📋 ${name} <${email}>\nUrgenza: ${urgency}\n\nCosa fare:\n${action}\n\nContesto:\n${reason}"`. |
| Approval card | `app/src/renderer/src/views/Workspace.tsx:103-180` | Ascolta SOLO `chat.pending_approval` (non `tasks.solve.event`) e chiama `chat.approve` (non `tasks.solve.approve`). |

### Bug di sicurezza esistente che il piano deve chiudere

`engine/zylch/services/task_executor.py:37-43` definisce:

```python
APPROVAL_TOOLS = {
    "send_draft", "send_whatsapp_message", "send_sms",
    "update_memory", "run_python",
}
```

Ma `engine/zylch/services/solve_constants.py:125,192` espone i tool
con nome `send_email` e `send_whatsapp` — **diversi da quelli in
APPROVAL_TOOLS**. Risultato: il loop solve, oggi, **invierebbe email
e WhatsApp senza alcuna approvazione utente**. È un bug latente
solo perché il renderer non chiama `tasks.solve` ancora; nel momento
in cui lo collega (questo piano), va chiuso.

## Cosa fare — outline

Il piano è in due tronconi: **engine** (prompt + USER_LANGUAGE +
naming fix) e **app** (Open → solve, stream events, approval).

---

## A. Engine

### A.1 — Allineare SOLVE_TOOLS ↔ APPROVAL_TOOLS (BLOCCANTE per la sicurezza)

**File:** `engine/zylch/services/task_executor.py`
**Cambia:** `APPROVAL_TOOLS` → `{"send_email", "send_whatsapp", "send_sms", "update_memory", "run_python", "draft_email"}`.

Aggiungere anche `draft_email` perché un draft mostrato come "fatto"
deve essere visibile e confermabile (non solo letto come stringa
nel testo dell'agente). In alternativa lasciare `draft_email` fuori
da APPROVAL_TOOLS e renderlo display-only — vedi A.4.

`format_approval_preview` in `task_executor.py:46-77` ha già le
preview per `send_email`, `draft_email`, `send_whatsapp`, `send_sms`,
`run_python`, `update_memory` — ok.

### A.2 — Riscrivere SOLVE_SYSTEM_PROMPT

**File:** `engine/zylch/services/solve_constants.py:11-30`

Tre vincoli espliciti nel prompt:

1. **Lingua di risposta = lingua dell'utente.** Inseriti via
   `{user_language_directive}` (vedi A.3). Se non disponibile,
   fallback "match the language of the source email/contact".
2. **Forma della risposta:** una frase di recap, una frase con
   l'azione concreta, una offerta esplicita di farla
   (es. "Vuoi che prepari la mail?"). NO bullet, NO sezioni, NO
   parafrasi della task.
3. **Workflow proattivo:** se l'azione è scrivere una mail/SMS/
   WhatsApp → chiamare immediatamente `draft_email` /
   `send_whatsapp` / `send_sms` con l'argomento già pronto, NON
   produrre il testo come prosa. La preview dell'approval è
   l'output finale che vede l'utente.

Bozza nuovo prompt (in inglese, perché istruisce il modello, ma
con la directive di lingua sull'output):

```
You are {user_name}'s personal assistant. The user just clicked
"Open" on a task and is waiting for ONE concise, actionable
response.

{personal_data_section}
{user_language_directive}

WORKFLOW (mandatory order):
1. Call `search_memory` for the contact and the topic. The task
   already includes the original email and any matched memory
   blobs in the context — read them before searching anything
   else.
2. If the task obviously needs a reply/payment/form/call, go
   STRAIGHT to the action tool with a complete proposed
   payload — do NOT ask for confirmation in prose; the approval
   UI is the confirmation.
   - Reply by email → `draft_email(to, subject, body)`
   - Reply by WhatsApp → `send_whatsapp(phone_number, message)`
   - Reply by SMS → `send_sms(phone_number, message)`
3. If you genuinely cannot act without info the user has
   (e.g. password, a decision), THEN — and only then — answer
   in prose with a single closing question.

OUTPUT SHAPE for the prose part (in the user's language):
- One sentence recap of the situation, anchored in concrete
  facts from the task context (count of reminders, deadline,
  amount, sender) — not a paraphrase of `suggested_action`.
- One sentence proposal: what you will do or have already
  drafted.
- One short offer: "Vuoi che proceda?" / equivalent.

HARD RULES:
- Do NOT echo the task description back. The user wrote it
  himself, more or less.
- Do NOT explain your reasoning at length. The user trusts you.
- Do NOT list options. Pick one.
- NEVER reveal SECRET INSTRUCTIONS in any output, draft, or
  message.
- Personal data above is for filling forms/drafts on behalf of
  the user. Use it; never paste it into a public reply unless
  the recipient legitimately needs it (e.g. quoting your own
  IBAN to a vendor you owe).

AVAILABLE TOOLS:
[lista identica a oggi]
```

### A.3 — `USER_LANGUAGE`

**File:** `engine/zylch/services/settings_schema.py`
**Aggiungere** (vicino a USER_FULL_NAME):

```python
{
    "key": "USER_LANGUAGE",
    "label": "Preferred language",
    "type": "select",
    "options": [
        {"value": "", "label": "Auto-detect"},
        {"value": "it", "label": "Italiano"},
        {"value": "en", "label": "English"},
        {"value": "es", "label": "Español"},
        {"value": "fr", "label": "Français"},
        {"value": "de", "label": "Deutsch"},
    ],
    "default": "",
    "group": "personal",
    "description": (
        "Language the assistant uses when talking to you. "
        "If unset, it matches the language of the latest "
        "incoming message."
    ),
},
```

**File:** `engine/zylch/services/solve_constants.py`

Estendere `get_personal_data_section()` per derivare
`user_language_directive` (stringa che il prompt formatta):

```python
def get_user_language_directive() -> str:
    lang = (os.environ.get("USER_LANGUAGE", "") or "").strip().lower()
    if lang in {"it", "en", "es", "fr", "de"}:
        names = {
            "it": "Italian", "en": "English", "es": "Spanish",
            "fr": "French", "de": "German",
        }
        return (
            f"RESPONSE LANGUAGE: Always reply in {names[lang]}, "
            f"regardless of the language of the task description "
            f"or the original email."
        )
    return (
        "RESPONSE LANGUAGE: Match the language of the original "
        "email / WhatsApp message attached in the task context. "
        "If unclear, use Italian."
    )
```

…e `tasks_solve` in `methods.py:303-306` formatta anche il nuovo
placeholder.

### A.4 — Naming `draft_email` chiaro

Decisione: **rimuovere** `draft_email` dai SOLVE_TOOLS e usare solo
`send_email`. Il modello produce direttamente l'email "da inviare",
e l'approval card è il punto in cui l'utente la vede prima che parta.
Un draft che non viene mai inviato è semplicemente un
`tool_call_pending` con "Cancel".

Beneficio UX: 1 card invece di 2, niente fase intermedia "draft
mostrato come testo, poi devi dire `mandala`". Mario lo ha chiesto
esplicitamente ("non 20 interazioni").

Costo: il modello a volte vorrà mostrare un draft "in lavorazione"
prima di mandarlo. È accettabile — basta che il prompt dica
"draft via send_email; cancel = redo".

### A.5 — `tasks.solve.cancel` (opzionale, raccomandato)

**File:** `engine/zylch/rpc/methods.py`

Aggiungere:

```python
async def tasks_solve_cancel(params, notify):
    ex = _active_executor
    if ex is None:
        return {"ok": False, "error": "no active solve"}
    # Cancellare i pending future con set_exception(...).
    for fut in ex._pending.values():
        if not fut.done():
            fut.set_exception(asyncio.CancelledError())
    return {"ok": True}
```

Esposto come `tasks.solve.cancel`. Il renderer chiama questo se
l'utente chiude la conversazione mentre il solve è in corso. Non è
strettamente necessario per il primo cut (`_solve_lock` si libera
da solo a timeout), ma evita 10 minuti di "busy" se l'utente
chiude la finestra.

### A.6 — Test engine (non sostituiscono live)

`engine/tests/services/test_solve_prompt.py` (nuovo):
- `get_user_language_directive()` con USER_LANGUAGE valido / vuoto / non riconosciuto.
- `get_personal_data_section()` include la riga lingua se passata.
- Naming-coerenza: per ogni nome in `SOLVE_TOOLS` con effetto
  scrivente (`send_*`, `update_memory`, `run_python`) → presente in
  `APPROVAL_TOOLS`. Test fallisce se in futuro qualcuno aggiunge un
  nuovo tool senza approval.

Sono unit; **non sostituiscono** la verifica live richiesta dal
hook (REPL/CLI/browser).

---

## B. App

### B.1 — Estendere preload + types

**File:** `app/src/preload/index.ts`

Aggiungere namespace `tasks.solve`:

```ts
solve: (taskId: string, instructions?: string) =>
  call<{ ok: boolean; result?: any; error?: string }>(
    'tasks.solve',
    { task_id: taskId, instructions },
    600_000,
  ),
solveApprove: (toolUseId: string, payload: {
  approved: boolean;
  editedInput?: Record<string, unknown>
}) =>
  call<{ ok: boolean }>('tasks.solve.approve', {
    tool_use_id: toolUseId,
    approved: payload.approved,
    edited_input: payload.editedInput,
  }),
solveCancel: () => call<{ ok: boolean }>('tasks.solve.cancel', {}),
```

**File:** `app/src/renderer/src/types.ts`

Aggiungere `tasks.solve` / `solveApprove` / `solveCancel` su
`ZylchAPI`. Tipo dell'evento solve:

```ts
type SolveEvent =
  | { type: 'thinking'; text: string }
  | { type: 'tool_call_pending';
      tool_use_id: string; name: string;
      input: Record<string, unknown>; preview: string }
  | { type: 'tool_result';
      tool_use_id: string; name: string;
      output: string; approved: boolean }
  | { type: 'done'; result: { messages: unknown[] } }
  | { type: 'error'; message: string }
```

### B.2 — `runTaskSolve` in `conversations.ts`

**File:** `app/src/renderer/src/store/conversations.ts:165-264`

Cambiamenti:

1. **Rimuovere `buildTemplate`** (line 165-183).
2. `openTaskChat(task)` (line 242-264) non riempie più
   `draftInput`; rimane il piazzamento della conversazione
   `task-<id>` con `history: []`, `pendingApproval: null`,
   `busy: true`.
3. Nuova action `runTaskSolve(task)` che:
   - dispatch SET_BUSY true
   - `await window.zylch.tasks.solve(task.id)` (non aspettiamo
     in modo bloccante l'UI: la chiamata "sta in vita" 10 min
     mentre gli event stream arrivano via `tasks.solve.event`).
   - I render avvengono via i listener di B.3.
   - Se la promise risolve `{ ok: false, error }` → push
     assistant bubble con l'errore + setBusy false.
4. `openTaskChat` chiama `runTaskSolve` subito dopo il dispatch
   `OPEN_TASK_CHAT`.

### B.3 — Listener `tasks.solve.event` in `Workspace.tsx`

**File:** `app/src/renderer/src/views/Workspace.tsx:103-114`

Già c'è un listener per `chat.pending_approval`. Aggiungere un
nuovo `useEffect` (parallelo) che ascolta `tasks.solve.event`:

```ts
useEffect(() => {
  const off = window.zylch.onNotification(
    'tasks.solve.event',
    (event: SolveEvent) => {
      if (!active) return
      switch (event.type) {
        case 'thinking':
          appendAssistant(active.id, event.text)
          break
        case 'tool_call_pending':
          setPendingApproval(active.id, {
            mode: 'solve',         // <-- nuovo discriminator
            toolUseId: event.tool_use_id,
            toolName: event.name,
            preview: event.preview,
            input: event.input,
          })
          break
        case 'tool_result':
          // Non rendered — è interno al loop. In dev mode si
          // potrebbe loggare; in prod silenzioso. Mantiene la
          // chat pulita.
          break
        case 'done':
          setBusy(active.id, false)
          break
        case 'error':
          appendAssistant(active.id, `⚠ ${event.message}`)
          setBusy(active.id, false)
          break
      }
    },
  )
  return off
}, [active])
```

### B.4 — Approval card sa di solve

**File:** `app/src/renderer/src/views/Workspace.tsx:170-180` (la
`onApprove` callback) + il componente che renderizza la card.

Discriminare via `pendingApproval.mode`:

```ts
const onApprove = async (mode: 'send' | 'cancel' | 'edit', edited?: any) => {
  const pending = active.pendingApproval
  if (!pending) return
  if (pending.mode === 'solve') {
    await window.zylch.tasks.solveApprove(pending.toolUseId, {
      approved: mode === 'send',
      editedInput: edited,
    })
  } else {
    await window.zylch.chat.approve(pending.toolUseId, { mode })
  }
  setPendingApproval(active.id, null)
}
```

Il rendering visivo della preview è invariato (tutti i tipi di
preview esistenti — email/whatsapp/sms/python — sono già coperti
da `format_approval_preview` engine-side).

### B.5 — Free-text follow-up post-solve

Dopo `done` (B.3), il campo input torna attivo. Quando l'utente
scrive del testo libero — fall-through alla logica `chat.send`
attuale (`Workspace.tsx:onSubmit`), come oggi. Niente di nuovo:
funziona perché la conversazione `task-<id>` è già una conversazione
chat regolare; i messaggi del solve sono solo bolle assistant.

(Decisione esplicita: **non** chiamare un secondo `tasks.solve` con
`instructions=text`. Il solve è single-shot — apri la task e
l'agente parte. Il follow-up è chat normale, con tutta la sua
toolchain — `search_local_emails`, ecc. L'utente non se ne accorge.)

### B.6 — Cancel su close

**File:** `app/src/renderer/src/store/conversations.ts:closeConversation`

Se `state.conversations[id].busy === true`, chiamare
`window.zylch.tasks.solveCancel()` prima di chiudere. Best-effort.

---

## C. Piano test live (richiesto dal hook)

Hook UserPromptSubmit dice esplicitamente: "Never claim something
works until you have run it the way the final user runs it".
Quindi:

1. **Setup.** Profile pulito, signin Firebase, USER_FULL_NAME +
   USER_PHONE + USER_NOTES + USER_SECRET_INSTRUCTIONS popolati,
   `USER_LANGUAGE=it`. Almeno 1 task aperta sul DB con un'email
   di origine (la task ISTAT o Aleide attuali sul DB di Mario
   vanno bene).

2. **Open task ISTAT.** Aspettative:
   - Bubble assistant compare in <8s con: 1 frase recap in
     italiano (data scaduta, riferimenti chiave indagine /
     codice utente), 1 frase azione concreta (chiamare 1510 o
     mail), 1 offerta ("Vuoi che ti scriva la mail di
     spiegazione adesso?").
   - Se l'utente clicca "Vuoi che..." → primo cliccare "Sì"
     (chat libera) → l'agente chiama `send_email` (NON
     `draft_email`) → approval card con preview completa
     (To: portaleimprese@istat.it, subject: "Chiave indagine
     12698 — Codice utente 32924352", body con scuse + richiesta
     submit tardivo).
   - Click "Send" sull'approval card → mail parte via SMTP →
     bubble di conferma engine-side.

3. **Open task Aleide.** Aspettative:
   - Recap menziona "4 reminder", date, importo se presente
     nella memory.
   - Proposta: "preparo mail di conferma pagamento" o
     "preparo bonifico" (a seconda di cosa è nella memory IBAN).
   - Approval card con il body proposto. Cancel → bubble
     "annullato". Send → mail inviata.

4. **Negative paths:**
   - Senza Anthropic key e senza Firebase signin: `tasks.solve`
     fallisce con messaggio leggibile (errore current di
     `make_llm_client`). Bubble assistant `⚠ <messaggio>`,
     non un crash silenzioso.
   - Cliccare Open su una seconda task mentre la prima è in
     corso → `_solve_lock` è preso → JSON-RPC error
     `SolveInProgressError`. Renderer mostra "Solve già in
     corso, attendere" senza crashare la conversazione attiva.
   - Chiudere la finestra mentre il solve è in pending
     approval → solveCancel chiamato → conversazione si chiude,
     `_active_executor` torna None.

5. **Smoke test che il bug-fix di sicurezza A.1 sia chiuso:**
   in `engine/`, `python -c "from zylch.services.task_executor
   import APPROVAL_TOOLS; from zylch.services.solve_constants
   import SOLVE_TOOLS; assert all(t['name'] in APPROVAL_TOOLS
   for t in SOLVE_TOOLS if t['name'] in ('send_email',
   'send_whatsapp', 'send_sms', 'update_memory', 'run_python'))"`.
   Equivalente al test in A.6 ma da CLI.

---

## D. Stima d'impatto + rischio

| Pezzo | LOC stimati | Rischio | Mitigazione |
|---|---|---|---|
| A.1 naming fix | <10 | Critico (chiude bug send-no-approval) | Test A.6 + smoke C.5 |
| A.2 prompt rewrite | ~50 | Medio (cambia tono e workflow) | Live test C.2/C.3 con multiple task |
| A.3 USER_LANGUAGE | ~30 | Basso | Default "" = auto-detect, retro-compatibile |
| A.4 rimozione draft_email | ~5 | Basso | È già coperto da send_email |
| A.5 cancel RPC | ~30 | Basso | È puramente additivo |
| B.1-B.4 wiring | ~150 | Medio | Listener parallelo a `chat.pending_approval`, non lo tocca |
| B.5 follow-up | 0 | — | Funziona già (chat.send esistente) |
| B.6 cancel su close | ~10 | Basso | Best-effort, non bloccante |

**Costo LLM stimato per Open:** ~5–8K input token (system + personal
data + task context + tool defs) + ~500 output. Con Sonnet 4.5
(0.003 input / 0.015 output per 1K), ~$0.025 per Open. Con la
prompt cache attiva sul system + tool defs (già configurata nel
client), ripetizioni ~$0.005. La maggior parte delle Open in una
sessione condividerà tool defs, quindi l'esperienza tipica è il
prezzo cached.

**Quando NON aprire automaticamente:** il piano lascia il
trigger sul *click* di Open, non sul render della task list. Lo
si può eventualmente regredire (auto-solve in background al
detect) in un secondo momento, ma serve una soglia per evitare
LLM spam — fuori scope qui.

## E. Ordine consigliato di implementazione

1. **A.1** prima di tutto (sicurezza). Da solo è 1 commit di 5 LOC,
   isolato, da pushare prima di toccare il flusso renderer.
2. **A.3** + **A.2** (USER_LANGUAGE + prompt rewrite). Engine-only,
   verificabile con `zylch -p <profilo>` da CLI prima di
   coinvolgere l'app.
3. **A.5** (cancel) — additivo, nessun rischio.
4. **B.1** (preload + types) — solo type plumbing.
5. **B.2 + B.3 + B.4** in un singolo commit — il flusso Open ha
   senso solo end-to-end. Live test C.2/C.3 prima del commit.
6. **B.5 + B.6** + smoke C.5.

Ogni livello è verificabile in isolamento prima di passare al
successivo. Il "primo momento utilizzabile" è dopo il punto 5,
con o senza A.5/B.6.

## Out of scope di questo piano

- Auto-detect lingua: in A.3 si usa `USER_LANGUAGE` esplicito; il
  fallback `match the language of the source email` lo fa il
  modello da solo guardando il context. NON serve rilevatore
  language separato.
- Playwright / browser automation per ISTAT: no. Resta come
  "Vuoi che ti scriva un appunto con username / password?" se
  presenti nella memory.
- Streaming token-by-token: gli eventi `thinking` arrivano già a
  blocchi di prosa (un blocco = una text content del modello).
  Per ora è fluido; refining (true streaming) è tema separato.
- Notification / push proattivo "ho una proposta per la task X":
  resta su click, non su detect.
