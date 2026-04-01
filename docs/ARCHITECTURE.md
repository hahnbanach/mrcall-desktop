---
description: |
  Zylch system architecture: four layers (Email, Intelligence, Automation, UI),
  PostgreSQL-only storage, multi-tenant via owner_id, Firebase Auth, deployed on Scaleway K8s.
---

# Architecture

> Pre-alpha development. No production users, no backward compatibility requirements.

## System Map

```
zylch/
├── api/                  # FastAPI HTTP layer
│   ├── main.py           # App factory, CORS, router registration
│   ├── routes/           # Route modules (auth, chat, sync, data, commands,
│   │                     #   connections, memory, jobs, mrcall, webhooks, admin)
│   └── firebase_auth.py  # Firebase token verification middleware
│
├── services/             # Business logic (stateless)
│   ├── chat_service.py   # Chat message processing, LLM orchestration
│   ├── chat_session.py   # Session state management
│   ├── command_handlers.py # Slash command dispatch (/sync, /tasks, /mrcall, etc.)
│   ├── command_matcher.py  # NL-to-command matching
│   ├── sync_service.py   # Email + calendar sync orchestration
│   ├── job_executor.py   # Background job runner
│   ├── sandbox_service.py # Sandboxed execution for MrCall config
│   ├── validation_service.py # Input validation
│   └── webhook_processor.py  # Inbound webhook handling
│
├── storage/              # Data access layer
│   ├── database.py       # SQLAlchemy engine + session factory
│   ├── models.py         # 29+ ORM models (all tables)
│   ├── supabase_client.py # Storage facade (legacy name, pure SQLAlchemy)
│   └── storage.py        # Additional storage utilities
│
├── tools/                # Claude tool definitions (callable by LLM)
│   ├── base.py           # Tool, ToolResult, ToolStatus base classes
│   ├── factory.py        # ToolFactory + SessionState (tool registry)
│   ├── gmail.py          # Gmail read/send/draft tools
│   ├── outlook.py        # Outlook email tools (Graph API)
│   ├── gcalendar.py      # Google Calendar tools
│   ├── outlook_calendar.py # Outlook Calendar tools
│   ├── email_sync.py     # Email sync tool
│   ├── email_archive.py  # Email archive search tool
│   ├── calendar_sync.py  # Calendar sync tool
│   ├── pipedrive.py      # Pipedrive CRM tools
│   ├── starchat.py       # StarChat/MrCall contact tools
│   ├── sendgrid.py       # SendGrid email campaign tools
│   ├── sms_tools.py      # SMS tools (Vonage)
│   ├── call_tools.py     # Phone call tools
│   ├── web_search.py     # Web search for contact enrichment
│   ├── sharing_tools.py  # Intelligence sharing tools
│   ├── mrcall/           # MrCall configuration tools
│   │   ├── config_tools.py     # MrCall variable management
│   │   ├── feature_context_tool.py # Feature context for LLM
│   │   ├── llm_helper.py       # MrCall-specific LLM utilities
│   │   └── variable_utils.py   # Variable parsing/validation
│   └── config.py         # Tool configuration
│
├── agents/               # AI agents (LLM-powered processors)
│   ├── base_agent.py     # Base agent class
│   ├── emailer_agent.py  # Email composition with memory context
│   ├── mrcall_agent.py   # MrCall configuration agent (conversation history, live context)
│   ├── mrcall_context.py # Live StarChat variable fetching + prompt assembly
│   ├── mrcall_templates.py # Fixed feature templates (welcome, booking, transfer, etc.)
│   ├── mrcall_memory.py  # Config memory persistence via blob storage
│   ├── task_orchestrator_agent.py   # Task detection orchestration
│   └── trainers/         # Agent training subsystem
│       ├── base.py               # Base trainer class
│       ├── emailer.py            # Emailer agent trainer
│       ├── task_email.py         # Task prompt generation (incremental, auto after sync)
│       ├── memory_email.py       # Memory-from-email trainer
│       ├── mrcall.py             # MrCall agent trainer (Layer 2 assembly)
│       ├── mrcall_configurator.py # MrCall config trainer (simplified, templates extracted)
│       └── memory_mrcall.py      # Memory-from-MrCall trainer
│
├── memory/               # Entity memory system (cross-cutting)
│   ├── blob_storage.py   # Blob CRUD (entity memory units)
│   ├── embeddings.py     # Embedding generation (fastembed)
│   ├── hybrid_search.py  # Combined vector + FTS search
│   ├── llm_merge.py      # LLM-powered memory reconsolidation
│   ├── pattern_detection.py # Behavioral pattern extraction
│   ├── text_processing.py # Text normalization and chunking
│   └── config.py         # Memory system configuration
│
├── llm/                  # LLM client abstraction
│   ├── client.py         # LLMClient (LiteLLM wrapper)
│   └── providers.py      # Provider configuration (OpenAI, Scaleway, Anthropic, Mistral)
│
├── skills/               # Skill registry (composable capabilities)
│   ├── base.py           # Base skill class
│   ├── cross_channel.py  # Cross-channel skill
│   ├── draft_composer.py # Email draft composition skill
│   └── registry.py       # Skill registration
│
├── sharing/              # Intelligence sharing between users
│   ├── authorization.py  # Consent-based sharing auth
│   └── intel_share.py    # Intelligence data sharing
│
├── integrations/         # External service integrations
├── workers/              # Background workers
├── models/               # Pydantic data models
├── router/               # Message routing
├── config.py             # Pydantic Settings (env vars)
└── __init__.py
```

## Data Flow

### Chat Request
```
Client (CLI/Dashboard/API)
  → POST /api/chat/message (Firebase JWT in Authorization header)
  → firebase_auth middleware validates token, extracts owner_id
  → chat_service.process_message()
  → command_matcher detects slash commands OR routes to LLM
  → LLM (via LLMClient) generates response, may call tools
  → tools execute (email, calendar, CRM, etc.)
  → response returned to client
```

### Email Sync
```
/sync command or POST /api/sync/emails
  → sync_service.sync_emails(owner_id, days_back)
  → Gmail API fetch (via oauth_tokens from DB)
  → Emails stored in `emails` table
  → Optional: memory extraction (emailer agent)
  → Optional: task detection (task_orchestrator_agent)
```

### MrCall Configuration
```
/agent mrcall run "..." or dashboard chat
  → chat_service calls MrCallAgent directly
  → agentic while(tool_use) loop (terminates when LLM stops calling tools, safety valve at 40 messages)
  → config_tools read/write MrCall variables via StarChat API
  → post-tool-use <config-progress> injection tracks completed/remaining work
  → prompts stored in agent_prompts table
```

### Why MrCall Tools Are Code, Not Skill Files

MrCall's 11 tools (`configure_welcome_inbound`, `get_current_config`, `respond_text`, etc.)
are Python functions inside `mrcall_agent.py`, **not** declarative skill files (`.md` prompts).

This is deliberate — unlike prompt-based skills (e.g., OpenClaw `.openclaw/skills/`), MrCall
tools require capabilities that skill files cannot provide:

| Requirement | Why skill files can't do it |
|---|---|
| **StarChat API calls** | `_process_configure` calls `starchat.update_business_variable()` — authenticated HTTP to an external service |
| **Business validation** | Checks variable names belong to the correct feature, rejects invalid ones, rolls back on error |
| **dry_run mode** | Validates and summarizes changes without applying — branching logic, not just prompt text |
| **Dynamic training** | Meta-prompts read *current* variable values from StarChat at training time — the prompt itself is generated, not static |

Skill files work well for tasks that are "follow these instructions using generic tools (read, edit, bash)."
MrCall tools are **typed API integrations with business logic** — they need code.

A skill-based layer *above* the tools could make sense in the future (e.g., "copy config from business A to B"),
but it would orchestrate the existing tools, not replace them.

### Future: MCP Integration (Planned)

The current tool architecture is internal Python code. Two MCP-based extensions are planned:

```
MCP clients (Claude Code, Cursor, Windsurf...)
    ↓ consume
Zylch MCP Server (wraps existing REST API)        ← Direction 1
    ↓ is
Zylch Backend (FastAPI, MrCallAgent, Python tools)
    ↓ consumes
External MCP Servers (custom CRM, client DB...)    ← Direction 2
```

**Direction 1 — Zylch as MCP Server**: Expose Zylch's REST API (`/api/chat/message`,
`/api/mrcall/apply-changes`, `/api/sync/emails`, etc.) as an MCP server. Any MCP-compatible
agent could then use Zylch as a tool: "ask Zylch for Mario Rossi's urgent tasks", "draft a
reply using Zylch data". The MCP server would handle auth (Firebase JWT) and map MCP tool
calls to existing API endpoints. Zero client-side code needed.

**Direction 2 — Zylch as MCP Consumer**: Today every integration (Pipedrive, Gmail, SendGrid)
is hand-written Python in `tools/`. If Zylch supported MCP as a *consumer*, a client could
plug in their own system (custom CRM, internal DB, proprietary ERP) by providing an MCP server.
Zylch would discover and call those tools at runtime — plugin architecture without touching
Zylch code. This turns the current closed tool set into an open, extensible one.

## Database Schema (Key Tables)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `emails` | Email archive | owner_id, gmail_id, thread_id, embedding (384-dim), fts_document |
| `calendar_events` | Calendar data | owner_id, google_event_id, start_time, attendees |
| `blobs` | Entity memory | owner_id, namespace, content, embedding |
| `blob_sentences` | Sentence-level embeddings | blob_id, sentence_text, embedding |
| `task_items` | Detected tasks | owner_id, event_type, event_id, urgency, action_required |
| `oauth_tokens` | Encrypted credentials | owner_id, provider, credentials (encrypted JSONB) |
| `agent_prompts` | Trained agent prompts | owner_id, agent_type, agent_prompt |
| `email_triage` | AI triage results | owner_id, thread_id, triage_category, confidence_score |
| `training_samples` | ML training data | owner_id, question_type, anonymized_input, model_answer |
| `patterns` | Behavioral patterns | owner_id, namespace, skill, intent, confidence |
| `background_jobs` | Async job tracking | owner_id, job_type, status, progress_pct |
| `mrcall_conversations` | Phone call records | owner_id, business_id, contact_phone, body |
| `triggers` | Event-driven automation | owner_id, trigger_type, instruction |
| `drafts` | Email drafts | owner_id, to_addresses, subject, body, status |
| `contacts` | Contact records | owner_id, email, name, phone |
| `sync_state` | Sync bookmarks | owner_id, history_id, last_sync |

## Infrastructure

### Deployment Topology
```
Scaleway Kubernetes (ARM64 nodes)
├── Namespace: starchat-test (dev branch)
│   └── Deployment: zylch (1 replica)
├── Namespace: starchat-production (production branch)
│   └── Deployment: zylch (1 replica)
└── Scaleway Managed PostgreSQL 16
    ├── Extensions: pgvector, uuid-ossp
    └── Instance: mrcall-test (shared test+prod for now)

GitLab CI/CD
├── Self-hosted ARM64 runner on Scaleway
│   ├── Instance: gitlab-runner-arm64 (COPARM1-2C-8G)
│   ├── IP: 51.15.139.29 (fr-par-1)
│   └── SSH: ssh ubuntu@51.15.139.29
├── Native ARM64 Docker builds (no QEMU emulation)
├── Auto-shutdown runner after 4h idle
└── If disk full: sudo docker system prune -af && sudo docker builder prune -af

Deploy configs: ~/hb/zylch-deploy/{test,production}/
├── secrets.env       # Env vars (OPENAI_API_KEY, SCW_SECRET_KEY, SYSTEM_LLM_PROVIDER, etc.)
├── create-secrets.sh # Updates K8s secrets from secrets.env
└── deploy.sh         # Rolls out new pod
```

### External Services
| Service | Purpose | Auth Method |
|---------|---------|-------------|
| Gmail API | Email read/send/drafts | OAuth 2.0 (per-user) |
| Google Calendar API | Events, Meet links | OAuth 2.0 (per-user) |
| Microsoft Graph API | Outlook email + calendar | OAuth 2.0 (per-user) |
| LLM Providers | AI processing (OpenAI, Scaleway/Mistral, Anthropic) | System key (OPENAI_API_KEY/SCW_SECRET_KEY) + BYOK per-user |
| StarChat/MrCall | Telephony, contacts, WhatsApp | OAuth 2.0 + API key |
| SendGrid | Email campaigns, tracking | API key |
| Vonage | SMS | API key (BYOK per-user) |
| Pipedrive | CRM contacts and deals | API token (BYOK per-user) |
| Firebase | Authentication | Service account (server) |

## Cross-Cutting Concerns

### Authentication
- **Firebase Auth**: JWT tokens validated server-side via `firebase_auth.py`
- **Multi-tenant isolation**: Every DB query filters by `owner_id` (application-layer)
- **Alpha testers**: Allowlist gate in `data/alpha_testers.txt`

### Credentials (BYOK Model)
- Users provide their own API keys via `/connect` commands
- Stored encrypted in `oauth_tokens` table (Fernet encryption)
- System-level LLM key as fallback for integrations (SYSTEM_LLM_PROVIDER selects: openai, scaleway, or anthropic)
- Web search: Anthropic/OpenAI natively; other providers fall back to OpenAI

### Memory System
- Entity-centric blobs with vector embeddings (384-dim, fastembed)
- Hybrid search: pgvector cosine similarity + PostgreSQL FTS
- LLM-powered reconsolidation (merge conflicting memories)
- Namespace: `{owner}:{entity_type}:{entity_id}`

### Telemetry
- Colored console logging via `colorlog`
- Configurable log level via `LOG_LEVEL` env var
- No external telemetry service (pre-alpha)
