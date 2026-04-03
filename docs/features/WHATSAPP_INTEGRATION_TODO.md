---
description: |
  [TODO - High Priority] WhatsApp integration via neonize (whatsmeow Python wrapper).
  Local connection, no cloud API, no StarChat dependency. QR code login, history sync,
  real-time messages. Analogous to IMAP for email. Store in SQLite, feed memory + gap analysis.
---

# WhatsApp Integration — Standalone via neonize

## Status
🟡 **HIGH PRIORITY** — Ready to implement (no external blockers)

## Architecture Decision

Zylch is standalone (local CLI, no server). WhatsApp connects **directly** via
**neonize** — a Python wrapper around whatsmeow (Go). No cloud API, no Meta Business
account, no StarChat intermediary.

| | Email | WhatsApp |
|---|---|---|
| Protocol | IMAP | WhatsApp Web Multi-Device |
| Library | `imaplib` / `imap_client.py` | **neonize** (whatsmeow) |
| Auth | App password in `.env` | QR code scan (first run) |
| Session | Credentials persist in `.env` | Session persists in SQLite file |
| Initial sync | IMAP SEARCH (history) | `HistorySyncEv` (history blobs) |
| Ongoing sync | IMAP SEARCH (incremental) | `MessageEv` (real-time events) |
| Storage | `emails` table | `whatsapp_messages` table |

### Why neonize

- **Local**: connects directly to WhatsApp servers, no cloud middleman
- **Python-native**: clean API, event decorators, protobuf models
- **Built on whatsmeow**: the most battle-tested WhatsApp Web implementation
  (powers mautrix-whatsapp bridge used by thousands)
- **Lightweight**: no browser, no Selenium, no headless Chrome
- **PyPI**: `pip install neonize` (actively maintained, v0.3.15+)

### Data Flow

```
User scans QR code (once)
  → neonize connects to WhatsApp servers
  → HistorySyncEv delivers past conversations
  → MessageEv delivers new messages in real-time
  → Zylch stores in SQLite (whatsapp_messages, whatsapp_contacts)
  → Memory extraction + gap analysis (same pipeline as email)
  → User asks "chi mi ha scritto su WhatsApp?" → Zylch answers
```

## What Exists Today

### Code (stubs — to be replaced)
- `GetWhatsAppContactsTool` in `contact_tools.py:513-618` — calls StarChat (wrong)
- `starchat.get_whatsapp_contacts()` in `starchat.py:836-861` — returns `[]` (wrong)
- Factory registration in `factory.py` — tool registered but non-functional

These stubs must be **replaced** with neonize-based implementations.

### Documentation (partially outdated)
- `standalone-transformation.md:964` — correctly says "GOWA runs locally"
- `project-split-plan.md:80` — correctly says "GOWA locale"
- `active-context.md:41` — correctly says "planned via GOWA"

**Note**: Previous references to "GOWA" meant go-whatsapp-web-multidevice (the Go
binary). With neonize we get the same engine (whatsmeow) directly in Python — no
separate Go binary needed. neonize embeds whatsmeow via CGo/ctypes.

## neonize API Reference

### Authentication (QR code)

```python
from neonize.client import NewClient
from neonize.events import MessageEv, HistorySyncEv, QREv

client = NewClient("~/.zylch/whatsapp.db")  # session persists here

@client.event(QREv)
def on_qr(client, event):
    # Display QR in terminal for user to scan
    print_qr_to_terminal(event.qr)

client.connect()  # blocks, handles events
```

After first QR scan, session persists in `~/.zylch/whatsapp.db`. Subsequent
runs reconnect automatically (like WhatsApp Web staying logged in).

### History Sync (initial)

```python
@client.event(HistorySyncEv)
def on_history(client, event):
    # event contains protobuf blobs with past conversations
    for conversation in event.data.conversations:
        for message in conversation.messages:
            store_whatsapp_message(message)
```

### Real-time Messages

```python
@client.event(MessageEv)
def on_message(client, event):
    msg = event.message
    sender = msg.info.source.sender  # JID
    text = msg.message.conversation or msg.message.extended_text_message.text
    store_whatsapp_message(msg)
```

### Contacts

```python
contacts = client.contact.get_all_contacts()
# Returns dict of JID → contact info (name, phone, etc.)
```

### Check WhatsApp Numbers

```python
results = client.is_on_whatsapp(["+393281234567", "+391234567890"])
# Returns which numbers are registered on WhatsApp
```

## Implementation Plan

### Phase 1: WhatsApp Client + QR Login (3-4 days)

**New file**: `zylch/whatsapp/client.py`

```python
class WhatsAppClient:
    """Local WhatsApp connection via neonize (whatsmeow)."""

    def __init__(self, db_path: str = "~/.zylch/whatsapp.db"):
        self.client = NewClient(db_path)
        self._setup_handlers()

    def connect(self, qr_callback=None):
        """Connect to WhatsApp. Shows QR on first run."""

    def disconnect(self):
        """Disconnect cleanly."""

    def get_contacts(self) -> list[dict]:
        """Get all WhatsApp contacts."""

    def is_connected(self) -> bool:
        """Check connection status."""
```

**New file**: `zylch/whatsapp/__init__.py`

**Modify**: `zylch/cli/setup.py` — add WhatsApp to `zylch init` wizard:
```
$ zylch init
...
📱 WhatsApp (optional): scan QR code to connect
[QR code displayed in terminal]
✅ WhatsApp connected as +39 328 123 4567
```

**Modify**: `zylch/config.py` — add:
```python
whatsapp_db_path: str = Field(
    default="~/.zylch/whatsapp.db",
    description="neonize session database path"
)
whatsapp_enabled: bool = Field(
    default=False,
    description="Whether WhatsApp is connected"
)
```

**Dependency**: add `neonize>=0.3.15` to `pyproject.toml`

### Phase 2: Message Sync + Storage (3-4 days)

**New models** in `zylch/storage/models.py`:

```python
class WhatsAppMessage(DictMixin, Base):
    __tablename__ = "whatsapp_messages"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    owner_id = Column(Text, nullable=False, index=True)
    message_id = Column(Text, unique=True, nullable=False)  # WhatsApp msg ID
    chat_jid = Column(Text, nullable=False, index=True)     # conversation JID
    sender_jid = Column(Text, nullable=False)
    sender_name = Column(Text)
    text = Column(Text)
    timestamp = Column(DateTime, nullable=False, index=True)
    is_from_me = Column(Boolean, default=False)
    is_group = Column(Boolean, default=False)
    media_type = Column(Text)       # text/image/video/audio/document (v2)
    status = Column(Text)           # sent/delivered/read
    created_at = Column(DateTime, default=_utcnow)
    memory_processed_at = Column(DateTime)
    task_processed_at = Column(DateTime)


class WhatsAppContact(DictMixin, Base):
    __tablename__ = "whatsapp_contacts"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    owner_id = Column(Text, nullable=False, index=True)
    jid = Column(Text, nullable=False)              # WhatsApp JID
    phone_number = Column(Text)
    name = Column(Text)
    push_name = Column(Text)                        # WhatsApp display name
    last_message_at = Column(DateTime)
    synced_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("owner_id", "jid",
                         name="wa_contact_owner_jid_unique"),
    )
```

**New file**: `zylch/whatsapp/sync.py`

```python
class WhatsAppSyncService:
    """Sync WhatsApp messages to local SQLite."""

    def __init__(self, wa_client, storage):
        self.wa = wa_client
        self.storage = storage

    async def handle_history_sync(self, event):
        """Process HistorySyncEv — initial history download."""

    async def handle_new_message(self, event):
        """Process MessageEv — store new incoming/outgoing message."""

    async def sync_contacts(self):
        """Fetch all contacts from neonize, upsert in whatsapp_contacts."""

    async def full_sync(self):
        """Connect + sync contacts + process pending history."""
```

**Modify**: `zylch/services/command_handlers.py` — add:
```
/sync whatsapp    → WhatsAppSyncService.full_sync()
/connect whatsapp → show QR code, connect
```

### Phase 3: LLM Tools (2-3 days)

**New file**: `zylch/tools/whatsapp_tools.py`

```python
class SearchWhatsAppTool(Tool):
    """Search WhatsApp messages in local SQLite."""
    name = "search_whatsapp"
    # Queries whatsapp_messages table (like GmailSearchTool queries emails)

class GetWhatsAppConversationTool(Tool):
    """Get WhatsApp conversation with a contact."""
    name = "get_whatsapp_conversation"
    # Returns messages for a specific chat_jid, ordered by timestamp

class SendWhatsAppMessageTool(Tool):
    """Send a WhatsApp message."""
    name = "send_whatsapp_message"
    # Uses neonize client.send_message()
```

**Modify**: `zylch/tools/factory.py` — register new tools, **remove** old
`GetWhatsAppContactsTool` (StarChat-based).

**Remove**: StarChat WhatsApp stubs from `starchat.py` and `contact_tools.py`.

### Phase 4: Memory + Gap Analysis (3-4 days)

Follow the same pipeline as email:

1. **Memory extraction**: process `whatsapp_messages` → `Blob` entities
   (same as `workers/memory.py` does for emails)

2. **Task detection**: process `whatsapp_messages` → `TaskItem`
   (same as `agents/trainers/task_email.py` does for emails)

3. **Gap analysis**: detect unanswered WhatsApp messages, silent contacts
   - New task types: `whatsapp_unanswered`, `whatsapp_silent`

4. **Trigger events**: add `whatsapp_received` to `Trigger.trigger_type` and
   `TriggerEvent.event_type` check constraints

### Phase 5: Unified Multi-Channel View (2-3 days)

Cross-reference contacts by phone number:
- `Contact` table already has `email` + `phone` fields
- Auto-populate from WhatsApp sync (phone → name mapping)
- LLM tool: "mostrami tutte le interazioni con Mario" → query emails +
  whatsapp_messages + mrcall_conversations by matched contact

## Files Summary

### New files
| File | Description | Phase |
|---|---|---|
| `zylch/whatsapp/__init__.py` | Package init | 1 |
| `zylch/whatsapp/client.py` | neonize wrapper, QR login, connection mgmt | 1 |
| `zylch/whatsapp/sync.py` | History sync + message storage | 2 |
| `zylch/tools/whatsapp_tools.py` | LLM tools (search, conversation, send) | 3 |
| `tests/test_whatsapp_client.py` | Client tests (with mocked neonize) | 1-2 |
| `tests/test_whatsapp_tools.py` | Tool tests | 3 |

### Modified files
| File | Change | Phase |
|---|---|---|
| `pyproject.toml` | Add `neonize>=0.3.15` dependency | 1 |
| `zylch/config.py` | Add `whatsapp_db_path`, `whatsapp_enabled` | 1 |
| `zylch/storage/models.py` | Add `WhatsAppMessage`, `WhatsAppContact` | 2 |
| `zylch/cli/setup.py` | Add WhatsApp to init wizard | 1 |
| `zylch/services/command_handlers.py` | Add `/sync whatsapp`, `/connect whatsapp` | 2 |
| `zylch/tools/factory.py` | Register new WA tools, remove StarChat stub | 3 |

### Deleted/cleaned
| File | Change | Phase |
|---|---|---|
| `zylch/tools/starchat.py:836-861` | Remove `get_whatsapp_contacts()` stub | 3 |
| `zylch/tools/contact_tools.py:513-618` | Remove `GetWhatsAppContactsTool` | 3 |

## User Experience

### First setup
```
$ zylch init
📧 Email: user@gmail.com
🔑 App password: ****
📱 WhatsApp (optional, press Enter to skip):
   Scan this QR code with WhatsApp on your phone:
   ┌─────────────────────┐
   │ ▄▄▄▄▄ █ ▄▄▄▄▄ █    │
   │ █   █ █ █   █ █    │
   │ ...                 │
   └─────────────────────┘
   ✅ WhatsApp connected as +39 328 123 4567
```

### Daily usage
```
$ zylch sync
📧 Email: 12 new messages synced
📱 WhatsApp: 34 new messages synced
📋 Tasks: 3 new tasks generated

$ zylch
> /tasks
1. 🔴 Mario Rossi ti ha scritto su WhatsApp 2 giorni fa (senza risposta)
2. 🟡 Lucia Bianchi — follow-up email dopo meeting di ieri
3. 🟢 Revisione proposta per Acme Corp (scadenza venerdì)

> cosa mi ha detto Mario su WhatsApp?
Mario Rossi ti ha scritto ieri alle 15:30:
"Ciao, hai visto la proposta che ti ho mandato? Fammi sapere entro venerdì"
Non hai ancora risposto.

> scrivi a Mario su WhatsApp "Ciao Mario, la sto guardando, ti dico entro domani"
✅ WhatsApp inviato a Mario Rossi (+39 328 123 4567)
```

## Open Questions

| # | Domanda | Proposta |
|---|---|---|
| 1 | neonize blocking vs async? | Wrap in thread (neonize client.connect() blocks) |
| 2 | QR code timeout? | 60s timeout, retry, clear instructions |
| 3 | Disconnection handling? | Auto-reconnect con backoff, notifica utente |
| 4 | Media messages (img, video)? | Solo testo in v1, media in v2 |
| 5 | Gruppi WhatsApp? | Solo chat 1:1 in v1, gruppi in v2 |
| 6 | Rate limit WhatsApp? | Rispettare limiti whatsmeow, non spammare |
| 7 | Session invalida (logout da telefono)? | Detect + prompt per re-scan QR |

## Timeline

```
Phase 1: Client + QR login         ~  4 giorni
Phase 2: Sync + Storage            ~  4 giorni
Phase 3: LLM Tools                 ~  3 giorni
Phase 4: Memory + Gap Analysis     ~  4 giorni
Phase 5: Unified Multi-Channel     ~  3 giorni
                                    ─────────
                                    ~ 18 giorni totale
```

Phases 1-3 are sequential. Phases 4-5 can run in parallel after Phase 3.

**No external blockers.** Can start immediately.

---

**Priority**: 🟡 **HIGH — Ready to implement**
**Last Updated**: April 2026
