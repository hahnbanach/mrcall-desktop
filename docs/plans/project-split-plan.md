# Piano di Separazione: mrcall-agent + zylch-standalone

**Data**: 2026-04-01
**Stato**: Da validare con sessione mrcall-agent
**Autore**: Sessione zylch-standalone (QA)

---

## Contesto

Zylch ha oggi due funzioni in un solo codebase:
1. **Configuratore MrCall** — SaaS, multi-tenant, configura assistenti telefonici
2. **Assistente alla vendita** — locale, mono-utente, intelligenza commerciale

I requisiti sono opposti. La condivisione di codice è minima.
Decisione: **due repository separati**.

## Architettura Target

### mrcall-agent (`~/hb/zylch` → rinominare repo)

```
Tipo:           SaaS multi-tenant
DB:             PostgreSQL esterno (Scaleway Managed)
Auth:           Firebase (talkmeapp)
Email:          IMAP + app password (non più OAuth)
Calendario:     Non necessario (MrCall non usa calendario)
WhatsApp:       mrzappa (StarChat, basato su whatsmeow, multi-tenant)
LLM:            Anthropic diretto (web search, streaming)
Embeddings:     fastembed + pgvector
Deploy:         Scaleway K8s (ARM64), GitLab CI
API:            - Pubblici: /api/chat/message/stream (dashboard SSE)
                - Privati: /api/mrcall/* (StarChat, rete interna)
Scalabilità:    Uvicorn workers + background job queue
```

**Cosa tiene da zylch/**:
- `agents/mrcall_agent.py`, `mrcall_context.py`, `mrcall_templates.py`
- `agents/mrcall_memory.py`, `mrcall_error_handler.py`
- `agents/trainers/mrcall_configurator.py`
- `tools/mrcall/` (config_tools, feature_context, variable_utils)
- `tools/starchat.py`, `tools/base.py`, `tools/session_state.py`
- `tools/factory.py` (ToolFactory, ridotto a ~589 righe dopo split)
- `services/chat_service.py` (streaming SSE)
- `services/job_executor.py` (background jobs)
- `storage/storage.py` (classe `Storage`, ex SupabaseStorage)
- `storage/database.py`, `storage/models.py` (modelli ridotti)
- `memory/` (pgvector, fastembed, reconsolidation)
- `api/routes/chat.py`, `mrcall.py`, `webhooks.py`, `auth.py`
- `llm/` (Anthropic direct client)

**Cosa elimina**:
- `tools/gmail_tools.py`, `tools/email_sync_tools.py` (split da factory)
- `tools/contact_tools.py`, `tools/crm_tools.py` (split da factory)
- `tools/gmail.py`, `outlook.py`, `gcalendar.py`, `outlook_calendar.py`
- `tools/pipedrive.py`, `sendgrid.py`, `sms_tools.py`
- `tools/email_sync.py`, `email_archive.py`, `calendar_sync.py`
- `agents/emailer_agent.py`, `task_orchestrator_agent.py`
- `agents/trainers/task_email.py`, `memory_email.py`, `emailer.py`
- `workers/task_creation.py`
- `services/sync_service.py`, `services/command_handlers.py`
- `api/routes/sync.py`, `connections.py`, `commands.py`
- `integrations/` (provider registry — MrCall non usa /connect)
- `frontend/` (dormant)

**Cosa aggiunge**:
- IMAP client per accesso email (supporto MrCall, non sync massiva)
- Endpoint privati con auth separata (API key o rete interna)

---

### zylch-standalone (`~/private/zylch-standalone` → questo repo)

```
Tipo:           CLI locale, mono-utente
DB:             SQLite (un file in ~/.zylch/zylch.db)
Auth:           Nessuna
Email:          IMAP + app password
Calendario:     CalDAV (Google, Outlook, iCloud — nessun OAuth)
WhatsApp:       GOWA locale (go-whatsapp-web-multidevice)
LLM:            BYOK multi-provider (Anthropic preferito)
Embeddings:     fastembed + numpy in-memory (vettori in SQLite BLOB)
Deploy:         pipx install zylch
CLI:            Integrata (non repo separata)
Config:         zylch init → scrive .env + .env.example
```

**Cosa tiene da zylch/**:
- `memory/` (embeddings.py con fastembed, refactored per SQLite + in-memory search)
- `agents/trainers/task_email.py` (incremental prompt, auto dopo sync)
- `agents/trainers/memory_email.py` (PERSON priority)
- `agents/emailer_agent.py`
- `agents/task_orchestrator_agent.py`
- `tools/base.py`, `tools/session_state.py`, `tools/factory.py`
- `tools/gmail_tools.py` → refactored per IMAP
- `tools/email_sync_tools.py` → refactored per IMAP
- `tools/contact_tools.py`, `tools/crm_tools.py`
- `services/command_handlers.py` (slash commands, `/email search` FTS)
- `services/chat_service.py` (adattato per CLI, auto-sync, no SSE)
- `workers/task_creation.py` (user_email da oauth_tokens, no MY_EMAILS env)
- `storage/storage.py` (classe `Storage`, adattata per SQLite)
- `llm/` (multi-provider via aisuite)

**Cosa elimina**:
- `tools/mrcall/` (tutto)
- `tools/starchat.py`
- `agents/mrcall_*.py` (tutto)
- `agents/trainers/mrcall*.py` (tutto)
- `api/` (niente FastAPI, niente HTTP server)
- `storage/models.py` (29 modelli → ~10 per SQLite)
- `storage/database.py` (SQLAlchemy PostgreSQL → SQLAlchemy SQLite)
- `storage/supabase_client.py` (già eliminato, era shim)
- Firebase auth (tutto)
- Docker/K8s configs
- `integrations/` (standalone non usa provider registry)

**Cosa aggiunge**:
- `zylch init` — onboarding interattivo (scrive .env)
- `.env.example` documentato
- IMAP email client (sostituisce Gmail OAuth)
- CalDAV calendar client
- GOWA WhatsApp integration (HTTP client verso GOWA locale)
- SQLite storage layer (rimpiazza PostgreSQL)
- In-memory vector search (rimpiazza pgvector)
- CLI integrata (assorbe ~/hb/zylch-cli)
- Cost tracking (stima costo LLM per operazione)
- Offline mode (FTS search + task consultazione senza LLM)
- `pyproject.toml` con entry point `zylch` per pipx

---

## Componenti Condivisi (copia, non pacchetto)

Poco codice è davvero condiviso. Dove serve, si copia e si diverge:

| Componente | Note |
|---|---|
| `memory/embeddings.py` | Identico (fastembed). Potrebbe essere un micro-pacchetto ma non vale la pena. |
| Reconsolidation logic | Stesso pattern concettuale, implementazione diversa (pgvector vs in-memory) |
| LLM prompt patterns | Task/memory prompts condivisi concettualmente, ma divergeranno |

**Decisione: nessun pacchetto condiviso.** Copy-paste iniziale, poi evoluzione indipendente.

---

## Piano di Esecuzione

### Fase 1: Preparazione — COMPLETATA
- Piano validato dalla sessione mrcall-agent (2026-04-01)
- Decisioni prese:
  - zylch-standalone: solo distribuzione via pipx, niente Railway
  - mrcall-agent: nuovo progetto in `~/hb/mrcall-agent`
  - Il repo `hahnbanach/zylch` rimane per lo standalone

### Fase 2: zylch-standalone (sessione standalone)
1. Eliminare tutto il codice MrCall dal repo
2. Sostituire PostgreSQL con SQLite
3. Sostituire Gmail OAuth con IMAP client
4. Aggiungere CalDAV client
5. Integrare CLI (assorbire zylch-cli)
6. Creare `zylch init` onboarding
7. Creare `pyproject.toml` con entry point
8. Aggiungere GOWA WhatsApp integration
9. Aggiungere cost tracking
10. Test end-to-end: `pipx install . && zylch init && zylch`

### Fase 3: mrcall-agent (sessione mrcall-agent)
Nuovo progetto in `~/hb/mrcall-agent`. Copia i file necessari da `~/hb/zylch`, poi:

1. **Struttura iniziale**: copiare da zylch solo i file elencati nella sezione
   "mrcall-agent → Cosa tiene" sopra. Nuovo CLAUDE.md, requirements.txt, Dockerfile.
2. **Pulire**: rimuovere import di moduli standalone (gmail_tools, contact_tools,
   email_sync_tools, crm_tools, sync_service, command_handlers standalone).
3. **Ridurre modelli DB**: rimuovere tabelle standalone (emails, calendar_events,
   drafts, task_items, email_triage, training_samples, pipedrive_deals, ecc.)
   Tenere: oauth_tokens, oauth_states, agent_prompts, background_jobs, blobs,
   blob_sentences, mrcall_conversations, error_logs.
4. **Ridurre requirements.txt**: rimuovere dipendenze standalone (google-api-python-client,
   pipedrive, sendgrid, vonage). Tenere: fastapi, uvicorn, anthropic, httpx, fastembed,
   sqlalchemy, psycopg2, alembic, firebase-admin, cryptography.
5. **Nuovo docker-compose.yml**: solo postgres + mrcall-agent, porta 8000.
6. **Nuovo CLAUDE.md**: documentazione specifica mrcall-agent.
7. **Testare**: docker compose up, /mrcall open, configurare GenColor,
   verificare variabili su StarChat.
8. **GitLab/GitHub**: creare repo `hahnbanach/mrcall-agent`, push.

### Fase 4: Verifica incrociata
1. Entrambi i progetti buildano e passano i test indipendentemente
2. Nessuna importazione incrociata
3. Deploy mrcall-agent su Scaleway funziona
4. `pipx install zylch` funziona su macchina pulita

---

## Rischi

| Rischio | Mitigazione |
|---|---|
| Dimenticare file necessari durante lo split | Grep per import incrociati dopo lo split |
| Rompere deploy MrCall durante lo split | mrcall-agent è un nuovo progetto, non tocca il repo zylch |
| Import circolari dopo rimozione moduli | Test di import all'avvio: `python -c "from mrcall_agent.api.main import app"` |

---

## Domande Risolte

1. **Repo**: mrcall-agent è un nuovo progetto in `~/hb/mrcall-agent`. Il repo `hahnbanach/zylch` rimane per standalone.
2. **Railway**: solo standalone lo usava, e standalone passa a pipx. Railway dismesso.
3. **Memoria blobs MrCall**: sì, servono per config memory (decisioni di configurazione passate).
4. **mrzappa**: da investigare durante lo sviluppo di mrcall-agent.

## Domande Aperte

1. Il package Python di mrcall-agent si chiama `mrcall_agent` o `zylch_mrcall` o altro?
2. L'immagine Docker di mrcall-agent usa lo stesso registry GitLab o uno nuovo?
