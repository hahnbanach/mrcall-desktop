---
description: |
  Zylch standalone architecture: local CLI sales intelligence tool.
  SQLite storage, IMAP email, fastembed vectors, BYOK LLM, no server.
---

# Architecture

> Local CLI tool. Mono-user. No server, no multi-tenant, no Docker.

## System Map

```
zylch/
├── cli/                  # CLI entry point (click)
│   ├── main.py           # Click group: init, sync, tasks, status
│   ├── setup.py          # zylch init wizard (writes ~/.zylch/.env)
│   ├── chat.py           # Interactive REPL (slash commands + natural language)
│   ├── commands.py       # Direct command shortcuts (sync, tasks, status)
│   └── utils.py          # Shared helpers (load_env, get_owner_id)
│
├── services/             # Business logic (stateless)
│   ├── chat_service.py   # Chat message processing, LLM orchestration
│   ├── chat_session.py   # Session state management
│   ├── command_handlers.py # Slash command dispatch (/sync, /tasks, etc.)
│   ├── command_matcher.py  # NL-to-command matching (fastembed)
│   ├── sync_service.py   # Email sync orchestration (IMAP)
│   ├── unified_conversation.py # Multi-channel timeline (email+WA+calls)
│   └── job_executor.py   # Background job runner
│
├── email/                # Email access (IMAP/SMTP)
│   └── imap_client.py    # IMAP client with auto-detect presets
│
├── whatsapp/             # WhatsApp channel (neonize/whatsmeow)
│   ├── client.py         # WhatsAppClient (QR login, send, contacts)
│   └── sync.py           # WhatsAppSyncService (history + messages → SQLite)
│
├── telegram/             # Telegram bot interface
│   └── bot.py            # Telegram-to-ChatService bridge (polling)
│
├── storage/              # Data access layer (SQLite)
│   ├── database.py       # SQLAlchemy engine (sqlite:///~/.zylch/zylch.db)
│   ├── models.py         # 19 ORM models
│   └── storage.py        # Storage class (CRUD, upserts, search)
│
├── tools/                # LLM tool definitions
│   ├── base.py           # Tool, ToolResult, ToolStatus base classes
│   ├── session_state.py  # SessionState (runtime context)
│   ├── factory.py        # ToolFactory (tool registry)
│   ├── gmail_tools.py    # Email search/draft/send tools (IMAP)
│   ├── email_sync_tools.py # Email sync tools
│   ├── email_sync.py     # EmailSyncManager (IMAP incremental)
│   ├── email_archive.py  # Email archive manager
│   ├── contact_tools.py  # Contact/task/memory tools
│   ├── crm_tools.py      # CRM + compose email tools
│   ├── whatsapp_tools.py  # WhatsApp tools (search, conversation, send, gap, timeline)
│   ├── starchat.py       # StarChat/MrCall HTTP client (channel)
│   ├── call_tools.py     # Phone call tools (via StarChat)
│   ├── sms_tools.py      # SMS tools (via StarChat)
│   ├── calendar_sync.py  # Calendar sync (pending CalDAV)
│   ├── pipedrive.py      # Pipedrive CRM tools
│   ├── web_search.py     # Web search for enrichment
│   ├── mrcall/__init__.py # MrCall channel package
│   ├── mrcall/oauth.py   # MrCall OAuth2 PKCE flow (CLI)
│   └── config.py         # Tool configuration
│
├── agents/               # AI agents
│   ├── base_agent.py     # Base agent class
│   ├── emailer_agent.py  # Email composition agent
│   ├── task_orchestrator_agent.py # Task detection orchestration
│   └── trainers/         # Prompt generation
│       ├── base.py       # Base trainer
│       ├── emailer.py    # Emailer prompt trainer
│       ├── task_email.py # Task prompt (incremental, auto after sync)
│       └── memory_email.py # Memory prompt (PERSON priority)
│
├── memory/               # Entity memory system
│   ├── blob_storage.py   # Blob CRUD (embeddings as BLOB)
│   ├── embeddings.py     # fastembed (ONNX, 384-dim)
│   ├── hybrid_search.py  # InMemoryVectorIndex + text search
│   ├── llm_merge.py      # Memory reconsolidation
│   ├── pattern_detection.py # Pattern extraction
│   ├── text_processing.py # Text normalization
│   └── config.py         # Memory configuration
│
├── llm/                  # LLM client
│   ├── client.py         # LLMClient (aisuite wrapper)
│   ├── providers.py      # Provider config (Anthropic, OpenAI)
│   └── exceptions.py     # LLM error types
│
├── api/                  # Compatibility shim
│   └── token_storage.py  # Delegates to Storage methods
│
├── assistant/            # Assistant orchestration
│   ├── core.py           # Core assistant logic
│   ├── models.py         # Assistant data models
│   └── prompts.py        # System prompts
│
├── workers/              # Background processors
│   ├── memory.py         # Memory extraction worker
│   └── task_creation.py  # Task detection worker
│
├── utils/                # Utilities
│   ├── auto_reply_detector.py # Email auto-reply detection
│   └── encryption.py     # Fernet encryption for credentials
│
└── config.py             # Pydantic Settings (from ~/.zylch/.env)
```

## Data Flow

```
User → CLI REPL or Telegram bot
  → command_handlers.py (slash commands) or chat_service.py (LLM)
  → tools execute (IMAP, neonize, StarChat, memory search)
  → Storage (SQLite) ← → fastembed (embeddings)
  → response printed to terminal or sent to Telegram
```

## Multi-Channel Architecture

| Channel | Protocol | Implementation |
|---------|----------|---------------|
| Email | IMAP/SMTP | `zylch/email/imap_client.py` |
| MrCall | StarChat HTTP + OAuth2 | `zylch/tools/starchat.py` + `mrcall/oauth.py` |
| WhatsApp | neonize (whatsmeow) | `zylch/whatsapp/client.py` + `sync.py` |
| Calendar | CalDAV | Planned |

### Interfaces

| Interface | Implementation | How to start |
|-----------|---------------|-------------|
| CLI REPL | `zylch/cli/chat.py` | `zylch` |
| Telegram bot | `zylch/telegram/bot.py` | `zylch telegram` |

### Unified Timeline

`zylch/services/unified_conversation.py` merges all channels into a single
chronological timeline per contact. The `get_contact_timeline` LLM tool
exposes this to the AI agent.

## Storage

- **Engine**: SQLite with WAL mode, foreign keys enabled
- **Location**: `~/.zylch/zylch.db` (main), `~/.zylch/whatsapp.db` (neonize session)
- **Models**: 19 (Email, WhatsAppMessage, WhatsAppContact, Blob, BlobSentence, TaskItem, etc.)
- **Embeddings**: stored as LargeBinary (BLOB), loaded into numpy for search
- **No pgvector**: cosine similarity computed in-memory via numpy
- **No Alembic**: tables created via `Base.metadata.create_all()`

## Dependencies

```
click               CLI framework
sqlalchemy          ORM (SQLite backend)
fastembed           Embeddings (ONNX, no PyTorch)
numpy               Vector math
httpx               HTTP client (StarChat, APIs)
aisuite             Multi-provider LLM
anthropic           Anthropic SDK
openai              OpenAI SDK
cryptography        Fernet encryption
pydantic-settings   Configuration
beautifulsoup4      HTML parsing
python-dotenv       .env loading
apscheduler         Background scheduling
neonize             WhatsApp Web client (whatsmeow wrapper)
python-telegram-bot Telegram Bot API (async, polling)
```
