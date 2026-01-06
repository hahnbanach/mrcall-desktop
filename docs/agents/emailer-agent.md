# Emailer Agent

Composes contextual emails using hybrid search and LLM.

## Purpose

Write emails with full context from:
- **PERSON, COMPANY, TEMPLATE blobs** via hybrid search (FTS + semantic)
- **Task sources** (emails, blobs linked to a task)
- **Recipient information** extracted from conversation or thread

## Components

### EmailContext

Dataclass holding gathered context:

```python
@dataclass
class EmailContext:
    contact_blobs: List[SearchResult]   # PERSON entities
    template_blobs: List[SearchResult]  # TEMPLATE entities
    company_blobs: List[SearchResult]   # COMPANY entities
    source_emails: List[dict]           # Emails from task sources
    source_blobs: List[dict]            # Blobs from task sources
```

### EmailContextGatherer

Gathers context for email composition:

1. **Task Sources**: If `task_num` provided, fetch task's `sources.emails` and `sources.blobs`
2. **Hybrid Search**: Run search with full user request to find relevant blobs
3. **Entity Separation**: Filter results by entity type (PERSON, COMPANY, TEMPLATE)

### EmailerAgent

Main agent class:

- Initializes `HybridSearchEngine` and `LLMClient`
- Gathers context via `EmailContextGatherer`
- Builds prompt with prioritized context sections
- Uses `write_email` tool for structured LLM output
- Returns threading headers for replies

## Usage

Exposed as `compose_email` tool in `factory.py`:

```python
result = await agent.compose(
    user_request="scrivi a Mario un'offerta",
    recipient_email="mario@example.com",  # optional
    task_num=3,  # optional, 1-indexed from /tasks
)
```

### Return Value

```python
{
    "subject": "Proposta di collaborazione",
    "body": "Gentile Mario, ...",
    # Threading headers (only if task has source emails):
    "in_reply_to": "<message-id@example.com>",
    "references": ["<msg1@example.com>", "<msg2@example.com>"],
    "thread_id": "gmail-thread-id",
    "recipient_email": "mario@example.com"  # extracted from thread
}
```

## Context Priority

When building the prompt, context is added in priority order with token budget:

1. **ABOUT THE RECIPIENT** - PERSON blobs (most important)
2. **RELEVANT COMPANY INFO** - COMPANY blobs
3. **EMAIL THREAD / SOURCES** - Source emails from task
4. **TEMPLATES TO USE** - TEMPLATE blobs for tone/structure

```python
MAX_CONTEXT_CHARS = 8000  # ~2000 tokens
```

## Threading

When replying to a task with source emails, the agent extracts threading headers:

| Header | Source | Purpose |
|--------|--------|---------|
| `in_reply_to` | `message_id_header` of latest email | Links reply to parent |
| `references` | Existing refs + latest message_id | Full thread chain (RFC 2822) |
| `thread_id` | Gmail thread ID | Keeps conversation grouped |

These headers are passed to `storage.create_draft()` so when the draft is sent, Gmail/Outlook keeps the reply in the original thread.

## Structured Output

Uses LLM tool_use instead of JSON parsing:

```python
WRITE_EMAIL_TOOL = {
    "name": "write_email",
    "description": "Output the composed email",
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "body": {"type": "string"}
        },
        "required": ["subject", "body"]
    }
}

response = await self.llm.create_message(
    messages=[{"role": "user", "content": prompt}],
    tools=[WRITE_EMAIL_TOOL],
    tool_choice={"type": "tool", "name": "write_email"},
    max_tokens=2000
)
```

## Files

| File | Purpose |
|------|---------|
| `zylch/agents/emailer_agent.py` | Agent implementation |
| `zylch/tools/factory.py` | `_ComposeEmailTool` wrapper |
| `zylch/services/command_handlers.py` | `get_task_by_number()` shared function |

## Flow Diagram

```
User: "rispondi al task 3"
         │
         ▼
    compose_email tool
         │
         ├─► get_task_by_number(3) ─► task with sources
         │
         ├─► HybridSearch(user_request) ─► PERSON, COMPANY, TEMPLATE blobs
         │
         ▼
    EmailerAgent.compose()
         │
         ├─► build_prompt_context() ─► prioritized context string
         │
         ├─► LLMClient.create_message() ─► write_email tool call
         │
         ▼
    {subject, body, in_reply_to, references, thread_id}
         │
         ▼
    storage.create_draft() ─► Draft saved with threading headers
         │
         ▼
    "Say 'send it' to send"
```
