# /tasks Refactor Plan

## Goal
Replace rule-based `/tasks` with LLM-reasoning approach that analyzes events and decides "Does user need to act?"

## Current Flow (to remove)
```
Query task_items table → Format as list
```

## New Flow
```
1. Get recent events (emails, calendar, mrcall)
2. For each event, load relevant Blobs from memory
3. Ask LLM: "Does user need to take action?"
4. Collect actionable items → Format as list
```

## Implementation

### 1. Create Task Agent Builder (`zylch/services/task_agent_builder.py`)

Similar pattern to `email_agent_builder.py`:

```python
TASK_AGENT_META_PROMPT = """You are creating a personalized prompt for analyzing events and deciding if the user needs to take action.

Your goal: Generate a prompt that will analyze an event (email, calendar, call) and determine if the user should do something.

=== USER'S PROFILE ===
{user_profile}

=== SAMPLE EVENTS AND RESPONSES ===
{event_samples}

---

Generate a SELF-CONTAINED prompt that will:

1. **ANALYZE THE EVENT**
   - What happened? (email received, meeting scheduled, call missed)
   - Who is involved?
   - What is the context from memory blobs?

2. **USER BEHAVIOR PATTERNS**
   - How quickly does this user typically respond to emails?
   - Do they use phrases like "I'll call you", "book on this link", etc.?
   - What commitments did they make that need follow-up?

3. **DECIDE: ACTION NEEDED?**
   Output ONE of:
   - ACTION: [brief description of what user should do]
   - NO_ACTION: [reason why no action needed]

The prompt will receive:
- {{event_type}} - "email" | "calendar" | "mrcall"
- {{event_data}} - JSON of the event
- {{memory_context}} - Related blobs from memory
- {{user_email}} - User's email (to filter out)
"""
```

### 2. Create Task Worker (`zylch/workers/task_worker.py`)

```python
class TaskWorker:
    """Analyzes events and determines if action is needed."""

    def __init__(self, storage, owner_id, anthropic_api_key):
        self.storage = storage
        self.owner_id = owner_id
        self.anthropic = anthropic.Anthropic(api_key=anthropic_api_key)
        self.hybrid_search = HybridSearchEngine(...)

    async def analyze_event(self, event_type: str, event: dict) -> Optional[dict]:
        """Analyze single event, return action if needed."""

        # 1. Load relevant memory blobs
        query = self._build_search_query(event_type, event)
        blobs = self.hybrid_search.search(query, namespace=f"user:{self.owner_id}")

        # 2. Get task prompt
        prompt = self._get_task_prompt()

        # 3. Ask LLM
        response = self.anthropic.messages.create(
            model=self.model,  # configured via env var
            messages=[{
                "role": "user",
                "content": prompt.format(
                    event_type=event_type,
                    event_data=json.dumps(event),
                    memory_context=self._format_blobs(blobs),
                    user_email=self.user_email
                )
            }]
        )

        # 4. Parse response
        return self._parse_action(response.content[0].text)

    async def get_tasks(self, limit: int = 50) -> List[dict]:
        """Get all actionable tasks across channels."""
        tasks = []

        # Filter: exclude user's own emails
        user_emails = set(e.lower() for e in settings.my_emails.split(','))

        # Emails
        emails = self.storage.get_recent_emails(self.owner_id, limit=limit)
        for email in emails:
            if email.get('from_email', '').lower() in user_emails:
                continue  # Skip own emails
            action = await self.analyze_event('email', email)
            if action:
                tasks.append(action)

        # Calendar
        events = self.storage.get_upcoming_events(self.owner_id, days=7)
        for event in events:
            action = await self.analyze_event('calendar', event)
            if action:
                tasks.append(action)

        # MrCall (TODO)
        # calls = self.storage.get_recent_calls(self.owner_id)
        # ...

        return tasks
```

### 3. Refactor `/tasks` command handler

In `command_handlers.py`, replace `handle_tasks()`:

```python
async def handle_tasks(args: List[str], owner_id: str) -> str:
    """Handle /tasks command - analyze events and show actionable items."""
    from zylch.agents.task_agent import TaskWorker

    # ... help text ...

    worker = TaskWorker(storage, owner_id, anthropic_key)
    tasks = await worker.get_tasks(limit=50)

    if not tasks:
        return "✨ **No action needed!** All caught up."

    return format_task_list(tasks)  # Update task_formatter.py
```

### 4. Update Task Formatting

Change to action-based formatting:

```python
def format_task_list(tasks: List[dict]) -> str:
    """Format LLM-analyzed tasks as numbered list."""

    lines = ["## 📋 Tasks Needing Action\n"]

    for i, task in enumerate(tasks, 1):
        event_type = task.get('event_type', 'unknown')
        icon = {'email': '📧', 'calendar': '📅', 'mrcall': '📞'}.get(event_type, '📌')
        action = task.get('action', 'Review')
        source = task.get('source', '')  # e.g., "John Smith" or "Meeting: Q4 Review"

        lines.append(f"{i}. {icon} **{source}**: {action}")

    lines.append(f"\n**Total: {len(tasks)} items**")
    return "\n".join(lines)
```

### 5. Add `/agent train tasks` subcommand

Similar to `/agent train email`:

```python
if agent_type == 'tasks':
    builder = TaskAgentBuilder(storage, owner_id, anthropic_key, user_email)
    prompt, metadata = await builder.build_task_prompt()
    storage.save_agent_prompt(owner_id, 'tasks', prompt, metadata)
    return "✅ Task analysis agent trained!"
```

## Files to Create
- `zylch/services/task_agent_builder.py` - META_PROMPT + builder class
- `zylch/workers/task_worker.py` - Event analysis worker

## Files to Modify
- `zylch/services/task_formatter.py` - Update for new task format
- `zylch/services/command_handlers.py` - Update `handle_tasks()`, add `train tasks`

## Single Logical Rule
- Filter out user's own email addresses from task analysis (don't suggest "call yourself")

## No New Rules
- No relationship_score thresholds
- No fixed priority levels
- No hardcoded "stale" definitions
- LLM decides importance based on context
