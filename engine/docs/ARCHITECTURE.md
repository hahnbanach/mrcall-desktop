---
description: |
  Zylch standalone architecture: local CLI sales intelligence tool.
  SQLite storage, IMAP email, WhatsApp (neonize), Telegram bot,
  fastembed vectors, BYOK LLM, no server.
---

# Architecture

> Local CLI tool. Mono-user. No server, no multi-tenant, no Docker.

## System Map

```
zylch/
├── cli/                  # CLI entry point (click)
│   ├── main.py           # Click group: init, process, sync, dream, tasks, status, telegram
│   ├── setup.py          # zylch init wizard (LLM → Email → WA → Telegram → MrCall)
│   ├── chat.py           # Interactive REPL (slash commands + NL + dashboard)
│   ├── commands.py       # Direct command shortcuts (process, sync, tasks, status)
│   ├── profiles.py       # Multi-profile support (select, activate, lock)
│   └── utils.py          # Shared helpers (load_env, get_owner_id)
│
├── services/             # Business logic (stateless)
│   ├── chat_service.py   # Chat message processing, LLM orchestration
│   ├── chat_session.py   # Session state management
│   ├── command_handlers.py # Slash command dispatch (/sync, /tasks, /agent, etc.)
│   ├── command_matcher.py  # NL-to-command matching (fastembed)
│   ├── process_pipeline.py # /process: sync → WA → memory → tasks pipeline
│   ├── dream.py          # Dream system: background memory consolidation (4 phases)
│   ├── digest.py         # Proactive digest builder (tasks, gaps)
│   ├── sync_service.py   # Email + MrCall sync orchestration
│   ├── unified_conversation.py # Multi-channel conversation timeline
│   └── job_executor.py   # Background job runner (REPL mode)
│
├── email/                # Email access (IMAP/SMTP)
│   └── imap_client.py    # IMAP client with auto-detect presets
│
├── whatsapp/             # WhatsApp (neonize/whatsmeow)
│   ├── client.py         # WhatsApp client (QR login, send, receive)
│   └── sync.py           # WA sync service (messages + contacts to SQLite)
│
├── telegram/             # Telegram bot interface
│   └── bot.py            # Long-polling bot, bridges to ChatService
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
│   ├── contact_tools.py  # Contact/task/memory search (SearchLocalMemoryTool returns blob_id)
│   ├── create_memory_tool.py # Create NEW memory blob under user:<owner_id>
│   ├── update_memory_tool.py # Update EXISTING blob — requires exact blob_id + new_content
│   ├── read_email_tool.py    # Read email by id
│   ├── read_document_tool.py # Read document (platform-aware paths)
│   ├── download_attachment_tool.py # Download email attachment
│   ├── run_python_tool.py    # Execute Python in sandbox
│   ├── crm_tools.py      # CRM + compose email tools
│   ├── whatsapp_tools.py # WhatsApp LLM tools
│   ├── starchat.py       # StarChat/MrCall HTTP client (channel)
│   ├── call_tools.py     # Phone call tools (via StarChat)
│   ├── sms_tools.py      # SMS tools (via StarChat)
│   ├── mrcall/oauth.py   # MrCall OAuth2 flow
│   ├── calendar_sync.py  # Calendar sync (pending CalDAV)
│   ├── pipedrive.py      # Pipedrive CRM tools
│   ├── web_search.py     # Web search for enrichment
│   └── config.py         # Tool configuration

# Memory tool contract (2026-04-21): the LLM — not the tool — decides which
# blob to update. update_memory takes an exact blob_id (never searches); the
# LLM first calls SearchLocalMemoryTool, picks a blob_id, then calls either
# update_memory(blob_id, new_content) or create_memory(content). No hardcoded
# rules, no fuzzy/substring match inside the tool.
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
│   ├── client.py         # LLMClient (direct Anthropic/OpenAI SDK)
│   ├── providers.py      # Provider config (models, features)
│   └── exceptions.py     # LLM error types
│
├── api/                  # Compatibility shim
│   └── token_storage.py  # Delegates to Storage methods
│
├── workers/              # Background processors
│   ├── memory.py         # Memory extraction worker
│   └── task_creation.py  # Task detection worker
│
├── utils/                # Utilities
│   ├── auto_reply_detector.py # Email auto-reply detection
│   └── encryption.py     # Fernet encryption for credentials
│
└── config.py             # Pydantic Settings (from profile ~/.zylch/.env)
```

## Data Flow

```
User
  → zylch CLI (click) or Telegram bot
  → command_handlers.py (slash commands) or chat_service.py (LLM)
  → tools execute (IMAP, neonize, StarChat, memory search)
  → Storage (SQLite) ← → fastembed (embeddings)
  → response printed to terminal or sent to Telegram
```

### Process Pipeline (`zylch process`)
```
[1/5] Email sync (IMAP → SQLite, incremental)
[2/5] WhatsApp sync (connect → history → contacts → disconnect)
[3/5] Memory extraction (LLM → entity blobs, auto-trains on first run)
[4/5] Task detection (LLM → task items, auto-trains on first run)
[5/5] Show action items
```

## Multi-Channel Architecture

| Channel | Protocol | Implementation |
|---------|----------|---------------|
| Email | IMAP/SMTP | `zylch/email/imap_client.py` |
| WhatsApp | neonize (whatsmeow) | `zylch/whatsapp/client.py` — QR login, sync on demand |
| MrCall | StarChat HTTP + OAuth2 | `zylch/tools/starchat.py` + `mrcall/oauth.py` |
| Telegram | python-telegram-bot | `zylch/telegram/bot.py` — bot interface (long-polling) |
| Calendar | CalDAV | Planned |

## Interfaces

| Interface | Command | How |
|-----------|---------|-----|
| CLI REPL | `zylch -p user@example.com` | Interactive chat with slash commands |
| CLI Process | `zylch -p user@example.com process` | Full pipeline (sync + AI) |
| CLI Sync | `zylch -p user@example.com sync` | Fetch only (no AI) |
| Telegram | `zylch telegram` | Bot, bridges to ChatService |

## Profile System

- Profiles stored in `~/.zylch/profiles/{email}/`
- Each profile has `.env`, `zylch.db`, `profile.lock`
- CLI `-p/--profile` option for explicit selection
- Auto-selects if only one profile exists
- Exclusive locking via `flock` (write commands)
- Profile matching is exact only — no substring/fuzzy

## Storage

- **Engine**: SQLite with WAL mode, foreign keys enabled
- **Location**: `~/.zylch/profiles/<name>/zylch.db`
- **Models**: 19 (Email, Blob, BlobSentence, TaskItem, OAuthToken, WhatsAppMessage, WhatsAppContact, MrcallConversation, etc.)
- **Embeddings**: stored as LargeBinary (BLOB), loaded into numpy for search
- **No pgvector**: cosine similarity computed in-memory via numpy
- **No Alembic**: tables created via `Base.metadata.create_all()`
- **WhatsApp session**: `~/.zylch/whatsapp.db` (neonize, separate from profile DB)

## Dependencies

```
click               CLI framework
sqlalchemy          ORM (SQLite backend)
fastembed           Embeddings (ONNX, no PyTorch)
numpy               Vector math
httpx               HTTP client (StarChat, APIs)
anthropic           Anthropic SDK (direct)
openai              OpenAI SDK (direct)
neonize             WhatsApp (whatsmeow wrapper)
python-telegram-bot Telegram bot interface
rich                Terminal formatting
cryptography        Fernet encryption
pydantic-settings   Configuration
beautifulsoup4      HTML parsing
python-dotenv       .env loading
apscheduler         Background scheduling
```
