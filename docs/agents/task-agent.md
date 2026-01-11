# Task Agent

Analyzes events using trained prompt and identifies actionable items with intelligent task lifecycle management.

## Purpose

Process emails and calendar events to detect tasks that require user action, using a personalized prompt trained via `/agent task train`. Consolidates tasks per contact and manages task lifecycle (create/update/close).

## Components

### TaskWorker

Main worker class in `zylch/agents/task_agent.py`:

```python
class TaskWorker:
    """Analyzes events using trained prompt and identifies actionable items."""
```

### TASK_DECISION_TOOL

Structured output via LLM tool_use with task lifecycle actions:

```python
TASK_DECISION_TOOL = {
    "name": "task_decision",
    "description": "Decide what action the user needs to take and how to manage the task",
    "input_schema": {
        "type": "object",
        "properties": {
            "action_required": {
                "type": "boolean",
                "description": "True if user needs to take action"
            },
            "task_action": {
                "type": "string",
                "enum": ["create", "update", "close", "none"],
                "description": "create=new task, update=modify existing, close=resolve existing, none=no action"
            },
            "urgency": {
                "type": "string",
                "enum": ["high", "medium", "low"]
            },
            "suggested_action": {
                "type": "string",
                "minLength": 10,
                "description": "Specific action the user should take"
            },
            "reason": {
                "type": "string",
                "minLength": 20,
                "description": "Why this needs attention - enough context for executive"
            },
            "target_task_id": {
                "type": "string",
                "description": "For update/close: the ID of the existing task to modify"
            }
        },
        "required": ["action_required", "task_action"]
    }
}
```

## Key Features

### 1. Task Actions (Lifecycle Management)

The LLM returns one of four actions:

| Action | Purpose | When Used |
|--------|---------|-----------|
| `create` | Create new task | New actionable item from contact |
| `update` | Update existing task | New info about existing open task |
| `close` | Mark task resolved | Conversation concluded, no action needed |
| `none` | Skip, no task | No action required from this email |

### 2. Hard Symbolic Check (`_is_user_email`)

User's own email can NEVER become a task contact. This is a hard symbolic rule - never trust LLM for this:

```python
def _is_user_email(self, email: str) -> bool:
    """Check if email belongs to the user (hard symbolic check)."""
    email_lower = email.lower()
    if self.user_email and email_lower == self.user_email:
        return True
    if email_lower in get_my_emails():
        return True
    if self.user_domain and self.user_domain in email_lower:
        return True
    return False
```

### 3. Existing Task Context

Before analyzing each email, the system fetches ALL existing open tasks for the same contact and passes them to the LLM with their IDs:

```python
existing_tasks = self.storage.get_tasks_by_contact(self.owner_id, contact_email)
if existing_tasks:
    existing_task_context = f"""
EXISTING OPEN TASKS FOR THIS CONTACT ({len(existing_tasks)} tasks):
"""
    for i, task in enumerate(existing_tasks, 1):
        task_id = task.get('id', 'unknown')
        existing_task_context += f"""
Task #{i} (ID: {task_id}):
- Action: {task.get('suggested_action', 'N/A')}
- Urgency: {task.get('urgency', 'N/A')}
- Reason: {task.get('reason', 'N/A')}
- Source emails: {len(task.get('sources', {}).get('emails', []))}
- Created: {task.get('created_at', '')[:10]}
"""

    existing_task_context += """
DECISION OPTIONS:
- UPDATE: Add to existing task (specify target_task_id)
- CLOSE: Mark resolved (specify target_task_id)
- CREATE: New issue not covered by existing tasks
- NONE: No action needed
"""
```

### 4. Contact Consolidation

One task per contact. When LLM returns `create` and an existing task exists, the old task is closed first.

### 5. Email Date Tracking

Tasks store `email_date` for temporal context display (e.g., "3 days ago").

### 6. Background Job Training

`/agent task train email` runs as a background job (5-30+ seconds), notifying user on completion. The trained prompt includes calendar awareness rules.

### 7. Calendar Context Awareness

When analyzing emails, the task agent fetches calendar events with the contact to make smarter decisions:

```python
def _get_calendar_context(self, contact_email: str) -> str:
    """Get calendar context for a contact (upcoming and recent meetings)."""
    events = self.storage.get_calendar_events_by_attendee(
        self.owner_id,
        contact_email,
        days_back=7,
        days_forward=14
    )
    # Format into UPCOMING MEETINGS and RECENT MEETINGS sections
```

**Decision Logic**:
- **Upcoming meeting exists** → Suppress "schedule call" type tasks (meeting already scheduled)
- **Recent meeting exists** → Consider follow-up based on meeting type (LLM decides)
  - "Proposal Review" → Likely needs follow-up
  - "Quick sync" → Probably doesn't
  - "Thanks for the call" email → Close task, no new follow-up

**Prompt Injection**:
The calendar context is injected via `{{calendar_context}}` placeholder:

```
CALENDAR CONTEXT WITH THIS CONTACT:

📅 UPCOMING MEETINGS (1):
(If there's already a meeting scheduled, you may not need to create a 'schedule call' task)
  - Strategy Call (2025-01-15 14:00)

📋 RECENT MEETINGS (1):
(If a meeting just happened, consider whether follow-up is needed based on meeting type)
  - Quarterly Review (2025-01-08 10:00)
```

**Performance Optimization**:
- Calendar context is pre-computed at batch level to avoid N+1 queries
- Uses `calendar_cache` parameter in `analyze_item_sync()`
- PostgreSQL RPC function `get_events_by_attendee()` for server-side filtering

## Task Detection Flow

```
/agent task process email
     │
     ▼
job_executor._execute_task_process()
     │
     ├─► get_unprocessed_emails_for_task()
     │         │
     │         ▼
     │    Pre-compute calendar_cache for all unique contacts (N+1 fix)
     │         │
     │         ▼
     │    For each email:
     │         │
     │         ├─► _is_user_email(from_email)? → Skip (hard symbolic)
     │         │
     │         ├─► get_tasks_by_contact(from_email) → existing_task_context
     │         │
     │         ├─► _get_blob_for_contact() → Memory context
     │         │
     │         ├─► calendar_cache[from_email] → Calendar context (from cache)
     │         │
     │         ├─► _analyze_event() with all context
     │         │         │
     │         │         ▼
     │         │    LLM returns task_action: create|update|close|none
     │         │
     │         └─► Handle task_action:
     │                 ├─► close: complete_task_item()
     │                 ├─► update: update_task_item()
     │                 ├─► create: store_task_item()
     │                 └─► none: skip
     │
     └─► calendar events (no calendar_cache, processed directly)
```

## Task Action Handling

```python
if result:
    task_action = result.get('task_action', 'create')
    target_task_id = result.get('target_task_id')

    # Find target task from existing_tasks list using ID from LLM
    target_task = None
    if target_task_id and existing_tasks:
        target_task = next((t for t in existing_tasks if t.get('id') == target_task_id), None)

    if task_action == 'close' and target_task:
        # Mark target task as completed
        self.storage.complete_task_item(self.owner_id, target_task['id'])

    elif task_action == 'update' and target_task:
        # Update target task with new info
        self.storage.update_task_item(
            self.owner_id,
            target_task['id'],
            urgency=result.get('urgency'),
            suggested_action=result.get('suggested_action'),
            reason=result.get('reason'),
            add_source_email=email_id
        )

    elif task_action == 'create' and result.get('action_required'):
        # Create new task (LLM decides explicitly via close action, not auto-close)
        result['email_date'] = email.get('date', '')
        result['sources'] = {
            'emails': [email_id],
            'blobs': [blob_id] if blob_id else []
        }
        self.storage.store_task_item(self.owner_id, result)
```

## Task Sources

Each task tracks its data sources for context:

```python
result['sources'] = {
    'emails': [email_id],           # Email IDs that created/updated this task
    'blobs': [blob_id] if blob_id,  # Blob IDs used for context
    'calendar_events': []           # Calendar event IDs (if applicable)
}
```

## CLI Commands

| Command | Purpose |
|---------|---------|
| `/agent task train email` | Generate personalized task detection agent with calendar awareness (background job) |
| `/agent task process [email\|calendar\|all]` | Detect tasks from data with calendar context (background job) |
| `/agent task show [email\|calendar]` | Display current task agent prompt |
| `/agent task reset [email\|calendar]` | Delete task agent prompt (keeps task items) |
| `/tasks` | Show tasks (cached) |
| `/tasks refresh` | Re-analyze all events |
| `/tasks reset` | Delete all task items + reset processing timestamps |

**Note**: `/agent task train email` creates a unified prompt that works for both email and calendar processing. No separate calendar trainer needed.

## Urgency Levels

| Level | Examples |
|-------|----------|
| `high` | Service outage, billing issues, security alerts, urgent deadlines |
| `medium` | Technical questions, support requests, pending decisions |
| `low` | General inquiries, newsletters, FYI, when time permits |

## Processed Tracking

Separate from memory processing:

| Table | Column | Purpose |
|-------|--------|---------|
| `emails` | `task_processed_at` | Track task analysis |
| `calendar_events` | `task_processed_at` | Track task analysis |

## Storage Methods

| Method | Purpose |
|--------|---------|
| `store_task_item()` | Create new task |
| `update_task_item()` | Update existing task with new info/sources |
| `complete_task_item()` | Mark task as completed |
| `get_tasks_by_contact()` | Get ALL open tasks for a contact (list) |
| `get_calendar_events_by_attendee()` | Get calendar events for a contact (uses RPC for performance) |

## Files

| File | Purpose |
|------|---------|
| `zylch/agents/task_agent.py` | TaskWorker with `_get_calendar_context()` and `analyze_item_sync()` |
| `zylch/agents/task_agent_email_trainer.py` | Prompt generation with calendar awareness |
| `zylch/storage/supabase_client.py` | Task and calendar storage methods |
| `zylch/services/command_handlers.py` | `/tasks` command handler, `format_task_items()` |
| `zylch/services/job_executor.py` | Background job with calendar cache pre-computation |
| `zylch/storage/migrations/022_calendar_attendee_search.sql` | RPC function + GIN index for attendee search |

## Related

- [Emailer Agent](emailer-agent.md) - Uses task sources for replies
- [Memory Agent](memory-agent.md) - Creates blobs used for context
