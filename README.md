# MrPark - Multi-Channel Sales Intelligence System

MrPark is a single-agent AI assistant that helps sales professionals manage email communications, enrich contact data, and automate follow-up workflows across multiple channels (email, SMS, phone).

## Design Philosophy

**Precision over economy**: MrPark uses Claude Sonnet for all analysis, prioritizing accuracy over cost.

**Task-focused**: The system answers one question: "What does Mario need to do?" No unnecessary classifications.

**Person-centric**: Tasks are aggregated by person, analyzing entire relationships rather than isolated threads.

## Key Innovation: Person-Centric Task Management

Unlike traditional email clients that show thread-by-thread views, MrPark aggregates all email threads **by person** to create intelligent, actionable tasks. One person = one task maximum.

## Features

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

### Task Management
- **Person-Centric Tasks**: Aggregate all email threads per contact into unified view
- **Priority Scoring**: 1-10 urgency score based on relationship context
- **Status Tracking**: Open, waiting, closed - know what needs action
- **Intelligent Analysis**: Sonnet-powered analysis with emotional context
- **Custom Email Patterns**: Configure your email addresses (supports wildcards)
- **Bot Detection**: Automatic identification and de-prioritization of automated emails

### Behavioral Memory (ReasoningBank)
- **👤 Personal Memory**: User-specific behavioral corrections (e.g., "use 'lei' with Luisa")
- **🌍 Global Memory**: Cross-user meta-rules (e.g., "always check past communication style")
- **Bayesian Confidence**: Rules strengthen/weaken based on success/failure
- **Automatic Injection**: Relevant memories added to LLM context automatically
- **Unix-Style CLI**: `/memory --add`, `/memory --list`, `/memory --stats` with flags
- See `MEMORY_USAGE.md` for full guide

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

# Set up environment
cp .env.example .env
# Edit .env with your API keys and settings:
#   - ANTHROPIC_API_KEY
#   - MY_EMAILS (comma-separated, supports wildcards like *@domain.com)
#   - EMAIL_STYLE_PROMPT (your writing preferences)
#   - PIPEDRIVE_API_TOKEN (optional)
#   - STARCHAT credentials

# Set up Gmail OAuth
# Follow: https://developers.google.com/gmail/api/quickstart/python
# Place credentials in: credentials/google_oauth.json

# Set up Google Calendar OAuth (uses same OAuth as Gmail)
```

## Quick Start

```bash
# Activate environment
source venv/bin/activate

# Start MrPark CLI
python -m mrpark.cli.main

# First time: sync emails (30 days, ~5-10 minutes)
You: sync emails

# Build person-centric tasks (~2-3 minutes for 200 contacts)
You: build tasks
```

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
You: create invite for all participants in Anna's email at the requested time with Meet link
# → Extracts time, participants, creates event with Google Meet link, sends invites
```

## Architecture

### Design Principles
- **Single-agent design**: One Claude agent with specialized tools (not multi-agent)
- **Direct Anthropic SDK**: Native function calling, no LangChain
- **Human-in-the-loop**: All actions require approval (assistance, not automation)
- **Cost-optimized**: Haiku for thread analysis (~$0.92/1K emails), Sonnet for task aggregation (~$1.40/200 contacts)

### Two-Tier Caching Strategy
```
Gmail API
    ↓
threads.json (Haiku - fast, thread-by-thread)
    ↓
TaskManager (aggregates by contact)
    ↓
tasks.json (Sonnet - intelligent, person-centric)
```

**Why two tiers?**
- `threads.json`: Fast sync, preserves all thread details, enables search
- `tasks.json`: Intelligent aggregation, one person = one task, actionable insights

### File Structure
```
mrpark/
├── mrpark/
│   ├── agent/          # Claude agent core + prompts
│   ├── tools/
│   │   ├── gmail.py           # Gmail API (OAuth, drafts, search)
│   │   ├── email_sync.py      # Thread caching with Haiku
│   │   ├── task_manager.py    # Person-centric aggregation with Sonnet
│   │   ├── pipedrive.py       # Pipedrive CRM integration
│   │   ├── gcalendar.py       # Google Calendar
│   │   └── starchat.py        # StarChat contact storage
│   └── cli/
│       └── main.py     # CLI interface with all tools
├── cache/
│   ├── emails/
│   │   └── threads.json       # Thread cache (Haiku analysis)
│   └── tasks.json             # Person-centric tasks (Sonnet analysis)
└── credentials/
    └── google_oauth.json      # OAuth tokens
```

## Configuration

### Environment Variables (.env)

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
MY_EMAILS=you@gmail.com,you@company.com,*@automated-domain.com

# Optional - Email Style
EMAIL_STYLE_PROMPT=NEVER use emoji. Write in plain text. Be concise.

# Optional - Pipedrive
PIPEDRIVE_API_TOKEN=your-token
PIPEDRIVE_ENABLED=true

# StarChat
STARCHAT_API_URL=https://...
STARCHAT_USERNAME=admin
STARCHAT_PASSWORD=...
STARCHAT_INDEX_NAME=...
```

### MY_EMAILS Patterns
MrPark uses this to identify which emails are yours vs. contacts:
- Exact match: `mario@gmail.com`
- Wildcard: `*@pipedrivemail.com` (matches all Pipedrive automated emails)

## Costs

- **Thread sync** (30 days, 1000 emails): ~$0.92 (Haiku)
- **Task build** (200 contacts): ~$1.40 (Sonnet)
- **Single task update**: <$0.01 (Sonnet)

Total initial sync: **~$2.50** for 1000 emails + 200 contacts

## Documentation

- `MRPARK_SPEC.md` - Complete implementation specification
- `TASK_MANAGEMENT.md` - Person-centric task system design (recommended read)
- `REASONING_BANK_DESIGN.md` - Behavioral memory system design & architecture
- `MEMORY_USAGE.md` - Memory CLI commands and usage guide
- `QUICK_START.md` - Getting started guide

## License

Proprietary - MrCall SRL
