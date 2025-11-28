# Zylch AI - Multi-Channel Sales Intelligence System

Zylch AI is a single-agent AI assistant that helps sales professionals manage email communications, enrich contact data, and automate follow-up workflows across multiple channels (email, SMS, phone).

## Design Philosophy

**Precision over economy**: When necessary, Zylch AI uses Claude Sonnet, prioritizing accuracy over cost.

**Task-focused**: The system answers one question: "What does Mario need to do?" No unnecessary classifications.

**Person-centric**: Tasks are aggregated by person, analyzing entire relationships rather than isolated threads.

**Multi-tenant**: Complete data isolation per owner with support for multiple assistants - run completely different businesses from the same system.

## Key Innovation: Person-Centric Task Management

Unlike traditional email clients that show thread-by-thread views, Zylch AI aggregates all email threads **by person** to create intelligent, actionable tasks. One person = one task maximum.

## Features

### Multi-Tenant Architecture ⭐ NEW
- **Complete Isolation**: Each owner (Firebase UID) has private workspace
- **Single-Assistant Mode**: One assistant per owner (v0.2.0 - no StarChat changes needed)
- **Person-Centric Memory**: Semantic memory per contact with HNSW vector search
- **Scalable**: Works with thousands of users
- **Namespace Structure**: `{owner}:{assistant}:{contact}` ensures zero data leakage
- **Auto-Setup**: Default assistant created automatically on first run
- **CLI Management**: `/assistant` and `/mrcall` commands
- See `docs/features/multi-tenant-architecture.md` for complete guide

### Email Intelligence
- **Thread Caching**: Fast caching of email threads with AI summaries (Haiku)
- **Task Aggregation**: Person-centric view combining all threads per contact (Sonnet)
- **Smart Search**: Find emails by participant (From, To, Cc), subject, or content
- **Draft Management**: Create, edit (nano), list, and update Gmail drafts
  - **Thread Preservation**: Drafts stay in conversation threads when edited
  - **Read-Only Headers**: To/Subject fields protected from accidental modification
  - **Threading Headers**: Automatic In-Reply-To and References for replies
- **Multi-account Support**: Gmail OAuth for multiple accounts
- **AI-Generated Email Detection**: Automatically filters low-priority AI-generated sales emails
- **Email Archive**: Permanent SQLite storage with full-text search (FTS5)

### Task Management
- **Person-Centric Tasks**: Aggregate all email threads per contact into unified view
- **Priority Scoring**: 1-10 urgency score based on relationship context
- **Status Tracking**: Open, waiting, closed - know what needs action
- **Intelligent Analysis**: Sonnet-powered analysis with emotional context
- **Custom Email Patterns**: Configure your email addresses (supports wildcards)
- **Bot Detection**: Automatic identification and de-prioritization of automated emails

### Behavioral Memory (ZylchMemory)
- **🧠 Semantic Search**: Vector-based memory retrieval with O(log n) HNSW indexing
- **👤 Personal Memory**: User-specific behavioral corrections (e.g., "use 'lei' with Luisa")
- **🌍 Global Memory**: Cross-user meta-rules (e.g., "always check past communication style")
- **Bayesian Confidence**: Rules strengthen/weaken based on success/failure
- **Pattern Learning**: Stores successful interaction patterns for reuse
- **Automatic Injection**: Relevant memories added to LLM context via semantic search
- **Unix-Style CLI**: `/memory --add`, `/memory --list`, `/memory --stats` with flags
- See `zylch_memory/` for architecture and implementation details

### Integrations
- **Pipedrive CRM**: Search contacts, retrieve deals with pipeline/stage filters
- **Google Calendar**: Task scheduling and follow-up reminders
  - **Google Meet Integration**: Automatically generate video conference links
  - **Email-to-Event**: Create calendar invites directly from emails with all participants
  - **Automatic Invites**: Sends calendar invitations to all attendees
- **StarChat**: Contact storage and phone orchestration
- **Campaign Management**: Mass emails via SendGrid, SMS via Vonage (future)
- **Web Search**: Contact enrichment via Anthropic API

## Installation

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e .

# Set up Gmail OAuth
# Follow: https://developers.google.com/gmail/api/quickstart/python
# Place credentials in: credentials/google_oauth.json
```

## Configuration

### Environment Variables (.env)

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
MY_EMAILS=you@gmail.com,you@company.com,*@automated-domain.com

# Multi-tenant Configuration
OWNER_ID=owner_default              # Firebase UID or placeholder
ZYLCH_ASSISTANT_ID=default_assistant  # Assistant identifier

# Optional - Email Style
EMAIL_STYLE_PROMPT=NEVER use emoji. Write in plain text. Be concise.

# Optional - Pipedrive
PIPEDRIVE_API_TOKEN=your-token
PIPEDRIVE_ENABLED=true

# StarChat
STARCHAT_API_URL=https://...
STARCHAT_USERNAME=admin
STARCHAT_PASSWORD=...
STARCHAT_BUSINESS_ID=...
```

**Setup:**
```bash
cp .env.example .env
# Edit .env with your API keys and settings
```

### MY_EMAILS Patterns
Zylch AI uses this to identify which emails are yours vs. contacts:
- Exact match: `mario@gmail.com`
- Wildcard: `*@pipedrivemail.com` (matches all Pipedrive automated emails)

## CLI Commands

### Core Commands
```bash
/help          - Show help
/quit          - Exit Zylch AI
/clear         - Clear conversation history
/history       - Show conversation history
```

### Email & Sync
```bash
/sync [days]   - Run morning sync (emails + calendar + gap analysis)
                 Examples: /sync (default 30 days), /sync 3 (last 3 days)
/gaps          - Show relationship gaps briefing
```

### Archive Management
```bash
/archive                    - View archive statistics
/archive --sync            - Sync new emails (incremental)
/archive --search "query"  - Search archive
/archive --init            - Initialize archive (first time)
```

### Memory & Learning
```bash
/memory --list      - List all behavioral memories
/memory --add       - Add new behavioral rule
/memory --stats     - Show memory statistics
/memory --help      - Complete memory command help
```

### Multi-Tenant
```bash
/assistant          - Show current assistant
/assistant --list   - List your assistant
/mrcall --id <id>   - Link to MrCall assistant
```

### Cache Inspection
```bash
/cache --help       - Cache management help
```

## Quick Start

```bash
# Activate environment
source venv/bin/activate

# Start Zylch AI CLI
python -m zylch.cli.main

# First time: sync emails (30 days, ~5-10 minutes)
You: sync emails

# Build person-centric tasks (~2-3 minutes for 200 contacts)
You: build tasks
```

## Architecture

Zylch AI uses a **single-agent design** with specialized tools (not multi-agent), direct Anthropic SDK (no LangChain), and a two-tier caching strategy (threads.json → tasks.json) for cost-optimized intelligence.

**Complete details:** See `.claude/ARCHITECTURE.md` for system design and key decisions.

## API Access

Zylch AI provides HTTP API endpoints for web/mobile integration. See `docs/api/chat-api.md` for complete API documentation.

## Documentation

### Core Documentation
- `docs/README.md` - **Complete documentation index** (start here!)
- `docs/features/multi-tenant-architecture.md` - Multi-tenant system guide
- `docs/features/memory-system.md` - Behavioral memory system
- `docs/features/email-archive.md` - Email archive system
- `docs/api/chat-api.md` - Chat API endpoints
- `docs/setup/quick-start.md` - Getting started guide

### Developer Documentation
- `.claude/ARCHITECTURE.md` - System design and key decisions
- `.claude/CONVENTIONS.md` - Code style and patterns
- `.claude/TESTING.md` - Testing strategy

### Legacy Documentation (Root)
- `MRPARK_SPEC.md` - Complete implementation specification
- `TASK_MANAGEMENT.md` - Person-centric task system design
- `REASONING_BANK_DESIGN.md` - Behavioral memory architecture
- `MEMORY_USAGE.md` - Memory CLI commands

## Costs

- **Thread sync** (30 days, 1000 emails): ~$0.92 (Haiku)
- **Task build** (200 contacts): ~$1.40 (Sonnet)
- **Single task update**: <$0.01 (Sonnet)

Total initial sync: **~$2.50** for 1000 emails + 200 contacts

---

## Usage Examples

### Email & Thread Management
```
You: search emails from luisa boni
You: show thread #5
You: write a reminder for email #5
You: save it  # Creates Gmail draft
You: list drafts
You: edit draft  # Opens nano editor
```

### Task Management (Person-Centric)
```
You: status di Luisa Boni
# Shows: all threads aggregated, priority score, action needed

You: show urgent tasks  # score >= 8
You: show open tasks
You: task stats  # Overview of all tasks
You: rebuild tasks force_rebuild=true  # Refresh all tasks
```

### Contact & CRM
```
You: who is john.doe@company.com?  # Enriches contact
You: search pipedrive person john.doe@company.com
You: get deals for person 123 in pipeline 5
```

### Calendar & Meeting Scheduling
```
You: what's on my calendar today?
You: schedule meeting tomorrow 2pm with john@company.com
You: create event with Meet link

# Create event from email with all participants
You: create invite for all participants in Natascia's email at the requested time with Meet link
# → Extracts time, participants, creates event with Google Meet link, sends invites
```

### Email Archive Queries
```bash
# Count total messages
sqlite3 cache/emails/archive.db "SELECT COUNT(*) FROM messages"

# Check date range
sqlite3 cache/emails/archive.db "SELECT MIN(date) as oldest, MAX(date) as newest FROM messages"

# Search messages
sqlite3 cache/emails/archive.db "SELECT subject, sender, date FROM messages WHERE subject LIKE '%proposal%' LIMIT 5"
```

---

## License

Proprietary - MrCall SRL
