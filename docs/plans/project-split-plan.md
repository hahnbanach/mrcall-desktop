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
- `agents/mrcall_memory.py`
- `agents/trainers/mrcall_configurator.py`
- `tools/mrcall/` (config_tools, feature_context, variable_utils)
- `tools/starchat.py`
- `services/chat_service.py` (streaming SSE)
- `services/job_executor.py` (background jobs)
- `storage/` (PostgreSQL, SQLAlchemy, models ridotti)
- `memory/` (pgvector, embeddings, reconsolidation)
- `api/routes/chat.py`, `mrcall.py`, `webhooks.py`, `auth.py`
- `llm/` (Anthropic direct client)

**Cosa elimina**:
- `tools/gmail.py`, `outlook.py`, `gcalendar.py`, `outlook_calendar.py`
- `tools/pipedrive.py`, `sendgrid.py`, `sms_tools.py`
- `tools/email_sync.py`, `email_archive.py`, `calendar_sync.py`
- `agents/emailer_agent.py`, `task_orchestrator_agent.py`
- `agents/trainers/task_email.py`, `memory_email.py`, `emailer.py`
- `workers/task_creation.py`
- `services/sync_service.py`
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
- `memory/` (embeddings.py refactored per SQLite + in-memory search)
- `agents/trainers/task_email.py` (incremental prompt, già refactored)
- `agents/trainers/memory_email.py` (PERSON priority, già refactored)
- `agents/emailer_agent.py`
- `agents/task_orchestrator_agent.py`
- `tools/` (gmail→imap, calendar→caldav, pipedrive, sendgrid, sms)
- `services/command_handlers.py` (slash commands)
- `services/chat_service.py` (adattato per CLI, no SSE)
- `workers/task_creation.py` (già refactored, no MY_EMAILS env)
- `llm/` (multi-provider via aisuite)

**Cosa elimina**:
- `tools/mrcall/` (tutto)
- `tools/starchat.py`
- `agents/mrcall_*.py` (tutto)
- `agents/trainers/mrcall*.py` (tutto)
- `api/` (niente FastAPI, niente HTTP server)
- `storage/models.py` (29 modelli → ~10 per SQLite)
- `storage/database.py` (SQLAlchemy → sqlite3 o SQLAlchemy-sqlite)
- Firebase auth (tutto)
- Docker/K8s configs

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

### Fase 1: Preparazione (entrambe le sessioni)
1. Validare questo piano con sessione mrcall-agent
2. Concordare lista definitiva di file per ciascun repo
3. Decidere se rinominare repo GitLab o crearne uno nuovo

### Fase 2: zylch-standalone (questa sessione)
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

### Fase 3: mrcall-agent (altra sessione)
1. Eliminare tutto il codice standalone/sales dal repo
2. Aggiungere IMAP client per accesso email
3. Separare endpoint pubblici/privati
4. Aggiungere endpoint privati per StarChat
5. Pulire modelli DB (rimuovere tabelle standalone)
6. Test end-to-end con dashboard + StarChat

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
| Rompere deploy MrCall durante lo split | Fare lo split su branch, testare prima di merge |
| IMAP meno affidabile di Gmail API | Retry + error handling robusto, logging |
| CalDAV non supportato da tutti i provider | Fallback: iCal feed (read-only) |
| GOWA deprecato/abbandonato | whatsmeow è la vera dipendenza, GOWA è sostituibile |

---

## Domande Aperte

1. Il repo GitLab `hahnbanach/zylch` diventa `hahnbanach/mrcall-agent`? O si crea nuovo?
2. Railway continua a deployare zylch-standalone? O solo distribuzione via PyPI/pipx?
3. La memoria (blobs) di MrCall include template di risposta email — servono ancora in mrcall-agent?
4. mrzappa ha un'API REST o serve integrazione diretta in StarChat?
