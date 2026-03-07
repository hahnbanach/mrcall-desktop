# Zylch AI Documentation

Welcome to Zylch AI - your AI-powered email assistant for relationship intelligence, task management, and automated workflows.

## 📚 Documentation Overview

This documentation is organized into the following sections:

### Quick Start
- **[Gmail OAuth Setup](guides/gmail-oauth.md)** - Configure Google OAuth for Gmail access
- **[Deployment Guide](guides/DEPLOYMENT.md)** - Scaleway Kubernetes deployment with GitLab CI/CD
- **[Getting Started Guide](../ZYLCH_BUSINESS_MODEL.md)** - Business model and product vision

### Core Features
- **[Email Archive](features/email-archive.md)** - Permanent email storage with full-text search
- **[Email Archive](features/email-archive.md)** - Two-tier email storage and AI-powered analysis
- **[Email Read Tracking](features/email-read-tracking.md)** - SendGrid webhooks and tracking pixel for email engagement ✅ **NEW**
  - [Implementation Guide](features/email-read-tracking-implementation.md) - Setup and configuration
- **[Calendar Integration](features/calendar-integration.md)** - Google Calendar with Meet links
- **[Relationship Intelligence](features/relationship-intelligence.md)** - Gap detection and task extraction
- **[Task Management](features/task-management.md)** - Task detection from emails and calendars
- **[Triggers & Automation](features/triggers-automation.md)** - Event-driven workflow automation *(coming soon)*
- **[Sharing System](features/sharing-system.md)** - Consent-based intelligence sharing *(coming soon)*
- **[Entity Memory System](features/entity-memory-system.md)** - Entity-centric persistent memory with hybrid search and reconsolidation
- **[MrCall Integration](features/mrcall-integration.md)** - Telephony and WhatsApp integration *(coming soon)*

### Future Development
- **[Billing System](features/BILLING_SYSTEM_TODO.md)** 🔴 Critical - Stripe integration and subscription tiers
- **[WhatsApp Integration](features/WHATSAPP_INTEGRATION_TODO.md)** 🔴 High - Multi-channel messaging
- **[Microsoft Calendar](features/MICROSOFT_CALENDAR_TODO.md)** 🟡 Medium-High - Outlook Calendar feature parity
- **[Desktop Application](features/DESKTOP_APP_TODO.md)** 🟡 Medium - Tauri desktop app
- **[Mobile Application](features/MOBILE_APP_TODO.md)** 🟡 Medium - React Native iOS/Android
- **[Real-Time Push](features/REAL_TIME_PUSH_TODO.md)** 🟡 Medium - Gmail Pub/Sub notifications
- **[Redis Scaling](features/REDIS_SCALING_TODO.md)** 🟢 Low - Caching and performance optimization

### Architecture & Development
- **[Architecture](ARCHITECTURE.md)** - System architecture, design patterns, and technical specifications
- **[Development Plan](../.claude/DEVELOPMENT_PLAN.md)** - Project roadmap and phases
- **[Conventions](../.claude/CONVENTIONS.md)** - Code style and development standards
- **[Testing Strategy](../.claude/TESTING.md)** - Testing approach and guidelines
- **[Documentation Guide](../.claude/DOCUMENTATION.md)** - How to write documentation

### User Guides
- **[CLI Commands](guides/cli-commands.md)** - Complete CLI command reference *(coming soon)*

### Archive
- **[Archived Documentation](../ARCHIVE/)** - Old documentation and completion reports

## 🎯 Quick Navigation

### For Users
1. Start with [Gmail OAuth Setup](guides/gmail-oauth.md) to configure authentication
2. Learn about [Email Archive](features/email-archive.md) to understand AI analysis
3. Explore [Relationship Intelligence](features/relationship-intelligence.md) for gap detection

### For Developers
1. Review [Architecture Overview](ARCHITECTURE.md) for system design
2. Check [Development Plan](../.claude/DEVELOPMENT_PLAN.md) for current phase and roadmap
3. Follow [Conventions](../.claude/CONVENTIONS.md) for code style guidelines
4. Reference [Testing Strategy](../.claude/TESTING.md) before writing tests

### For Product Managers
1. Read [Business Model](../ZYLCH_BUSINESS_MODEL.md) for product vision
2. Review [Future Development](features/) TODO files for upcoming features
3. Check [Development Plan](../.claude/DEVELOPMENT_PLAN.md) for timeline and milestones

## 🔍 Finding Information

### By Feature
- **Email**: See [Email Archive](features/email-archive.md) and [Relationship Intelligence](features/relationship-intelligence.md)
- **Calendar**: See [Calendar Integration](features/calendar-integration.md) and [Microsoft Calendar TODO](features/MICROSOFT_CALENDAR_TODO.md)
- **Tasks**: See [Relationship Intelligence](features/relationship-intelligence.md)
- **Automation**: See [Triggers & Automation](features/triggers-automation.md) *(coming soon)*
- **Sharing**: See [Sharing System](features/sharing-system.md) *(coming soon)*
- **Memory**: See [Entity Memory System](features/entity-memory-system.md)

### By Technology
- **Gmail API**: [Gmail OAuth](guides/gmail-oauth.md), [Email Archive](features/email-archive.md)
- **Google Calendar API**: [Calendar Integration](features/calendar-integration.md)
- **Microsoft Graph API**: [Microsoft Calendar TODO](features/MICROSOFT_CALENDAR_TODO.md)
- **Anthropic Claude**: [Email Archive](features/email-archive.md), [Relationship Intelligence](features/relationship-intelligence.md)
- **Supabase**: [Architecture](ARCHITECTURE.md#data-storage)
- **Firebase Auth**: [Architecture](ARCHITECTURE.md#authentication)

### By User Type
- **CLI Users**: [CLI Commands](guides/cli-commands.md) *(coming soon)* — primary interface at `~/hb/zylch-cli`
- **MrCall Dashboard Users**: `~/hb/mrcall-dashboard` — Vue 3 + PrimeVue business configuration
- **API Users**: API documentation *(coming soon)*
- **Web Dashboard Users**: `frontend/` — dormant prototype, not under active development
- **Mobile Users**: [Mobile App TODO](features/MOBILE_APP_TODO.md) (future)
- **Desktop Users**: [Desktop App TODO](features/DESKTOP_APP_TODO.md) (future)

## 📊 Documentation Status

| Category | Status | Files |
|----------|--------|-------|
| **Core Features** | 🟡 Partial | 4/9 complete |
| **Future Development** | ✅ Complete | 7/7 TODO files |
| **Architecture** | ✅ Complete | All files updated |
| **User Guides** | 🔴 In Progress | 1/2 complete |
| **API Documentation** | 🔴 Not Started | 0/4 planned |

### Completion Legend
- ✅ **Complete** - Documentation finished and reviewed
- 🟡 **Partial** - Some documentation exists, needs completion
- 🔴 **In Progress** - Currently being written
- ⚪ **Planned** - Documented in TODO files, not yet started

## 🚀 Getting Started

### Prerequisites
- Python 3.11+
- Google Cloud project with Gmail API enabled
- User credentials (BYOK model - each user provides their own via `/connect`):
  - Anthropic API key (`/connect anthropic`)
  - Vonage SMS credentials (`/connect vonage`) - optional
  - Pipedrive API token (`/connect pipedrive`) - optional

### Quick Setup

```bash
# 1. Clone and install
cd /path/to/zylch
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -e .

# 2. Configure OAuth
# Follow: docs/guides/gmail-oauth.md

# 3. Start CLI
./zylch-cli

# 4. Try these commands
/help                # Show all commands
/sync                # Sync emails and calendar
/gaps                # See relationship gaps
```

### Web Dashboard

Visit https://app.zylchai.com for the web interface.

## 💡 Key Concepts

### Two-Tier Email System
- **Archive**: Permanent storage of all emails (Supabase)
- **Intelligence Cache**: 30-day AI-analyzed window for active intelligence

### Person-Centric Architecture
A person is NOT an email address - they can have multiple emails, phones, and names. Zylch's memory system reflects this reality.

### Memory Reconsolidation
Like human memory, Zylch updates existing memories rather than creating duplicates when new information arrives.

### Relationship Intelligence
Goes beyond inbox management by correlating email + calendar data to identify communication gaps and opportunities.

## 🏗️ System Architecture

```
Zylch AI
├── Email Layer
│   ├── Gmail/Outlook API sync
│   ├── Archive (permanent Supabase storage)
│   └── Intelligence Cache (30-day analyzed window)
│
├── Intelligence Layer
│   ├── Memory System (person-centric with reconsolidation)
│   ├── Relationship Analyzer (gap detection)
│   ├── Task Manager (person-centric task extraction)
│   └── Task Agent (task detection from communications)
│
├── Automation Layer
│   ├── Trigger Service (event-driven workflows)
│   ├── Webhook Handlers (StarChat, SendGrid, Vonage)
│   └── Scheduler (APScheduler for reminders)
│
└── User Interfaces
    ├── CLI — ~/hb/zylch-cli (primary Zylch interface, Python/Textual)
    ├── MrCall Dashboard — ~/hb/mrcall-dashboard (Vue 3/PrimeVue, MrCall config)
    ├── API (FastAPI at api.zylchai.com)
    └── [DORMANT] Web Dashboard (Vue 3 at frontend/, prototype only)
```

## 🔗 External Integrations

### Current
- ✅ Gmail (OAuth 2.0, read/send/drafts)
- ✅ Google Calendar (OAuth 2.0, Meet link generation)
- ✅ Microsoft Outlook (Graph API, email + calendar)
- ✅ Anthropic Claude (BYOK - user provides key via `/connect anthropic`)
- ✅ StarChat/MrCall (contacts, telephony)
- ✅ SendGrid (email campaigns)
- ✅ Vonage SMS (BYOK - user provides credentials via `/connect vonage`)
- ✅ Pipedrive CRM (BYOK - user provides token via `/connect pipedrive`)

### Planned
- ⏳ WhatsApp Business API (awaiting StarChat endpoint)
- ⏳ Real-time Gmail Push (Pub/Sub)
- ⏳ Redis caching (Upstash)
- ⏳ Stripe billing
- ⏳ Mobile apps (React Native)
- ⏳ Desktop app (Tauri)

## 🧪 Testing

See [Testing Strategy](../.claude/TESTING.md) for comprehensive testing approach.

Quick test:
```bash
# Run all tests
python -m pytest tests/ -v

# Test specific component
python -m pytest tests/test_email_archive.py -v
```

## 📁 Repository Structure

```
zylch/
├── docs/                    # Documentation (you are here)
│   ├── README.md            # This file
│   ├── features/            # Feature documentation
│   ├── guides/              # User guides
│   ├── architecture/        # Architecture docs
│   └── ARCHIVE/             # Old documentation
├── .claude/                 # Development guidelines
├── zylch/                   # Source code
│   ├── agent/               # AI agent core
│   ├── api/                 # FastAPI endpoints
│   ├── cli/                 # CLI interface
│   ├── services/            # Business logic
│   ├── tools/               # Email, Calendar, Archive, etc.
│   ├── storage/             # Supabase client
│   └── workers/             # Background workers
├── frontend/                # [DORMANT] Vue 3 web dashboard prototype (not active)
├── zylch-cli/               # Thin CLI client (separate repo at ~/hb/zylch-cli)
├── tests/                   # Test suite
└── cache/                   # Legacy (gitignored, unused)
```

## 🤝 Contributing to Documentation

See [Documentation Guide](../.claude/DOCUMENTATION.md) for:
- Documentation standards and style guide
- How to structure feature documentation
- Adding new documentation files
- Keeping documentation in sync with code

## 📞 Support

- **Issues**: Report documentation issues at the project repository
- **Questions**: Contact the development team
- **Updates**: Check [Development Plan](../.claude/DEVELOPMENT_PLAN.md) for latest status
- **Web App**: https://app.zylchai.com
- **API**: https://api.zylchai.com

## 📝 Recent Updates

**March 2026**:
- ✅ Migrated deployment from Railway to Scaleway Kubernetes (ARM64 nodes)
- ✅ GitLab CI/CD with self-hosted ARM runner on Scaleway (native builds, no QEMU)
- ✅ Auto-shutdown runner after 4h idle, auto-start via pre-push git hook
- ✅ Database migration planned: Supabase → Scaleway Managed PostgreSQL (Phase 2)

**February 2026**:
- ✅ MrCall training optimization: selective retraining (only stale features), snapshot-based change detection
- ✅ Training status button in MrCall Dashboard (BusinessConfiguration.vue)
- ✅ Training status indicator in ConfigureAI sidebar
- ✅ New API endpoints: `GET /api/mrcall/training/status`, `POST /api/mrcall/training/start`
- ✅ Clarified active interfaces: CLI (`~/hb/zylch-cli`) + MrCall Dashboard (`~/hb/mrcall-dashboard`), frontend/ is dormant

**December 2025**:
- ✅ Created 7 comprehensive TODO files for future development
- ✅ Updated ARCHITECTURE.md with TODOs section
- ✅ Enhanced DEVELOPMENT_PLAN.md with detailed phases (H, I.5, J)
- ✅ Fixed documentation references (calendar_sync.py → gcalendar.py)
- ✅ Clarified credential paths in Gmail OAuth guide
- ✅ Added command syntax clarification in relationship intelligence docs
- ✅ Created ARCHIVE/ directory structure for old documentation

See [CHANGELOG](../CHANGELOG.md) for complete version history.

---

**Last Updated**: March 2026
**Version**: 0.3.0
