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
Share intelligence with colleagues and team members.

### 🔧 Configuration
Customize AI behavior and system settings.

### 📚 Utility
Help, tutorials, and system management.

---

## Semantic Command Matching

Zylch uses **semantic embeddings** to understand natural language and route to commands without using the Claude API.

### How It Works

1. Your message is embedded using `all-MiniLM-L6-v2` (384 dimensions)
2. Compared against pre-computed trigger templates using cosine similarity
3. If confidence > 0.70, parameters are extracted and command is executed
4. Falls back to Claude for complex queries

### Example Matches

| Natural Language | Command | Confidence |
|-----------------|---------|------------|
| "synchronize with the past 2 days" | `/sync 2` | 0.90 |
| "who is Mario Rossi" | `/memory --search Mario Rossi` | 0.85 |
| "show me the last 5 drafts" | `/email --list --draft --limit 5` | 0.88 |
| "what's on my calendar tomorrow" | `/calendar --list --date tomorrow` | 0.82 |

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
| `model` | "use {model:model}" | `haiku`, `sonnet`, `opus` |

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

📧 Data Management:
• /sync [days] - Sync email and calendar
• /briefing [days] - Daily briefing of tasks and conversations
• /archive - Email archive management

✉️ Email:
• /email - Draft management (list, create, send, delete)

🧠 Memory & Automation:
• /memory [search|store|stats|list|reset] - Entity memory with hybrid search
• /trigger - Event-driven automation

📞 Integrations:
• /mrcall - MrCall/StarChat phone integration

🔗 Sharing:
• /share <email> - Share data with someone
• /revoke <email> - Revoke sharing access
• /sharing - Show sharing status

🔧 Configuration:
• /model [haiku|sonnet|opus|auto] - Change AI model

📚 Utility:
• /tutorial [topic] - Quick guides
• /clear - Clear conversation history
• /help - Show this message

💡 Tip: You can also chat naturally! Ask "who emailed me today?"
```

---

## 📧 Data Management Commands

### `/sync [days] [--status] [--reset]`

**Summary**: Sync emails and calendar from Google/Microsoft

**Description**: Fetches new emails from Gmail/Outlook and calendar events from Google Calendar. Performs incremental sync after first run.

**Arguments**:
- `days` - Number of days to sync (default: 30 for first sync, incremental after)
- `--status` - Show sync status without syncing
- `--reset` - Clear sync state and force full re-sync

**Examples**:
```bash
# Basic sync (incremental after first run)
/sync

# Sync last 7 days
/sync 7

# Sync last 300 days (extensive history)
/sync 300

# Check sync status
/sync --status

# Reset sync state (then run /sync [days])
/sync --reset
```

**Output**:
```
🔄 Sync Complete

✅ Email: +42 new, -3 deleted
🔄 Avatars: 15 contacts queued for analysis (~5 min)
ℹ️  Incremental sync - fetching changes since 2025-12-01
   If you want to go further back, run /sync --reset first

✅ Calendar: 5 new, 2 updated

✅ Done! Run /gaps [days] to analyze tasks.
```

**Status Output** (`/sync --status`):
```
📊 Sync Status

✅ Last synced: 2025-12-08 09:30:00 UTC
📧 Emails archived: 1,234
📅 Calendar events: 89

Run /sync [days] to sync more data.
```

**Performance**:
- Email sync: ~100 messages/second
- Calendar sync: ~50 events/second
- Incremental sync after first run (only fetches changes)

---

### `/gaps [days]`

**Summary**: Analyze email threads for unanswered conversations

**Description**: Queries pre-computed avatars (from `/sync`) to detect relationship gaps - emails requiring action, meetings needing follow-up, or contacts going silent.

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

# Alternative name
/briefing
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

**Note**: Must run `/sync` first to populate avatar data.

---

### `/archive [--stats|--sync|--init|--search]`

**Summary**: Email archive management (Gmail only)

**Description**: Manage the local email archive for fast searching and offline access.

**Options**:

**Show statistics** (`/archive` or `/archive --stats`):
```bash
/archive
```

Output:
```
📦 Email Archive Statistics

Total Messages: 12,456
Total Threads: 3,421
Date Range: 2023-01-15 to 2025-12-08
Full Sync: ✅ Completed
Last Sync: 2025-12-08 09:30:00

Storage: /Users/mal/.zylch/archive/email_archive.db

Use /archive --help for more commands.
```

**Initialize archive** (`/archive --init [months]`):
```bash
# Initialize with 6 months history (default)
/archive --init

# Initialize with 12 months history
/archive --init 12

# Initialize with 3 months history
/archive --init 3
```

Output:
```
✅ Archive Initialized

Downloaded: 4,523 emails (6 months)
Stored: 4,523 messages
Time: 45.3s

Run /archive --stats to see archive details.
```

**Incremental sync** (`/archive --sync`):
```bash
/archive --sync
```

Output:
```
✅ Archive Sync Complete

Added: 42 new messages
Deleted: 3 messages
Duration: 2.1s
```

**Search archive** (`/archive --search <query> --limit N`):
```bash
# Search for "contract"
/archive --search contract

# Search with limit
/archive --search "budget review" --limit 20

# Search by sender
/archive --search "from:john@example.com"
```

Output:
```
📬 Found 8 emails matching: contract

• Q4 Contract Review
  From: john@example.com | 2025-12-05

• Contract Amendment - Acme Corp
  From: sarah@acmecorp.com | 2025-12-01

• Re: Service Contract Renewal
  From: mike@vendor.com | 2025-11-28

...
```

**Note**: Currently Gmail-only. Outlook archiving coming in Phase I.5.

---

## ✉️ Email Commands

### `/email [--list|--create|--send|--delete|--search]`

**Summary**: Manage email drafts stored in Supabase

**Description**: Drafts are stored in Supabase (not Gmail/Outlook drafts). When sent, they go through Gmail or Outlook API based on user's connected provider. This is a Superhuman-style approach where drafts live in Zylch.

**Options**:

**List drafts** (`/email --list --draft`):
```bash
# List recent drafts
/email --list --draft

# List last 5 drafts
/email --list --draft --limit 5
```

**Create draft** (`/email --create`):
```bash
# Create draft to specific recipient
/email --create --to mario@example.com --subject "Meeting follow-up"

# Create draft (opens editor)
/email --create
```

**Send draft** (`/email --send <draft_id>`):
```bash
/email --send abc123
```

**Delete draft** (`/email --delete <draft_id>`):
```bash
/email --delete abc123
```

**Search emails** (`/email --search`):
```bash
# Search by keyword
/email --search "budget proposal"

# Search by sender
/email --search --from john@example.com

# Search with date range
/email --search "contract" --days 30
```

**Provider Routing**: Emails are sent via Gmail API (if Google connected) or Outlook API (if Microsoft connected).

---

## 🧠 Memory & Automation Commands

### `/memory [search|store|stats|list|reset]`

**Summary**: Entity-centric memory with hybrid search

**Description**: The memory system stores "blobs" of natural language information about entities (people, companies, topics). Unlike traditional databases, all facts about an entity live in a single blob that gets reconsolidated when new information arrives.

**Options**:

**Search memory** (`/memory search <query>` or `/memory --search <query>`):
```bash
# Search for a person
/memory search Mario Rossi

# Natural language query
/memory search "who is the CTO of Acme Corp"

# Semantic triggers also work:
"who is Mario Rossi"  →  /memory --search who is Mario Rossi
```

Output:
```
🧠 Memory Search: "Mario Rossi"

📄 **Mario Rossi**
   Mario Rossi is the CTO of Acme Corp. He prefers formal communication
   and responds well to data-driven proposals. Met him at the Milan
   conference in October 2025.

   Last updated: 2025-12-15
   Similarity: 0.92
```

**Store memory** (`/memory store <content>`):
```bash
# Store a fact
/memory store "Mario Rossi moved to the Rome office"

# Store relationship info
/memory store "John Smith is very responsive, usually replies within 2 hours"
```

Output:
```
✅ Memory stored

Content: Mario Rossi moved to the Rome office
Action: Reconsolidated with existing memory (similarity: 0.87)

The existing blob about Mario Rossi has been updated with this new information.
```

**Memory statistics** (`/memory stats`):
```bash
/memory stats
```

Output:
```
🧠 Memory Statistics

Total Blobs: 156
Total Sentences: 892
Index Size: 2.3 MB

By Entity Type (estimated):
• People: 89
• Companies: 42
• Topics: 25

Storage: Supabase (blobs + blob_sentences tables)
```

**List memories** (`/memory list [limit]`):
```bash
# List recent memories
/memory list

# List last 20 memories
/memory list 20
```

**Reset memory** (`/memory reset`):
```bash
# Clear all memories (requires confirmation)
/memory reset
```

**Hybrid Search**: Combines PostgreSQL full-text search (FTS) with pgvector semantic search. Named entities (like "Mario Rossi") weight FTS higher (α=0.7), conceptual queries weight semantic higher (α=0.3).

**Reconsolidation**: When storing new info, Zylch searches for similar existing memories. If found (similarity > 0.65), the LLM merges the old and new info instead of creating duplicates.

**Performance**: <50ms for search (HNSW index), <200ms for store (includes reconsolidation check).

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

**Execution Model**: Claude Haiku (fast, economical, ~$0.0001-0.0003 per trigger execution)

**Performance**: <1s per trigger execution (depends on instruction complexity)

---

## 📞 Integration Commands

### `/mrcall [business_id] [--unlink]`

**Summary**: MrCall/StarChat telephony integration

**Description**: Links your Zylch to a MrCall business for AI-powered phone calls, SMS automation, and call transcript sync.

**Options**:

**Show status** (`/mrcall`):
```bash
/mrcall
```

Output (if linked):
```
📞 MrCall Status

Linked Business: 3002475397
Connected Since: 2025-12-01

Features enabled:
• Phone call handling
• SMS automation
• call_received triggers
• sms_received triggers

Commands:
• /mrcall --unlink - Disconnect
• /trigger --add call_received "..." - Add call automation
```

Output (if not linked):
```
📞 MrCall Status

Status: Not linked

Connect your Zylch to a MrCall business to enable:
• AI-powered phone call handling
• SMS automation
• Call/SMS triggers

Usage: /mrcall <business_id>

Example: /mrcall 3002475397

Contact support@zylchai.com to get your MrCall business ID.
```

**Link to business** (`/mrcall <business_id>`):
```bash
/mrcall 3002475397
```

Output:
```
✅ MrCall Linked

Business ID: 3002475397

Your Zylch is now connected to MrCall!

Next steps:
1. Configure your MrCall assistant to forward to Zylch
2. Add triggers: /trigger --add call_received "Summarize the call"
3. Test with a phone call

Need help? Contact support@zylchai.com
```

**Unlink** (`/mrcall --unlink`):
```bash
/mrcall --unlink
```

Output:
```
✅ MrCall Unlinked

Your Zylch is no longer connected to a MrCall business.
```

**Use Cases**:
- Auto-create contacts from phone calls
- Send call summaries via email
- Trigger actions when VIP calls
- Update CRM after calls

**See Also**: [MrCall Integration](../features/mrcall-integration.md)

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
• Avatar data

Manage: /sharing | /revoke colleague@example.com
```

**What Gets Shared**:
- Contact avatars (relationship intelligence)
- Email threads metadata (not content)
- Calendar meeting context
- Relationship strength scores

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

### `/sharing [--authorize]`

**Summary**: Show sharing status

**Description**: Lists all sharing connections - who you're sharing with (outgoing) and who's sharing with you (incoming).

**Options**:

**Show status** (`/sharing`):
```bash
/sharing
```

Output:
```
📊 Sharing Status

📤 Your Recipients (you share with them)
✅ colleague@example.com (authorized)
⏳ teammate@example.com (pending)

📥 Sharing With You (you receive their data)
✅ boss@example.com (authorized)
⏳ partner@client.com - Pending your authorization
   → /sharing --authorize partner@client.com

Commands: /share <email> | /revoke <email>
```

**Icons**:
- ✅ Authorized (sharing active)
- ⏳ Pending (awaiting authorization)
- ❌ Revoked (sharing stopped)

**Authorize incoming share** (`/sharing --authorize <email>`):
```bash
/sharing --authorize partner@client.com
```

Output:
```
✅ Sharing Authorized

From: partner@client.com

You will now receive their shared data:
• Contact intelligence
• Relationship context
• Avatar data
```

---

## 🔧 Configuration Commands

### `/model [haiku|sonnet|opus|auto]`

**Summary**: Switch AI model

**Description**: Changes which Claude model Zylch uses for responses. Each model has different speed/quality/cost tradeoffs.

**Models**:
- `haiku` - Claude 3.5 Haiku (fast, economical)
- `sonnet` - Claude 3.5 Sonnet (balanced) ⭐ default
- `opus` - Claude 3 Opus (powerful, expensive)
- `auto` - Automatic selection based on task

**Usage**:
```bash
# Switch to Haiku (fast)
/model haiku

# Switch to Sonnet (balanced)
/model sonnet

# Switch to Opus (powerful)
/model opus

# Enable automatic selection
/model auto
```

**Output**:
```
✅ Model selected: sonnet

Model ID: claude-3-5-sonnet-20241022

For this to take effect:
API clients should include in context for future requests:
{
  "context": {
    "forced_model": "claude-3-5-sonnet-20241022"
  }
}
```

**Model Comparison**:

| Model | Speed | Quality | Cost | Best For |
|-------|-------|---------|------|----------|
| Haiku | Fast | Good | Low | Quick queries, triggers |
| Sonnet | Medium | Excellent | Medium | General use, drafts |
| Opus | Slow | Best | High | Complex analysis, critical emails |

**Note**: Model selection is per-session. For programmatic access, pass `forced_model` in API context.

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

### `/tutorial [topic]`

**Summary**: Quick guides and tutorials

**Description**: Learn how to use Zylch with interactive guides.

**Topics**:
- `contact` - Contact management
- `email` - Email operations
- `calendar` - Calendar management
- `sync` - Morning sync workflow
- `memory` - Memory system

**Usage**:
```bash
# List available topics
/tutorial

# Show contact management guide
/tutorial contact

# Show sync workflow guide
/tutorial sync
```

**Example Output** (`/tutorial sync`):
```
🔄 Morning Sync Workflow

Daily routine:
1. Run /sync - Fetch emails + calendar
2. Check /gaps - See unanswered emails
3. Review: "Summarize today's emails"
4. Respond: "Draft reply to Mario's email"

Quick workflow: /sync → /gaps → respond

Pro tip: Use /cache to inspect cached data.
```

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

### Sharing with Team

**Goal**: Share relationship intelligence with colleague.

```bash
# 1. Send share request
/share colleague@example.com

# 2. Ask colleague to authorize
"Ask colleague to run: /sharing --authorize your@email.com"

# 3. Verify sharing active
/sharing
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
    "forced_model": "claude-3-5-sonnet-20241022"
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
| `/gaps` | <100ms | Pre-computed avatars |
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
1. No avatars computed yet → Wait 5 minutes after `/sync`
2. All conversations closed → Correct behavior
3. Relationship score threshold too high → Check avatar scores

**Fix**:
```bash
# Check sync status
/sync --status

# Verify avatars queued
# (should show "X contacts queued for analysis")

# Wait 5 minutes for background worker
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
- **[Memory System](../features/memory-system.md)** - Behavioral memory and patterns
- **[Sharing System](../features/sharing-system.md)** - Consent-based intelligence sharing
- **[MrCall Integration](../features/mrcall-integration.md)** - Telephony and WhatsApp
- **[Email Archive](../features/email-archive.md)** - Email archiving details
- **[Architecture](../architecture/overview.md)** - System architecture

---

**Last Updated**: December 2025
