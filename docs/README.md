# Zylch AI Documentation

**Complete technical documentation for Zylch AI - AI-powered communication assistant**

---

## 📚 Documentation Index

### User Guide (Non-Technical)

- **[User Features](./user-features/README.md)** - What Zylch can do for you (no technical jargon!)
  - [Contact Intelligence](./user-features/contact-intelligence.md) - Know everyone you know
  - [Email Management](./user-features/email-management.md) - Draft and find emails fast
  - [Calendar Integration](./user-features/calendar-integration.md) - Schedule with context
  - [Daily Briefing](./user-features/daily-briefing.md) - Know what needs attention
  - [Memory & Learning](./user-features/memory-learning.md) - Zylch learns your style
  - [Task Management](./user-features/task-management.md) - See what needs doing
  - [Sharing](./user-features/sharing.md) - Share intel with colleagues
  - [MrCall Integration](./user-features/mrcall-integration.md) - Phone assistant config

### Getting Started

- **[Quick Start Guide](./setup/quick-start.md)** - Get Zylch AI up and running in minutes
- **[Gmail OAuth Setup](./setup/gmail-oauth.md)** - Configure Google authentication for Gmail and Calendar
- **[Email Sending Setup](./setup/email-sending-setup.md)** - Configure email sending capabilities

### Core Features

- **[Multi-Tenant Architecture](./features/multi-tenant-architecture.md)** - Complete isolation per owner with multiple assistants support
- **[User Persona Learning](./features/user-persona-learning.md)** - ⭐ NEW! Background AI that learns about the user from conversations
- **[Email Archive System](./features/email-archive.md)** - Permanent email storage with full-text search and incremental sync
- **[Relationship Intelligence](./features/relationship-intelligence.md)** - Cross-channel communication gap analysis
- **[Task Management](./features/task-management.md)** - AI-powered task tracking and prioritization
- **[Calendar & Meet Integration](./features/calendar-integration.md)** - Google Calendar with automatic Meet link generation
- **[Memory System](./features/memory-system.md)** - Channel-based behavioral learning from user corrections
- **[Cache Management](./features/cache-management.md)** - Data caching and performance optimization

### API Documentation

- **[Chat API](./api/chat-api.md)** - Conversational AI HTTP endpoint with 25+ tools

### Developer Documentation

- **[Implementation Notes](./implementation-notes.md)** - ⭐ Recent changes and implementation decisions (Nov 2025)
- **[Architecture](./.claude/ARCHITECTURE.md)** - System design and key decisions
- **[Conventions](./.claude/CONVENTIONS.md)** - Code style and patterns
- **[Testing](./.claude/TESTING.md)** - Testing strategy and examples
- **[Documentation](./.claude/DOCUMENTATION.md)** - How to document

### Root Documentation

Essential documents in the project root:

- **[README.md](../README.md)** - Project overview and main entry point
- **[ZYLCH_SPEC.md](../spec/ZYLCH_SPEC.md)** - Complete technical specification
- **[ZYLCH_BUSINESS_MODEL.md](../ZYLCH_BUSINESS_MODEL.md)** - Business context and model
- **[CHANGELOG.md](../CHANGELOG.md)** - Version history and changes

---

## 🎯 Quick Navigation

### I want to...

**Get started with Zylch AI**
→ [Quick Start Guide](./setup/quick-start.md)

**Set up Gmail integration**
→ [Gmail OAuth Setup](./setup/gmail-oauth.md)

**Search my email archive**
→ [Email Archive System](./features/email-archive.md)

**Build a chatbot with Zylch**
→ [Chat API](./api/chat-api.md)

**Teach Zylch AI my preferences**
→ [Memory System - Usage Guide](./features/memory-system.md#usage-guide)

**Understand relationship gaps**
→ [Relationship Intelligence](./features/relationship-intelligence.md)

**Learn about system architecture**
→ [Architecture](./.claude/ARCHITECTURE.md)

**Integrate Zylch AI with my workflow**
→ [Task Management](./features/task-management.md)

**Understand the complete system**
→ [Technical Specification](../spec/ZYLCH_SPEC.md)

---

## 📖 Feature Documentation

### Email Archive System

**What it does:** Permanent email storage with incremental sync and full-text search.

**Key features:**
- 💾 Complete history preservation (never lose old emails)
- ⚡ Incremental sync (<1 second daily)
- 🔍 Full-text search (FTS5-powered)
- 🗄️ SQLite backend with optional PostgreSQL
- 📊 Two-tier architecture (Archive + Intelligence Cache)

**Read more:** [Email Archive Documentation](./features/email-archive.md)

### User Persona Learning ⭐ NEW

**What it does:** Background AI system that learns about the user from conversations and uses this proactively.

**Key features:**
- 🧠 **Background Learning**: Extracts facts without blocking conversation
- 👤 **Personal Knowledge**: Relationships, preferences, work context, patterns
- 🔄 **Reconsolidation**: Similar facts merged, not duplicated
- 💬 **Proactive Usage**: AI references facts naturally ("Since Francesca is your sister...")
- 💰 **Economical**: Uses Haiku model for fast, low-cost extraction

**Example:**
```
User: "Scrivi a mia sorella Francesca"
Zylch: [learns: user has sister named Francesca]

# Later...
User: "Manda un messaggio a Francesca"
Zylch: "Scrivo a tua sorella Francesca?"
```

**Read more:** [User Persona Learning Documentation](./features/user-persona-learning.md)

### Multi-Tenant Architecture

**What it does:** Complete data isolation per owner with support for multiple completely isolated assistants.

**Key features:**
- 🏢 **Multi-Tenant**: Complete isolation per owner (Firebase UID)
- 🤖 **Multiple Assistants**: Each owner can run completely different businesses
- 👤 **Person-Centric Memory**: Semantic memory per contact with HNSW vector search
- 🔒 **Zero Data Leakage**: `{owner}:{assistant}:{contact}` namespace structure
- 📊 **Scalable**: Works with thousands of users

**Example use case:**
```
owner_mario:mrcall_assistant    → Telecom business
owner_mario:caffe_assistant     → Coffee shop (ISOLATED!)
```

**CLI commands:**
```bash
# Manage assistants
/assistant --create "MrCall Business"
/assistant --list

# Link MrCall assistant for contacts
/mrcall --id hahnbanach_personal
```

**Read more:** [Multi-Tenant Architecture Documentation](./features/multi-tenant-architecture.md)

### Chat API

**What it does:** Conversational AI HTTP endpoint for web/mobile integration.

**Key features:**
- 💬 Natural language conversation
- 🔧 25+ tools (email, calendar, tasks, CRM, web search)
- 🤖 Automatic model selection (Haiku/Sonnet/Opus)
- 📡 RESTful API with OpenAPI docs

**Read more:** [Chat API Documentation](./api/chat-api.md)

### Memory System

**What it does:** Zylch AI learns from your corrections and automatically applies them in future interactions.

**Key concepts:**
- 📡 Channel-based organization (email, calendar, WhatsApp, phone, tasks)
- 👤 Personal memory (user-specific preferences)
- 🌍 Global memory (system-wide improvements, admin only)
- 📈 Confidence scoring (rules improve over time)
- 🔄 Automatic application (injected into AI prompts)

**Read more:** [Memory System Documentation](./features/memory-system.md)

### Relationship Intelligence

**What it does:** Analyzes communication across email and calendar to identify gaps and opportunities.

**Key features:**
- 🤖 AI semantic filtering (distinguishes genuine emails from newsletters)
- 🧠 Memory-based personalization (learns your filtering preferences)
- 🚫 Automated bot detection
- ✅ Meeting acceptance filtering
- 📊 Cross-channel gap analysis

**Gap types detected:**
1. **Meetings without follow-up** - You had a meeting but didn't send follow-up email
2. **Urgent emails without meeting** - Important email but no meeting scheduled
3. **Silent contacts** - Contacts with past interactions but no recent communication

**Read more:** [Relationship Intelligence Documentation](./features/relationship-intelligence.md)

### Task Management

**What it does:** AI-powered task tracking integrated with email and calendar context.

**Read more:** [Task Management Documentation](./features/task-management.md)

---

## 🚀 Quick Start

```bash
# 1. Clone and setup
cd /path/to/zylch
source venv/bin/activate

# 2. Configure OAuth (first time only)
# Follow: docs/setup/gmail-oauth.md

# 3. Start Zylch AI
python -m zylch.cli.main

# 4. Try these commands
/tutorial           # Interactive tour of all features
/sync               # Sync emails and calendar
/gaps               # See relationship intelligence briefing
/memory --list      # View your learned preferences
```

---

## 🏗️ Architecture Overview

```
Zylch AI
├── Communication Sync
│   ├── Email (Gmail API)
│   ├── Calendar (Google Calendar API)
│   └── Cache (threads.json, events.json)
│
├── Intelligence Layer
│   ├── Memory System (behavioral learning)
│   ├── Relationship Analyzer (gap detection)
│   └── AI Filtering (Sonnet semantic analysis)
│
├── Task Management
│   ├── Task extraction from communications
│   ├── Priority scoring
│   └── Context enrichment
│
└── User Interface
    ├── CLI (interactive commands)
    ├── Morning sync (cron automation)
    └── API (future: web interface)
```

---

## 📁 File Structure

```
zylch/
├── docs/                           # 📚 This directory
│   ├── README.md                   # Documentation index (you are here)
│   ├── features/                   # Feature documentation
│   │   ├── user-persona-learning.md # ⭐ NEW! User persona learning
│   │   ├── email-archive.md        # Email archive system
│   │   ├── relationship-intelligence.md
│   │   ├── task-management.md
│   │   ├── calendar-integration.md
│   │   ├── memory-system.md
│   │   └── cache-management.md
│   ├── api/                        # API documentation
│   │   └── chat-api.md             # Chat API endpoint
│   ├── setup/                      # Setup guides
│   │   ├── quick-start.md
│   │   ├── gmail-oauth.md
│   │   └── email-sending-setup.md
│   ├── admin/                      # Admin documentation
│   └── archive/                    # Historical docs
│
├── .claude/                        # 🔧 Developer guidelines
│   ├── ARCHITECTURE.md             # System design
│   ├── CONVENTIONS.md              # Code standards
│   ├── TESTING.md                  # Test strategy
│   └── DOCUMENTATION.md            # Documentation guide
│
├── spec/                           # 📋 Technical specifications
│   ├── ZYLCH_SPEC.md
│   ├── ZYLCH_DEVELOPMENT_PLAN.md
│   └── MEMORY_GAP_ANALYSIS.md
│
├── zylch/                          # 💻 Source code
│   ├── cli/                        # CLI interface
│   ├── api/                        # HTTP API (FastAPI)
│   ├── services/                   # Business logic
│   ├── tools/                      # Gmail, Calendar, Archive, etc.
│   ├── agent/                      # AI agent core
│   └── tutorial/                   # Interactive tutorial system
│       ├── tutorial_manager.py     # Tutorial orchestrator
│       ├── sandbox/                # Mock data for demos
│       └── steps/                  # Tutorial step definitions
│
├── cache/                          # 💾 Data storage
│   ├── emails/
│   │   ├── archive.db              # SQLite email archive (permanent)
│   │   └── threads.json            # Intelligence cache (30-day)
│   ├── calendar/events.json        # Calendar events
│   ├── relationship_gaps.json      # Detected gaps
│   └── memory_mario.json           # User memory
│
├── README.md                       # 📄 Main project README
├── CLAUDE.md                       # 🤖 Claude Code instructions
├── ZYLCH_BUSINESS_MODEL.md         # 💼 Business context
└── CHANGELOG.md                    # 📝 Version history
```

---

## 🧪 Testing

### Manual Testing

```bash
# Test email sync
python -c "from zylch.tools.email_sync import EmailSyncManager; ..."

# Test relationship analysis
python test_relationship_intelligence.py

# Test memory system
python test_channel_memory.py
```

### End-to-End Testing

```bash
# Start Zylch AI and run full workflow
python -m zylch.cli.main

# In Zylch AI CLI:
/sync 7        # Sync last 7 days
/gaps          # View relationship briefing
/memory --list # Check learned preferences
```

---

## 🔗 External Integrations

### Current
- ✅ Gmail (read, send, modify, draft management with thread preservation)
- ✅ Google Calendar (read, create events, Google Meet link generation)
- ✅ Claude AI (Haiku for analysis, Sonnet for semantic filtering and task aggregation)
- ✅ AI-Generated Email Detection (filters low-priority sales emails)

### Planned
- ⏳ WhatsApp Business API
- ⏳ MrCall phone assistant integration
- ⏳ Slack integration
- ⏳ Microsoft Teams

---

## 💡 Key Concepts

### Communication Channels

Zylch AI operates across 5 distinct channels:
- **email** - Email drafting and responses
- **calendar** - Event scheduling and management
- **whatsapp** - WhatsApp messaging
- **mrcall** - Phone assistant behavior
- **task** - Task management (Zylch AI internal)

Each channel has independent memory and rules.

### Memory-Based Learning

Instead of forgetting corrections, Zylch AI:
1. Stores corrections in channel-specific memory
2. Builds confidence scores based on outcomes
3. Automatically applies learned rules
4. Improves over time

### Relationship Intelligence

Goes beyond simple inbox management:
- Correlates email + calendar data
- Identifies communication gaps
- Detects patterns (silent contacts, missing follow-ups)
- Provides actionable insights

---

## 🆘 Support

### Getting Help

- **Documentation Issues**: Check this index and linked docs
- **Setup Problems**: See [Gmail OAuth Setup](./setup/gmail-oauth.md)
- **Bug Reports**: File issue in project repository
- **Feature Requests**: Discuss with maintainers

### Common Issues

**"OAuth not working"**
→ Follow [Gmail OAuth Setup](./setup/gmail-oauth.md) carefully

**"Memory rules not applied"**
→ Check confidence threshold, see [Memory System](./features/memory-system.md#confidence-scoring)

**"Gaps analysis showing wrong emails"**
→ Teach the system with memory rules, see [Relationship Intelligence](./features/relationship-intelligence.md#personalized-filtering-with-memory-system)

**"Email archive not syncing"**
→ Check History ID expiration, see [Email Archive - Troubleshooting](./features/email-archive.md#troubleshooting)

---

## 📝 Contributing

When adding documentation:

1. **Add to this index** - Update relevant sections
2. **Use clear structure** - Follow existing doc patterns
3. **Link between docs** - Create cross-references
4. **Include examples** - Show, don't just tell
5. **Update CHANGELOG** - Document significant changes

---

## 📄 License & Credits

See [main README](../README.md) for licensing information.

**Inspiration:**
- Google ReasoningBank (memory system)
- Getting Things Done methodology (task management)
- Inbox Zero philosophy (communication management)

---

**Last Updated:** November 2025
**Version:** 0.2.0
