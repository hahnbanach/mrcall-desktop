# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Zylch AI — pre-alpha multi-channel sales intelligence system. Python 3.11+ / FastAPI / PostgreSQL with pgvector. Firebase Auth for multi-tenant isolation (every query filters by `owner_id`).

### Dual Role

Zylch ha oggi due funzioni distinte:

1. **Assistente alla vendita**: connette email (Gmail/Outlook), calendario (Google/Microsoft), CRM (Pipedrive/StarChat), e in futuro WhatsApp per fornire intelligenza commerciale multi-canale
2. **Configuratore MrCall** (via chat): permette di configurare gli assistenti telefonici MrCall tramite interfaccia conversazionale (dry-run + batch apply)

### Inter-Service Dependencies

- **Zylch → StarChat** (`tools/starchat.py` via httpx): lettura/scrittura variabili business, contatti, conversazioni. Base URL: env `MRCALL_BASE_URL` (default `https://test-env-0.scw.hbsrv.net`). Auth: OAuth token o Firebase JWT in header `auth`.
- **Dashboard → Zylch** (solo AI): chat streaming (`POST /api/chat/message/stream` SSE), training (`/api/mrcall/training/*`), apply changes (`POST /api/mrcall/apply-changes`). La dashboard chiama StarChat direttamente per tutto il CRUD business.
- **Zylch → Servizi esterni**: Gmail, Google Calendar, Outlook, Pipedrive, SendGrid, Vonage (SMS), LLM providers (Anthropic/OpenAI/LiteLLM).

### Two Configurator Systems

StarChat contiene un **framework agentico nativo in Scala** (sviluppato dal CTO Angelo Leto) con il proprio configuratore, multi-agent orchestrator, tool registry, memory, e workflow engine. Sia Zylch che StarChat operano sulle stesse variabili business di StarChat. Vedi `~/hb/docs/dependency-map.md` per il confronto dettagliato.

## Documentation

The directory ./docs/ is continuosly updated through the commands /doc-*.

Whenever you have a question, check docs/README.md in order to understand how the documentation is organized.

After context compaction, run /doc-intrasession before resuming work!

## Quick Reference

```bash
# Build & Run
pip install -e .                              # Install in dev mode
uvicorn zylch.api.main:app --reload           # Start API server
alembic upgrade head                          # Run DB migrations

# Test
python -m pytest tests/ -v                    # Run all tests
python -m pytest tests/test_agent.py -v       # Run specific test

# Lint & Format
black --check zylch/ tests/                   # Check formatting
black zylch/ tests/                           # Auto-format
ruff check zylch/ tests/                      # Lint
ruff check --fix zylch/ tests/                # Auto-fix lint issues

# Deploy (via GitLab CI)
# Push to `dev` branch → auto-deploy to starchat-test
# Push to `production` branch → auto-deploy to starchat-production
```

## Architecture

### Request Flow
```
Client (CLI/Dashboard/API)
  → POST /api/chat/message (Firebase JWT)
  → firebase_auth middleware → extracts owner_id
  → chat_service.process_message()
  → command_matcher: slash commands → command_handlers.py, else → LLM
  → LLM (via LLMClient/aisuite) may call tools
  → tools execute (gmail, calendar, CRM, etc.)
  → response returned
```

### Key Layers

- **`zylch/api/`** — FastAPI app factory (`main.py`) + route modules in `routes/` (auth, chat, sync, commands, mrcall, webhooks, etc.)
- **`zylch/services/`** — Stateless business logic: `chat_service.py` (LLM orchestration), `command_handlers.py` (slash command dispatch), `sync_service.py` (email+calendar sync), `webhook_processor.py`
- **`zylch/storage/`** — SQLAlchemy ORM: `models.py` (29+ models), `database.py` (engine/session), `supabase_client.py` (storage facade, legacy name — it's pure SQLAlchemy)
- **`zylch/tools/`** — Claude tool definitions (callable by LLM). Each tool inherits from `base.py` (`Tool`, `ToolResult`). Registry in `factory.py` (`ToolFactory` + `SessionState`). Subdir `mrcall/` for MrCall config tools.
- **`zylch/agents/`** — LLM-powered processors. `trainers/` subdirectory holds agent training (generates optimized prompts from user data, stored in `agent_prompts` table)
- **`zylch/memory/`** — Entity-centric memory with 384-dim vector embeddings (sentence-transformers), hybrid search (pgvector cosine + PostgreSQL FTS), LLM reconsolidation
- **`zylch/llm/`** — `LLMClient` wraps aisuite for multi-provider support (OpenAI, Scaleway/Mistral, Anthropic). MrCall agent calls Anthropic SDK directly for native web search + streaming. Provider config in `providers.py`, exceptions in `exceptions.py`

### Credentials Model (BYOK)
Users provide their own API keys via `/connect` commands → encrypted in `oauth_tokens` table (Fernet). System-level LLM key as fallback, selected by `SYSTEM_LLM_PROVIDER` env var.

### Configuration
All config via `zylch/config.py` — Pydantic `Settings` class loading from `.env`. Key vars: `DATABASE_URL`, `SYSTEM_LLM_PROVIDER`, `LOG_LEVEL`, Google OAuth creds, Firebase creds.

### Database Migrations
Alembic in `alembic/` directory. DB URL read from Settings in `alembic/env.py`. PostgreSQL with pgvector + uuid-ossp extensions.

### Deployment
Scaleway Kubernetes (ARM64 nodes). GitLab CI builds native ARM64 Docker images on self-hosted runner. Two namespaces: `starchat-test` (dev branch) and `starchat-production` (production branch). Deploy configs at `~/hb/zylch-deploy/`.

### Related Repositories
- `~/hb/zylch-cli` — Python/Textual CLI client (primary user interface)
- `~/hb/mrcall-dashboard` — Vue 3/PrimeVue dashboard for MrCall business config
- `frontend/` — dormant Vue 3 prototype, not under active development

## Critical Rules

- **NO OUTPUT TRUNCATION**: Never use `[:8]`, `[:50]`, `[:100]` slicing for display. Show FULL values.
- **DEBUG LOGGING MANDATORY**: Every feature must log inputs, calls, and results. Pattern: `logger.debug(f"[/cmd] func(param={param}) -> result={result}")`
- **NEVER log secrets**: Only "present"/"absent".
- **CONCURRENT OPERATIONS**: Batch all independent operations in a single message.
- **NO ROOT FILES**: Never save working files to root. Use: `/zylch` (source), `/tests` (tests), `/docs` (docs), `/scripts` (scripts).
- **FILES < 500 LINES**: Keep modules small and focused.
- **NO HARDCODED SECRETS**: Use environment variables via Pydantic Settings.
- **POSTGRESQL ONLY**: No local filesystem for data storage.
- **Line length**: 100 chars (black + ruff configured in pyproject.toml).
