# Zylch AI Development Plan

**For Agent-driven Code Implementation**

---

## Critical: No Local Filesystem

**The backend uses Supabase for ALL data storage. NO local filesystem.**

- OAuth tokens → Supabase `oauth_tokens` (encrypted with Fernet)
- All user data → Supabase (scoped by `owner_id`)
- Memory/Blobs → Supabase pg_vector

---

## Project Overview

Zylch AI is a multi-channel sales intelligence system that helps sales professionals manage email communications, track relationships, and automate follow-up actions through an AI-powered assistant.

### Core Principles

1. **Person-centric architecture** — A person is NOT an email address; memory system reflects this reality
2. **Human-in-the-loop** — AI assists and recommends, human makes final decisions
3. **Multi-provider support** — Works with Gmail AND Outlook (provider-agnostic)
4. **Cloud-based storage** — All data in Supabase (scoped by owner_id with RLS)
5. **Multi-platform goal** — CLI now, desktop and mobile apps in the future

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
- ZylchAIAgent with LLM API through LiteLLM (Anthropic, Google, OpenAI, Mistral)
- Native function calling with 30+ tools
- Conversational CLI interface

**Email Intelligence**
- Gmail integration (OAuth, read/send/drafts)
- Microsoft Outlook integration (Graph API)
- Two-tier caching: Archive (permanent) + Intelligence (30-day analyzed)
- Thread analysis, task detection, relationship gaps
- Email read tracking (SendGrid webhooks + custom pixel)

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
| **LLM** | Uses LiteLLM | — | Defined in .env
| **Data Storage** | Supabase (Postgres) | — | All data (emails, AI summaries, tokens) |
| **User Auth** | Firebase Auth | — | Separate project per product |
| **Backend Hosting** | Railway | — | ✅ Live at api.zylchai.com |
| **Frontend Hosting** | Vercel | — | ✅ Live at app.zylchai.com |
| **Payments** | — | Stripe | To be implemented |
| **Jobs** | In Postgres | - | For scaling |
| **Email Providers** | Gmail, Outlook | — | Provider-agnostic |
| **Telephony** | StarChat/MrCall | — | Outbound calls |
| **SMS** | Vonage | — | Campaigns + webhooks |
| **Email Campaigns** | SendGrid | — | Bulk email |
| **Desktop App** | Terminal | - | Future consideration |
| **Mobile/Web App** | Just a test in ./frontend |  | Most probably no native |

---

## Repository Structure

```
zylch/
├── .claude/
│   ├── CONVENTIONS.md
│   ├── DEVELOPMENT_PLAN.md      # This file
│   ├── DOCUMENTATION.md
│   └── TESTING.md
├── zylch/
│   ├── agents/
│   │   ├── memory_agent.py      # Memory extraction agent
│   │   └── task_agent.py        # Task detection agent
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
│   │   ├── blob_storage.py      # Vector storage
│   │   ├── hybrid_search.py     # Search engine
│   │   └── llm_merge.py         # Reconsolidation
│   ├── ml/
│   │   └── anonymizer.py        # PII stripping
│   ├── models/
│   │   └── importance_rules.py  # Importance logic
│   ├── services/
│   │   ├── archive_service.py
│   │   ├── assistant_manager.py
│   │   ├── chat_service.py
│   │   ├── command_handlers.py         # Slash command handlers
│   │   ├── email_memory_agent_trainer.py
│   │   ├── email_task_agent_trainer.py
│   │   ├── scheduler.py
│   │   ├── sync_service.py
│   │   ├── trigger_service.py          # Event-driven trigger worker
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
├── zylch_memory/                 # Legacy/Standalone memory package
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

### Current: Supabase (Cloud-Based)

**All data stored in Supabase**, scoped by `owner_id` (Firebase UID):

| Table | Purpose |
|-------|---------|
| `emails` | Email metadata and content with vector embeddings |
| `task_items` | Tasks with sources JSONB for traceability |
| `calendar_events` | Calendar events |
| `sync_state` | Gmail/Outlook history IDs |
| `oauth_tokens` | Encrypted tokens (Google, Microsoft, Anthropic) |
| `scheduled_jobs` | Scheduled reminders and timed actions |
| `triggers` | Triggered instructions |
| `trigger_events` | Event queue |
| `sharing_auth` | Sharing authorizations |
| `blobs` | Memory storage (pg_vector) |
| `agent_prompts` | Personalized agent prompts |
| `task_items` | Detected tasks |
| `email_read_events` | Email read tracking events |
| `sendgrid_message_mapping` | SendGrid message ID mapping |

**Security**:
- All tables use UUID primary keys
- Row Level Security (RLS) for multi-tenant isolation
- Indexes on `owner_id` for performance
- Sensitive tokens encrypted with Fernet before storage

See `zylch/storage/supabase_client.py` for storage operations.

### Future: Local-First Options (Not Yet Implemented)

When desktop/mobile apps are developed, we may explore local-first storage:

| Approach | Technology | Use Case |
|----------|------------|----------|
| **SQLite (Local)** | SQLite + sqlcipher | CLI, Desktop apps |
| **IndexedDB** | Web Crypto AES-GCM | Web app (PWA) |
| **Tauri + SQLite** | Tauri (Rust) + SQLite | Desktop app |
| **Capacitor + SQLite** | Capacitor plugin | Mobile app |
| **Flutter + SQLite** | sqflite / Hive | Cross-platform mobile |

**Decision pending**: Will evaluate when building desktop/mobile apps.

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
| POST | `/webhooks/sendgrid` | SendGrid email events + read tracking |
| POST | `/webhooks/vonage/status` | SMS delivery status |
| POST | `/webhooks/vonage/inbound` | Inbound SMS |
| GET | `/api/track/pixel/{id}` | Email read tracking pixel |

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
/sync                      # Full sync (email + calendar)
/tasks                     # Show detected tasks
/archive --stats           # Archive statistics
/archive --search <query>  # Search emails
/memory search <query>     # Search memory blobs
/memory list               # List memories
/agent memory train        # Train memory agent
/agent task train          # Train task agent
/connect                   # Show integrations status
/connect --help            # Show connect help
/trigger --list            # List triggered instructions
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
| `/tasks` | ✅ | `handle_tasks()` |
| `/archive` | ✅ | `handle_archive()` |
| `/memory` | ✅ | `handle_memory()` |
| `/agent` | ✅ | `handle_agent()` |
| `/connect` | ✅ | `handle_connect()` |
| `/trigger` | ✅ | `handle_trigger()` |
| `/mrcall` | ✅ | `handle_mrcall()` |
| `/share` | ✅ | `handle_share()` |
| `/revoke` | ✅ | `handle_revoke()` |
| `/sharing` | ✅ | `handle_sharing()` |
| `/tutorial` | ✅ | `handle_tutorial()` |

**Performance Optimization** (Complete):
- [x] `get_tasks` tool — Returns pre-formatted task list from task_items (avoids 27s LLM formatting)
- [x] Update `/gaps` to show task details, not just counts
- [x] `/gaps` no longer loads ZylchMemory (removed ~1min ML model load)

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

### ✅ Phase G.5: Email Read Tracking (Complete)

**Goal**: Track when recipients open emails sent by Zylch for improved follow-up intelligence.

**Status**: ✅ **COMPLETE** - Implementation finished December 2025

**Reference**: See `docs/features/email-read-tracking.md` and `IMPLEMENTATION_SUMMARY.md` for complete details

**Approach**:
- **PRIMARY**: SendGrid webhooks for batch emails (leverages SendGrid's built-in tracking)
- **SECONDARY**: Custom 1x1 tracking pixel for individual emails

**Completed Tasks**:
- [x] Database migration (003_email_read_tracking.sql)
  - [x] `email_read_events` table with RLS policies
  - [x] `sendgrid_message_mapping` table
  - [x] Modified `messages` table with `read_events` JSONB column
  - [x] 12 performance indexes
  - [x] Helper functions and triggers
- [x] API endpoints
  - [x] `POST /api/webhooks/sendgrid` - SendGrid webhook handler with ECDSA verification
  - [x] `GET /api/track/pixel/{tracking_id}` - Tracking pixel endpoint
- [x] Storage layer (`supabase_client.py`)
  - [x] `create_sendgrid_message_mapping()`
  - [x] `get_sendgrid_message_mapping()`
  - [x] `record_sendgrid_read_event()`
  - [x] `record_custom_pixel_read_event()`
  - [x] `_update_message_read_events()`
- [x] Intelligence integration
  - [x] Task agent: Read tracking data method
  - [x] Task agent: Priority boosting (+2 for unread 7+ days, +1 for unread 3+ days)
  - [x] Task agent: Enhanced LLM action generation with read context
  - [x] Task display: Display indicators `📧❌ (unread 5d)` or `📧✓ (read 4d ago)`
- [x] Documentation
  - [x] Feature documentation (`docs/features/email-read-tracking.md`)
  - [x] Implementation guide (`docs/features/email-read-tracking-implementation.md`)
  - [x] Implementation summary (`IMPLEMENTATION_SUMMARY.md`)
  - [x] Updated `docs/README.md`
  - [x] Updated `.claude/ARCHITECTURE.md`
  - [x] Updated `.claude/DEVELOPMENT_PLAN.md`

**Deliverables**:
- ✅ Dual tracking system operational (SendGrid webhooks + custom pixel)
- ✅ Read tracking data integrated into task system
- ✅ Database schema with multi-tenant RLS
- ✅ Privacy-compliant (US laws: CAN-SPAM, CCPA)
- ✅ 90-day data retention with auto-cleanup
- ✅ Task list shows read indicators for all tasks
- ✅ Complete documentation suite

**Next Steps** (Pending Testing):
- [ ] Run database migration on staging
- [ ] Configure SendGrid webhook
- [ ] End-to-end testing with real emails
- [ ] Add `ecdsa` to requirements.txt
- [ ] Deploy to production

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

### Phase H: Billing (Stripe) (🔴 Critical - Revenue Generation)

**Goal**: Subscription billing for paid features.

**Status**: ❌ Not started - Required for monetization

**Reference**: See `docs/features/BILLING_SYSTEM_TODO.md` for comprehensive implementation plan

**Pricing Tiers**:
- **Free**: $0/month - 500 emails, 50 calendar events, basic features
- **Pro**: $29/month - 10K emails, 1K calendar events, advanced AI, priority support
- **Team**: $99/month - 50K emails, 5K events, team features, API access

**Tasks**:
- [ ] Set up Stripe account and products
- [ ] Create subscription products and pricing
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
- [ ] Feature gating per tier
- [ ] Usage tracking and quota enforcement

**Deliverables**:
- ✅ Stripe integration working
- ✅ Users can subscribe and manage billing
- ✅ Feature gating based on subscription
- ✅ Usage tracking and quota limits
- ✅ Trial period and conversion tracking

**Business Impact**:
- Revenue generation: Target $14,500/month by month 12
- Customer acquisition: Free tier for onboarding
- Retention: Pro tier value proposition
- Growth: Team tier for enterprise

**Timeline**: 5 weeks (see BILLING_SYSTEM_TODO.md for phases)

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

### Phase I.5: Microsoft Calendar Feature Parity (🟡 Medium-High - Enterprise Adoption)

**Goal**: Complete Outlook Calendar implementation for feature parity with Google Calendar.

**Status**: ❌ Not started - Partial implementation exists

**Reference**: See `docs/features/MICROSOFT_CALENDAR_TODO.md` for comprehensive plan

**Current State**:
- ✅ `OutlookCalendarClient` class exists (partially implemented)
- ✅ Microsoft OAuth flow working
- ✅ Graph API access configured
- ❌ Calendar tools not registered
- ❌ No Teams meeting link generation
- ❌ No calendar sync integration

**Tasks**:
- [ ] Complete `OutlookCalendarClient` implementation
  - [ ] Finish `create_event()` method
  - [ ] Implement `update_event()` method
  - [ ] Implement `search_events()` method
  - [ ] Add Teams meeting link generation
- [ ] Create calendar tools:
  - [ ] `ListOutlookCalendarEventsTool`
  - [ ] `CreateOutlookCalendarEventTool`
  - [ ] `SearchOutlookCalendarEventsTool`
  - [ ] `UpdateOutlookCalendarEventTool`
- [ ] Extend `SyncService` for Outlook calendar
- [ ] Integrate with gap analysis (meeting without follow-up)
- [ ] Add provider column to database schema

**Deliverables**:
- ✅ 100% feature parity with Google Calendar
- ✅ Teams meeting links work
- ✅ Outlook calendar syncs automatically
- ✅ Gap analysis includes Outlook meetings

**Business Impact**:
- Target: 40%+ of users connect Outlook calendar
- Enterprise adoption: 60%+ of enterprise users use Outlook
- Multi-provider: 20%+ use both Google and Outlook

**Timeline**: 2-3 weeks (see MICROSOFT_CALENDAR_TODO.md for phases)

---

### Phase J: Scaling & Optimization (🟢 Low - Triggered by Growth)

**Goal**: Production hardening and performance for scale.

**Status**: ❌ Not started - Waiting for scaling needs

**Reference**: See `docs/features/REDIS_SCALING_TODO.md` for comprehensive plan

**Trigger Conditions**:
- API response times exceed 500ms P95
- Database costs exceed $200/month
- 1,000+ concurrent users
- Performance degradation detected

**Tasks**:
- [ ] Add Upstash Redis for:
  - [ ] Session management
  - [ ] Rate limiting (tier-based)
  - [ ] Webhook retry queue
  - [ ] Caching (80%+ hit rate target)
- [ ] Implement caching strategy:
  - [ ] Cache relationship gaps (5 min TTL)
  - [ ] Cache tasks (10 min TTL)
  - [ ] Cache contact memory (1 hour TTL)
- [ ] Implement rate limiting per user/tier
- [ ] Add Sentry for error tracking
- [ ] Set up logging and monitoring
- [ ] Performance optimization
- [ ] Load testing with Locust

**Deliverables**:
- ✅ Production-ready infrastructure
- ✅ Monitoring and alerting
- ✅ Scalable architecture (10,000+ users)
- ✅ <100ms API response times (cached endpoints)
- ✅ 80%+ cache hit rate
- ✅ 5x reduction in database load

**Business Impact**:
- Cost savings: 50% reduction in Supabase costs
- User experience: 3x faster perceived performance
- Scalability: Support 10,000+ concurrent users

**Timeline**: 3 weeks when triggered (see REDIS_SCALING_TODO.md for phases)

---

## Future Enhancements

Detailed implementation plans for future features are documented in `docs/features/`:

### 🔴 High Priority Future Features

**WhatsApp Integration** (Reference: `WHATSAPP_INTEGRATION_TODO.md`)
- **Market**: 6.9 billion WhatsApp users worldwide
- **Status**: Tool structure ready, awaiting StarChat REST API endpoint
- **Implementation**: Multi-channel conversation threading, WhatsApp gap analysis
- **Timeline**: 2-3 weeks once API endpoint available
- **Business Impact**: Reach 6.9B users, multi-channel intelligence

### 🟡 Medium Priority Future Features

**Desktop Application** (Reference: `DESKTOP_APP_TODO.md`)
- **Technology**: Tauri (Rust + Vue 3) - 600KB vs 60MB Electron
- **Features**: Local SQLite database, hybrid cloud sync, system tray, keyboard shortcuts
- **Target Users**: Power users, privacy-conscious professionals, offline workers
- **Timeline**: 5-6 weeks
- **Business Impact**: 15%+ desktop adoption, premium positioning

**Mobile Application** (Reference: `MOBILE_APP_TODO.md`)
- **Technology**: React Native (iOS + Android)
- **Features**: Push notifications, biometric auth (Face ID/Touch ID), offline support
- **Market**: 5.3 billion smartphone users, 90% of internet time on mobile
- **Timeline**: 6-8 weeks
- **Business Impact**: 10,000+ downloads in 3 months, App Store presence

**Real-Time Gmail Push** (Reference: `REAL_TIME_PUSH_TODO.md`)
- **Technology**: Gmail Pub/Sub, WebSocket live updates
- **Performance**: <5 second latency from email arrival to frontend update
- **Features**: Instant relationship gaps, zero-latency intelligence
- **Timeline**: 3 weeks
- **Business Impact**: 2x increase in daily active users, 40% faster response time

### Enhancement Priorities

**Reasoning Bank (Pattern Learning)**
- Supabase-based pattern storage
- Cross-contact learning
- Strategy recommendations
- Confidence scoring
- **Status**: Future consideration

**Vector Search Scaling**
- Migrate to dedicated vector DB when >5K contacts
- Options: Pinecone, Weaviate, or continue with Supabase pg_vector
- **Trigger**: When semantic search becomes bottleneck

**Multi-Assistant Support**
- Multiple Zylch assistants per owner
- Different contexts (work, personal, team)
- **Status**: Future consideration for Team tier

---

## Milestone Checklist

- [x] **M1: Core Working** — Agent + tools + CLI (Phases A-B)
- [x] **M2: Multi-Tenant** — Auth + sharing + webhooks (Phases C-E)
- [x] **M2.5: CLI Migration** — Backend command handlers (Phase E.5) — *Complete*
- [x] **M3: Production Backend** — Railway deployment (Phase F) — *Complete & deployed at api.zylchai.com*
- [x] **M4: Dashboard** — Web UI (Phase G) — *Complete & deployed on Vercel*
- [x] **M4.5: Email Read Tracking** — Intelligence integration (Phase G.5) — *Complete*
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
Models: Configured via ANTHROPIC_MODEL env var (one model per provider)
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
