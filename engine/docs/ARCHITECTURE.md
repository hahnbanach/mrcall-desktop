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
│   ├── database.py       # Two SQLite files per profile — zylch.db (mail, tasks, tokens) + the company memory store — bound per table
│   ├── migrations.py     # Idempotent single-owner migration runner (schema_version, backup, <db>.migrate.lock)
│   ├── step_*.py         # Steps: 0001_company_key, 0002_memory_split (profile); 0001_identifiers_company_unique (store)
│   ├── models.py         # 20+ ORM models (incl. EmailBlob, CalendarBlob, WhatsAppBlob, PersonIdentifier)
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
│   ├── create_memory_tool.py # Create NEW memory blob under user:<company key>
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
├── memory/               # Entity memory system — one store per company key
│   ├── company_key.py    # MEMORY_KEY mint/validate; namespace families (user/facts by key, template/prefs by owner)
│   ├── scope.py          # blob_visible — the one visibility predicate every memory path applies
│   ├── store.py          # ~/.zylch/memory/<key>.db: open/create by provenance, memory_meta (self-notion, mutation_seq, last_sweep_seq)
│   ├── join.py           # memory.join — merge a profile's store into another key's store, rebind in-process
│   ├── blob_storage.py   # Blob CRUD (embeddings as BLOB), compare-and-swap updates
│   ├── embeddings.py     # fastembed (ONNX, 384-dim)
│   ├── hybrid_search.py  # InMemoryVectorIndex + text search
│   ├── llm_merge.py      # Memory reconsolidation — identifier-clustered union-find + LLM merge gate + cross-reference migration before delete (Phase 1c, whatsapp-pipeline-parity)
│   ├── pattern_detection.py # Pattern extraction
│   ├── text_processing.py # Text normalization
│   └── config.py         # Memory configuration

# Cross-channel person identity (Phase 1, whatsapp-pipeline-parity, 2026-05-08):
# `person_identifiers(company_key, kind, value, blob_id)` — unique per
# company, `owner_id` as provenance — indexes structured identifiers
# (email/phone/lid) parsed from each blob's `#IDENTIFIERS` block.
# `MemoryWorker._upsert_entity` matches identifier-first then falls back to
# cosine; `reconsolidate_now` clusters via union-find on these tuples (+ Name
# fallback). Helpers `_parse_identifiers_block` / `_normalise_phone` live in
# `workers/memory.py`. Cross-reference migration via
# `Storage.migrate_blob_references` before delete keeps email_blobs /
# calendar_blobs / task_items.sources.blobs intact through dedup.
# `reconsolidate_now` runs at the end of every update's memory stage when
# the store changed since the last sweep (`memory_meta.mutation_seq` vs
# `last_sweep_seq`), once per company under `<store>.sweep.lock`; the
# Settings button and `zylch memory-sweep` force it.
│
├── llm/                  # LLM client
│   ├── client.py         # LLMClient (direct Anthropic/OpenAI SDK; "mrcall" → MrCallProxyClient)
│   ├── proxy_client.py   # MrCallProxyClient — anthropic-shaped client over mrcall-agent's
│   │                     # /api/desktop/llm/proxy (Firebase JWT auth, SSE → Message reconstruct,
│   │                     # typed exceptions: MrCallInsufficientCredits/AuthError/ProxyError)
│   ├── providers.py      # Provider config (models, features, is_metered flag)
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

- Firebase profiles stored in `~/.zylch/profiles/{firebase_uid}/`
- Each profile has `.env`, `zylch.db`, `profile.lock`; the `.env` carries `MEMORY_KEY` (+ `MEMORY_KEY_SOURCE`: `mint` | `provision` | `join`), which selects the company memory store
- CLI `-p/--profile` option for explicit selection
- Auto-selects if only one profile exists
- Exclusive locking via `flock` (write commands)
- Profile matching is exact only — no substring/fuzzy

## Storage

- **Engine**: SQLite with WAL mode, foreign keys enabled
- **Location**: `~/.zylch/profiles/<name>/zylch.db` (mail, tasks, tokens, sync cursors) + `~/.zylch/memory/<MEMORY_KEY>.db` (the memory tables: blobs, sentences, email/calendar/whatsapp links, identifiers, meta, fact history, aliases), one store per company shared by every profile with the key; a store is created only by mint, migration or provisioning — a typed key opens an existing store or is refused
- **Models**: 20+ (Email, Blob, BlobSentence, TaskItem, OAuthToken, WhatsAppMessage, WhatsAppContact, MrcallConversation, EmailBlob/CalendarBlob/WhatsAppBlob join tables, PersonIdentifier index for cross-channel identity, etc.)
- **Embeddings**: stored as LargeBinary (BLOB), loaded into numpy for search
- **No pgvector**: cosine similarity computed in-memory via numpy
- **Migrations**: `storage/migrations.py` — idempotent steps recorded in `schema_version`, one owner at a time (`<db>.migrate.lock`), SQLite backup before a destructive step; new tables via `Base.metadata.create_all()`
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
