# Piano Operativo: Integrazione WhatsApp via GOWA/StarChat

**Data**: 2026-04-03
**Stato**: Pianificazione
**Dipendenza bloccante**: StarChat REST API per WhatsApp (non ancora disponibile)

---

## 1. Analisi dello Stato Attuale

### Codice Esistente (pronto)

| Componente | File | Stato |
|---|---|---|
| `GetWhatsAppContactsTool` | `zylch/tools/contact_tools.py:513-618` | Stub registrato in factory |
| `get_whatsapp_contacts()` | `zylch/tools/starchat.py:836-861` | Ritorna `[]`, logga warning |
| Factory registration | `zylch/tools/factory.py:465-467` | Tool registrato in `_create_memory_tools()` |
| Documentazione feature | `docs/features/WHATSAPP_INTEGRATION_TODO.md` | Completa (444 righe) |

### Pattern di Riferimento (canali funzionanti)

| Canale | Client | Tool | DB Model |
|---|---|---|---|
| Email | `imap_client.py` | `gmail_tools.py` | `Email` |
| MrCall (Calls) | `starchat.py` | `call_tools.py` (`InitiateCallTool`) | `MrcallConversation` |
| SMS | `vonage.py` | `sms_tools.py` (`SendSMSTool`) | - (no local storage) |
| **WhatsApp** | **`starchat.py` (stub)** | **`contact_tools.py` (stub)** | **Da creare** |

### API StarChat Richieste (bloccanti)

```
GET  /mrcall/v1/{realm}/whatsapp/contacts          # Lista contatti WhatsApp
GET  /mrcall/v1/{realm}/whatsapp/messages           # Storico messaggi
POST /mrcall/v1/{realm}/whatsapp/send               # Invio messaggio
WS/Webhook /mrcall/v1/{realm}/whatsapp/events       # Notifiche real-time
```

Header auth: `auth: {access_token}` (come gli altri endpoint StarChat).

---

## 2. Piano di Implementazione (5 Fasi)

### Fase 1: Modelli DB + Client StarChat (3-5 giorni)

**Prerequisito**: API StarChat disponibile

**1.1 — Nuovi modelli SQLAlchemy** (`zylch/storage/models.py`)

```python
class WhatsAppMessage(DictMixin, Base):
    __tablename__ = "whatsapp_messages"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    owner_id = Column(Text, nullable=False, index=True)
    starchat_message_id = Column(Text, unique=True, nullable=False)
    contact_phone = Column(Text, nullable=False)
    contact_name = Column(Text)
    sender = Column(Text, nullable=False)       # 'me' o phone number
    text = Column(Text)
    timestamp = Column(DateTime, nullable=False)
    status = Column(Text)                        # sent/delivered/read
    media_type = Column(Text)                    # text/image/document (v2)
    created_at = Column(DateTime, default=_utcnow)
    memory_processed_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint("owner_id", "starchat_message_id",
                         name="wa_msg_owner_sc_unique"),
    )


class WhatsAppContact(DictMixin, Base):
    __tablename__ = "whatsapp_contacts"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    owner_id = Column(Text, nullable=False, index=True)
    starchat_contact_id = Column(Text, unique=True, nullable=False)
    phone_number = Column(Text, nullable=False)
    name = Column(Text)
    last_message_at = Column(DateTime)
    synced_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("owner_id", "phone_number",
                         name="wa_contact_owner_phone_unique"),
    )
```

Tabelle create automaticamente via `Base.metadata.create_all()` (niente Alembic).

**1.2 — Implementare metodi StarChat** (`zylch/tools/starchat.py`)

Completare gli stub esistenti:

```python
async def get_whatsapp_contacts(self, business_id, days_back=30):
    path = f"/mrcall/v1/{self.realm}/whatsapp/contacts"
    params = {"businessId": business_id, "daysBack": days_back}
    return await self._get(path, params=params)

async def get_whatsapp_messages(self, business_id, contact_phone, days_back=30):
    path = f"/mrcall/v1/{self.realm}/whatsapp/messages"
    params = {"businessId": business_id, "contactPhone": contact_phone,
              "daysBack": days_back}
    return await self._get(path, params=params)

async def send_whatsapp_message(self, business_id, to, text, reply_to=None):
    path = f"/mrcall/v1/{self.realm}/whatsapp/send"
    body = {"businessId": business_id, "to": to, "text": text}
    if reply_to:
        body["replyToMessageId"] = reply_to
    return await self._post(path, json=body)
```

**1.3 — Completare `GetWhatsAppContactsTool`** (`zylch/tools/contact_tools.py:513`)

Aggiornare l'`execute()` per salvare i risultati nel DB locale come cache.

**1.4 — Sync service** (`zylch/services/whatsapp_sync.py` — nuovo file)

```python
class WhatsAppSyncService:
    """Sync WhatsApp messages from StarChat to local SQLite."""

    async def sync_contacts(self, owner_id, business_id):
        """Fetch contacts from StarChat, upsert in whatsapp_contacts."""

    async def sync_messages(self, owner_id, business_id, days_back=30):
        """Fetch messages from StarChat, upsert in whatsapp_messages."""

    async def full_sync(self, owner_id, business_id):
        """Sync contacts + messages. Called by /sync whatsapp."""
```

**1.5 — Comando CLI `/sync whatsapp`**

Estendere `command_handlers.py` per aggiungere sync WhatsApp:
- `zylch sync --channel whatsapp` oppure `/sync whatsapp` nel REPL.

---

### Fase 2: Invio Messaggi + Tool LLM (2-3 giorni)

**2.1 — Nuovo file `zylch/tools/whatsapp_tools.py`**

```python
class SendWhatsAppMessageTool(Tool):
    name = "send_whatsapp_message"
    description = "Send a WhatsApp message to a contact"

    async def execute(self, phone_number, message, reply_to=None):
        # 1. Validare business_id da session_state
        # 2. Chiamare starchat.send_whatsapp_message()
        # 3. Salvare in whatsapp_messages locale
        # 4. Return ToolResult

class GetWhatsAppConversationTool(Tool):
    name = "get_whatsapp_conversation"
    description = "Get WhatsApp message history with a contact"

    async def execute(self, phone_number, days_back=30):
        # 1. Cercare messaggi locali (cache SQLite)
        # 2. Se cache stale, refresh da StarChat
        # 3. Return conversazione ordinata per timestamp
```

**2.2 — Registrare in factory** (`zylch/tools/factory.py`)

Aggiungere `SendWhatsAppMessageTool` e `GetWhatsAppConversationTool` a `_create_memory_tools()` o creare `_create_whatsapp_tools()`.

**2.3 — Memory integration**

Dopo invio, salvare in entity memory (`Blob`) per relationship intelligence:
```python
await memory.store_memory(
    namespace=f"whatsapp/{contact_name}",
    content=f"WhatsApp sent: {message[:200]}"
)
```

---

### Fase 3: Conversazione Unificata Multi-Canale (3-4 giorni)

**Obiettivo**: Timeline unica email + WhatsApp + chiamate + SMS per contatto.

**3.1 — Servizio unificato** (`zylch/services/unified_conversation.py`)

```python
async def get_unified_timeline(owner_id, contact_identifier):
    """Merge all channel interactions for a contact.

    contact_identifier: email, phone, or contact name.
    Returns sorted list of interactions across all channels.
    """
    # 1. Risolvere contact → email + phone (dalla tabella contacts)
    # 2. Query emails (by email)
    # 3. Query whatsapp_messages (by phone)
    # 4. Query mrcall_conversations (by phone)
    # 5. Merge + sort by timestamp
    # 6. Return timeline unificata
```

**3.2 — Tool LLM per conversazione unificata**

```python
class GetContactTimelineTool(Tool):
    name = "get_contact_timeline"
    description = "Show unified conversation across email, WhatsApp, calls, SMS"
```

**3.3 — Cross-referencing contatti**

Estendere il modello `Contact` per collegare phone ↔ email:
- Usare la tabella `contacts` esistente (ha già `email` + `phone`)
- Popolare automaticamente durante sync WhatsApp + email

---

### Fase 4: Gap Analysis WhatsApp (3-4 giorni)

**Obiettivo**: Rilevare messaggi WhatsApp senza risposta e contatti silenziosi.

**4.1 — Estendere il sistema di gap detection**

Aggiungere al task processor (`agents/trainers/task_email.py` pattern):

```python
async def detect_whatsapp_gaps(owner_id, days_back=7):
    """Find:
    1. Messaggi ricevuti senza risposta (ultimo msg da contatto)
    2. Contatti silenziosi (>30 giorni senza messaggi)
    3. Follow-up mancanti post-chiamata (chiamata MrCall senza WhatsApp follow-up)
    """
```

**4.2 — Nuovi tipi di task**

Estendere `TaskItem.event_type` per includere:
- `whatsapp_unanswered` — messaggio ricevuto senza risposta
- `whatsapp_silent` — contatto silenzioso
- `cross_channel_gap` — gap multi-canale (es. chiamata senza follow-up)

**4.3 — Trigger WhatsApp**

Aggiungere `whatsapp_received` ai tipi di trigger consentiti in `Trigger` e `TriggerEvent`.

---

### Fase 5: Sync Real-Time via Webhook (2-3 giorni)

**Prerequisito**: StarChat webhook support per WhatsApp

**5.1 — Endpoint webhook** (se CLI, via polling; se server futuro, via HTTP)

Per la versione CLI standalone:
```python
async def poll_whatsapp_updates(owner_id, business_id, interval=60):
    """Poll StarChat per nuovi messaggi WhatsApp.
    Alternativa al webhook per architettura CLI senza server.
    """
    last_sync = get_last_whatsapp_sync(owner_id)
    new_messages = await starchat.get_whatsapp_messages(
        business_id, since=last_sync
    )
    # Upsert + trigger event processing
```

**5.2 — Background job**

Registrare come `BackgroundJob` (modello esistente) con `job_type="whatsapp_sync"`.

---

## 3. File da Creare/Modificare

### Nuovi file

| File | Descrizione | Fase |
|---|---|---|
| `zylch/tools/whatsapp_tools.py` | `SendWhatsAppMessageTool`, `GetWhatsAppConversationTool` | 2 |
| `zylch/services/whatsapp_sync.py` | Sync contacts + messages da StarChat | 1 |
| `zylch/services/unified_conversation.py` | Timeline multi-canale | 3 |
| `tests/test_whatsapp_tools.py` | Test per i tool WhatsApp | 1-2 |
| `tests/test_whatsapp_sync.py` | Test per il sync service | 1 |

### File da modificare

| File | Modifica | Fase |
|---|---|---|
| `zylch/storage/models.py` | Aggiungere `WhatsAppMessage`, `WhatsAppContact` | 1 |
| `zylch/tools/starchat.py:836-861` | Completare stub `get_whatsapp_contacts()`, aggiungere `get_whatsapp_messages()`, `send_whatsapp_message()` | 1 |
| `zylch/tools/contact_tools.py:513-618` | Aggiornare `GetWhatsAppContactsTool.execute()` con cache DB | 1 |
| `zylch/tools/factory.py` | Registrare nuovi tool WhatsApp | 2 |
| `zylch/services/command_handlers.py` | Aggiungere handler `/sync whatsapp` | 1 |
| `zylch/storage/storage.py` | Aggiungere metodi CRUD per `WhatsAppMessage`/`WhatsAppContact` | 1 |

---

## 4. Rischi e Domande Aperte

| # | Domanda | Impatto | Decisione proposta |
|---|---|---|---|
| 1 | StarChat usa WhatsApp Business API o GOWA personale? | Rate limit, features disponibili | Progettare per entrambi, configurabile |
| 2 | Limite storico messaggi recuperabili? | Qualita gap analysis al primo sync | Default 90 giorni, configurabile |
| 3 | Supporto media (immagini, doc, audio)? | Complessita storage e UI | Solo testo in v1, media in v2 |
| 4 | Chat di gruppo? | Complessita threading | Solo chat 1:1 in v1 |
| 5 | Rate limit API StarChat? | Frequenza polling sync | Rispettare header `Retry-After`, backoff esponenziale |
| 6 | Architettura CLI senza server = no webhook | Latenza notifiche | Polling ogni 60s come background job |

---

## 5. Timeline Stimata

```
Fase 0: API StarChat disponibile         ← BLOCCANTE (in attesa)
Fase 1: DB + Client + Sync               ~  5 giorni
Fase 2: Invio messaggi + Tool LLM        ~  3 giorni
Fase 3: Conversazione unificata           ~  4 giorni
Fase 4: Gap analysis WhatsApp             ~  4 giorni
Fase 5: Sync real-time (polling)          ~  3 giorni
                                          ─────────
                                          ~ 19 giorni totale
```

Le fasi 1-2 sono sequenziali. Le fasi 3, 4, 5 possono procedere in parallelo.

---

## 6. Prossimi Passi Immediati

1. **Sollecitare StarChat** per la disponibilita delle API WhatsApp REST
2. **Preparare i modelli DB** (`WhatsAppMessage`, `WhatsAppContact`) — fattibile subito
3. **Preparare i test** con mock delle API StarChat — fattibile subito
4. **Quando API disponibile**: procedere con Fase 1 implementazione client
