# Existing User Experience Documentation

**Purpose**: This document captures the EXISTING user experience from the main branch that MUST be preserved during the avatar integration. Any deviations from this UX are regressions.

**Source Branch**: `zylch-main` (main production branch)
**Analysis Date**: 2025-12-08
**Working Directory**: `/Users/mal/hb/zylch-main`

---

## Table of Contents

1. [User Mental Model](#user-mental-model)
2. [Command Reference](#command-reference)
3. [Natural Language Interaction](#natural-language-interaction)
4. [Data Flow & Architecture](#data-flow--architecture)
5. [Performance Characteristics](#performance-characteristics)
6. [Key UX Principles](#key-ux-principles)

---

## User Mental Model

### Core Concepts

Users think about Zylch in terms of these primary concepts:

1. **Person-Centric Organization**
   - Everything revolves around PEOPLE, not threads or messages
   - One person can have multiple emails, phones, contact points
   - Tasks are aggregated BY PERSON (not by thread)
   - "Who emailed me?" vs "What thread is this?"

2. **Threads & Conversations**
   - Email threads are cached and analyzed as units
   - Thread summaries powered by AI (Claude Haiku for speed)
   - Threads can span multiple messages over time
   - Thread preservation in drafts is critical (In-Reply-To headers)

3. **Tasks & Gaps**
   - Tasks = things you need to do
   - Two types: "answer" (respond to question) and "reminder" (you promised something)
   - Gaps = unanswered conversations or silent contacts
   - Person-level aggregation (all threads with Mario = 1 task max)

4. **Memory & Learning**
   - **Behavioral Memory** (`/memory`): Always-on rules ("always use 'lei' with Luisa")
   - **Triggered Instructions** (`/trigger`): Event-driven automation ("when email arrives, do X")
   - **Persona Learning**: AI learns user's preferences, relationships, work context
   - Semantic search with HNSW vector indexing

5. **Multi-Tenant Isolation**
   - Each user (owner_id) has completely isolated workspace
   - Namespace structure: `{owner}:{assistant}:{contact}`
   - One assistant per user (single-assistant mode in v0.2.0)
   - MrCall business linkage optional

---

## Command Reference

### 1. Data Management Commands

#### `/sync [days]`
**What it does**: Fetches emails and calendar events from provider (Gmail/Outlook)

**Parameters**:
- `days` (optional): Number of days to sync (default: 30)

**Output Format**:
```markdown
**🔄 Sync Complete**

✅ **Email:** +15 new, -2 deleted
✅ **Calendar:** 8 new, 3 updated

✅ **Done!** Run `/gaps [days]` to analyze tasks.
```

**Data Flow**:
- NO LLM calls during sync (pure data archiving)
- Stores to Supabase (email_threads, calendar_events tables)
- Updates local JSON cache for speed
- No gap analysis unless explicitly requested

**Examples**:
- `/sync` → sync last 30 days
- `/sync 7` → sync last 7 days
- `/sync 90` → sync last 90 days

---

#### `/gaps [days]` or `/briefing`
**What it does**: AI analysis of email threads to detect tasks

**Parameters**:
- `days` (optional): Number of days to analyze (default: 7)

**Output Format**:
```markdown
**📊 Gap Analysis** (last 7 days)

✅ **Threads analyzed:** 12 new, 5 updated

**Tasks found:**
   • Need answer: 3
   • Need reminder: 2
   • Open threads: 8
   • Closed: 15
```

**Data Flow**:
- **HEAVY LLM USAGE**: Claude Sonnet analyzes each thread
- Reads from cache/Supabase
- Aggregates by person (multiple threads → 1 task per person max)
- Detects task types: "answer" or "reminder"
- Priority scoring 1-10

**Examples**:
- `/gaps` → analyze last 7 days
- `/gaps 1` → analyze last 24 hours
- `/gaps 30` → analyze last month

---

#### `/archive [--help]`
**What it does**: Email archive management (Gmail only)

**Subcommands**:
- `/archive` or `/archive --stats` → Show archive statistics
- `/archive --sync` → Incremental sync
- `/archive --init [months]` → Initialize archive (download history)
- `/archive --search <query> --limit N` → Search emails

**Output Format**:
```markdown
**📦 Email Archive Statistics**

**Total Messages:** 15,234
**Total Threads:** 3,456
**Date Range:** 2023-01-15 to 2025-12-08
**Full Sync:** ✅ Completed
**Last Sync:** 2025-12-08 09:30

**Storage:** /Users/mal/.zylch/cache/email_archive.db
```

**Data Flow**:
- NO LLM calls
- Local SQLite with FTS5 (full-text search)
- Direct Gmail API access
- Microsoft Outlook NOT supported yet

**Examples**:
- `/archive --stats`
- `/archive --search "contract" --limit 10`
- `/archive --init 6` → initialize with 6 months history

---

#### `/cache [--help]`
**What it does**: View cached data (emails, calendar, gaps)

**Subcommands**:
- `/cache` → Overview of all caches
- `/cache emails` → Email cache details
- `/cache calendar` → Calendar cache details
- `/cache gaps` → Gaps cache details
- `/cache --clear all|emails|calendar|gaps` → Clear caches

**Output Format**:
```markdown
**💾 Cache Overview**

📧 Email threads: 125
📅 Calendar events: 45
⚠️ Relationship gaps: 12

**Commands:**
• `/cache emails` - View email cache
• `/cache calendar` - View calendar cache
• `/cache gaps` - View gaps cache
• `/cache --clear all` - Clear all caches
```

**Data Flow**:
- NO LLM calls
- Reads local JSON files from `settings.cache_dir`
- Fast lookup for debugging

---

### 2. Memory & Automation Commands

#### `/memory [--help]`
**What it does**: Behavioral memory management (always-on rules)

**Subcommands**:
- `/memory --list [scope]` → List memories (personal/global/all)
- `/memory --stats [scope]` → Memory statistics
- `/memory --add <issue> <correct> <channel>` → Add memory manually

**Scope Values**:
- `personal` → Your personal memories (namespace: `user:{owner_id}`)
- `global` → Global system memories (namespace: `global`)
- `all` → Both personal and global

**Output Format**:
```markdown
**🧠 Behavioral Memories** (15 total, scope: all)

🌍 **Used tu** → **Use lei**
   Category: email | Confidence: 0.95

👤 **Short responses** → **Detailed explanations**
   Category: communication | Confidence: 0.87
```

**Data Flow**:
- NO LLM calls during list/stats
- Stored in ZylchMemory SQLite database
- HNSW vector search for semantic retrieval
- Bayesian confidence scoring

**Examples**:
- `/memory --list personal`
- `/memory --stats all`
- `/memory --add "Used tu" "Use lei" email`

---

#### `/trigger [--help]`
**What it does**: Event-driven automation (triggered instructions)

**Trigger Types**:
- `session_start` → Fires when starting conversation
- `email_received` → Fires when new email arrives
- `sms_received` → Fires when SMS arrives (via MrCall)
- `call_received` → Fires when call comes in (via MrCall)

**Subcommands**:
- `/trigger` or `/trigger --list` → List all triggers
- `/trigger --types` → Show trigger types
- `/trigger --add <type> <instruction>` → Add trigger
- `/trigger --remove <id>` → Remove trigger
- `/trigger --toggle <id>` → Enable/disable trigger

**Output Format**:
```markdown
**⚡ Your Triggers** (2 total)

✅ **session_start** (ID: `abc12345`)
   Say good morning and list my meetings...

✅ **email_received** (ID: `def67890`)
   Summarize important emails from unknow...

**Commands:** `/trigger --remove <id>` | `/trigger --toggle <id>`
```

**Data Flow**:
- NO LLM calls during management commands
- Stored in Supabase `triggers` table
- `session_start` triggers injected into system prompt
- Event triggers queued and processed asynchronously

**Examples**:
- `/trigger --add session_start "Say good morning and list today's meetings"`
- `/trigger --add email_received "Summarize VIP emails"`
- `/trigger --remove abc12345`

---

### 3. Integration Commands

#### `/mrcall [--help]`
**What it does**: MrCall/StarChat phone integration

**Subcommands**:
- `/mrcall` → Show current MrCall link status
- `/mrcall <business_id>` → Link to MrCall business
- `/mrcall --unlink` → Remove MrCall link

**Output Format**:
```markdown
**📞 MrCall Status**

**Linked Business:** `3002475397`
**Connected Since:** 2025-12-01

**Features enabled:**
• Phone call handling
• SMS automation
• `call_received` triggers
• `sms_received` triggers

**Commands:**
• `/mrcall --unlink` - Disconnect
• `/trigger --add call_received "..."` - Add call automation
```

**Data Flow**:
- NO LLM calls
- Stored in Supabase `user_mrcall_links` table
- Links owner_id to MrCall business_id
- Enables phone/SMS tools and triggers

**Examples**:
- `/mrcall 3002475397` → link to business
- `/mrcall` → show status
- `/mrcall --unlink` → disconnect

---

### 4. Sharing Commands

#### `/share <email>`
**What it does**: Share data with another user

**Parameters**:
- `email` (required): Recipient email address

**Output Format**:
```markdown
✅ **Share Request Sent**

**Recipient:** colleague@example.com
**Status:** Pending authorization

The recipient needs to authorize this sharing from their Zylch account.

Once authorized, they will receive:
• Your contact intelligence
• Relationship context
• Avatar data

**Manage:** `/sharing` | `/revoke colleague@example.com`
```

**Data Flow**:
- NO LLM calls
- Stored in Supabase `sharing_recipients` table
- Status: pending → authorized (after recipient accepts)
- Enables data sharing across owner_ids

**Examples**:
- `/share colleague@example.com`

---

#### `/revoke <email>`
**What it does**: Revoke sharing access

**Parameters**:
- `email` (required): Recipient email to revoke

**Output Format**:
```markdown
✅ **Sharing Revoked**

**Recipient:** colleague@example.com

They will no longer receive your data updates.

**Note:** Any data already shared remains with them, but no new updates will be sent.

**Restore:** Use `/share colleague@example.com` to share again.
```

**Data Flow**:
- NO LLM calls
- Updates Supabase `sharing_recipients` table
- Stops future data sharing

**Examples**:
- `/revoke colleague@example.com`

---

#### `/sharing`
**What it does**: Show sharing status (who you share with, who shares with you)

**Output Format**:
```markdown
**📊 Sharing Status**

**📤 Your Recipients** (you share with them)
✅ colleague@example.com (authorized)
⏳ partner@example.com (pending)

**📥 Sharing With You** (you receive their data)
✅ boss@example.com (authorized)
⏳ teammate@example.com - **Pending your authorization**
   → `/sharing --authorize teammate@example.com`

**Commands:** `/share <email>` | `/revoke <email>`
```

**Data Flow**:
- NO LLM calls
- Reads from Supabase `sharing_recipients` table
- Shows bidirectional sharing relationships

**Examples**:
- `/sharing`
- `/sharing --authorize sender@example.com` → accept incoming share

---

### 5. Configuration Commands

#### `/model [haiku|sonnet|opus|auto]`
**What it does**: Change AI model for subsequent requests

**Options**:
- `haiku` → Claude 3.5 Haiku (fast, economical)
- `sonnet` → Claude 3.5 Sonnet (balanced) ⭐ default
- `opus` → Claude 3 Opus (powerful, expensive)
- `auto` → Automatic selection

**Output Format**:
```markdown
✅ **Model selected: sonnet**

Model ID: `claude-3-5-sonnet-20241022`

**For this to take effect:**
API clients should include in context for future requests:
```json
{
  "context": {
    "forced_model": "claude-3-5-sonnet-20241022"
  }
}
```
```

**Data Flow**:
- NO LLM calls (metadata only)
- Affects subsequent API calls
- NOT persisted (session-only)

**Examples**:
- `/model haiku` → switch to Haiku
- `/model auto` → enable auto-selection

---

### 6. Utility Commands

#### `/help`
**What it does**: Show available commands

**Output Format**:
```markdown
**📋 Zylch AI Commands**

**📧 Data Management:**
• `/sync [days]` - Sync email and calendar
• `/gaps` or `/briefing` - Analyze unanswered conversations
• `/archive [--help]` - Email archive management
• `/cache [--help]` - Cache management

**🧠 Memory & Automation:**
• `/memory [--help]` - Behavioral memory management
• `/trigger [--help]` - Event-driven automation

**📞 Integrations:**
• `/mrcall [--help]` - MrCall/StarChat phone integration

**🔗 Sharing:**
• `/share <email>` - Share data with someone
• `/revoke <email>` - Revoke sharing access
• `/sharing` - Show sharing status

**🔧 Configuration:**
• `/model [haiku|sonnet|opus|auto]` - Change AI model

**📚 Utility:**
• `/tutorial [topic]` - Quick guides
• `/clear` - Clear conversation history
• `/help` - Show this message

**💡 Tip:** You can also chat naturally! Ask "who emailed me today?" or "help me with my emails".
```

**Data Flow**: NO LLM calls (static text)

---

#### `/clear`
**What it does**: Clear conversation history

**Output Format**:
```markdown
✅ **History Cleared**

**📝 Client Note:** The server doesn't maintain history.
Clear your local `conversation_history` array.
```

**Data Flow**:
- NO LLM calls
- Server is STATELESS (no persistent conversation history)
- Client must maintain `conversation_history` for context

---

#### `/tutorial [topic]`
**What it does**: Show quick guides for specific features

**Topics**:
- `contact` → Contact management guide
- `email` → Email operations guide
- `calendar` → Calendar management guide
- `sync` → Morning sync workflow
- `memory` → Memory system guide

**Output Format** (example: `/tutorial sync`):
```markdown
**🔄 Morning Sync Workflow**

**Daily routine:**
1. Run `/sync` - Fetch emails + calendar
2. Check `/gaps` - See unanswered emails
3. Review: "Summarize today's emails"
4. Respond: "Draft reply to Mario's email"

**Quick workflow:** `/sync` → `/gaps` → respond

**Pro tip:** Use `/cache` to inspect cached data.
```

**Data Flow**: NO LLM calls (static guides)

**Examples**:
- `/tutorial sync`
- `/tutorial email`
- `/tutorial memory`

---

## Natural Language Interaction

### Supported Query Types

Users can interact with Zylch using natural language. The AI agent processes these via **Anthropic Claude** with tool calling.

#### 1. Email Queries

**Search Emails**:
- "Show emails from today"
- "Who emailed me this week?"
- "Find emails about contracts"
- "Unread emails from Mario"

**Draft Emails**:
- "Draft email to mario@example.com about meeting"
- "Prepare a response to Cameron saying not interested"
- "Write a follow-up to #5" (reference specific email)

**Manage Drafts**:
- "List my drafts"
- "Edit draft #3"
- "Send the draft to Cameron"
- "Save this as a draft" (after showing draft)

**Threading** (CRITICAL):
- Replies MUST preserve thread headers (`In-Reply-To`, `References`, `thread_id`)
- Without these, drafts appear OUTSIDE conversation threads
- Agent automatically extracts threading headers from search results

---

#### 2. Contact Queries

**Search Contacts**:
- "Who is mario@example.com?"
- "Find contact for Acme Corp"
- "Show my relationship with Luisa"

**Create/Update Contacts**:
- "Create contact for luisa@example.com"
- "Add phone +39 123456789 to Mario Rossi"

**Person-Centric Architecture**:
- ALWAYS searches `search_local_memory` FIRST (O(1) lookup)
- Only calls remote APIs if cache miss or stale data
- Aggregates multiple contact points (emails, phones) per person

---

#### 3. Calendar Queries

**View Events**:
- "Show calendar for today"
- "Meetings this week"
- "When am I free tomorrow?"

**Create Events**:
- "Schedule meeting with Mario tomorrow 3pm"
- "Create an invite for all participants with Meet link" (from email)

**Event Features**:
- Google Meet link generation (`add_meet_link=true`)
- Timezone handling
- Attendee extraction from email threads
- Duration suggestions based on meeting type

---

#### 4. Task & Workflow Queries

**Task Management**:
- "What tasks do I have?"
- "What's urgent?"
- "Show unanswered emails"

**Workflow Automation**:
- "Remind me in 3 days if I don't hear back"
- "Schedule follow-up for next week"
- "Create task from this email"

---

### AI Agent Flow

**High-Level Process**:

1. **Command Interception** (chat_service.py):
   ```python
   if user_message.startswith('/'):
       # Execute command handler (NO LLM call)
       return command_result
   ```

2. **Natural Language Processing**:
   ```python
   # Initialize agent with tools
   agent = ZylchAIAgent(tools, memory, persona_analyzer)

   # Process message
   response = await agent.process_message(user_message, context)
   ```

3. **Tool Calling**:
   - Agent selects relevant tools based on query
   - Tools execute (API calls, database queries, etc.)
   - Agent synthesizes results into response

4. **Memory Integration**:
   - Persona analyzer learns user preferences
   - Behavioral memory injects relevant rules
   - Triggered instructions fire on events

---

## Data Flow & Architecture

### Storage Layers

#### 1. Supabase (PostgreSQL)
**Purpose**: Persistent, multi-tenant storage

**Tables**:
- `email_threads` → Synced emails with AI summaries
- `email_messages` → Individual messages in threads
- `calendar_events` → Synced calendar events
- `triggers` → Triggered instructions (event-driven automation)
- `user_mrcall_links` → MrCall business linkages
- `sharing_recipients` → Data sharing relationships

**Isolation**: Per `owner_id` (Firebase UID)

**Performance**:
- Indexed by owner_id
- Multi-tenant with row-level security
- Used for ALL persistent data

---

#### 2. Local Cache (JSON)
**Purpose**: Fast local lookup for CLI

**Files** (`settings.cache_dir`):
- `emails/email_threads.json` → Cached email threads
- `calendar_events.json` → Cached calendar events
- `relationship_gaps.json` → Gap analysis results

**Performance**:
- Sub-second reads
- No network latency
- Synced from Supabase during `/sync`

---

#### 3. ZylchMemory (SQLite + HNSW)
**Purpose**: Behavioral memory with semantic search

**Features**:
- HNSW vector indexing (O(log n) search)
- Semantic similarity matching
- Bayesian confidence scoring
- Personal vs. global namespaces

**Storage**:
- Local SQLite database (`memory.db`)
- Namespace structure: `{owner}:{assistant}:{contact}`

**Performance**:
- Vector search: ~10ms for 1000s of memories
- Exact lookup: ~1ms

---

#### 4. Email Archive (SQLite + FTS5)
**Purpose**: Permanent email storage with full-text search

**Features**:
- FTS5 (Full-Text Search) indexing
- Complete email history (months/years)
- Gmail-only (Outlook not supported yet)

**Storage**:
- Local SQLite database (`email_archive.db`)
- Separate from cache (permanent vs. transient)

**Performance**:
- Full-text search: ~50ms for 10,000s of emails
- Incremental sync: fast delta updates

---

### Query Flow Examples

#### Example 1: `/sync 7`

```
User: /sync 7
  ↓
[Command Handler] (NO LLM)
  ↓
[Sync Service]
  → GmailClient/OutlookClient.fetch_emails(days=7)
  → GoogleCalendarClient/OutlookCalendarClient.fetch_events(days=7)
  ↓
[Supabase Storage]
  → INSERT INTO email_threads ...
  → INSERT INTO calendar_events ...
  ↓
[Local JSON Cache]
  → Write emails/email_threads.json
  → Write calendar_events.json
  ↓
Response: "✅ Email: +15 new, -2 deleted"
```

**LLM Calls**: 0
**Performance**: ~2-5 seconds (network-bound)

---

#### Example 2: `/gaps 7`

```
User: /gaps 7
  ↓
[Command Handler] (NO LLM)
  ↓
[Gap Service]
  → Load cached threads from Supabase/JSON
  ↓
[EmailSyncManager]
  → For each thread:
    ↓
    [Claude Sonnet API] (HEAVY LLM USAGE)
      → Analyze thread for tasks
      → Detect type: "answer" or "reminder"
      → Assign priority 1-10
  ↓
[Aggregate by Person]
  → Multiple threads per person → 1 task max
  → Store in relationship_gaps.json
  ↓
Response: "📊 Gap Analysis... • Need answer: 3 • Need reminder: 2"
```

**LLM Calls**: ~10-50 (depends on thread count)
**Performance**: ~15-60 seconds (LLM-bound)

---

#### Example 3: "Show emails from Mario"

```
User: "Show emails from Mario"
  ↓
[Chat Service]
  ↓
[ZylchAIAgent]
  → Tool selection: search_emails
  ↓
[search_emails tool]
  → Query local cache (emails/email_threads.json)
  → Filter by participant="Mario"
  ↓
[Claude Sonnet API] (LIGHT LLM USAGE)
  → Synthesize response with email details
  ↓
Response: "Here are Mario's emails: ..."
```

**LLM Calls**: 2 (tool selection + response synthesis)
**Performance**: ~1-3 seconds

---

#### Example 4: "Who is luisa@example.com?"

```
User: "Who is luisa@example.com?"
  ↓
[ZylchAIAgent]
  → Tool selection: search_local_memory (CRITICAL!)
  ↓
[search_local_memory tool]
  → Check local cache (~1ms)
  → Return cached data if fresh
  ↓
[IF CACHE MISS OR STALE]:
  → get_contact (StarChat API)
  → search_gmail (Gmail API for history)
  → web_search (Anthropic web search)
  ↓
[Claude Sonnet API]
  → Synthesize contact info
  ↓
Response: "Luisa is..."
```

**LLM Calls**: 2-5 (depends on cache hit)
**Performance**:
- Cache hit: ~1 second
- Cache miss: ~5-10 seconds (remote APIs)

---

## Performance Characteristics

### LLM Call Counts

| Operation | LLM Calls | Model | Cost Impact |
|-----------|-----------|-------|-------------|
| `/sync` | 0 | N/A | FREE |
| `/gaps` (10 threads) | 10-15 | Sonnet | $$$ |
| `/cache` | 0 | N/A | FREE |
| `/memory --list` | 0 | N/A | FREE |
| `/trigger --list` | 0 | N/A | FREE |
| "Show emails from X" | 2 | Sonnet | $ |
| "Who is X?" (cache hit) | 2 | Sonnet | $ |
| "Who is X?" (cache miss) | 5 | Sonnet | $$ |
| "Draft email to X" | 3-5 | Sonnet | $$ |

---

### Response Times

| Operation | Response Time | Bottleneck |
|-----------|---------------|------------|
| `/sync 7` | 2-5s | Gmail/Outlook API |
| `/gaps 7` (10 threads) | 15-30s | Claude API (parallel) |
| `/cache emails` | <100ms | Local JSON |
| `/memory --list` | <500ms | SQLite query |
| "Show emails from X" | 1-2s | Claude API |
| "Who is X?" (cache hit) | <1s | Local cache |
| "Who is X?" (cache miss) | 5-10s | Remote APIs |

---

### Data Volume

**Typical User**:
- Email threads: 100-500 (last 30 days)
- Calendar events: 20-100 (upcoming month)
- Behavioral memories: 10-50
- Triggered instructions: 2-10

**Heavy User**:
- Email threads: 1,000-5,000 (last 90 days)
- Email archive: 10,000-100,000 (years of history)
- Calendar events: 100-500
- Behavioral memories: 50-200
- Triggered instructions: 10-30

---

## Key UX Principles

### 1. Person-Centric Architecture
**Principle**: Everything is organized by PERSON, not threads/messages.

**Implementation**:
- Task aggregation: Multiple threads with Mario → 1 task max
- Contact unification: Multiple emails/phones → 1 person
- Memory namespacing: `{owner}:{assistant}:{contact}`

**UX Impact**:
- Users ask "What does Mario need?" not "What thread is this?"
- Gaps show PEOPLE needing responses, not thread IDs
- Contact searches return PERSON info, not just email matches

---

### 2. Instant Commands, Heavy Analysis
**Principle**: Commands are instant, analysis is slow.

**Implementation**:
- `/sync` = NO LLM (2-5s, network-bound)
- `/gaps` = HEAVY LLM (15-60s, analysis-bound)
- `/cache` = NO LLM (<100ms, local-bound)

**UX Impact**:
- Users expect `/sync` to be fast
- Users expect `/gaps` to take time (show progress?)
- Never make simple lookups slow with unnecessary LLM calls

---

### 3. Local Cache First
**Principle**: Check local cache before remote APIs.

**Implementation**:
- `search_local_memory` called FIRST for contact lookups
- O(1) cache hit vs. 10s remote API calls
- "Fresh" indicator prevents unnecessary refreshes

**UX Impact**:
- Sub-second responses for known contacts
- User prompted before expensive refreshes
- Saves API costs and time

---

### 4. Thread Preservation
**Principle**: Email replies MUST stay in conversation threads.

**Implementation**:
- Draft creation MUST include `In-Reply-To`, `References`, `thread_id`
- Agent extracts headers from `search_emails` results
- Without headers, draft appears OUTSIDE thread (UX regression)

**UX Impact**:
- Replies show in Gmail conversation view
- Maintains conversation context visually
- Critical for professional communication

---

### 5. Multi-Tenant Isolation
**Principle**: Complete data isolation per owner_id.

**Implementation**:
- All queries filtered by `owner_id`
- Namespace structure prevents cross-contamination
- Row-level security in Supabase

**UX Impact**:
- Users never see other users' data
- Scales to thousands of users
- Enterprise-ready privacy

---

### 6. Stateless Server, Stateful Client
**Principle**: Server maintains NO conversation history.

**Implementation**:
- Client sends `conversation_history` with each request
- Server processes and returns, then forgets
- Enables horizontal scaling

**UX Impact**:
- `/clear` clears CLIENT state, not server
- API clients must maintain history array
- RESTful architecture

---

### 7. Explicit Approval for Actions
**Principle**: NEVER send emails or modify calendar without approval.

**Implementation**:
- Agent always shows draft before sending
- "Would you like me to save this as a draft?"
- Separate "draft" vs. "send" tool calls

**UX Impact**:
- User maintains control
- No accidental sends
- Clear distinction: write draft → save draft → send email

---

### 8. Semantic Memory with Confidence
**Principle**: Behavioral rules strengthen/weaken over time.

**Implementation**:
- Bayesian confidence scoring (0.0-1.0)
- Rules update based on success/failure
- HNSW vector search finds relevant memories

**UX Impact**:
- AI learns from corrections ("use lei, not tu")
- High-confidence rules applied automatically
- Low-confidence rules prompt for confirmation

---

## Workflow Examples

### Morning Workflow

**User Goal**: Catch up on emails and tasks

**Steps**:
1. `/sync` → Fetch latest emails/calendar (2-5s)
2. `/gaps` → Analyze for tasks (15-30s)
3. "Summarize today's emails" → Natural language query (2-3s)
4. "Draft reply to Mario's email" → Create draft (3-5s)
5. "Save it" → Save draft to Gmail (1-2s)

**Total Time**: ~25-45 seconds
**LLM Calls**: 15-20 (mostly in `/gaps`)

---

### Contact Lookup Workflow

**User Goal**: Get info about a contact

**Steps**:
1. "Who is luisa@example.com?" → Search local cache (1s if hit, 10s if miss)
2. "Show my relationship with Luisa" → Analyze shared emails (3-5s)
3. "What's her phone?" → Extract from contact data (1s)

**Total Time**: ~5-15 seconds
**LLM Calls**: 5-10

---

### Event Creation Workflow

**User Goal**: Schedule meeting from email

**Steps**:
1. "Show email from Cameron about meeting" → Search emails (2s)
2. "Create invite for all participants with Meet link" → Parse email, create event (3-5s)
3. Review event details (0s)
4. "Looks good" → Confirm creation (1s)

**Total Time**: ~6-8 seconds
**LLM Calls**: 5-7

---

## Summary: Critical UX Requirements

**MUST PRESERVE**:
1. ✅ Person-centric task aggregation (not thread-centric)
2. ✅ Instant commands (`/sync`, `/cache`) with NO LLM calls
3. ✅ Heavy analysis (`/gaps`) with EXPECTED slowness
4. ✅ Local cache first (`search_local_memory` before remote APIs)
5. ✅ Thread preservation in email drafts (`In-Reply-To`, `References`, `thread_id`)
6. ✅ Multi-tenant isolation (owner_id filtering everywhere)
7. ✅ Stateless server (conversation_history sent by client)
8. ✅ Explicit approval for actions (no auto-send)
9. ✅ Semantic memory with confidence scoring
10. ✅ Behavioral memory vs. triggered instructions distinction

**MUST NOT CHANGE**:
- Command syntax (`/sync`, `/gaps`, `/memory`, etc.)
- Output format (markdown with emojis and structure)
- Data isolation (namespace structure)
- Tool calling architecture (Claude + tools)
- Threading behavior (replies stay in threads)
- Cache-first performance pattern

---

**Next Steps**:
- Use this document as reference for avatar integration
- Any deviations = regressions to report
- Performance benchmarks = baseline for comparison
- Tool behavior = must match exactly

**Files Analyzed**:
- `/Users/mal/hb/zylch-main/zylch/services/command_handlers.py` (1,552 lines)
- `/Users/mal/hb/zylch-main/zylch/cli/main.py` (CLI interface)
- `/Users/mal/hb/zylch-main/zylch/services/chat_service.py` (API service)
- `/Users/mal/hb/zylch-main/zylch/agent/prompts.py` (System prompts)
- `/Users/mal/hb/zylch-main/zylch/tools/factory.py` (Tool initialization)
- `/Users/mal/hb/zylch-main/docs/TRIGGERED_INSTRUCTIONS.md` (Trigger docs)
- `/Users/mal/hb/zylch-main/README.md` (Project overview)
