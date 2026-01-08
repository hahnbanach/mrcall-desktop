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

Before analyzing each email, the system fetches any existing open task for the same contact and passes it to the LLM:

```python
existing_task = self.storage.get_task_by_contact(self.owner_id, from_email)
if existing_task:
    existing_task_context = f"""
EXISTING OPEN TASK FOR THIS CONTACT:
- Action: {existing_task.get('suggested_action', 'N/A')}
- Urgency: {existing_task.get('urgency', 'N/A')}
- Reason: {existing_task.get('reason', 'N/A')}
- Source emails: {len(existing_task.get('sources', {}).get('emails', []))}

You must decide: UPDATE this task with new info? REPLACE it (create new)? CLOSE it (no longer needed)? Or keep as-is (none)?
"""
```

### 4. Contact Consolidation

One task per contact. When LLM returns `create` and an existing task exists, the old task is closed first.

### 5. Email Date Tracking

Tasks store `email_date` for temporal context display (e.g., "3 days ago").

### 6. Background Job Training

`/agent task train` runs as a background job (5-30+ seconds), notifying user on completion.

## Task Detection Flow

```
/agent task process
     │
     ▼
_analyze_recent_events()
     │
     ├─► get_unprocessed_emails_for_task()
     │         │
     │         ▼
     │    Group by thread_id (latest only)
     │         │
     │         ▼
     │    For each email:
     │         │
     │         ├─► _is_user_email(from_email)? → Skip (hard symbolic)
     │         │
     │         ├─► get_task_by_contact(from_email) → existing_task_context
     │         │
     │         ├─► _get_blob_for_contact() → Memory context
     │         │
     │         ├─► _analyze_event() with existing_task_context
     │         │         │
     │         │         ▼
     │         │    LLM returns task_action: create|update|close|none
     │         │
     │         └─► Handle task_action:
     │                 ├─► close: complete_task_item()
     │                 ├─► update: update_task_item()
     │                 ├─► create: store_task_item() (close existing first)
     │                 └─► none: skip
     │
     └─► Same for calendar events
```

## Task Action Handling

```python
if result:
    task_action = result.get('task_action', 'create')

    if task_action == 'close' and existing_task:
        # Mark existing task as completed
        self.storage.complete_task_item(self.owner_id, existing_task['id'])

    elif task_action == 'update' and existing_task:
        # Update existing task with new info
        self.storage.update_task_item(
            self.owner_id,
            existing_task['id'],
            urgency=result.get('urgency'),
            suggested_action=result.get('suggested_action'),
            reason=result.get('reason'),
            add_source_email=email_id
        )

    elif task_action == 'create' and result.get('action_required'):
        # Create new task (close existing if any)
        if existing_task:
            self.storage.complete_task_item(self.owner_id, existing_task['id'])

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
| `/agent task train [email\|calendar\|all]` | Generate personalized task detection agent (background job) |
| `/agent task process [email\|calendar\|all]` | Detect tasks from data |
| `/agent task show [email\|calendar]` | Display current task agent |
| `/agent task reset [email\|calendar]` | Delete task agent |
| `/tasks` | Show tasks (cached) |
| `/tasks refresh` | Re-analyze all events |

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
| `get_task_by_contact()` | Find existing open task for contact |

## Files

| File | Purpose |
|------|---------|
| `zylch/agents/task_agent.py` | TaskWorker implementation |
| `zylch/agents/email_task_agent_trainer.py` | Prompt generation from email patterns |
| `zylch/storage/supabase_client.py` | Task item storage methods |
| `zylch/services/command_handlers.py` | `/tasks` command handler, `format_task_items()` |
| `zylch/services/job_executor.py` | Background job execution for training |

## Related

- [Emailer Agent](emailer-agent.md) - Uses task sources for replies
- [Memory Agent](memory-agent.md) - Creates blobs used for context
