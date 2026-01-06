# Task Agent

Analyzes events using trained prompt and identifies actionable items.

## Purpose

Process emails and calendar events to detect tasks that require user action, using a personalized prompt trained via `/agent train tasks`.

## Components

### TaskWorker

Main worker class:

```python
class TaskWorker:
    """Analyzes events using trained prompt and identifies actionable items."""
```

### TASK_DECISION_TOOL

Structured output via LLM tool_use:

```python
TASK_DECISION_TOOL = {
    "name": "task_decision",
    "description": "Report whether the user needs to take action on this event",
    "input_schema": {
        "type": "object",
        "properties": {
            "action_required": {
                "type": "boolean",
                "description": "True if user needs to take action, False otherwise"
            },
            "urgency": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "high=service outage/billing, medium=technical questions, low=general"
            },
            "suggested_action": {
                "type": "string",
                "description": "Brief description of what user should do"
            },
            "reason": {
                "type": "string",
                "description": "Why this needs attention"
            }
        },
        "required": ["action_required"]
    }
}
```

## Task Detection Flow

### 1. Get Unprocessed Events

```python
# Emails: only unprocessed, latest per thread
all_emails = self.storage.get_unprocessed_emails_for_task(self.owner_id, limit=200)

# Group by thread_id, keep only latest
threads: Dict[str, Dict] = {}
for email in all_emails:
    thread_id = email.get('thread_id')
    if not existing or date_timestamp > existing_timestamp:
        threads[thread_id] = email
```

### 2. Skip User's Own Emails

```python
user_emails = get_my_emails()  # From settings.my_emails

if from_email in user_emails:
    self.storage.mark_email_task_processed(self.owner_id, email_id)
    continue
```

### 3. Get Blob Context

```python
def _get_blob_for_contact(self, contact_email: str) -> tuple:
    """Get memory blob content and ID for a contact."""
    results = self.hybrid_search.search(
        owner_id=self.owner_id,
        query=contact_email,
        namespace=namespace,
        limit=1
    )
    if results:
        return results[0].content[:500], results[0].blob_id
    return "(no prior context)", None
```

### 4. Analyze with Trained Prompt

```python
formatted_prompt = prompt.replace(
    "{event_type}", event_type
).replace(
    "{event_data}", event_data_json
).replace(
    "{blob_context}", blob_context
).replace(
    "{user_email}", self.user_email
)

response = await self.client.create_message(
    messages=[{"role": "user", "content": formatted_prompt}],
    tools=[TASK_DECISION_TOOL],
    tool_choice={"type": "tool", "name": "task_decision"}
)
```

### 5. Store Task Item

```python
if result.get("action_required"):
    task = {
        'action_required': True,
        'urgency': result.get('urgency', 'medium'),
        'suggested_action': result.get('suggested_action', ''),
        'reason': result.get('reason', ''),
        'event_id': email_id,
        'event_type': 'email',
        'contact_email': from_email,
        'sources': {
            'emails': [email_id],
            'blobs': [blob_id] if blob_id else []
        }
    }
    self.storage.store_task_item(self.owner_id, task)
```

## Task Sources

Each task tracks its data sources for context:

```python
result['sources'] = {
    'emails': [email_id],           # Email IDs that created this task
    'blobs': [blob_id] if blob_id   # Blob IDs used for context
}
```

These sources are used by the [Emailer Agent](emailer-agent.md) when replying to tasks.

## Usage

### Get Tasks

```python
worker = TaskWorker(
    storage=storage,
    owner_id=user_id,
    api_key=api_key,
    provider="anthropic",
    user_email="user@example.com"
)

# Get cached tasks
tasks, _ = await worker.get_tasks(refresh=False)

# Force re-analysis
tasks, _ = await worker.get_tasks(refresh=True)
```

### CLI Command

```
/tasks          # Show tasks (cached)
/tasks refresh  # Re-analyze all events
```

## Urgency Levels

| Level | Examples |
|-------|----------|
| `high` | Service outage, billing issues, security alerts |
| `medium` | Technical questions, support requests |
| `low` | General inquiries, newsletters, FYI |

## Processed Tracking

Separate from memory processing:

| Table | Column | Purpose |
|-------|--------|---------|
| `emails` | `task_processed_at` | Track task analysis |
| `calendar_events` | `task_processed_at` | Track task analysis |

## Flow Diagram

```
/tasks refresh
     │
     ▼
get_tasks(refresh=True)
     │
     ├─► clear_task_items()
     │
     ├─► _analyze_recent_events()
     │         │
     │         ├─► get_unprocessed_emails_for_task()
     │         │         │
     │         │         ▼
     │         │    Group by thread_id (latest only)
     │         │         │
     │         │         ▼
     │         │    For each thread:
     │         │         │
     │         │         ├─► Skip if from user
     │         │         │
     │         │         ├─► _get_blob_for_contact() ─► Memory context
     │         │         │
     │         │         ├─► _analyze_event() ─► LLM with tool_use
     │         │         │         │
     │         │         │         ▼
     │         │         │    task_decision tool result
     │         │         │
     │         │         └─► store_task_item() if action_required
     │         │
     │         └─► Same for calendar events
     │
     ▼
get_task_items(action_required=True)
```

## Files

| File | Purpose |
|------|---------|
| `zylch/agents/task_agent.py` | TaskWorker implementation |
| `zylch/storage/supabase_client.py` | Task item storage methods |
| `zylch/services/command_handlers.py` | `/tasks` command handler |

## Related

- [Task Management](../features/task-management.md) - Task items table schema
- [Emailer Agent](emailer-agent.md) - Uses task sources for replies
- [Memory Agent](memory-agent.md) - Creates blobs used for context
