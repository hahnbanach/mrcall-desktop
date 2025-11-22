# MrPark Documentation

**Complete technical documentation for MrPark - AI-powered communication assistant**

---

## 📚 Documentation Index

### Getting Started

- **[Quick Start Guide](./quick-start.md)** - Get MrPark up and running in minutes
- **[Gmail OAuth Setup](./setup/gmail-oauth.md)** - Configure Google authentication for Gmail and Calendar

### Core Features

- **[Memory System](./memory-system.md)** - Channel-based behavioral learning from user corrections
- **[Relationship Intelligence](./relationship-intelligence.md)** - Cross-channel communication gap analysis
- **[Task Management](./task-management.md)** - AI-powered task tracking and prioritization
- **[Calendar & Meet Integration](./calendar-integration.md)** - Google Calendar with automatic Meet link generation

### Root Documentation

Essential documents in the project root:

- **[README.md](../README.md)** - Project overview and main entry point
- **[MRPARK_SPEC.md](../MRPARK_SPEC.md)** - Complete technical specification
- **[MRPARK_BUSINESS_MODEL.md](../MRPARK_BUSINESS_MODEL.md)** - Business context and model
- **[CHANGELOG.md](../CHANGELOG.md)** - Version history and changes

---

## 🎯 Quick Navigation

### I want to...

**Get started with MrPark**
→ [Quick Start Guide](./quick-start.md)

**Set up Gmail integration**
→ [Gmail OAuth Setup](./setup/gmail-oauth.md)

**Teach MrPark my preferences**
→ [Memory System - Usage Guide](./memory-system.md#usage-guide)

**Understand relationship gaps**
→ [Relationship Intelligence](./relationship-intelligence.md)

**Learn about memory architecture**
→ [Memory System - Design Philosophy](./memory-system.md#design-philosophy)

**Integrate MrPark with my workflow**
→ [Task Management](./task-management.md)

**Understand the complete system**
→ [MRPARK_SPEC.md](../MRPARK_SPEC.md)

---

## 📖 Feature Documentation

### Memory System

**What it does:** MrPark learns from your corrections and automatically applies them in future interactions.

**Key concepts:**
- 📡 Channel-based organization (email, calendar, WhatsApp, phone, tasks)
- 👤 Personal memory (user-specific preferences)
- 🌍 Global memory (system-wide improvements, admin only)
- 📈 Confidence scoring (rules improve over time)
- 🔄 Automatic application (injected into AI prompts)

**Read more:** [Memory System Documentation](./memory-system.md)

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

**Read more:** [Relationship Intelligence Documentation](./relationship-intelligence.md)

### Task Management

**What it does:** AI-powered task tracking integrated with email and calendar context.

**Read more:** [Task Management Documentation](./task-management.md)

---

## 🚀 Quick Start

```bash
# 1. Clone and setup
cd /path/to/mrpark
source venv/bin/activate

# 2. Configure OAuth (first time only)
# Follow: docs/setup/gmail-oauth.md

# 3. Start MrPark
python -m mrpark.cli.main

# 4. Try these commands
/sync               # Sync emails and calendar
/gaps               # See relationship intelligence briefing
/memory --list      # View your learned preferences
```

---

## 🏗️ Architecture Overview

```
MrPark
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
mrpark/
├── docs/                           # 📚 This directory
│   ├── README.md                   # Documentation index (you are here)
│   ├── memory-system.md            # Memory system guide
│   ├── relationship-intelligence.md # Relationship intelligence guide
│   ├── task-management.md          # Task management guide
│   ├── quick-start.md              # Getting started guide
│   └── setup/
│       └── gmail-oauth.md          # OAuth setup instructions
│
├── mrpark/                         # 💻 Source code
│   ├── cli/                        # CLI interface
│   ├── memory/                     # Memory system
│   ├── tools/                      # Gmail, Calendar, sync managers
│   └── agent/                      # AI agent core
│
├── cache/                          # 💾 Data storage
│   ├── emails/threads.json         # Email threads with AI analysis
│   ├── calendar/events.json        # Calendar events
│   ├── relationship_gaps.json      # Detected gaps
│   └── memory_mario.json           # User memory
│
├── README.md                       # 📄 Main project README
├── MRPARK_SPEC.md                  # 📋 Technical specification
├── MRPARK_BUSINESS_MODEL.md        # 💼 Business context
└── CHANGELOG.md                    # 📝 Version history
```

---

## 🧪 Testing

### Manual Testing

```bash
# Test email sync
python -c "from mrpark.tools.email_sync import EmailSyncManager; ..."

# Test relationship analysis
python test_relationship_intelligence.py

# Test memory system
python test_channel_memory.py
```

### End-to-End Testing

```bash
# Start MrPark and run full workflow
python -m mrpark.cli.main

# In MrPark CLI:
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

MrPark operates across 5 distinct channels:
- **email** - Email drafting and responses
- **calendar** - Event scheduling and management
- **whatsapp** - WhatsApp messaging
- **mrcall** - Phone assistant behavior
- **task** - Task management (MrPark internal)

Each channel has independent memory and rules.

### Memory-Based Learning

Instead of forgetting corrections, MrPark:
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
→ Check confidence threshold, see [Memory System](./memory-system.md#confidence-scoring)

**"Gaps analysis showing wrong emails"**
→ Teach the system with memory rules, see [Relationship Intelligence](./relationship-intelligence.md#personalized-filtering-with-memory-system)

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
