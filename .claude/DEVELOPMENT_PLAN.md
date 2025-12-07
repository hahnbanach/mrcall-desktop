# Zylch AI Development Plan

**For Claude Code Implementation**

---

## Critical: No Local Filesystem

**The backend uses Supabase for ALL data storage. NO local filesystem.**

- OAuth tokens → Supabase `oauth_tokens` (encrypted with Fernet)
- All user data → Supabase (scoped by `owner_id`)
- Memory/Avatars → Supabase pg_vector

**NEVER use `credentials/`, `cache/`, or local pickle files. These are LEGACY and UNUSED.**

---

## Project Overview

Zylch AI is a multi-channel sales intelligence system that helps sales professionals manage email communications, track relationships, and automate follow-up actions through an AI-powered assistant.

### Core Principles

1. **Person-centric architecture** — A person is NOT an email address; memory system reflects this reality
2. **Human-in-the-loop** — AI assists and recommends, human makes final decisions
3. **Multi-provider support** — Works with Gmail AND Outlook (provider-agnostic)
4. **Database-only backend** — All server data in Supabase, no local filesystem
5. **Local-first email storage** — Email content stored in browser IndexedDB (encrypted), never on Zylch servers (like Superhuman)

---

## Current State Summary

### Completed Phases

| Phase | Description | Status |
|-------|-------------|--------|
| **Phase A** | Core Agent + Tools | ✅ Complete |
| **Phase B** | Memory System (ZylchMemory) | ✅ Complete |
| **Phase C** | Intelligence Sharing | ✅ Complete |
| **Phase D** | Multi-Tenant + Docker | ✅ Complete |
| **Phase E** | Webhook Server | ✅ Complete |

### Implemented Features

**Core Agent**
- ZylchAIAgent with Claude API (Haiku/Sonnet/Opus tiering)
- Native function calling with 30+ tools
- Conversational CLI interface

**Email Intelligence**
- Gmail integration (OAuth, read/send/drafts)
- Microsoft Outlook integration (Graph API)
- Two-tier caching: Archive (permanent) + Intelligence (30-day analyzed)
- Thread analysis, task detection, relationship gaps

**Calendar**
- Google Calendar integration
- Outlook Calendar integration
- Event management with Meet/Teams links

**Memory System**
- ZylchMemory (Supabase pg_vector + semantic search)
- Person-centric architecture with reconsolidation
- Behavioral memory and corrections
- Identifier map for O(1) lookups

**Integrations**
- StarChat/MrCall (contacts, telephony)
- SendGrid (email campaigns)
- Vonage (SMS)
- Pipedrive CRM (optional)

**Multi-Tenant**
- Firebase Authentication (Google, Microsoft OAuth)
- Per-user isolation (owner_id from Firebase UID)
- Provider-based client selection

**Automation**
- Triggered instructions system (event-driven)
- Webhook server (StarChat, SendGrid, Vonage events)
- APScheduler for reminders
- Validation system with --check flag

**User Experience**
- Interactive CLI with tab completion
- Tutorial system with sandbox mode
- Persona learning (background analysis)

---

## Technology Stack

| Component | Current | Future | Notes |
|-----------|---------|--------|-------|
| **Language** | Python 3.11+ | — | FastAPI, async throughout |
| **LLM** | Anthropic Claude | — | Haiku/Sonnet/Opus tiering |
| **Email Storage** | IndexedDB (browser) | — | Local-first, encrypted (like Superhuman) |
| **Email Encryption** | Web Crypto API | — | AES-GCM 256-bit, PBKDF2 key derivation |
| **Server Database** | Supabase (Postgres) | — | AI summaries & metadata only (no email content) |
| **User Auth** | Firebase Auth | — | Separate project per product |
| **Backend Hosting** | Railway | — | ✅ Live at api.zylchai.com |
| **Frontend Hosting** | Vercel | — | ✅ Live at app.zylchai.com |
| **Payments** | — | Stripe | To be implemented |
| **Queues** | — | Upstash Redis | For scaling |
| **Email Providers** | Gmail, Outlook | — | Provider-agnostic |
| **Telephony** | StarChat/MrCall | — | Outbound calls |
| **SMS** | Vonage | — | Campaigns + webhooks |
| **Email Campaigns** | SendGrid | — | Bulk email |

---

## Repository Structure

```
zylch/
├── .claude/
│   ├── ARCHITECTURE.md
│   ├── CONVENTIONS.md
│   ├── DEVELOPMENT_PLAN.md      # This file
│   ├── DOCUMENTATION.md
│   └── TESTING.md
├── zylch/
│   ├── agent/
│   │   ├── core.py              # ZylchAIAgent
│   │   ├── models.py
│   │   └── prompts.py
│   ├── api/
│   │   ├── main.py              # FastAPI app
│   │   └── routes/
│   │       ├── archive.py
│   │       ├── chat.py
│   │       ├── data.py
│   │       ├── gaps.py
│   │       ├── sync.py
│   │       └── webhooks.py
│   ├── cli/
│   │   ├── main.py              # ZylchAICLI
│   │   ├── auth.py              # CLIAuthManager
│   │   ├── auth_server.py       # OAuth callback server
│   │   ├── local_storage.py     # Legacy (unused)
│   │   └── modifier_queue.py    # Offline operations
│   ├── memory/
│   │   ├── pattern_store.py
│   │   └── reasoning_bank.py
│   ├── services/
│   │   ├── archive_service.py
│   │   ├── assistant_manager.py
│   │   ├── chat_service.py
│   │   ├── command_handlers.py    # Slash command handlers
│   │   ├── gap_service.py
│   │   ├── persona_analyzer.py
│   │   ├── scheduler.py
│   │   ├── sync_service.py
│   │   ├── trigger_service.py     # Event-driven trigger worker
│   │   ├── validation_service.py
│   │   └── webhook_processor.py
│   ├── sharing/
│   │   ├── authorization.py
│   │   └── intel_share.py
│   ├── storage/
│   │   ├── email_store.py
│   │   ├── calendar_store.py
│   │   └── contact_store.py
│   ├── tools/
│   │   ├── factory.py           # ToolFactory
│   │   ├── gmail.py
│   │   ├── outlook.py
│   │   ├── gcalendar.py
│   │   ├── outlook_calendar.py
│   │   ├── email_archive.py
│   │   ├── email_sync.py
│   │   ├── starchat.py
│   │   ├── instruction_tools.py
│   │   └── ...
│   ├── tutorial/
│   │   ├── tutorial_manager.py
│   │   └── steps/
│   └── config.py
├── zylch_memory/                 # Semantic memory package
├── zylch-cli/                    # Thin client (separate)
├── zylch-website/                # Marketing site
├── tests/
├── cache/                        # Legacy (unused, gitignored)
├── credentials/                  # Legacy (unused, gitignored)
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── zylch-cli                     # Launcher script
```

---

## Environment Variables

### Backend (.env)

```bash
# Environment
ENVIRONMENT=development  # development | staging | production

# Anthropic
ANTHROPIC_API_KEY=sk-ant-xxx

# Firebase (separate project per product)
FIREBASE_PROJECT_ID=zylch-xxx
FIREBASE_API_KEY=xxx
FIREBASE_AUTH_DOMAIN=zylch-xxx.firebaseapp.com
# Firebase (Base64-encoded service account JSON)
FIREBASE_SERVICE_ACCOUNT_BASE64=eyJ0eXBlIjoic2VydmljZV9hY2NvdW50Ii...

# Google/Microsoft OAuth tokens stored in Supabase oauth_tokens table (encrypted)

# StarChat/MrCall
STARCHAT_API_URL=https://api.starchat.com
STARCHAT_USERNAME=xxx
STARCHAT_PASSWORD=xxx
STARCHAT_BUSINESS_ID=xxx

# SendGrid
SENDGRID_API_KEY=SG.xxx

# Vonage SMS
VONAGE_API_KEY=xxx
VONAGE_API_SECRET=xxx
VONAGE_FROM_NUMBER=+1xxx

# Pipedrive (optional)
PIPEDRIVE_API_TOKEN=xxx
PIPEDRIVE_ENABLED=false

# Email Style
EMAIL_STYLE_PROMPT="Use professional tone, no emojis"
MY_EMAILS=mario@example.com,*@mrcall.ai

# Future: Stripe
# STRIPE_SECRET_KEY=sk_xxx
# STRIPE_WEBHOOK_SECRET=whsec_xxx
# STRIPE_PRICE_ID=price_xxx

# Future: Supabase
# DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/postgres

# Future: Railway
# Configured via Railway dashboard
```

---

## Data Storage Architecture

### Browser Storage (IndexedDB) - Email Content

**Email content stored locally, encrypted** (like Superhuman):

| Store | Content | Encryption |
|-------|---------|------------|
| `emails` | Full email bodies (HTML, plaintext) | AES-GCM 256-bit |
| `email_metadata` | From, to, subject, date, thread_id | AES-GCM 256-bit |
| `attachments` | Cached attachment content | AES-GCM 256-bit |
| `crypto_keys` | Non-extractable CryptoKey | Browser-protected |

**Encryption**: Web Crypto API, key derived from user auth via PBKDF2.

### Server Storage (Supabase) - Metadata & AI Only

**NO email content on server.** Only AI summaries and sync state:

| Table | Purpose |
|-------|---------|
| `thread_analysis` | AI-generated summaries (no raw email) |
| `calendar_events` | Calendar events |
| `sync_state` | Gmail/Outlook history IDs |
| `relationship_gaps` | Detected gaps |
| `oauth_tokens` | Encrypted tokens (Google, Microsoft, Anthropic) |
| `triggers` | Triggered instructions |
| `trigger_events` | Event queue |
| `sharing_auth` | Sharing authorizations |

All Supabase tables use UUID primary keys, RLS for multi-tenant isolation, indexes on `owner_id`.

See `zylch/storage/supabase_client.py` for server storage operations.

---

## API Endpoints Summary

### Public API (requires Firebase auth)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/chat/message` | Send chat message |
| GET | `/api/chat/history` | Get chat history |
| GET | `/api/archive/search` | Search email archive |
| GET | `/api/archive/stats` | Archive statistics |
| POST | `/api/sync/full` | Full sync (email + calendar) |
| POST | `/api/sync/emails` | Sync emails only |
| POST | `/api/sync/calendar` | Sync calendar only |
| GET | `/api/gaps` | Get relationship gaps |
| GET | `/api/data/emails` | List email threads |
| GET | `/api/data/calendar` | List calendar events |
| GET | `/api/data/contacts` | List contacts |

### Webhooks

| Method | Endpoint | Source |
|--------|----------|--------|
| POST | `/webhooks/starchat` | StarChat call events |
| POST | `/webhooks/sendgrid` | SendGrid email events |
| POST | `/webhooks/vonage/status` | SMS delivery status |
| POST | `/webhooks/vonage/inbound` | Inbound SMS |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |

---

## CLI Commands Reference

### Authentication
```bash
./zylch-cli --login        # Browser OAuth login
./zylch-cli --logout       # Clear credentials
./zylch-cli --status       # Show auth status
```

### Interactive Commands
```
/help                      # Show all commands
/sync                      # Full sync (email + calendar + gaps)
/gaps                      # Show relationship gaps
/archive --stats           # Archive statistics
/archive --search <query>  # Search emails
/memory --list             # List behavioral memories
/memory --add              # Add behavioral memory
/trigger --list            # List triggered instructions
/trigger --add             # Add triggered instruction
/cache --clear             # Clear caches
/model <haiku|sonnet|opus> # Switch AI model
/tutorial                  # Start tutorial
/quit                      # Exit
```

---

## Implementation Phases

### ✅ Phase A: Core Agent + Tools (Complete)

- ZylchAIAgent with Claude API
- Gmail integration (OAuth, read/send/drafts)
- Google Calendar integration
- StarChat/MrCall integration
- Contact enrichment tools
- Basic CLI interface

### ✅ Phase B: Memory System (Complete)

- ZylchMemory (Supabase pg_vector + semantic search)
- Person-centric architecture
- Behavioral corrections
- Pattern learning
- Identifier map cache

### ✅ Phase C: Intelligence Sharing (Complete)

- SharingAuthorizationManager
- IntelShareManager
- Consent-based sharing
- CLI commands: /share, /revoke, /sharing

### ✅ Phase D: Multi-Tenant + Supabase (Complete)

- Firebase Authentication (Google, Microsoft OAuth)
- owner_id from Firebase UID
- All data in Supabase (no local storage)
- Microsoft Outlook integration

### ✅ Phase E: Webhook Server (Complete)

- FastAPI webhook endpoints
- StarChat message webhooks
- SendGrid email webhooks
- Vonage SMS webhooks
- Firebase JWT validation

### ✅ Phase E.5: CLI Migration to Backend (Complete)

**Goal**: Migrate old monolithic CLI to thin client with backend command handlers.

**Completed**:
- [x] Backend command handlers for all slash commands
- [x] Trigger system with Supabase storage
- [x] Trigger service worker for event-driven automation
- [x] MrCall integration handler (`/mrcall`)
- [x] Sharing system (`/share`, `/revoke`, `/sharing`)
- [x] All tests passing (163 tests, 7 skipped)

**Command Handlers** (`zylch/services/command_handlers.py`):
| Command | Status | Handler |
|---------|--------|---------|
| `/help` | ✅ | `handle_help()` |
| `/sync` | ✅ | `handle_sync()` |
| `/gaps` | ✅ | `handle_gaps()` |
| `/archive` | ✅ | `handle_archive()` |
| `/cache` | ✅ | `handle_cache()` |
| `/memory` | ✅ | `handle_memory()` |
| `/model` | ✅ | `handle_model()` |
| `/trigger` | ✅ | `handle_trigger()` |
| `/mrcall` | ✅ | `handle_mrcall()` |
| `/share` | ✅ | `handle_share()` |
| `/revoke` | ✅ | `handle_revoke()` |
| `/sharing` | ✅ | `handle_sharing()` |
| `/tutorial` | ✅ | `handle_tutorial()` |

**Trigger Service** (`zylch/services/trigger_service.py`):
- Event queue with Supabase storage
- Background worker for processing
- Support for: `session_start`, `email_received`, `sms_received`, `call_received`

**Documentation**:
- `docs/TRIGGERED_INSTRUCTIONS.md` - Updated for new architecture
- `docs/SHARING.md` - New documentation for sharing system

### ✅ Phase G: Dashboard (Frontend) (Complete & Deployed)

**Goal**: Web dashboard for non-CLI users.

**Status**: ✅ **DEPLOYED ON VERCEL** at https://app.zylchai.com

**Tasks**:
- [x] Set up Vue 3 + Vite + TypeScript project
- [x] Configure Tailwind CSS and component architecture
- [x] Implement Firebase Auth (Google, Microsoft OAuth)
- [x] Build core views:
    - [x] Login/Signup with OAuth
    - [x] Dashboard (chat interface)
    - [x] Email view (threads, drafts, archive)
    - [x] Tasks view (Kanban board)
    - [x] Calendar view
    - [x] Contacts view
    - [x] Memory management
    - [x] Settings (integrations, API keys)
    - [x] Sync status
    - [x] MrCall integration
- [x] Connect to backend API with Axios + interceptors
- [x] Pinia state management with persistence
- [x] Mobile-responsive design
- [x] Deploy to Vercel

**Deliverables**:
- ✅ Complete Vue 3 dashboard with ~58 components
- ✅ Full feature parity with CLI
- ✅ Firebase authentication
- ✅ Real-time sync status
- ✅ BYOK (Bring Your Own Key) for Anthropic API
- ✅ **Live at https://app.zylchai.com**

---

---

## Remaining Phases

### ✅ Phase F: Railway Deployment (Complete & Deployed)

**Goal**: Deploy backend to Railway for production hosting.

**Status**: ✅ **DEPLOYED ON RAILWAY** at https://api.zylchai.com

**Tasks**:
- [x] Create railway.json configuration
- [x] Create Procfile for web process
- [x] Create requirements.txt from pyproject.toml
- [x] Create .env.example with all environment variables
- [x] Configure health checks in railway.json
- [x] Create deployment documentation (docs/DEPLOYMENT.md)
- [x] Create Railway project
- [x] Configure environment variables in Railway
- [x] Set up custom domain api.zylchai.com
- [x] Deploy and verify health check

**Deliverables**:
- ✅ Backend running on Railway
- ✅ API accessible at https://api.zylchai.com
- ✅ Health check: `GET /health` returns `{"status": "healthy"}`

---

### Phase H: Billing (Stripe) ()

**Goal**: Subscription billing for paid features.

**Tasks**:
- [ ] Set up Stripe account and products
- [ ] Create pricing tiers:
  - Free: Limited emails/month
  - Pro: Full access
  - Team: Multi-user (future)
- [ ] Implement backend routes:
  - [ ] `POST /api/billing/checkout` — Create Stripe checkout
  - [ ] `GET /api/billing/portal` — Stripe customer portal
  - [ ] `POST /webhooks/stripe` — Handle Stripe events
- [ ] Handle Stripe webhooks:
  - [ ] `checkout.session.completed`
  - [ ] `customer.subscription.updated`
  - [ ] `customer.subscription.deleted`
  - [ ] `invoice.payment_failed`
- [ ] Add subscription checking middleware
- [ ] Build billing UI in dashboard
- [ ] Implement trial logic (14 days)

**Deliverables**:
- Stripe integration working
- Users can subscribe and manage billing
- Feature gating based on subscription

---

### ✅ Phase I: Supabase Migration (Complete)

**Goal**: All data in Supabase Postgres.

**Status**: ✅ **COMPLETE** - All data stored in Supabase.

**Completed**:
- [x] Supabase project configured
- [x] Schema with RLS (row-level security)
- [x] All storage via `supabase_client.py`
- [x] pg_vector for semantic memory
- [x] Multi-tenant isolation by owner_id
- [x] Encrypted token storage (Fernet)

**No local filesystem storage.**

---

### Phase J: Scaling & Optimization

**Goal**: Production hardening and performance.

**Tasks**:
- [ ] Add Upstash Redis for:
  - [ ] Session management
  - [ ] Rate limiting
  - [ ] Webhook retry queue
- [ ] Implement rate limiting per user
- [ ] Add Sentry for error tracking
- [ ] Set up logging and monitoring
- [ ] Performance optimization
- [ ] Load testing

**Deliverables**:
- Production-ready infrastructure
- Monitoring and alerting
- Scalable architecture

---

## Future Enhancements

### Reasoning Bank (Pattern Learning)
- Supabase-based pattern storage
- Cross-contact learning
- Strategy recommendations
- Confidence scoring

### Vector Search Scaling
- Migrate to dedicated vector DB when >5K contacts
- Options: Pinecone, Weaviate, or Supabase pg_vector

### WhatsApp Integration
- Pending StarChat REST API endpoint (ApiZapi?)
- Tool structure already in place

### Real-Time Gmail Push
- Gmail Pub/Sub notifications
- Zero-latency email intelligence

### Multi-Assistant Support
- Multiple Zylch assistants per owner
- Different contexts (work, personal)

---

## Milestone Checklist

- [x] **M1: Core Working** — Agent + tools + CLI (Phases A-B)
- [x] **M2: Multi-Tenant** — Auth + sharing + webhooks (Phases C-E)
- [x] **M2.5: CLI Migration** — Backend command handlers (Phase E.5) — *Complete*
- [x] **M3: Production Backend** — Railway deployment (Phase F) — *Complete & deployed at api.zylchai.com*
- [x] **M4: Dashboard** — Web UI (Phase G) — *Complete & deployed on Vercel*
- [ ] **M5: Monetization** — Stripe billing (Phase H)
- [x] **M6: Supabase** — Database migration (Phase I) — *Complete*
- [ ] **M7: Scale** — Redis for caching (Phase J)

---

## Code Style & Conventions

### Python (Backend)
- Use `async`/`await` throughout
- Type hints on all functions
- Pydantic for all request/response schemas
- SQLAlchemy 2.0 style queries
- Dependency injection via FastAPI `Depends`

### TypeScript (Frontend - when implemented)
- Composition API with `<script setup>`
- Pinia for state management
- Axios for HTTP
- TypeScript strict mode

### Naming
- API endpoints: kebab-case (`/api/email-archive`)
- Python: snake_case
- TypeScript: camelCase
- Database: snake_case

### Git
- Conventional commits: `feat:`, `fix:`, `docs:`, `chore:`
- Branch from `main`
- PR for all changes

---

## Testing Strategy

### Current
- Unit tests: `tests/` directory
- pytest + pytest-asyncio
- Run: `python -m pytest tests/ -v`

### Target Coverage
- Tools: 80%+
- Services: 70%+
- API routes: 60%+

---

## Security Considerations

### Current (Development)
- OAuth tokens encrypted at rest
- API keys in environment variables
- Firebase auth on all endpoints
- Per-user data isolation

### Production (Phases F+)
- HTTPS enforced
- CORS properly configured
- Rate limiting
- Input validation
- Audit logging
- GDPR compliance (data export, deletion)

---

## Quick Reference: External APIs

### Anthropic Claude
```
Models: claude-3-5-haiku, claude-sonnet-4, claude-opus-4
Features: tool_use, prompt caching
```

### Gmail API
```
Scopes: gmail.readonly, gmail.send, gmail.compose
Auth: OAuth 2.0
```

### Microsoft Graph
```
Scopes: Mail.Read, Mail.Send, Calendars.ReadWrite
Auth: OAuth 2.0 via Firebase
```

### StarChat
```
Auth: Basic Auth (username/password)
Endpoints: /mrcall/v1/crm/*, /mrcall/v1/call/*
```

---

*This document is the source of truth for Zylch development. Update as phases progress.*
