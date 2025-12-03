# Zylch AI Development Plan

**For Claude Code Implementation**

---

## Project Overview

Zylch AI is a multi-channel sales intelligence system that helps sales professionals manage email communications, track relationships, and automate follow-up actions through an AI-powered assistant.

### Core Principles

1. **Person-centric architecture** — A person is NOT an email address; memory system reflects this reality
2. **Human-in-the-loop** — AI assists and recommends, human makes final decisions
3. **Multi-provider support** — Works with Gmail AND Outlook (provider-agnostic)
4. **Local-first, cloud-ready** — SQLite now, Supabase migration planned

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
- ZylchMemory (SQLite + semantic search)
- Person-centric architecture with reconsolidation
- Behavioral memory and corrections
- Identifier map cache for O(1) lookups

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
| **Database** | SQLite (local) | Supabase (Postgres) | Migration planned |
| **User Auth** | Firebase Auth | — | Separate project per product |
| **Backend Hosting** | Docker (local) | Railway | Migration planned |
| **Frontend Hosting** | — | Vercel | For dashboard |
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
│   │   ├── local_storage.py     # Offline cache
│   │   └── modifier_queue.py    # Offline operations
│   ├── memory/
│   │   ├── pattern_store.py
│   │   └── reasoning_bank.py
│   ├── services/
│   │   ├── archive_service.py
│   │   ├── assistant_manager.py
│   │   ├── chat_service.py
│   │   ├── gap_service.py
│   │   ├── persona_analyzer.py
│   │   ├── scheduler.py
│   │   ├── sync_service.py
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
├── cache/                        # Local cache (gitignored)
├── credentials/                  # OAuth tokens (gitignored)
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
FIREBASE_SERVICE_ACCOUNT_PATH=credentials/firebase-service-account.json

# Google OAuth (Gmail, Calendar)
GOOGLE_CREDENTIALS_PATH=credentials/google_oauth.json
GOOGLE_TOKEN_PATH=~/.zylch/credentials/google/

# Microsoft Graph API (Outlook)
# Tokens stored in ~/.zylch/credentials/microsoft/

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

## Database Schema

### Current: SQLite (Local)

**Email Archive** (`cache/emails/archive.db`)
```sql
CREATE TABLE emails (
    id TEXT PRIMARY KEY,
    thread_id TEXT,
    subject TEXT,
    from_email TEXT,
    to_emails TEXT,  -- JSON array
    date TIMESTAMP,
    body TEXT,
    labels TEXT,     -- JSON array
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE emails_fts USING fts5(
    subject, body, from_email,
    content='emails', content_rowid='rowid'
);
```

**Memory** (`zylch_memory.db`)
```sql
CREATE TABLE memories (
    id INTEGER PRIMARY KEY,
    namespace TEXT,
    category TEXT,
    context TEXT,
    pattern TEXT,
    examples TEXT,   -- JSON
    confidence REAL,
    embedding BLOB,  -- Vector
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

**Sharing** (`cache/sharing.db`)
```sql
CREATE TABLE authorizations (
    id TEXT PRIMARY KEY,
    owner_id TEXT,
    recipient_id TEXT,
    permissions TEXT,  -- JSON
    created_at TIMESTAMP,
    expires_at TIMESTAMP
);
```

### Future: Supabase (Postgres)

Migration will preserve same schema structure with:
- UUID primary keys
- Row-level security (RLS) for multi-tenant
- Indexes on owner_id, timestamps
- pg_vector extension for embeddings

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

- ZylchMemory (SQLite + semantic search)
- Person-centric architecture
- Behavioral corrections
- Pattern learning
- Identifier map cache

### ✅ Phase C: Intelligence Sharing (Complete)

- SharingAuthorizationManager
- IntelShareManager
- Consent-based sharing
- CLI commands: /share, /revoke, /sharing

### ✅ Phase D: Multi-Tenant + Docker (Complete)

- CLI Firebase Authentication (browser OAuth)
- owner_id from Firebase UID
- Dockerfile + docker-compose.yml
- Persistent volumes for cache/data
- Microsoft Outlook integration

### ✅ Phase E: Webhook Server (Complete)

- FastAPI webhook endpoints
- StarChat message webhooks
- SendGrid email webhooks
- Vonage SMS webhooks
- Firebase JWT validation

### Phase G: Dashboard (Frontend) (Completed)

**Goal**: Web dashboard for non-CLI users.

**Tasks**:
- [ ] Set up Vue 3 + Vite + TypeScript project
- [ ] Configure Vercel deployment
- [ ] Implement Firebase Auth (same project as backend)
- [ ] Build core views:
    - [ ] Login/Signup
    - [ ] Dashboard (overview, status)
    - [ ] Email view (gaps, threads)
    - [ ] Calendar view
    - [ ] Settings
- [ ] Connect to backend API
- [ ] Mobile-responsive design

**Deliverables**:
- Dashboard at app.zylch.com (Vercel)
- Full feature parity with CLI
- Mobile-friendly

---

---

## Remaining Phases

### Phase F: Railway Deployment (Configuration Complete)

**Goal**: Deploy backend to Railway for production hosting.

**Status**: ✅ Configuration files created. Ready for Railway project creation.

**Tasks**:
- [x] Create railway.json configuration
- [x] Create Procfile for web process
- [x] Create requirements.txt from pyproject.toml
- [x] Create .env.example with all environment variables
- [x] Configure health checks in railway.json
- [x] Create deployment documentation (docs/DEPLOYMENT.md)
- [ ] Create Railway project (manual step)
- [ ] Configure environment variables in Railway (manual step)
- [ ] Set up custom domain api.zylch.com (manual step)
- [ ] Configure persistent volume for SQLite (manual step)

**Files Created**:
- `railway.json` - Railway build and deploy configuration
- `Procfile` - Process definition (uvicorn with 2 workers)
- `requirements.txt` - Python dependencies
- `.env.example` - Complete environment variable template
- `docs/DEPLOYMENT.md` - Full deployment guide

**Deliverables**:
- Backend running on Railway
- API accessible via custom domain
- Automatic deploys from main branch

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

### Phase I: Supabase Migration

**Goal**: Migrate from local SQLite to Supabase Postgres.

**Tasks**:
- [ ] Set up Supabase project
- [ ] Design schema with RLS (row-level security)
- [ ] Create migration scripts
- [ ] Add SQLAlchemy + asyncpg
- [ ] Update storage layer to use Postgres
- [ ] Migrate memory system to pg_vector
- [ ] Test multi-tenant isolation
- [ ] Data migration from SQLite

**Deliverables**:
- All data in Supabase
- Multi-tenant RLS working
- Local SQLite as optional fallback

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
- SQLite-based pattern storage
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
- [~] **M3: Production** — Railway deployment (Phase F) — *Config complete, manual steps pending*
- [ ] **M4: Dashboard** — Web UI on Vercel (Phase G)
- [ ] **M5: Monetization** — Stripe billing (Phase H)
- [ ] **M6: Scale** — Supabase + Redis (Phases I-J)

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
