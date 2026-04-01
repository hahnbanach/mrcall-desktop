# Execution Plan: Zylch Standalone Transformation

**Data**: 2026-03-31
**Stato**: Ready for execution
**Obiettivo**: Transform this repo from shared codebase into a local CLI-only sales intelligence tool

---

## Vision: Multi-Channel Sales Intelligence

Zylch standalone is a **multi-channel sales intelligence tool**. Every data source is a channel:

| Channel | Protocol | Use |
|---------|----------|-----|
| Email | IMAP/SMTP | Read/send email |
| WhatsApp | GOWA (HTTP) | Read/send messages |
| Phone/MrCall | StarChat API (HTTP) | Read calls, trigger calls, delegate configuration |
| Calendar | CalDAV | Read/create events |

MrCall is NOT eliminated — it becomes a **channel** like email and WhatsApp. Zylch reads from
StarChat (contacts, call logs, conversations) and requests actions (call, SMS, configure). For
complex configuration, Zylch delegates to StarChat which delegates to mrcall-agent.

### The Delegation Pattern

```
User → Zylch: "configura l'assistente per rispondere 9-18"
  → Zylch calls StarChat API: update business variables
    → StarChat delegates to mrcall-agent for complex configuration
```

Zylch standalone does NOT configure MrCall directly. It:
- **READS** from StarChat (contacts, calls, status, business config)
- **REQUESTS** actions from StarChat (call, SMS, simple variable updates)
- **DELEGATES** complex configuration to StarChat/mrcall-agent

---

## Current State Analysis

### Codebase inventory (137 Python files under `zylch/`)

**Files to DELETE (32 files)** — MrCall configurator, Firebase, API, unused integrations:

```
# MrCall configurator agents (7 files) — configurator logic, NOT channel access
zylch/agents/mrcall_agent.py
zylch/agents/mrcall_context.py
zylch/agents/mrcall_error_handler.py
zylch/agents/mrcall_memory.py
zylch/agents/mrcall_orchestrator_agent.py
zylch/agents/mrcall_templates.py
zylch/agents/mrcall_variable_validator.py

# MrCall trainers (3 files) — configurator training
zylch/agents/trainers/mrcall.py
zylch/agents/trainers/mrcall_configurator.py
zylch/agents/trainers/memory_mrcall.py

# MrCall configurator tools (4 files) — variable management for configurator
zylch/tools/mrcall/config_tools.py
zylch/tools/mrcall/feature_context_tool.py
zylch/tools/mrcall/llm_helper.py
zylch/tools/mrcall/variable_utils.py

# Firebase auth (1 file)
zylch/api/firebase_auth.py

# Entire API layer (14 files) — no HTTP server in standalone
zylch/api/__init__.py
zylch/api/main.py
zylch/api/token_storage.py
zylch/api/routes/__init__.py
zylch/api/routes/admin.py
zylch/api/routes/auth.py
zylch/api/routes/chat.py
zylch/api/routes/commands.py
zylch/api/routes/connections.py
zylch/api/routes/data.py
zylch/api/routes/jobs.py
zylch/api/routes/memory.py
zylch/api/routes/mrcall.py
zylch/api/routes/settings.py
zylch/api/routes/sync.py
zylch/api/routes/tracking.py
zylch/api/routes/webhooks.py

# Services only used by MrCall configurator / SaaS
zylch/services/sandbox_service.py
zylch/services/webhook_processor.py
zylch/services/validation_service.py

# Integrations registry (SaaS-only)
zylch/integrations/__init__.py
zylch/integrations/registry.py

# Sharing (multi-tenant feature)
zylch/sharing/__init__.py
zylch/sharing/authorization.py
zylch/sharing/intel_share.py

# SaaS-only tools
zylch/tools/sendgrid.py
zylch/tools/sharing_tools.py
zylch/tools/vonage.py
```

**Files to KEEP as MrCall channel (6 files)**:

```
# StarChat HTTP client — this IS the MrCall channel adapter
zylch/tools/starchat.py               # KEEP: contacts, calls, business config reads
                                        # MODIFY: remove create_starchat_client's dependency
                                        # on zylch.api.token_storage, simplify auth

zylch/tools/mrcall/__init__.py         # KEEP: package init for channel tools

# Tools that READ from or REQUEST actions via StarChat
zylch/tools/call_tools.py             # KEEP: InitiateCallTool — triggers outbound calls
zylch/tools/sms_tools.py              # KEEP: SendSMSTool — but refactor away from Vonage,
                                        # use StarChat API for SMS instead
zylch/tools/contact_tools.py          # KEEP: GetContactTool, GetWhatsAppContactsTool
                                        # These read from StarChat — they're channel tools
```

**Files to DELETE (non-Python, 10+ items)**:

```
# Deployment infra
Dockerfile
docker-compose.yml
Procfile
entrypoint.sh
railway.json
k8s/                          # entire directory
alembic.ini                   # replaced by simple schema init
alembic/                      # entire directory (SQLite uses CREATE IF NOT EXISTS)

# MrCall data
dt_variables_for_mrcall.json
data/alpha_testers.txt        # no alpha gating in local tool

# Legacy
frontend/                     # dormant Vue 3 prototype
migrations/                   # old migration scripts
zylch/storage/migrations/     # PostgreSQL migration SQL files
zylch/integrations/migrations/
consolidate-docs.sh
kb.sh
setup.sh
start-mcp.sh
test_api.sh
swarms/
spec/
credentials/
```

**Files to HEAVILY MODIFY (20 files)**:

```
zylch/config.py                    # Strip Firebase/SaaS config, add IMAP/SQLite config
                                    # KEEP MrCall config fields (base_url, realm, credentials)
zylch/storage/database.py          # PostgreSQL → SQLite engine
zylch/storage/models.py            # 29 models → ~12, remove PG-specific types
zylch/storage/storage.py           # pg_insert → SQLite upsert, remove TSVECTOR/ARRAY
zylch/tools/factory.py             # Remove SendGrid; KEEP StarChat client init + MrCall tools
                                    # Refactor StarChat client creation for local auth
zylch/tools/config.py              # Remove configurator-specific MrCall fields
                                    # KEEP MrCall channel fields (business_id, etc.)
zylch/tools/session_state.py       # Remove mrcall_config_mode; KEEP business_id selection
zylch/tools/starchat.py            # Remove dependency on zylch.api.token_storage
                                    # Simplify auth: Basic Auth or stored credentials
                                    # KEEP: all contact/business/call methods
zylch/tools/call_tools.py          # Light edits: adapt for local auth
zylch/tools/sms_tools.py           # Refactor: use StarChat for SMS instead of Vonage
zylch/tools/contact_tools.py       # Light edits: keep StarChat-based tools working
zylch/tools/gmail.py               # Replace Gmail API with IMAP (or delete + new file)
zylch/tools/gmail_tools.py         # Adapt for IMAP client
zylch/tools/email_sync.py          # IMAP incremental sync (UIDVALIDITY + UID)
zylch/tools/email_sync_tools.py    # Adapt for IMAP sync manager
zylch/services/chat_service.py     # Remove MrCall configurator routing (~300 lines), no SSE
                                    # KEEP: ability to route to MrCall channel tools
zylch/services/command_handlers.py # Remove MrCall configurator commands, add /init handler
                                    # KEEP: /mrcall select (pick business_id for channel)
zylch/services/sync_service.py     # IMAP sync instead of Gmail API
zylch/memory/hybrid_search.py      # Remove PG stored function, use numpy cosine
zylch/memory/blob_storage.py       # Store embeddings as BLOB, not pgvector
zylch/assistant/core.py            # Remove MrCall configurator references
zylch/assistant/prompts.py         # Remove MrCall configurator system prompts
                                    # ADD: MrCall channel description in system prompt
pyproject.toml                     # New deps, entry point, metadata
```

**Files to KEEP mostly as-is (30+ files)**:

```
zylch/llm/client.py               # Multi-provider via aisuite — keep
zylch/llm/providers.py             # Provider configs — keep
zylch/llm/exceptions.py            # LLM error types — keep
zylch/memory/embeddings.py         # fastembed engine — keep (no PG dependency)
zylch/memory/config.py             # Memory config — keep
zylch/memory/text_processing.py    # Sentence splitting — keep
zylch/memory/llm_merge.py          # Reconsolidation — keep
zylch/memory/pattern_detection.py  # Entity patterns — keep
zylch/tools/base.py                # Tool base classes — keep
zylch/tools/crm_tools.py           # Local CRM tools — keep (remove Pipedrive)
zylch/tools/web_search.py          # Web search tool — keep
zylch/agents/emailer_agent.py      # Email agent — keep
zylch/agents/task_orchestrator_agent.py  # Task agent — keep (light edits)
zylch/agents/base_agent.py         # Agent base — keep (remove MrCall configurator refs)
zylch/agents/trainers/base.py      # Trainer base — keep
zylch/agents/trainers/task_email.py     # Email task trainer — keep
zylch/agents/trainers/memory_email.py   # Email memory trainer — keep
zylch/agents/trainers/emailer.py        # Emailer trainer — keep
zylch/workers/task_creation.py     # Task creation — keep (adapt)
zylch/workers/memory.py            # Memory worker — keep (adapt)
zylch/utils/encryption.py          # Fernet encryption — keep
zylch/utils/auto_reply_detector.py # Auto-reply detection — keep
zylch/services/chat_session.py     # Chat session — keep
zylch/services/job_executor.py     # Job executor — keep (light edits)
zylch/services/command_matcher.py  # Semantic matching — keep (light edits)
zylch/ml/anonymizer.py             # Data anonymizer — keep
zylch/models/importance_rules.py   # Importance rules — keep
zylch/router/intent_classifier.py  # Intent router — keep
```

**Files to CREATE (12 files)**:

```
zylch/cli/__init__.py              # CLI package
zylch/cli/main.py                  # Entry point: `zylch` command
zylch/cli/chat.py                  # Interactive chat loop (absorb zylch-cli)
zylch/cli/init.py                  # `zylch init` onboarding wizard
zylch/cli/commands.py              # CLI subcommands (sync, status, etc.)
zylch/email/__init__.py            # Email package
zylch/email/imap_client.py         # IMAP client (replaces Gmail API)
zylch/storage/sqlite_init.py       # Schema creation (CREATE TABLE IF NOT EXISTS)
.env.example                       # Documented env template
```

---

## Dependencies: What Changes

### Remove (14 packages)

```
fastapi                    # No HTTP server
uvicorn                    # No HTTP server
firebase-admin             # No Firebase auth
google-auth-oauthlib       # No Google OAuth
google-api-python-client   # No Gmail/Calendar API (using IMAP)
psycopg2-binary            # No PostgreSQL
pgvector                   # No pgvector (numpy in-memory)
vonage                     # No Vonage (SMS via StarChat API)
sendgrid                   # No SendGrid
hnswlib                    # Replace with numpy brute-force
scikit-learn               # Not needed (numpy cosine is enough)
apscheduler                # No scheduled jobs in CLI
croniter                   # No cron
ecdsa                      # Firebase dependency
```

### Keep (11 packages)

```
anthropic                  # Direct Anthropic SDK for Claude
aisuite                    # Multi-provider LLM (OpenAI, Mistral, etc.)
httpx                      # HTTP client (StarChat, GOWA, web search)
pydantic                   # Data validation
pydantic-settings          # .env loading
python-dotenv              # .env file support
sqlalchemy                 # ORM (works with SQLite)
numpy                      # Vector cosine similarity
fastembed                  # Local embeddings (ONNX)
cryptography               # Fernet encryption for credentials
beautifulsoup4             # HTML email parsing (IMAP returns raw HTML)
```

### Add (5 packages)

```
rich                       # Terminal formatting (from zylch-cli)
click                      # CLI framework (from zylch-cli)
prompt-toolkit             # Already in deps — interactive input
alembic                    # Keep for schema migrations (lightweight with SQLite)
```

### Decision: alembic

Keep Alembic. SQLite schema will evolve over time and users running `pipx upgrade zylch`
need automatic migration. Create a single initial migration with all tables. Future
migrations handle schema changes. Migration runs automatically on `zylch` startup.

### Decision: litellm vs aisuite

Drop `litellm`. The codebase uses `aisuite` for multi-provider LLM. litellm is a
heavyweight dependency (~100MB) that duplicates functionality. If needed later, re-add.

### Decision: requests vs httpx

Drop `requests`. Keep `httpx` only. StarChat client already uses httpx. Consolidate
all HTTP to httpx (also needed for GOWA WhatsApp client in the future).

### Decision: beautifulsoup4

Keep `beautifulsoup4`. IMAP returns raw MIME including HTML bodies. We need bs4 to
extract text from HTML email bodies for indexing and display.

---

## Execution Plan: Work Streams

### Stream A: Delete MrCall Configurator Code (Complexity: LOW, ~2h)

This is the safest first step — deletion of configurator-specific code, while preserving
the MrCall channel (StarChat client + read/action tools).

**Guiding principle**: If the code CONFIGURES MrCall (writes variables, manages templates,
orchestrates configuration), delete it. If the code READS from MrCall or TRIGGERS actions
(contacts, calls, business status), keep it.

**A1. Delete MrCall configurator agents**
```
rm zylch/agents/mrcall_agent.py
rm zylch/agents/mrcall_context.py
rm zylch/agents/mrcall_error_handler.py
rm zylch/agents/mrcall_memory.py
rm zylch/agents/mrcall_orchestrator_agent.py
rm zylch/agents/mrcall_templates.py
rm zylch/agents/mrcall_variable_validator.py
rm zylch/agents/trainers/mrcall.py
rm zylch/agents/trainers/mrcall_configurator.py
rm zylch/agents/trainers/memory_mrcall.py
```

**A2. Delete MrCall configurator tools (keep `__init__.py`)**
```
rm zylch/tools/mrcall/config_tools.py
rm zylch/tools/mrcall/feature_context_tool.py
rm zylch/tools/mrcall/llm_helper.py
rm zylch/tools/mrcall/variable_utils.py
```

Note: `zylch/tools/mrcall/__init__.py` is kept — the package survives as the MrCall
channel tool package. Future MrCall channel-specific tools go here.

**A3. Delete Firebase + API layer**
```
rm zylch/api/firebase_auth.py
rm -rf zylch/api/               # Entire API layer
```

**A4. Delete SaaS-only services and tools**
```
rm zylch/services/sandbox_service.py
rm zylch/services/webhook_processor.py
rm zylch/services/validation_service.py
rm -rf zylch/integrations/
rm -rf zylch/sharing/
rm zylch/tools/sendgrid.py
rm zylch/tools/sharing_tools.py
rm zylch/tools/vonage.py
```

**A5. Delete deployment infra**
```
rm Dockerfile docker-compose.yml Procfile entrypoint.sh railway.json
rm alembic.ini
rm -rf alembic/ k8s/ frontend/ swarms/ spec/ credentials/
rm dt_variables_for_mrcall.json
rm consolidate-docs.sh kb.sh setup.sh start-mcp.sh test_api.sh
```

**A6. Refactor starchat.py for standalone auth**

The `create_starchat_client()` factory function currently depends on
`zylch.api.token_storage` (deleted in A3). Refactor to:

```python
# New auth flow for standalone:
# 1. Read credentials from OAuthToken table (encrypted, local SQLite)
# 2. Support Basic Auth (env vars) or stored OAuth token
# 3. No Firebase JWT — standalone users authenticate via stored credentials

async def create_starchat_client(owner_id: str, storage=None) -> StarChatClient:
    """Create StarChat client from locally stored credentials."""
    from zylch.config import settings

    # Try stored OAuth credentials first
    if storage:
        creds = storage.get_oauth_token(owner_id, provider="mrcall")
        if creds and creds.get("access_token"):
            return StarChatClient(
                base_url=settings.mrcall_base_url,
                auth_type="oauth",
                access_token=creds["access_token"],
                realm=settings.mrcall_realm,
            )

    # Fallback to Basic Auth from env
    if settings.starchat_username:
        return StarChatClient(
            base_url=settings.mrcall_base_url,
            auth_type="basic",
            username=settings.starchat_username,
            password=settings.starchat_password,
            realm=settings.mrcall_realm,
        )

    raise ValueError("MrCall not connected. Use /connect mrcall to set up.")
```

Also remove the `_refresh_token_if_needed()` method's dependency on
`zylch.api.token_storage` — use local storage instead.

**A7. Clean MrCall configurator references in remaining files**

Files requiring MrCall **configurator** reference removal (imports, conditionals, comments).
References to MrCall as a **channel** (StarChat client, business_id, contacts) are kept.

| File | What to remove | What to KEEP |
|---|---|---|
| `zylch/agents/__init__.py` | MrCall configurator imports | — |
| `zylch/agents/base.py` | MrCall configurator references | — |
| `zylch/agents/base_agent.py` | MrCall configurator references | — |
| `zylch/agents/trainers/__init__.py` | MrCall trainer imports | — |
| `zylch/tools/factory.py` | MrCall configurator tool creation, SendGrid tools | StarChat client init, call_tools, contact_tools with StarChat |
| `zylch/tools/config.py` | MrCall configurator config fields | MrCall channel fields (business_id) |
| `zylch/tools/session_state.py` | `mrcall_config_mode`, `sandbox_mode` | `business_id` selection state |
| `zylch/tools/contact_tools.py` | — | All tools (they read from StarChat) |
| `zylch/tools/call_tools.py` | — | All tools (they trigger calls via StarChat) |
| `zylch/tools/sms_tools.py` | Vonage dependency | Refactor to use StarChat SMS API |
| `zylch/services/chat_service.py` | ~400 lines of configurator routing, sandbox, `/mrcall` config commands | MrCall channel tool routing |
| `zylch/services/command_handlers.py` | `/mrcall configure` commands | `/mrcall` business selection command |
| `zylch/services/command_matcher.py` | MrCall configurator command patterns | MrCall channel command patterns |
| `zylch/services/job_executor.py` | MrCall configurator job types | — |
| `zylch/workers/memory.py` | MrCall configurator memory processing | — |
| `zylch/assistant/core.py` | MrCall configurator agent references | — |
| `zylch/assistant/prompts.py` | MrCall configurator system prompts | MrCall channel description in prompts |
| `zylch/config.py` | Firebase fields, CORS, webhook, alpha tester | MrCall fields: `mrcall_base_url`, `mrcall_realm`, `starchat_username`, `starchat_password`, `starchat_verify_ssl` |
| `zylch/storage/storage.py` | `MrcallConversation` imports, `set_mrcall_link`, `get_mrcall_link` | — |
| `zylch/storage/models.py` | `MrcallConversation` model | — |
| `zylch/llm/providers.py` | MrCall-specific provider config (if any) | — |

**A7 verification**: After deletion, run `python -c "import zylch"` to check for broken imports.

---

### Stream B: PostgreSQL to SQLite (Complexity: HIGH, ~6h)

This is the most invasive change. Every storage layer file changes.

**B1. Rewrite `zylch/storage/database.py`**

Replace PostgreSQL engine with SQLite:

```python
# Key changes:
# - database_url default: "sqlite:///~/.zylch/zylch.db" (expanded at runtime)
# - Remove pool_size, max_overflow, pool_recycle (not needed for SQLite)
# - Add connect_args={"check_same_thread": False} for SQLite
# - Add WAL mode pragma on connect event
# - Auto-create ~/.zylch/ directory
```

**B2. Rewrite `zylch/storage/models.py`**

Current state: 29 models using PostgreSQL-specific types (UUID, JSONB, TSVECTOR, ARRAY, Vector).

Target state: ~12 models using SQLite-compatible types.

| PostgreSQL Type | SQLite Replacement |
|---|---|
| `UUID(as_uuid=True)` | `Text` (store UUID as string) |
| `JSONB` | `Text` (store JSON as string, parse in Python) |
| `TSVECTOR` | Remove (FTS done differently or not needed) |
| `ARRAY(Text)` | `Text` (store as JSON array string) |
| `Vector(384)` | `LargeBinary` (store as numpy bytes via BLOB) |
| `server_default=text("gen_random_uuid()")` | `default=lambda: str(uuid.uuid4())` |
| `server_default=text("now()")` | `default=datetime.utcnow` |
| `Computed(...)` | Remove (computed columns not supported in SQLite) |

Models to KEEP (12):

| Model | Notes |
|---|---|
| `Email` | Core. Remove `fts_document`, `tsv` (computed cols). `embedding` → BLOB. |
| `CalendarEvent` | Keep for future CalDAV. |
| `Blob` | Core memory. `embedding` → BLOB, remove `tsv`. |
| `BlobSentence` | Core memory. `embedding` → BLOB. |
| `OAuthToken` | Stores IMAP credentials, LLM API keys, AND MrCall credentials. `credentials` → JSON Text. |
| `TaskItem` | Core task tracking. `sources` → JSON Text. |
| `BackgroundJob` | Job tracking. `result`, `params` → JSON Text. |
| `AgentPrompt` | LLM prompt storage. `metadata` → JSON Text. |
| `UserNotification` | Notification queue. |
| `Contact` | Contact storage. `metadata` → JSON Text. |
| `Draft` | Email drafts. ARRAY cols → JSON Text. |
| `SyncState` | Sync tracking. |

Models to DROP (17):

```
OAuthState          # No OAuth flow
Trigger             # No webhook triggers
TriggerEvent        # No webhook events
SharingAuth         # No multi-tenant sharing
PipedriveDeal       # Pipedrive CRM (future: generic CRM)
EmailReadEvent      # SendGrid tracking
SendgridMessageMapping  # SendGrid
MrcallConversation  # MrCall configurator state
VerificationCode    # SMS verification
EmailTriage         # Complex triage (simplify into TaskItem)
TrainingSample      # ML training samples
ImportanceRule      # Can re-add later if needed
IntegrationProvider # SaaS integration registry
TriageTrainingSample # ML training
Pattern             # Behavioral patterns (can re-add later)
ScheduledJob        # Server-side scheduling
ThreadAnalysis      # Legacy
ErrorLog            # Server error logging
```

**B3. Rewrite `zylch/storage/storage.py`**

Major changes:
- Replace `from sqlalchemy.dialects.postgresql import insert as pg_insert` with SQLite-compatible upsert
- SQLite upsert: `INSERT OR REPLACE` or `sqlite_insert(...).on_conflict_do_update()`
- All JSONB access patterns → parse JSON strings in Python
- All ARRAY column access → parse JSON array strings
- Remove FTS queries (PostgreSQL `ts_query`) — replace with SQLite FTS5 or LIKE
- Remove MrCall configurator methods (`set_mrcall_link`, `get_mrcall_link`, ~100 lines)
- Remove SendGrid, SMS verification, sharing methods
- `owner_id` becomes a fixed default value (mono-user) — keep the column for schema compatibility but auto-fill

**B4. Create `zylch/storage/sqlite_init.py`**

```python
# Schema initialization for SQLite
# - CREATE TABLE IF NOT EXISTS for all 12 models
# - CREATE INDEX for frequently queried columns
# - FTS5 virtual table for email full-text search
# - WAL mode pragma
# - Called from `zylch init` and on first startup
```

**B5. Alembic for SQLite**

- New `alembic.ini` pointing to SQLite
- Single initial migration creating all tables
- Auto-migration on startup: `alembic upgrade head` called from CLI entry point
- Keep Alembic env.py simple (no pgvector, no extensions)

**B5 verification**: Create test that initializes fresh SQLite DB, runs migrations, inserts sample data.

---

### Stream C: IMAP Email Client (Complexity: MEDIUM, ~4h)

**C1. Create `zylch/email/__init__.py` and `zylch/email/imap_client.py`**

IMAP client replacing Gmail API. Uses Python stdlib `imaplib` + `email` modules.

```python
class IMAPClient:
    """IMAP email client for Zylch standalone.

    Supports:
    - Connect via IMAP + app password (Gmail, Outlook, any provider)
    - Fetch messages (by UID range, by date, by search)
    - Incremental sync via UIDVALIDITY + highest UID
    - Parse MIME messages to subject/from/to/body_plain/body_html
    - Mark as read/unread
    - Search (IMAP SEARCH command)
    """

    def __init__(self, host: str, port: int, email: str, password: str):
        ...

    def connect(self) -> None: ...
    def fetch_messages(self, since_uid: int = None, folder: str = "INBOX") -> List[dict]: ...
    def search(self, query: str, folder: str = "INBOX") -> List[dict]: ...
    def get_message(self, uid: int) -> dict: ...
    def sync_incremental(self, last_uid: int, last_uidvalidity: int) -> dict: ...
```

Key IMAP details:
- Gmail: `imap.gmail.com:993`, requires app password (not regular password)
- Outlook: `outlook.office365.com:993`, requires app password
- Generic: configurable host/port
- Store `uidvalidity` and `last_uid` in SyncState table for incremental sync

**C2. Delete/replace Gmail OAuth files**

```
DELETE: zylch/tools/gmail.py           # Gmail API client (OAuth-based)
DELETE: zylch/tools/outlook.py         # Outlook Graph API client
DELETE: zylch/tools/outlook_calendar.py # Outlook calendar
DELETE: zylch/tools/gcalendar.py       # Google Calendar API (keep for CalDAV later?)
DELETE: zylch/tools/calendar_sync.py   # Google Calendar sync
DELETE: zylch/tools/email_archive.py   # Gmail archive manager
DELETE: zylch/tools/pipedrive.py       # Pipedrive CRM
```

**C3. Adapt `zylch/tools/gmail_tools.py` → `zylch/tools/email_tools.py`**

Rename and adapt tool classes to use IMAP client instead of Gmail API:
- `GmailSearchTool` → `EmailSearchTool` (IMAP SEARCH)
- `CreateDraftTool` → keep (store draft locally, send via SMTP)
- Remove `RefreshGoogleAuthTool` (no OAuth)

**C4. Adapt `zylch/tools/email_sync_tools.py`**

- `SyncEmailsTool` → use IMAP incremental sync
- `SearchEmailsTool` → use SQLite FTS5 for local search
- Keep `CloseEmailThreadTool`, `EmailStatsTool`

**C5. Adapt `zylch/services/sync_service.py`**

Replace Gmail API sync logic with IMAP sync:
- Use UIDVALIDITY to detect mailbox restructure
- Track last synced UID per folder
- Parse MIME messages into Email model fields

**C6. Add SMTP support for sending**

```python
# zylch/email/smtp_client.py (future, lower priority)
# For now, drafts are stored locally. Sending is Phase 2.
```

---

### Stream D: Integrate CLI (Complexity: MEDIUM, ~4h)

**D1. Create `zylch/cli/` package**

Absorb relevant parts from `zylch-cli/zylch_cli/`:

| Source (zylch-cli) | Target (zylch/cli/) | Notes |
|---|---|---|
| `cli.py` (ZylchCLI class) | `zylch/cli/chat.py` | Adapt: direct function calls, no HTTP |
| `config.py` (CLIConfig) | `zylch/cli/config.py` | Simplify: no server URL, no session token |
| `local_storage.py` | Remove | Use main SQLite DB instead |
| `api_client.py` | Remove | No HTTP — direct service calls |
| `oauth_handler.py` | Remove | No OAuth flow |
| `modifier_queue.py` | `zylch/cli/modifier_queue.py` | Keep if useful for input buffering |

**D2. Create `zylch/cli/main.py`**

```python
"""Zylch CLI entry point.

Usage:
    zylch              # Interactive chat mode
    zylch init         # Onboarding wizard
    zylch sync         # Manual email sync
    zylch status       # Show connection status
    zylch search <q>   # Search emails/memory
"""

@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx):
    if ctx.invoked_subcommand is None:
        # Default: interactive chat
        run_chat()

@main.command()
def init():
    """Interactive setup wizard."""
    ...

@main.command()
def sync():
    """Sync emails from IMAP."""
    ...

@main.command()
def status():
    """Show connection status."""
    ...
```

**D3. Create `zylch/cli/chat.py`**

Interactive chat loop using `prompt_toolkit` and `rich`:
- Direct calls to `ChatService.process_message()` — no HTTP
- Slash command routing via existing `command_handlers.py`
- Rich markdown rendering for responses
- History saved to `~/.zylch/history`
- Auto-sync on first message (if not synced recently)

**D4. Create `zylch/cli/init.py`**

`zylch init` onboarding wizard:

```
1. Welcome message
2. Ask: LLM provider (anthropic/openai/mistral)
3. Ask: API key → validate with test call
4. Ask: Email address
5. Ask: IMAP host (auto-detect from email domain)
6. Ask: App password → validate with IMAP login test
7. Optional: MrCall connection
   - Ask: StarChat base URL (or skip)
   - Ask: StarChat credentials (Basic Auth username/password)
   - Validate with test call to StarChat
8. Create ~/.zylch/ directory
9. Write .env file
10. Initialize SQLite DB (run migrations)
11. Run initial email sync (last 30 days)
12. "Ready! Run `zylch` to start."
```

Auto-detect IMAP settings:
```python
IMAP_PRESETS = {
    "gmail.com": ("imap.gmail.com", 993),
    "outlook.com": ("outlook.office365.com", 993),
    "hotmail.com": ("outlook.office365.com", 993),
    "yahoo.com": ("imap.mail.yahoo.com", 993),
    "icloud.com": ("imap.mail.me.com", 993),
}
```

---

### Stream E: In-Memory Vector Search (Complexity: MEDIUM, ~3h)

**E1. Rewrite `zylch/memory/hybrid_search.py`**

Current: calls PostgreSQL stored function `hybrid_search_blobs()` with pgvector.

Target: pure Python/numpy implementation.

```python
class HybridSearchEngine:
    """Hybrid search: SQLite FTS5 + numpy cosine similarity."""

    def __init__(self, get_session, embedding_engine):
        self._get_session = get_session
        self.embeddings = embedding_engine
        self._vector_cache = {}  # blob_id → numpy array, loaded on first search

    def _load_vectors(self, owner_id, namespace=None):
        """Load all blob embeddings into memory from SQLite BLOB columns."""
        ...

    def _cosine_search(self, query_vec, vectors, top_k):
        """Brute-force cosine similarity with numpy."""
        # vectors: (N, 384) numpy array
        # query_vec: (384,) numpy array
        similarities = vectors @ query_vec / (
            np.linalg.norm(vectors, axis=1) * np.linalg.norm(query_vec)
        )
        top_indices = np.argsort(similarities)[-top_k:][::-1]
        return top_indices, similarities[top_indices]

    def search(self, owner_id, query, namespace=None, limit=10, alpha=0.5):
        """Hybrid search combining FTS5 + cosine similarity."""
        # 1. FTS5 search on SQLite (if query has identifiers)
        # 2. Cosine search on in-memory vectors
        # 3. Combine scores with alpha weighting
        # 4. Return top-k results
        ...
```

**E2. Adapt `zylch/memory/blob_storage.py`**

- Store embeddings as `numpy.tobytes()` in SQLite BLOB column
- Load embeddings with `numpy.frombuffer()`
- Invalidate vector cache when new blobs are stored

**E3. SQLite FTS5 setup**

Create FTS5 virtual table for email full-text search:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
    subject, body_plain, from_email, from_name,
    content='emails', content_rowid='rowid'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER emails_fts_insert AFTER INSERT ON emails BEGIN
    INSERT INTO emails_fts(rowid, subject, body_plain, from_email, from_name)
    VALUES (new.rowid, new.subject, new.body_plain, new.from_email, new.from_name);
END;
```

FTS5 for blobs:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS blobs_fts USING fts5(
    content, namespace,
    content='blobs', content_rowid='rowid'
);
```

**E3 note**: SQLite FTS5 replaces PostgreSQL `TSVECTOR` + `ts_query`. The search syntax
is different (`MATCH` instead of `@@`) but the concept is the same.

---

### Stream F: Package for pipx (Complexity: LOW, ~1h)

**F1. Rewrite `pyproject.toml`**

```toml
[project]
name = "zylch"
version = "0.2.0"
description = "Local AI sales intelligence — email analysis, memory, task management"
authors = [{name = "Mario Alemi", email = "mario@zylchai.com"}]
license = {text = "MIT"}
requires-python = ">=3.11"
keywords = ["cli", "ai", "email", "sales", "intelligence", "memory"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Environment :: Console",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
]
dependencies = [
    "anthropic>=0.39.0",
    "aisuite>=0.1.14",
    "httpx>=0.25.0",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.0.0",
    "python-dotenv>=1.0.0",
    "sqlalchemy>=2.0.0",
    "alembic>=1.13.0",
    "numpy>=1.24.0",
    "fastembed>=0.4.0",
    "cryptography>=41.0.0",
    "rich>=13.7.0",
    "click>=8.1.7",
    "prompt-toolkit>=3.0.50",
    "beautifulsoup4>=4.12.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.23.0",
    "black>=23.0.0",
    "ruff>=0.1.0",
]

[project.scripts]
zylch = "zylch.cli.main:main"

[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"
```

**F2. Create `.env.example`**

```env
# === Zylch Configuration ===
# Generated by `zylch init`. Edit manually if needed.

# LLM Provider (anthropic, openai, mistral)
SYSTEM_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
# MISTRAL_API_KEY=

# Email (IMAP)
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_EMAIL=you@gmail.com
IMAP_PASSWORD=your-app-password

# SMTP (for sending — optional)
# SMTP_HOST=smtp.gmail.com
# SMTP_PORT=587
# SMTP_EMAIL=you@gmail.com
# SMTP_PASSWORD=your-app-password

# MrCall / StarChat (optional — phone channel)
# MRCALL_BASE_URL=https://test-env-0.scw.hbsrv.net
# MRCALL_REALM=default
# STARCHAT_USERNAME=
# STARCHAT_PASSWORD=

# Database (default: ~/.zylch/zylch.db)
# DATABASE_URL=sqlite:///~/.zylch/zylch.db

# Encryption key (auto-generated by `zylch init`)
ENCRYPTION_KEY=

# Log level
LOG_LEVEL=INFO
```

**F3. Delete old zylch-cli directory**

```
rm -rf zylch-cli/     # Now absorbed into zylch/cli/
```

**F4. Update `README.md`**

Rewrite for standalone local tool. Installation:
```
pipx install zylch
zylch init
zylch
```

---

## Execution Order and Dependencies

```
Stream A (Delete MrCall Configurator, Keep Channel)
    │
    ├── can start immediately, no dependencies
    │
    v
Stream B (SQLite)          Stream C (IMAP)         Stream D (CLI)
    │                          │                       │
    ├── depends on A           ├── depends on A        ├── depends on A
    │   (clean imports)        │   (clean imports)     │   (clean imports)
    │                          │                       │
    v                          v                       v
Stream E (Vector Search)   ← depends on B (SQLite models must exist)
    │
    v
Stream F (Package)         ← depends on all above
    │
    v
Final: Integration Test
    pipx install . && zylch init && zylch
```

**Recommended serial execution order:**

1. **Stream A** — Delete MrCall configurator code, refactor StarChat for local auth (2h)
2. **Stream B** — SQLite migration (6h) — most critical, enables everything else
3. **Stream C** — IMAP email client (4h) — can partially overlap with B
4. **Stream E** — In-memory vector search (3h) — depends on B
5. **Stream D** — CLI integration (4h) — can partially overlap with C/E
6. **Stream F** — Packaging (1h) — final step

**Total estimated effort: ~20h of focused work (3-4 sessions)**

---

## Future Items (Not Planned in Detail)

### 8. CalDAV Calendar
- Library: `caldav` (Python CalDAV client)
- Supports Google Calendar, Outlook, iCloud, Nextcloud
- No OAuth needed — CalDAV uses basic auth or app passwords
- Store events in existing `CalendarEvent` model
- Priority: after email sync is stable

### 9. GOWA WhatsApp Integration
- GOWA = go-whatsapp-web-multidevice (Go binary, runs locally)
- Zylch communicates via GOWA REST API (localhost)
- New `zylch/whatsapp/gowa_client.py`
- Store messages in new `WhatsAppMessage` model
- Priority: after CalDAV

### 10. MrCall Channel Enhancements
- Read call logs from StarChat (inbound/outbound history)
- Read WhatsApp conversations from StarChat
- Delegate complex configuration requests to StarChat/mrcall-agent
- Show MrCall assistant status (active, configured features)
- Priority: after core channels (email, calendar) are stable

### 11. Cost Tracking
- Track LLM token usage per operation
- Store in `llm_usage` table (model, input_tokens, output_tokens, cost_usd)
- Show daily/weekly cost summary via `/cost` command
- Anthropic SDK already returns usage in response
- Priority: low, add when LLM costs become relevant

---

## Verification Checklist

After all streams complete:

- [ ] `python -c "import zylch"` succeeds with no import errors
- [ ] `python -m pytest tests/ -v` passes (update/delete broken tests)
- [ ] `zylch init` creates `~/.zylch/`, writes `.env`, initializes SQLite
- [ ] `zylch` starts interactive chat, processes slash commands
- [ ] `/sync` fetches emails via IMAP and stores in SQLite
- [ ] `/email search <query>` finds emails via FTS5
- [ ] Free-form chat queries LLM with tool access
- [ ] Memory search returns results via numpy cosine similarity
- [ ] StarChat client connects and reads contacts (if MrCall configured)
- [ ] `/mrcall` selects a business and shows status
- [ ] Call and SMS tools work via StarChat API
- [ ] `pipx install .` works on clean Python 3.11+ environment
- [ ] `ruff check zylch/` passes with no errors
- [ ] `black --check zylch/` passes
- [ ] No file exceeds 500 lines
- [ ] No references to Firebase, PostgreSQL, pgvector remain
- [ ] No references to MrCall **configurator** remain (agents, templates, variable validator)
- [ ] `grep -r "firebase\|psycopg\|pgvector" zylch/` returns nothing
- [ ] `grep -r "mrcall_agent\|mrcall_context\|mrcall_templates\|mrcall_orchestrator\|mrcall_variable_validator\|mrcall_error_handler\|mrcall_memory\|mrcall_configurator" zylch/` returns nothing
- [ ] StarChat references in `starchat.py`, `call_tools.py`, `contact_tools.py` remain and work
