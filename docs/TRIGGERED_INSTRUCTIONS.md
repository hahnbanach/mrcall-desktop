# Triggered Instructions

## Overview

Triggered Instructions are event-driven automation rules that execute when specific events occur. They are different from Behavioral Memory (`/memory`), which contains always-on behavioral rules.

**Key Difference:**
- **Triggered Instructions** (`/trigger`): "Do X **when** Y happens" (event-driven)
- **Behavioral Memory** (`/memory`): "**Always** do X" (always-on)

## Architecture

Triggered instructions are stored in **Supabase** and processed by the backend. This allows:
- Multi-client access (CLI, web app, mobile)
- Persistent storage across sessions
- Background processing via trigger service worker

### Storage

| Component | Details |
|-----------|---------|
| **Database** | Supabase PostgreSQL |
| **Table** | `triggers` |
| **Isolation** | Per `owner_id` (multi-tenant) |

### Data Model

```sql
CREATE TABLE triggers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_id TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    instruction TEXT NOT NULL,
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_triggers_owner ON triggers(owner_id);
CREATE INDEX idx_triggers_type ON triggers(owner_id, trigger_type);
```

## Trigger Types

### 1. session_start
Executes when a new CLI or API session starts.

**Examples:**
- "Greet me at the start of every session with Good morning, today is [date]"
- "Show my top 3 priorities for today"
- "Check for urgent emails and summarize"

### 2. email_received
Executes when a new email arrives (via sync or webhook).

**Examples:**
- "When a new email arrives from unknown sender, create a contact"
- "Alert me for VIP emails"
- "Auto-categorize newsletters"

### 3. sms_received
Executes when a new SMS arrives (via MrCall integration).

**Examples:**
- "Log all SMS in calendar"
- "Alert for messages from family"

### 4. call_received
Executes when a new phone call is received (via MrCall integration).

**Examples:**
- "Send follow-up email after sales calls"
- "Log call duration in CRM"
- "Summarize call and email transcript"

## CLI Commands

### Help
```bash
/trigger --help
```

### List Triggers
```bash
/trigger
# or
/trigger --list
```

**Output:**
```
**Your Triggers** (2 total)

 **session_start** (ID: `abc12345`)
   Say good morning and list my meetings...

 **email_received** (ID: `def67890`)
   Summarize important emails from unknow...

**Commands:** `/trigger --remove <id>` | `/trigger --toggle <id>`
```

### Show Trigger Types
```bash
/trigger --types
```

### Add Trigger
```bash
/trigger --add <type> <instruction>
```

**Examples:**
```bash
/trigger --add session_start "Say good morning and list my meetings for today"
/trigger --add email_received "Summarize important emails from unknown senders"
/trigger --add call_received "Send a follow-up email summarizing the call"
```

### Remove Trigger
```bash
/trigger --remove <id>
```

The ID is the first 8 characters shown in `/trigger --list`.

### Toggle Trigger
```bash
/trigger --toggle <id>
```

Enables/disables a trigger without deleting it.

## Execution Flow

### Session Start Triggers

1. User starts a new session (CLI or web app)
2. Chat service loads active `session_start` triggers for `owner_id`
3. Trigger instructions are injected into the system prompt
4. Claude executes them on first interaction

### Event-Based Triggers (email/sms/call)

1. Event occurs (webhook or sync detects new item)
2. System queues a trigger event in `trigger_events` table
3. Trigger service worker picks up pending events
4. For each matching trigger:
   - Builds context message with event data
   - Executes via AI agent
   - Marks event as completed/failed
5. Results logged for audit

### Trigger Event Queue

```sql
CREATE TABLE trigger_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_data JSONB NOT NULL,
    status TEXT DEFAULT 'pending',  -- pending, processing, completed, failed
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);
```

## Implementation Files

### Backend Services

| File | Purpose |
|------|---------|
| `zylch/services/command_handlers.py` | `/trigger` command handler |
| `zylch/services/trigger_service.py` | Background trigger processor |
| `zylch/storage/supabase_client.py` | Database operations |

### Key Functions

**Command Handler** (`command_handlers.py`):
- `handle_trigger(args, owner_id, user_email)` - Routes trigger commands

**Trigger Service** (`trigger_service.py`):
- `TriggerService.queue_event(owner_id, event_type, event_data)` - Queue trigger event
- `TriggerService.process_pending_events(limit)` - Process queued events
- `TriggerService._execute_with_agent(context)` - Execute trigger via AI
- `TriggerService._build_context_message(event_type, event_data, instruction)` - Build prompt

**Storage** (`supabase_client.py`):
- `list_triggers(owner_id)` - Get user's triggers
- `add_trigger(owner_id, trigger_type, instruction)` - Create trigger
- `remove_trigger(owner_id, trigger_id)` - Delete trigger
- `toggle_trigger(owner_id, trigger_id)` - Enable/disable
- `get_triggers_by_type(owner_id, trigger_type)` - Get triggers for event
- `queue_trigger_event(owner_id, event_type, event_data)` - Queue event
- `get_pending_events(limit)` - Get pending events
- `mark_event_processing(event_id)` - Lock event
- `mark_event_completed(event_id, result)` - Mark success
- `mark_event_failed(event_id, error)` - Mark failure

## Integration Points

### Email Sync
When `/sync` detects new emails, it can queue `email_received` events:

```python
from zylch.services.trigger_service import queue_trigger_event

# After syncing new email
await queue_trigger_event(
    owner_id=owner_id,
    event_type='email_received',
    event_data={
        'from': sender_email,
        'subject': email_subject,
        'snippet': email_snippet[:500]
    }
)
```

### MrCall Webhooks
When MrCall sends webhook for SMS/call:

```python
# In webhook handler
await queue_trigger_event(
    owner_id=owner_id,
    event_type='call_received',
    event_data={
        'caller': caller_phone,
        'duration_seconds': call_duration,
        'transcript': call_transcript
    }
)
```

## Best Practices

### When to Use Triggered Instructions

** Use /trigger for:**
- Event-driven automation: "Do X when Y happens"
- One-time actions on events: "Create contact when email arrives"
- Time-based greetings: "Greet me at session start"
- Automated workflows: "Send follow-up after calls"

** Don't use /trigger for:**
- Always-on behavior: "Always use formal tone"  Use /memory
- Continuous preferences: "Prefer short emails"  Use /memory
- Global settings: "Never mention competitors"  Use /memory

### Writing Good Instructions

**Clear and Specific:**
```
 "Greet me at the start of every session with today's date"
 "Say hi sometimes"
```

**Include Context:**
```
 "When email arrives from unknown sender, create a contact with their email and name"
 "Make contacts"
```

**Action-Oriented:**
```
 "Check for urgent emails and summarize them"
 "Emails are important"
```

### Naming Patterns

Keep instructions concise but descriptive:
```
 "Say good morning and list today's meetings"
 "Check urgent emails from VIPs and alert me"
 "After sales calls, draft a follow-up email"
```

## Troubleshooting

### Trigger Not Executing

**For session_start:**
1. Check trigger is active: `/trigger --list`
2. Start a new session (triggers only fire once per session)
3. Check backend logs for loading confirmation

**For email_received:**
1. Verify trigger is active: `/trigger --list`
2. Run `/sync` to trigger email processing
3. Check that webhooks are configured (for real-time)

**For sms_received / call_received:**
1. Verify MrCall integration is linked: `/mrcall`
2. Check webhook endpoint is accessible
3. Review trigger service logs

### Finding Trigger IDs

```bash
# List shows all IDs (first 8 chars)
/trigger --list

# IDs format: abc12345 (full UUID in database)
# Use the displayed ID for --remove or --toggle
```

### Debugging Trigger Events

Check the `trigger_events` table in Supabase for:
- `status = 'pending'` - Events waiting to be processed
- `status = 'failed'` - Events that failed with `error_message`
- `status = 'completed'` - Successfully processed events

## API Endpoints (Future)

REST endpoints for programmatic access:

```bash
# List triggers
GET /api/triggers

# Create trigger
POST /api/triggers
{
  "trigger_type": "session_start",
  "instruction": "Say good morning"
}

# Delete trigger
DELETE /api/triggers/{id}

# Toggle trigger
PATCH /api/triggers/{id}
{
  "active": false
}
```

## Migration Notes

### From Old CLI to Backend

The trigger system was migrated from the monolithic CLI (`zylch/cli/main.py`) to backend services. Key changes:

| Old (CLI) | New (Backend) |
|-----------|---------------|
| ZylchMemory storage | Supabase PostgreSQL |
| Local execution | Backend trigger service |
| Single client | Multi-client support |
| Sync processing | Async event queue |

### Behavioral Memory Separation

Triggered instructions are separate from behavioral memory (`/memory`):

- `/trigger` = Event-driven, fires once per event
- `/memory` = Always-on, affects all interactions

If you previously stored event-driven rules in `/memory`, migrate them to `/trigger` for proper execution.
