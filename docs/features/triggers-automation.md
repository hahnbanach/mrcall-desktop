# Triggers & Automation - Event-Driven Workflow Automation

## Overview

The Triggers & Automation system enables event-driven workflow automation in Zylch. Users can define instructions that execute automatically when specific events occur, such as email arrivals, phone calls, or SMS messages.

## Key Concepts

### Triggered Instructions vs Behavioral Memory

**Triggered Instructions** (`/trigger`):
- Event-driven: Execute ONLY when specific events occur
- Example: "When a new email arrives, categorize the sender"
- Stored in `triggers` table in Supabase
- Queued for background processing

**Behavioral Memory** (`/memory`):
- Always-on: Applied to EVERY interaction
- Example: "Always use formal tone"
- Stored in ZylchMemory (pg_vector)
- Injected into every AI prompt

### Supported Event Types

| Event Type | Trigger | Description |
|------------|---------|-------------|
| **Session Start** | `session_start` | When user starts a new CLI/chat session |
| **Email Received** | `email_received` | When a new email arrives via Gmail/Outlook |
| **SMS Received** | `sms_received` | When an SMS is received via Vonage |
| **Call Received** | `call_received` | When a phone call is received via StarChat/MrCall |

## How It Works

### 1. User Creates Trigger

Via CLI `/trigger` command or `add_triggered_instruction` tool:

```bash
/trigger --add

# Example: Session start greeting
Trigger type: session_start
Instruction: All'inizio di ogni sessione devi dirmi 'Buongiorno Mario e benvenuto nella tua giornata' e poi mostrarmi i relationship gaps

# Example: Auto-respond to unknown contacts
Trigger type: email_received
Instruction: When a new email arrives from someone I don't know, create a contact in StarChat and send them an auto-reply
```

**Validation mode** (`--check`): Preview what would be created without saving.

### 2. Event Occurs

When an event happens, the webhook handler or sync process queues it:

**Email received** (via Gmail sync):
```python
# In email sync service
from zylch.services.trigger_service import TriggerService

service = TriggerService()
await service.queue_event(
    owner_id="user123",
    event_type="email_received",
    event_data={
        'from_email': 'john@example.com',
        'subject': 'Re: Meeting request',
        'thread_id': 'thread_abc123'
    }
)
```

**Call received** (via StarChat webhook):
```python
# In webhook handler
@app.post("/webhooks/starchat")
async def starchat_webhook(request: Request):
    payload = await request.json()

    if payload['event'] == 'call.received':
        await trigger_service.queue_event(
            owner_id=get_owner_by_phone(payload['to_number']),
            event_type="call_received",
            event_data={
                'caller': payload['from_number'],
                'timestamp': payload['timestamp']
            }
        )
```

### 3. Background Worker Processes Event

The `TriggerService` background worker processes queued events:

```python
# Run from cron job (every 1 minute)
service = TriggerService()
stats = await service.process_pending_events(limit=10)

# Output: {'processed': 5, 'succeeded': 5, 'failed': 0}
```

**Processing flow**:
1. Fetch pending events from `trigger_events` table (status=`pending`)
2. Mark event as `processing` to prevent duplicates
3. Find matching triggers for event type and owner
4. Execute each matching trigger's instruction
5. Mark event as `completed` or `failed`

### 4. Instruction Execution

For each matching trigger:

```python
# 1. Load trigger instruction
trigger = db.get_trigger(trigger_id)
instruction = trigger['instruction']

# 2. Build context from event data
context = f"""
Event: {event['event_type']}
Data: {json.dumps(event['event_data'])}

User instruction: {instruction}
"""

# 3. Execute with AI (Claude Haiku for speed)
response = await claude_client.messages.create(
    model="claude-3-5-haiku-20241022",
    max_tokens=1024,
    messages=[{"role": "user", "content": context}]
)

# 4. Log execution result
db.log_trigger_execution(trigger_id, event_id, response)
```

## Implementation Details

### File References

**Core Service**:
- `zylch/services/trigger_service.py` - Background worker that processes events

**Tools**:
- `zylch/tools/instruction_tools.py` - CLI tools for managing triggers
  - `AddTriggeredInstructionTool` - Create new trigger
  - `ListTriggeredInstructionsTool` - List all triggers
  - `DeleteTriggeredInstructionTool` - Remove trigger

**Command Handler**:
- `zylch/services/command_handlers.py:handle_trigger()` - CLI `/trigger` command dispatcher

**Webhooks**:
- `zylch/api/routes/webhooks.py` - Webhook endpoints that queue events

### Database Schema

**`triggers` table**:
```sql
CREATE TABLE triggers (
  id TEXT PRIMARY KEY,  -- trigger_{8-char-uuid}
  owner_id TEXT NOT NULL,
  event_type TEXT NOT NULL,  -- session_start, email_received, etc.
  instruction TEXT NOT NULL,
  name TEXT,
  active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),

  -- Index for fast lookups
  INDEX idx_owner_event (owner_id, event_type, active)
);
```

**`trigger_events` table** (queue):
```sql
CREATE TABLE trigger_events (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  owner_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  event_data JSONB NOT NULL,
  status TEXT DEFAULT 'pending',  -- pending, processing, completed, failed
  trigger_id TEXT,  -- Trigger that matched (null if no match)
  execution_result TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  processed_at TIMESTAMPTZ,

  -- Index for worker queries
  INDEX idx_pending_events (status, created_at)
);
```

### Key Classes

#### `TriggerService`

Main service for event processing.

**Methods**:
- `queue_event(owner_id, event_type, event_data)` → Optional[Dict]
  - Queues event for background processing
  - Returns created event record or None

- `process_pending_events(limit=10)` → Dict[str, int]
  - Processes up to `limit` pending events
  - Returns stats: `{'processed': N, 'succeeded': N, 'failed': N}`

**Private methods**:
- `_execute_event(event)` → Dict
  - Finds matching triggers for event
  - Executes each trigger's instruction
  - Returns execution result

#### `AddTriggeredInstructionTool`

Tool for creating triggers via AI agent.

**Parameters**:
- `instruction` (required): What Zylch should do when event occurs
- `trigger` (required): Event type (session_start, email_received, sms_received, call_received)
- `name` (optional): Short name for the trigger
- `validation_only` (default: False): Preview without saving

**Returns**: ToolResult with trigger ID and preview

## Usage Examples

### Example 1: Session Start Greeting

**User intent**: "I want a personalized greeting every time I start Zylch"

```bash
/trigger --add

Trigger type: session_start
Instruction: At the start of every session, say 'Good morning Mario, welcome to your day' and then show me relationship gaps
```

**What happens**:
1. Trigger stored with `event_type='session_start'`
2. Every time CLI starts, event queued: `{'event_type': 'session_start', 'event_data': {'user_id': 'user123'}}`
3. Background worker executes instruction before first user interaction
4. User sees greeting automatically

### Example 2: Auto-Categorize Unknown Senders

**User intent**: "Create a contact in StarChat when unknown people email me"

```bash
/trigger --add

Trigger type: email_received
Instruction: When a new email arrives from someone not in my contacts, create a contact in StarChat with their name and email
```

**What happens**:
1. Email arrives from john@unknown.com
2. Event queued: `{'event_type': 'email_received', 'event_data': {'from_email': 'john@unknown.com', 'from_name': 'John Smith'}}`
3. Background worker:
   - Checks if john@unknown.com exists in StarChat
   - If not, calls `create_contact` tool
   - Creates contact with name="John Smith", email="john@unknown.com"

### Example 3: Auto-Reply to Prospects

**User intent**: "When prospects reply to my cold email, invite them to call our demo number"

```bash
/trigger --add

Trigger type: email_received
Instruction: When an email arrives with subject containing 'Re: Product Demo', send an auto-reply saying 'Thanks for your interest! Call us at +39-123-456-789 for a personalized demo'
```

**What happens**:
1. Email arrives with subject "Re: Product Demo Request"
2. Event queued with full email data
3. Background worker:
   - Checks subject matches condition
   - If yes, drafts reply email
   - Sends reply via Gmail API

### Example 4: SMS Notification

**User intent**: "Text me when VIP contacts email me"

```bash
/trigger --add

Trigger type: email_received
Instruction: When an email arrives from john@client.com or mary@partner.com, send me an SMS via Vonage saying 'VIP email received from {sender}'
```

**What happens**:
1. Email from john@client.com arrives
2. Background worker checks sender against VIP list
3. If match, calls Vonage SMS API
4. User receives SMS notification

## CLI Commands

### `/trigger --add`
Create a new triggered instruction.

**Interactive prompts**:
```
Trigger type (session_start, email_received, sms_received, call_received):
Instruction:
Name (optional):
```

**Output**:
```
✅ Triggered instruction created
ID: trigger_abc12345
Event: Email received
Instruction: When a new email arrives from...
```

### `/trigger --list`
List all triggers for current user.

**Output**:
```
📋 Triggered Instructions (3 active)

1. Session Greeting (session_start)
   ID: trigger_001
   "Say 'Good morning' and show gaps"

2. Unknown Contact Handler (email_received)
   ID: trigger_002
   "Create contact for unknown senders"

3. VIP Email Alert (email_received)
   ID: trigger_003
   "SMS me when VIP emails arrive"
```

### `/trigger --delete <id>`
Delete a trigger.

```bash
/trigger --delete trigger_001

✅ Trigger deleted: trigger_001
```

### `/trigger --check`
Preview what would be created (validation mode).

```bash
/trigger --add --check

PREVIEW: This would add a triggered instruction.
Event: When an email is received
Example: Runs automatically every time Gmail sync detects new mail
Instruction: Create contact for unknown senders

No changes made (validation mode).
```

## Background Worker Setup

### Cron Job (Recommended)

Run trigger worker every 1 minute:

```bash
# crontab -e
* * * * * cd /path/to/zylch && python -m zylch.services.trigger_service

# Or via systemd timer (production)
# /etc/systemd/system/zylch-triggers.service
[Unit]
Description=Zylch Trigger Worker

[Service]
Type=oneshot
ExecStart=/path/to/venv/bin/python -m zylch.services.trigger_service
User=zylch
```

### APScheduler (In-Process)

Run worker alongside API server:

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from zylch.services.trigger_service import TriggerService

scheduler = AsyncIOScheduler()

async def process_triggers():
    service = TriggerService()
    stats = await service.process_pending_events()
    print(f"Processed {stats['processed']} events")

# Run every 60 seconds
scheduler.add_job(process_triggers, 'interval', seconds=60)
scheduler.start()
```

### Manual Execution

For testing or debugging:

```bash
python -c "
from zylch.services.trigger_service import TriggerService
import asyncio

async def main():
    service = TriggerService()
    stats = await service.process_pending_events(limit=50)
    print(stats)

asyncio.run(main())
"
```

## Performance Characteristics

### Event Queue
- **Write latency**: <10ms (INSERT to Supabase)
- **Processing latency**: <1s per event (depends on instruction complexity)
- **Batch size**: 10 events per worker run (configurable)

### Trigger Matching
- **Query time**: <50ms (indexed by `owner_id`, `event_type`, `active`)
- **Typical matches**: 1-3 triggers per event
- **Max triggers per user**: No hard limit (recommended <100)

### Execution
- **Model**: Claude Haiku (fast, economical)
- **Token usage**: ~200-500 tokens per execution
- **Cost**: ~$0.0001-0.0003 per trigger execution
- **Timeout**: 30 seconds per instruction

## Known Limitations

1. **No conditional logic**: Triggers can't have complex conditions (use instruction text for simple conditions)
2. **Sequential processing**: Events processed one-at-a-time (not parallelized)
3. **No retry mechanism**: Failed events marked as failed, not retried
4. **Event data limited**: Only basic metadata passed to instruction (full email body not included for privacy)
5. **No trigger chaining**: One trigger can't invoke another trigger

## Future Enhancements

### Planned (Phase E+)
- **Conditional triggers**: Add filter expressions (e.g., "only if from_email contains '@client.com'")
- **Trigger priorities**: Execute high-priority triggers first
- **Retry logic**: Exponential backoff for failed events
- **Batch actions**: Execute multiple similar triggers in one LLM call
- **Trigger analytics**: Dashboard showing trigger execution stats

### Optimization (Phase J - Scaling)
- **Parallel processing**: Process multiple events concurrently
- **Redis queue**: Move event queue to Redis for faster throughput
- **Webhook retry**: Retry failed webhook deliveries automatically
- **Rate limiting**: Prevent trigger spam (max N executions per hour)

## Security Considerations

### Trigger Isolation
- Triggers scoped by `owner_id` (multi-tenant isolation)
- Can only access user's own data
- No cross-user trigger execution

### Input Validation
- Event type must match allowed types
- Instruction text sanitized before LLM execution
- Event data validated before queuing

### Execution Safety
- Triggers run in background worker (isolated from web requests)
- Timeout enforced (30 seconds)
- Failed triggers logged but don't crash worker

## Related Documentation

- **[Memory System](memory-system.md)** - Always-on behavioral memory (vs event-driven triggers)
- **[Email Archive](email-archive.md)** - Source of `email_received` events
- **[Webhook Integration](../../zylch/api/routes/webhooks.py)** - Webhook handlers that queue events
- **[Architecture](../../.claude/ARCHITECTURE.md#automation)** - Automation layer design

## References

**Source Code**:
- `zylch/services/trigger_service.py` - Main background worker
- `zylch/tools/instruction_tools.py` - Trigger management tools
- `zylch/services/command_handlers.py:handle_trigger()` - CLI command handler
- `zylch/api/routes/webhooks.py` - Webhook handlers

**Database Tables**:
- `triggers` - Trigger definitions
- `trigger_events` - Event queue

---

**Last Updated**: December 2025
