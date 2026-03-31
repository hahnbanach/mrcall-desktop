---
description: |
  Complete slash commands reference: /sync (data), /gaps (relationships), /memory and /trigger
  (memory + automation), /connect and /mrcall (integrations), /share and /revoke (sharing).
  Features semantic command matching via local embeddings (no Claude API calls) - natural language
  like "synchronize with the past 2 days" auto-routes to /sync 2. All commands support --help.
---

# CLI Commands Reference

## Overview

Zylch provides a comprehensive set of slash commands for managing your emails, calendar, contacts, and automation. All commands are accessible via the CLI, web interface, and mobile app.

**Key Features**:
- **Semantic command matching**: Natural language like "synchronize with the past 2 days" automatically routes to `/sync 2`
- Slash commands for specific operations (`/sync`, `/gaps`, `/memory`)
- All commands support `--help` flag for detailed usage
- No Claude API calls for command routing (uses local embeddings)

## Command Categories

### 📧 Data Management
Sync and manage your email and calendar data.

### ✉️ Email (Drafts)
Create, list, send, and manage email drafts stored in Supabase.

### 🧠 Memory & Automation
Configure entity memory and event-driven automation.

### 📞 Integrations
Connect with external services (MrCall, WhatsApp).

### 🔗 Sharing
Share intelligence with colleagues (via `/share` and `/revoke`).

### 🔧 Configuration
Customize AI behavior and system settings.

### 📚 Utility
Help, tutorials, and system management.

---

## Semantic Command Matching

Zylch uses **hybrid scoring** (keyword + semantic) to understand natural language and route to commands without using the Claude API. This is the same pattern used for memory blob search.

### Hybrid Scoring

```
hybrid_score = alpha * keyword_overlap + (1-alpha) * semantic_similarity
```

- **alpha=0.5** (default): Equal weight to keywords and semantics
- **Keyword matching**: FTS-style coverage scoring with stop word removal
- **Semantic matching**: Cosine similarity with `all-MiniLM-L6-v2` embeddings
- **Threshold**: 0.65 minimum confidence for match

### How It Works

1. Your message is embedded using `all-MiniLM-L6-v2` (384 dimensions)
2. Keywords extracted (stop words removed)
3. Hybrid score computed: keyword overlap + semantic similarity
4. If confidence > 0.65, parameters are extracted and command is executed
5. Falls back to Claude for complex queries

### Example Matches

| Natural Language | Command | Hybrid Score | Keyword | Semantic |
|-----------------|---------|--------------|---------|----------|
| "sync" | `/sync` | 0.93 | 1.00 | 0.85 |
| "synchronize with the past 2 days" | `/sync 2` | 0.85 | 0.80 | 0.90 |
| "my tasks" | `/tasks` | 0.92 | 1.00 | 0.84 |
| "email stats" | `/stats` | 0.95 | 1.00 | 0.90 |
| "what's on my calendar" | `/calendar` | 0.88 | 0.75 | 0.92 |

### Typed Parameter DSL

Triggers support typed parameters using `{param:type}` syntax:

| Type | Example | Extracts |
|------|---------|----------|
| `int` | "last {days:int} days" | `12` from "last 12 days" |
| `email` | "email to {to:email}" | `mario@example.com` |
| `text` | "who is {query:text}" | `Mario Rossi` |
| `date` | "on {date:date}" | `tomorrow`, `next monday` |
| `time` | "at {time:time}" | `3pm`, `15:30` |
| `duration` | "in {duration:duration}" | `30 minutes`, `2 hours` |
| `model` | "use {model:model}" | Model configured via env vars |

**Performance**: <100ms matching (embeddings cached after first request)

---

## Core Commands

### `/help`

**Summary**: Show all available commands

**Usage**:
```bash
/help
```

**Output**:
```
📋 Zylch AI Commands

💡 Remember: All commands accept --help for detailed usage

📧 Data & Email:
• /sync [days] - Sync email and calendar
• /stats - Email statistics (count, threads)
• /email list|create|send|delete|search - Manage drafts and search

📅 Calendar & Tasks:
• /calendar [days] - Show upcoming events
• /tasks - List open tasks (needs response)
• /jobs - Scheduled reminders and jobs

🧠 Memory & Automation:
• /memory [search|store|stats|list|reset] - Entity memory with hybrid search
• /trigger - Event-driven automation

📞 Integrations:
• /connect - View and manage external connections
• /mrcall - MrCall/StarChat phone integration

🔗 Sharing:
• /share <email> - Share data with someone
• /revoke <email> - Revoke sharing access

🔧 Configuration:
• Model configured via env vars (ANTHROPIC_MODEL, OPENAI_MODEL, etc.)

📚 Utility:
• /tutorial [topic] - Quick guides
• /clear - Clear conversation history
• /help - Show this message

💡 Tip: Chat naturally! "show my tasks", "email stats", "what's on my calendar"
```

---

## 📧 Data Management Commands

### `/sync [--days <n>] [--status] [--reset]`

**Summary**: Sync emails, calendar, and Pipedrive from connected services

**Description**: Fetches new emails from Gmail/Outlook, calendar events from Google Calendar, and deals from Pipedrive (if connected). This is a **data sync only** - it does NOT process data into memory blobs. Use `/memory process` after syncing to extract facts.

**Arguments**:
- `--days <n>` - Number of days to sync (default: 30 for first sync, incremental after)
- `--status` - Show sync status without syncing
- `--reset` - Clear sync state and force full re-sync (warns about memory)

**Examples**:
```bash
# Basic sync (incremental after first run)
/sync

# Sync last 7 days
/sync --days 7

# Sync last 300 days (extensive history)
/sync --days 300

# Check sync status
/sync --status

# Reset sync state (then run /sync)
/sync --reset

# Full workflow - sync then process into memory
/sync --days 30
/memory process
```

**Output**:
```
🔄 Sync Complete

✅ Email: +42 new, -3 deleted
ℹ️  Incremental sync - fetching changes since 2025-12-01
   If you want to go further back, run /sync --reset first, then /sync --days <n>

✅ Calendar: 5 new, 2 updated
✅ Pipedrive: 12 deals synced

✅ Done! Run /memory process to extract facts into memory.
```

**Status Output** (`/sync --status`):
```
📊 Sync Status

✅ Last synced: 2025-12-08 09:30:00 UTC
📧 Emails archived: 1,234
📅 Calendar events: 89

Run /sync or /sync --days <n> to sync more data.
```

**Performance**:
- Email sync: ~100 messages/second
- Calendar sync: ~50 events/second
- Incremental sync after first run (only fetches changes)

**Note**: `/sync` only fetches data. To extract facts into searchable memory, run `/memory process` after syncing.

---

### `/stats`

**Summary**: Show email statistics

**Description**: Displays statistics about your synced emails - total count, unread, threads, date range, and open conversations needing response. No Claude API call required.

**Usage**:
```bash
/stats
```

**Output**:
```
📊 Email Statistics

Total Emails: 1,234
Threads: 456
Unread: 23
Date Range: 2024-06-15 → 2025-12-16

Open Conversations: 12 need response

Run /sync to update or /tasks for details.
```

**Semantic Triggers**: "stats", "email stats", "inbox statistics", "how many emails", "unread count"

---

### `/calendar [days] [--limit N]`

**Summary**: Show upcoming calendar events

**Description**: Displays your upcoming calendar events from synced Google/Outlook calendar. Events are grouped by date.

**Arguments**:
- `days` - Days ahead to show (default: 7)
- `--limit N` - Max events to show (default: 20)

**Usage**:
```bash
# Events for next 7 days (default)
/calendar

# Today only
/calendar 1

# Next 30 days, up to 50 events
/calendar 30 --limit 50
```

**Output**:
```
📅 Calendar (8 events, next 7 days)

Monday, December 16
• 09:00 - Team Standup
• 14:00 - Client Call - Acme Corp 📍 Zoom

Tuesday, December 17
• 10:30 - 1:1 with Mario
• 15:00 - Product Review 📍 Conference Room A

Wednesday, December 18
• 11:00 - Demo Presentation 📍 Google Meet
```

**Semantic Triggers**: "calendar", "my calendar", "schedule today", "meetings this week", "what's on my calendar"

---

### `/tasks [--limit N]`

**Summary**: List open tasks (emails needing response)

**Description**: Shows your open tasks - emails that need response. Tasks are sorted by urgency (high → medium → low).

**Arguments**:
- `--limit N` - Max tasks to show (default: 50)

**Usage**:
```bash
# List all open tasks
/tasks

# List top 10 tasks
/tasks --limit 10
```

**Output**:
```
✅ Open Tasks (5 found)

🔴 High Priority:
• John Smith - Re: Budget Approval
  Waiting 3 days | Score: 9

• Sarah Chen - Partnership Proposal
  Waiting 5 days | Score: 8

🟡 Medium Priority:
• Mike Johnson - Meeting Follow-up
  Waiting 1 week | Score: 6

Run /sync to check for new emails.
```

**Semantic Triggers**: "tasks", "my tasks", "todo list", "what do I need to do", "action items", "things to do"

---

### `/jobs [--cancel <id>]`

**Summary**: List scheduled jobs and reminders

**Description**: Shows your scheduled reminders and automation jobs. Use `--cancel <id>` to cancel a job.

**Arguments**:
- `--cancel <id>` - Cancel a job by ID

**Usage**:
```bash
# List all scheduled jobs
/jobs

# Cancel a job
/jobs --cancel abc12345
```

**Output**:
```
⏰ Scheduled Jobs (2 found)

🔔 reminder (ID: abc12345)
   Call Mario about the proposal
   Next: 2025-12-16 14:00

⚡ conditional (ID: def67890)
   Send follow-up if no reply in 3 days
   Next: 2025-12-19 09:00

Use /jobs --cancel <id> to cancel.
```

**Semantic Triggers**: "jobs", "scheduled jobs", "my reminders", "upcoming reminders", "what's scheduled"

---

### `/gaps [days]`

**Summary**: Analyze email threads for unanswered conversations

**Description**: Analyzes `task_items` to detect relationship gaps - emails requiring action, meetings needing follow-up, or contacts going silent.

**Arguments**:
- `days` - Number of days to analyze (default: 7)

**Examples**:
```bash
# Analyze last 7 days (default)
/gaps

# Analyze last 1 day
/gaps 1

# Analyze last 30 days
/gaps 30

```

**Output**:
```
⚠️ Relationship Gaps (23 total)

🔴 High Priority (Score 8-10):
• John Smith - Re: Q4 Budget Review
  Last message: Dec 5 (3 days ago)
  Waiting for: Your budget approval

• Sarah Chen - Partnership Discussion
  Last message: Dec 4 (4 days ago)
  Waiting for: Contract review

🟡 Medium Priority (Score 5-7):
• Mike Johnson - Meeting Follow-up
  Last message: Dec 1 (1 week ago)
  Waiting for: Schedule next sync

🟢 Low Priority (Score 3-4):
• Lisa Brown - Newsletter Feedback
  Last message: Nov 28 (10 days ago)
  Waiting for: Your feedback

⚠️ Note: Gaps older than 30 days may be stale. Run /sync to refresh.
```

**Task Types Detected**:
- **answer** - Someone asked you a question
- **reminder** - You promised to do something
- **follow_up** - Meeting or conversation needs follow-up
- **waiting** - Someone is waiting for your response

**Scoring** (relationship_score 0-10):
- 8-10: High priority (recent, important contacts)
- 5-7: Medium priority (moderate urgency)
- 3-4: Low priority (older conversations)

**Note**: Must run `/sync` first to fetch emails, then `/agent task process` to detect tasks.

---

## ✉️ Email Commands

### `/email <subcommand> [options]`

**Summary**: Manage emails and drafts

**Description**: Unified email management with positional subcommands. Drafts are stored in Supabase. Emails are synced from Gmail/Outlook.

**Subcommands**:

**List emails** (`/email list`):
```bash
# List recent emails
/email list

# List last 5 emails
/email list --limit 5

# List drafts
/email list --draft
```

**Create draft** (`/email create`):
```bash
# Create draft to specific recipient
/email create --to mario@example.com --subject "Meeting follow-up"
```

**Send draft** (`/email send <draft_id>`):
```bash
/email send abc123
```

**Delete draft** (`/email delete <draft_id>`):
```bash
/email delete abc123
```

**Search emails** (`/email search <query>`):
```bash
# Search by keyword
/email search "budget proposal"

# Search with limit
/email search "contract" --limit 20
```

**Provider Routing**: Emails are sent via Gmail API (if Google connected) or Outlook API (if Microsoft connected).

---

## 🧠 Memory & Automation Commands

### `/memory [process|search|store|stats|list|--reset]`

**Summary**: Entity-centric memory with hybrid search and automatic fact extraction

**Description**: The memory system stores "blobs" of natural language information about entities (people, companies, topics). Facts are extracted from synced emails and calendar events via `/memory process`, then stored with automatic reconsolidation.

**Workflow**:
1. `/sync` - Fetch emails/calendar to local database
2. `/memory process` - Extract facts into searchable blobs
3. `/memory search <query>` - Find stored information

---

**Process synced data** (`/agent memory run email`):
```bash
# Process emails + calendar into memory (email always includes calendar)
/agent memory run email
```

Output:
```
🧠 Memory Processing Complete

📧 Emails: 42 processed
📅 Calendar: 15 processed

Use /memory search <query> to find stored information.
```

**Note**: The `email` channel automatically includes calendar events. There is no separate `calendar` channel.

**How Processing Works**:
1. Fetches unprocessed items (where `memory_processed_at IS NULL`)
2. Extracts facts using LLM
3. Searches for existing blob about same entity (hybrid search)
4. If found (score ≥ 0.65): LLM-merges new facts with existing
5. If not found: Creates new blob
6. Marks source item as processed (sets `memory_processed_at`)

---

**Search memory** (`/memory search <query>`):
```bash
# Search for a person
/memory search Mario Rossi

# Natural language query
/memory search "who is the CTO of Acme Corp"

# Semantic triggers also work:
"who is Mario Rossi"  →  /memory search Mario Rossi
```

Output:
```
🔍 Search Results (3 found)

1. Mario Rossi is the CTO of Acme Corp. He prefers formal communication
   and responds well to data-driven proposals. Met him at the Milan
   conference in October 2025.
   Score: hybrid: 0.92 (FTS: 0.95, semantic: 0.89)

2. ...
```

---

**Store memory manually** (`/memory store <content>`):
```bash
# Store a fact
/memory store "Mario Rossi moved to the Rome office"

# Store relationship info
/memory store "John Smith is very responsive, usually replies within 2 hours"
```

Output:
```
✅ Memory reconsolidated (ID: abc12345...)

Merged with existing memory (score: 0.87)

New content added to existing entity blob.
```

---

**Memory statistics** (`/memory stats`):
```bash
/memory stats
```

Output:
```
🧠 Memory Statistics

Total Blobs: 156
Total Sentences: 892
Avg Sentences/Blob: 5.7
Namespaces: 1

Namespaces:
• user:abc123
```

---

**List memories** (`/memory list [limit]`):
```bash
# List recent memories (default: 10)
/memory list

# List last 20 memories
/memory list 20
```

---

**Reset memory** (`/memory --reset`):
```bash
# Delete ALL blobs AND reset processing timestamps (irreversible!)
/memory --reset
```

Output:
```
🗑️ Memory reset complete

Deleted:
• 156 memory blobs and all associated sentences

Reset timestamps:
• 1,234 emails marked as unprocessed
• 89 calendar events marked as unprocessed

Run /memory process to rebuild memory from your synced data.
```

**Fresh Start**: To rebuild memory from scratch:
```bash
/memory --reset      # Delete blobs + reset timestamps
/memory process      # Re-extract facts from existing synced data
```

Or for a complete reset (including re-syncing data):
```bash
/memory --reset      # Delete blobs + reset timestamps
/sync --reset        # Clear synced emails/calendar
/sync --days 30      # Re-sync from services
/memory process      # Extract facts into blobs
```

---

**Hybrid Search**: Combines PostgreSQL full-text search (FTS) with pgvector semantic search using formula:
```
hybrid_score = α × FTS_score + (1-α) × semantic_score
```
Default α=0.5 (balanced). Named entities weight FTS higher.

**Reconsolidation**: When storing new info, Zylch searches for similar existing memories. If found (score ≥ 0.65), the LLM merges old + new info instead of creating duplicates.

**Performance**:
- Search: <50ms (HNSW index)
- Store: <200ms (includes reconsolidation check)
- Process: ~1-2s per item (includes LLM extraction)

---

### `/trigger [--add|--list|--remove|--toggle]`

**Summary**: Manage event-driven automation

**Description**: Triggered instructions execute automatically when specific events occur (email received, session start, SMS received, call received). Unlike behavioral memory (always-on), triggers are event-driven.

**Event Types**:
- `session_start` - When you start a conversation
- `email_received` - When new email arrives (via `/sync`)
- `sms_received` - When SMS arrives (via MrCall)
- `call_received` - When phone call comes in (via MrCall)

**Options**:

**List triggers** (`/trigger` or `/trigger --list`):
```bash
/trigger
```

Output:
```
⚡ Your Triggers (3 total)

✅ **session_start** (ID: abc12345)
   All'inizio di ogni sessione devi dirmi 'Buongiorno Mario...

✅ **email_received** (ID: def67890)
   When a new email arrives from someone I don't know, creat...

❌ **sms_received** (ID: ghi11111)
   When SMS arrives from VIP contacts, notify me via email...

Commands: /trigger --remove <id> | /trigger --toggle <id>
```

**Icons**:
- ✅ Active trigger
- ❌ Inactive trigger

**Add trigger** (`/trigger --add <type> <instruction>`):
```bash
# Session start greeting
/trigger --add session_start "Say good morning and show me my relationship gaps"

# Auto-create contacts from unknown senders
/trigger --add email_received "When email arrives from unknown sender, create contact in StarChat"

# VIP email notification
/trigger --add email_received "When email from john@client.com or mary@partner.com arrives, send me SMS"

# Call summary
/trigger --add call_received "After call ends, summarize the conversation and add to contacts"
```

Output:
```
✅ Trigger Created

Type: email_received
Instruction: When email arrives from unknown sender, create contact in StarChat
ID: abc12345

This trigger will fire automatically when the event occurs.
```

**Remove trigger** (`/trigger --remove <id>`):
```bash
/trigger --remove abc12345
```

Output:
```
✅ Trigger Removed (ID: abc12345)
```

**Toggle trigger** (`/trigger --toggle <id>`):
```bash
# Disable trigger (keeps it but stops execution)
/trigger --toggle abc12345

# Enable trigger again
/trigger --toggle abc12345
```

Output:
```
✅ Trigger disabled (ID: abc12345)
```

**Show trigger types** (`/trigger --types`):
```bash
/trigger --types
```

**Background Processing**: Triggers execute in background worker (runs every 1 minute). Events are queued in `trigger_events` table and processed asynchronously.

**Execution Model**: LLM (configured via env var)

**Performance**: <1s per trigger execution (depends on instruction complexity)

---

## 📞 Integration Commands

### MrCall/StarChat Integration

MrCall integration enables AI-powered configuration of your phone assistant. `chat_service.py` calls `MrCallAgent` directly — no orchestrator layer. The agent uses an **agentic while(tool_use) loop** that terminates naturally when the LLM stops calling tools (safety valve at 40 messages). Training is handled by:
1. **ConfiguratorTrainer**: Generates feature-specific sub-prompts from current config
2. **AgentTrainer**: Combines sub-prompts into unified agent with tool selection

**OAuth Scopes Required**:
```
business:read business:write contacts:read contacts:write sessions:read sessions:write templates:read
```

---

### `/connect mrcall`

**Summary**: Authenticate with MrCall via OAuth

**Description**: Initiates OAuth 2.0 flow with PKCE to connect your Zylch account with MrCall/StarChat. Opens browser for consent.

**Usage**:
```bash
/connect mrcall
```

**Flow**:
1. CLI starts local HTTP server on `localhost:8766`
2. Opens browser to StarChat consent page
3. User logs in and approves permissions
4. Tokens stored encrypted in Supabase
5. Ready to use MrCall commands

**Output**:
```
🔐 Starting MrCall OAuth...

Opening browser for authentication...
Waiting for callback on http://localhost:8766/callback

✅ MrCall Connected!

Next: Run /mrcall list to see your assistants
```

---

### `/mrcall` or `/mrcall status`

**Summary**: Show MrCall connection status

**Usage**:
```bash
/mrcall
```

**Output** (if connected and linked):
```
📞 MrCall Status

✅ Connected to MrCall
🔗 Linked to: My Business (abc123...)

Commands:
• /mrcall list - List all assistants
• /mrcall unlink - Disconnect current assistant
• /agent mrcall train - Train configuration agent
• /agent mrcall run "..." - Configure via natural language
```

---

### `/mrcall list`

**Summary**: List all your MrCall assistants

**Description**: Shows all assistants associated with your MrCall account. Use the number to link.

**Usage**:
```bash
/mrcall list
```

**Output**:
```
📞 Your MrCall Assistants (3 found)

1. Mario's Pizzeria
   📧 mario@pizzeria.it | 📱 +39 02 1234567
   🤖 +39 800 123456 | Template: restaurant
   ← LINKED

2. Acme Corp Reception
   📧 info@acme.com | 📱 +39 06 9876543
   🤖 +39 800 654321 | Template: business

3. Dr. Rossi Clinic
   📧 clinic@rossi.it | 📱 +39 011 5551234
   🤖 +39 800 111222 | Template: medical

Use /mrcall link <business_id> to switch assistant
```

---

### `/mrcall link <business_id>`

**Summary**: Link to a specific MrCall assistant

**Description**: Connects Zylch to the assistant by business ID from `/mrcall list`. Required before using agent commands.

**Usage**:
```bash
/mrcall link ac390829-4b89-3dc4-b628-95f84cb2ba7f
```

**Output**:
```
✅ Linked to: Mario's Pizzeria

Business ID: abc123-def456-...

Next steps:
1. /connect anthropic (if not done)
2. /agent mrcall train
3. /agent mrcall run "enable booking"
```

---

### `/mrcall unlink`

**Summary**: Disconnect from current assistant

**Usage**:
```bash
/mrcall unlink
```

**Output**:
```
✅ Unlinked from Mario's Pizzeria

Use /mrcall list and /mrcall link <business_id> to connect to another assistant.
```

---

### `/mrcall variables [get|set]`

**Summary**: View or modify MrCall assistant variables

**Description**: Direct access to assistant configuration variables. For AI-powered modification, use `/agent mrcall run` instead.

**List all variables**:
```bash
/mrcall variables
/mrcall variables get
```

**Filter by name**:
```bash
/mrcall variables get --name BOOKING
```

**Set a variable directly**:
```bash
/mrcall variables set OSCAR_OBJECTIVE "Answer calls professionally"
```

**Output** (list):
```
📋 MrCall Variables (42 found)

1. OSCAR_OBJECTIVE
   Description: Main objective for the assistant
   Value: "Answer incoming calls and take messages"

2. START_BOOKING_PROCESS
   Description: Enable/disable appointment booking
   Value: "true"

3. BOOKING_EVENTS_MINUTES
   Description: Default appointment duration
   Value: "30"

... (truncated)

Use /mrcall variables get --name <filter> to filter
```

---

### `/agent mrcall train [feature]`

**Summary**: Train MrCall configuration agent

**Description**: Analyzes current MrCall configuration and generates training prompts. Must be run before using `/agent mrcall run`.

**Usage**:
```bash
# Train all features (recommended)
/agent mrcall train

# Train specific feature only
/agent mrcall train welcome_message
/agent mrcall train booking
```

**Output**:
```
🧠 Training MrCall Agent...

✅ Feature: welcome_message (3.2s)
✅ Feature: booking (4.1s)
✅ Unified agent built (1.5s)

Agent ready! Use:
/agent mrcall run "your instruction"
```

**Duration**: 5-15 seconds depending on features

---

### `/agent mrcall run "instruction"`

**Summary**: Configure assistant via natural language

**Description**: The unified agent interprets your instruction and selects the appropriate tool:
- **configure_welcome_message** - Change greeting behavior
- **configure_booking** - Change booking settings
- **get_current_config** - Show raw settings
- **respond_text** - Answer questions about settings

**Usage**:
```bash
# Configuration changes
/agent mrcall run "enable booking with 30-min appointments"
/agent mrcall run "make the greeting more formal, use Lei"
/agent mrcall run "disable booking"

# Questions (uses respond_text)
/agent mrcall run "is booking enabled?"
/agent mrcall run "does the assistant answer formally?"
/agent mrcall run "how does it greet callers?"

# View raw settings (uses get_current_config)
/agent mrcall run "show my current settings"
```

**Output** (configuration):
```
✅ Configuration Updated

Changed:
• START_BOOKING_PROCESS: "false" → "true"
• BOOKING_EVENTS_MINUTES: "60" → "30"
• ENABLE_GET_CALENDAR_EVENTS: "false" → "true"

Your assistant will now offer 30-minute appointments.
```

**Output** (question):
```
💬 Response

Yes, booking is currently enabled. The assistant offers 30-minute
appointments during business hours (Mon-Fri 9:00-17:00).

Callers can book by saying "I'd like to schedule an appointment"
and the assistant will check your calendar for availability.
```

**Duration**: 5-15 seconds

---

### `/agent mrcall show`

**Summary**: Display current agent prompt

**Usage**:
```bash
/agent mrcall show
```

**Output**:
```
🤖 MrCall Agent Prompt

Created: 2025-01-10 14:30:00
Features: welcome_message, booking

---
You are the MrCall configuration agent.

You help users configure their MrCall AI phone assistant...
(full prompt displayed)
```

---

### `/agent mrcall reset`

**Summary**: Delete agent prompt (must retrain)

**Usage**:
```bash
/agent mrcall reset
```

**Output**:
```
🗑️ Agent Reset

Deleted mrcall agent prompt.

Run /agent mrcall train to recreate.
```

---

### MrCall Workflow

**First-time setup**:
```bash
/connect mrcall              # OAuth authentication
/mrcall list                 # See your assistants
/mrcall link <business_id>   # Link by ID from list
/connect anthropic           # Connect LLM (if not done)
/agent mrcall train          # Train agent
/agent mrcall run "..."      # Configure!
```

**Daily usage**:
```bash
/agent mrcall run "enable booking for tomorrow"
/agent mrcall run "is the greeting professional?"
/agent mrcall run "show current settings"
```

**See Also**:
- [MrCall Integration](../features/mrcall-integration.md) - OAuth, API details
- [MrCall Configurator Agent](../agents/mrcall-configurator.md) - Architecture

---

## 🔗 Sharing Commands

### `/share <email>`

**Summary**: Share intelligence with colleague

**Description**: Registers a recipient to receive shared data from you. Sharing is consent-based - recipient must authorize before receiving data.

**Usage**:
```bash
/share colleague@example.com
```

**Output**:
```
✅ Share Request Sent

Recipient: colleague@example.com
Status: Pending authorization

The recipient needs to authorize this sharing from their Zylch account.

Once authorized, they will receive:
• Your contact intelligence
• Relationship context
• Task data

Manage: /sharing | /revoke colleague@example.com
```

**What Gets Shared**:
- Contact intelligence
- Email threads metadata (not content)
- Calendar meeting context
- Task data

**Privacy**: Email/calendar content is NOT shared, only metadata and intelligence.

**Authorization Flow**:
1. You send share request: `/share colleague@example.com`
2. Recipient sees pending request: `/sharing` (shows pending authorization)
3. Recipient authorizes: `/sharing --authorize your@email.com`
4. Your intelligence flows to recipient's namespace: `shared:{recipient_id}:{sender_id}`

**Use Cases**:
- Team handoffs (colleague takes over your accounts)
- Shared relationship management
- Cross-team visibility

**See Also**: [Sharing System](../features/sharing-system.md)

---

### `/revoke <email>`

**Summary**: Revoke sharing access

**Description**: Stops sharing your data with a recipient. Already-shared data remains with them, but no new updates are sent.

**Usage**:
```bash
/revoke colleague@example.com
```

**Output**:
```
✅ Sharing Revoked

Recipient: colleague@example.com

They will no longer receive your data updates.

Note: Any data already shared remains with them, but no new updates will be sent.

Restore: Use /share colleague@example.com to share again.
```

---

## 🔧 Configuration Commands

### Model Configuration

**Summary**: Model is configured via environment variables, not runtime commands.

**Description**: The model is now set per-provider via environment variables. There is no runtime `/model` command -- one model per provider is used for all tasks.

**Environment Variables**:
- `ANTHROPIC_MODEL` - Anthropic model (e.g. `claude-sonnet-4-20250514`)
- `OPENAI_MODEL` - OpenAI model
- `MISTRAL_MODEL` - Mistral model
- `DEFAULT_MODEL` - Fallback model identifier

**Note**: No multi-tier selection. All tasks use the same model per provider.

---

## 📚 Utility Commands

### `/clear`

**Summary**: Clear conversation history

**Description**: Clears the conversation history. Note: Zylch server is stateless, so this clears client-side history only.

**Usage**:
```bash
/clear
```

**Output**:
```
✅ History Cleared

📝 Client Note: The server doesn't maintain history.
Clear your local conversation_history array.
```

**Client Implementation**: Web/mobile clients should clear their local `conversation_history` array when this command is received.

---

### `/reset [--hard]`

**Summary**: Reset all user data (destructive operation)

**Description**: Deletes ALL user data from the database. This is a destructive, irreversible operation intended for users who want to start completely fresh. OAuth tokens are preserved so you remain connected to your email/calendar providers.

**Safety**: Requires explicit `--hard` flag to execute. Running `/reset` without the flag shows a warning and asks for confirmation.

**Usage**:
```bash
# Show warning (does not delete anything)
/reset

# Execute full data reset (irreversible!)
/reset --hard
```

**Warning Output** (`/reset`):
```
⚠️ **Data Reset Warning**

This will **permanently delete** ALL your data:

📧 Emails & Calendar events
🧠 Memory (blobs & sentences)
✅ Tasks & Triggers
✉️ Drafts & Notifications
🤖 Agent prompts & Background jobs

**What stays**: Your OAuth connections (Google, Microsoft)

To proceed, run: `/reset --hard`
```

**Execution Output** (`/reset --hard`):
```
🗑️ **Data Reset Complete**

Deleted:
• 156 memory blobs
• 892 memory sentences
• 23 tasks
• 5 triggers
• 12 trigger events
• 3 drafts
• 1,234 emails
• 89 calendar events
• 2 background jobs
• 8 notifications
• 4 agent prompts

✅ Your account is now fresh. OAuth connections preserved.

Next steps:
1. /sync --days 30  → Re-sync your data
2. /memory process  → Rebuild memory
3. /tutorial        → See onboarding guide
```

**Tables Deleted**:
| Table | Content |
|-------|---------|
| `entity_memory_blobs` | Memory blobs |
| `entity_memory_sentences` | Memory sentences (FTS) |
| `task_items` | Tasks detected from emails |
| `triggers` | Event-driven automation rules |
| `trigger_events` | Queued trigger events |
| `drafts` | Email drafts |
| `emails` | Synced emails |
| `calendar_events` | Synced calendar events |
| `background_jobs` | Scheduled jobs |
| `user_notifications` | Notifications |
| `agent_prompts` | Trained agent prompts |

**Preserved**:
- OAuth tokens (remain connected to Google/Microsoft)
- User account settings

**Use Cases**:
- Starting fresh with a clean account
- Testing/development reset
- Privacy: removing all stored data

**Semantic Triggers**: "reset", "reset all data", "delete all my data", "start fresh", "clear everything", "wipe my account"

---

### `/tutorial [--dev] <topic>`

**Summary**: Complete onboarding guide for new users

**Description**: Shows a comprehensive setup flow and daily workflow diagram for new Zylch users. Explains how to connect services, train AI agents, and use the system effectively.

**Usage**:
```bash
/tutorial
```

**Output**:
```
📚 Welcome to Zylch! Here's how to get started:

═══════════════════════════════════════════════════════════════════
                    🚀 SETUP FLOW (One-time)
═══════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────────┐
│  1️⃣  CONNECT YOUR SERVICES                                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   📧 Email & Calendar:                                          │
│   • Go to app.zylchai.com/settings                              │
│   • Click "Connect Google" or "Connect Microsoft"               │
│   • Authorize access to Gmail/Outlook + Calendar                │
│                                                                 │
│   📞 Phone (Optional):                                          │
│   • /mrcall <business_id>  → Link MrCall/StarChat               │
│                                                                 │
│   ✅ Check status: /connect                                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2️⃣  INITIAL SYNC                                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   /sync --days 30                                               │
│   └── Fetches last 30 days of emails + 14 days calendar         │
│                                                                 │
│   ⏱️  Takes 30-60 seconds depending on email volume             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3️⃣  TRAIN YOUR AI AGENTS                                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   /agent memory train                                           │
│   └── Learns what facts to extract about contacts               │
│                                                                 │
│   /agent task train email                                       │
│   └── Learns what tasks need your attention                     │
│                                                                 │
│   ⏱️  Each takes 15-30 seconds (background job)                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4️⃣  BUILD YOUR MEMORY                                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   /memory process                                               │
│   └── Extracts facts from emails → searchable memory            │
│                                                                 │
│   ⏱️  Takes 1-2 min depending on email volume                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  5️⃣  DETECT YOUR TASKS                                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   /agent task process email                                     │
│   └── Finds emails that need your response                      │
│                                                                 │
│   ⏱️  Takes 1-2 min depending on email volume                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════════
                    🔄 DAILY WORKFLOW
═══════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────────┐
│  ☀️  MORNING ROUTINE (~30 seconds)                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   /sync              → Fetch new emails + calendar              │
│        │                                                        │
│        ▼                                                        │
│   /tasks             → See what needs your attention            │
│        │                                                        │
│        ▼                                                        │
│   /calendar          → Today's meetings                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  💬 CHAT NATURALLY                                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   "Who is Mario Rossi?"                                         │
│   └── Searches memory for everything about Mario                │
│                                                                 │
│   "Draft a reply to John's email about the proposal"            │
│   └── Creates draft with context from memory                    │
│                                                                 │
│   "What did Sarah say about the budget?"                        │
│   └── Searches emails + memory for relevant info                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════════
                    📋 COMMAND REFERENCE
═══════════════════════════════════════════════════════════════════

📧 Data:     /sync  /stats  /calendar  /tasks  /gaps
🧠 Memory:   /memory search|process|store|stats|--reset
🤖 Agents:   /agent memory|task train|process|show|reset
⚡ Triggers: /trigger --add|--list|--remove|--toggle
📞 Phone:    /mrcall  /connect
🔧 Config:   Model via env vars (ANTHROPIC_MODEL, etc.)
📚 Help:     /help  /tutorial  /reset

💡 All commands support --help for details
```

**Semantic Triggers**: "tutorial", "getting started", "how to use", "help me start", "onboarding", "setup guide", "how do I start", "new user guide", "quick start", "first steps", "how to use mrcall", "mrcall tutorial", "mrcall guide"

**Description**: Learn how to use Zylch with interactive guides. Use `--dev` flag for developer-focused technical guides.

**Topics**:
| Topic | Description |
|-------|-------------|
| `mrcall` | MrCall phone assistant setup and usage |
| `contact` | Contact management |
| `email` | Email operations |
| `calendar` | Calendar management |
| `sync` | Morning sync workflow |
| `memory` | Memory system |

**Usage**:
```bash
# List available tutorials
/tutorial

# MrCall user guide (setup, connect, train, run)
/tutorial mrcall

# MrCall developer guide (adding new features)
/tutorial --dev mrcall

# Show sync workflow guide
/tutorial sync
```

**Example Output** (`/tutorial mrcall`):
```
MrCall Tutorial - User Guide

MrCall lets you configure your AI phone assistant through natural language.

---

## Step 1: Connect
/connect mrcall
Opens OAuth login to StarChat. Grant business:write permission.

## Step 2: List Your Assistants
/mrcall list
Shows all MrCall assistants linked to your account.

## Step 3: Link an Assistant
/mrcall link <business_id>
Copy the business ID from list and paste here.

## Step 4: Train the Agent
/agent mrcall train
Trains the AI agent on your current configuration.

## Step 5: Use the Agent
/agent mrcall run "enable booking with 30-min appointments"
/agent mrcall run "is booking enabled?"
/agent mrcall run "make the greeting more casual"
```

**Developer Mode** (`/tutorial --dev mrcall`):

Shows technical implementation guide for adding new MrCall features:
- Two-tier architecture overview
- Single source of truth (FEATURES dict)
- Step-by-step: meta-prompt, FEATURES entry, tool, handler
- Key files and their purposes

---

## Common Patterns

### Morning Workflow

**Goal**: Start day with overview of tasks and emails.

```bash
# 1. Sync latest data
/sync

# 2. Check relationship gaps
/gaps

# 3. Review emails (natural language)
"Summarize emails from today"

# 4. Respond to urgent items
"Draft reply to John's email about budget"
```

**Time**: ~30 seconds

---

### Adding Automation

**Goal**: Automate repetitive tasks.

```bash
# 1. Add session start greeting
/trigger --add session_start "Say buongiorno and show my calendar"

# 2. Add email auto-categorization
/trigger --add email_received "When email from unknown sender arrives, create contact in StarChat"

# 3. Add VIP notification
/trigger --add email_received "When email from john@client.com arrives, send me SMS"
```

---

### Debugging Sync Issues

**Goal**: Troubleshoot sync problems.

```bash
# 1. Check sync status
/sync --status

# 2. View cached data
/cache emails
/cache calendar

# 3. If stale, reset and re-sync
/sync --reset
/sync 30

# 4. Clear cache if needed
/cache --clear all
```

---

## Tips & Tricks

### Natural Language First

You don't always need slash commands. Zylch understands natural language:

```
✅ "Who emailed me today?"
✅ "Show my calendar for tomorrow"
✅ "Draft reply to John's email about the budget"
✅ "Create a contact for sarah@example.com"

Instead of:
❌ /cache emails
❌ /gaps 1
```

### Use `--help` Flag

Every command supports `--help`:

```bash
/sync --help
/memory --help
/trigger --help
```

### Batch Commands

Run multiple commands in sequence:

```bash
/sync
# Wait for completion
/gaps
# Review output
"Summarize high priority gaps"
```

### Check Before Reset

Always check status before resetting:

```bash
# DON'T:
/sync --reset  # Immediately clears data

# DO:
/sync --status  # Check current state first
# Then decide if reset is needed
/sync --reset
```

### Incremental Sync

After first sync, Zylch uses incremental sync (faster):

```bash
# First sync (downloads 30 days)
/sync 30

# Subsequent syncs (only fetch changes)
/sync  # Fast, only new data
```

To go further back after incremental sync:

```bash
/sync --reset  # Clear sync state
/sync 300      # Re-sync 300 days
```

### Verify Sharing Authorization

Before sharing, verify recipient is Zylch user:

```bash
# BAD: Send request before checking
/share unknown@example.com
# Error: unknown@example.com is not a Zylch user

# GOOD: Verify first
"Is colleague@example.com a Zylch user?"
/share colleague@example.com
```

---

## API Integration

### Programmatic Access

All CLI commands are accessible via API:

```javascript
// POST /api/chat
{
  "message": "/sync 7",
  "owner_id": "user123",
  "context": {
    "forced_model": "configured-via-env-var"
  }
}
```

**Response**:
```javascript
{
  "response": "🔄 Sync Complete\n\n✅ Email: +42 new...",
  "metadata": {
    "command": "/sync",
    "args": ["7"]
  }
}
```

### Client Implementation

Web/mobile clients should:

1. **Detect slash commands** in user input
2. **Call API** with command string
3. **Display formatted response** (markdown)
4. **Handle special commands** (`/clear` clears client history)

**Example** (React):
```javascript
const handleMessage = async (message) => {
  if (message.startsWith('/')) {
    // Slash command
    const response = await fetch('/api/chat', {
      method: 'POST',
      body: JSON.stringify({
        message,
        owner_id: userId,
        context: { forced_model: currentModel }
      })
    });

    const data = await response.json();

    // Handle /clear locally
    if (message === '/clear') {
      setConversationHistory([]);
    }

    return data.response;
  } else {
    // Natural language
    // ... handle normally
  }
};
```

---

## Performance Characteristics

### Command Latency

| Command | Average Latency | Notes |
|---------|----------------|-------|
| `/help` | <10ms | Static text |
| `/sync` | 2-10s | Depends on email count |
| `/gaps` | <100ms | Queries task_items |
| `/memory --list` | <50ms | SQLite query |
| `/trigger --add` | <100ms | Supabase insert |
| `/cache` | <10ms | File read |
| `/archive --search` | <50ms | SQLite FTS query |

### Sync Performance

- **Email sync**: ~100 messages/second
- **Calendar sync**: ~50 events/second
- **Incremental sync**: <2s (only fetches changes)
- **First sync (30 days)**: ~5-10s (depends on email volume)

### Memory Operations

- **Memory retrieval**: O(log n) with HNSW indexing
- **Memory storage**: <100ms (with reconsolidation check)
- **Similarity search**: 150x faster than brute-force

---

## Troubleshooting

### Sync Fails

**Symptom**: `/sync` returns error

**Common Causes**:
1. Authentication expired → Re-authenticate
2. No internet connection → Check network
3. Google/Microsoft API rate limit → Wait 5 minutes

**Fix**:
```bash
# Check sync status
/sync --status

# Re-authenticate if needed
# (web interface: Settings → Reconnect Google)

# Retry sync
/sync
```

---

### Gaps Not Showing

**Symptom**: `/gaps` returns "No gaps found"

**Common Causes**:
1. No tasks detected yet → Run `/agent task process` after sync
2. All conversations closed → Correct behavior
3. No action_required tasks → Check task_items table

**Fix**:
```bash
# Check sync status
/sync --status

# Process emails into tasks
/agent task process email

# Then retry
/gaps
```

---

### Memory Not Applied

**Symptom**: Zylch doesn't remember correction

**Common Causes**:
1. Memory not stored → Check `/memory --list`
2. Similarity threshold not met → Memory reconsolidated with existing
3. Wrong namespace → Check scope (personal vs global)

**Fix**:
```bash
# Verify memory exists
/memory --list personal

# If missing, add manually
/memory --add "issue" "correct" "email"

# Check confidence
/memory --stats
```

---

### Trigger Not Firing

**Symptom**: Trigger created but doesn't execute

**Common Causes**:
1. Event not queued → Check trigger_events table
2. Trigger inactive → Check `/trigger --list`
3. Background worker not running → Start worker

**Fix**:
```bash
# Verify trigger exists and active
/trigger --list

# If inactive, toggle
/trigger --toggle <id>

# Verify background worker running
# (production: systemd service)
# (dev: manual run)
```

---

## Related Documentation

- **[Triggers & Automation](../features/triggers-automation.md)** - Event-driven automation system
- **[Entity Memory System](../features/entity-memory-system.md)** - Entity-centric memory with hybrid search
- **[Sharing System](../features/sharing-system.md)** - Consent-based intelligence sharing
- **[MrCall Integration](../features/mrcall-integration.md)** - Telephony and WhatsApp
- **[Email Archive](../features/email-archive.md)** - Email archiving details
- **[Architecture](../ARCHITECTURE.md)** - System architecture

---

**Last Updated**: December 2025
