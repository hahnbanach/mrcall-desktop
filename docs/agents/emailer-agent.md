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

## Training: `/agent email train`

Unlike a static prompt, the EmailerAgent can learn your personal writing style.

### Training Command

```
/agent email train
```

This analyzes your **sent emails** to learn:
- **Greeting patterns**: "Ciao", "Gentile", "Hi" etc.
- **Sign-off style**: Signature, title, formality
- **Tone**: Formal/informal, language preferences
- **Structure**: Short/long emails, bullet points, paragraphs

### How It Works

1. **Collect sent emails**: Filter emails where `from_email` matches user's domain
2. **Extract patterns**: Greetings, signatures, subjects, languages
3. **Generate prompt**: LLM analyzes samples and creates personalized writing instructions
4. **Store prompt**: Saved in `agent_prompts` table with `agent_type='emailer'`

### Trainer Class

```python
class EmailerAgentTrainer:
    """Builds personalized email writing agent by analyzing user's sent emails."""

    async def build_emailer_prompt(self) -> Tuple[str, Dict[str, Any]]:
        # 1. Get user's SENT emails
        sent_emails = self._get_sent_emails(limit=50)

        # 2. Analyze writing patterns
        user_profile = self._analyze_writing_style(sent_emails)

        # 3. Format samples for meta-prompt
        sent_samples = self._format_sent_samples(sent_emails, max_samples=15)

        # 4. Generate personalized prompt via LLM
        prompt_content = self._generate_prompt(user_profile, sent_samples)

        return prompt_content, metadata
```

### Trained vs Untrained

| Aspect | Without Training | With Training |
|--------|------------------|---------------|
| Style | Generic | Matches your writing |
| Language | Infers from context | Knows your preferences |
| Signature | None | Your actual signature |
| Tone | Neutral | Your natural tone |

### Other Commands

```
/agent email show   # View your trained prompt
/agent email reset  # Delete and retrain
```

## Files

| File | Purpose |
|------|---------|
| `zylch/agents/emailer_agent.py` | Agent implementation |
| `zylch/agents/emailer_agent_trainer.py` | Training meta-prompt and style analysis |
| `zylch/tools/factory.py` | `_ComposeEmailTool` wrapper |
| `zylch/services/command_handlers.py` | `/agent email train` handler |

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
