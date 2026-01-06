# Example: Emailer Agent

The email agent is a complete example of a multi-tool agent.

## Files

- `zylch/agents/emailer_agent.py` - Agent (runner)
- `zylch/agents/emailer_agent_trainer.py` - Trainer
- `zylch/services/command_handlers.py` - Command handlers

## Tools

```python
EMAIL_AGENT_TOOLS = [
    {
        "name": "write_email",
        "description": "Compose and save an email as draft",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "to": {"type": "string"}
            },
            "required": ["subject", "body"]
        }
    },
    {
        "name": "search_memory",
        "description": "Search blobs for context about person/company/template",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_email",
        "description": "Fetch original email by ID",
        "input_schema": {
            "type": "object",
            "properties": {
                "email_id": {"type": "string"}
            },
            "required": ["email_id"]
        }
    },
    {
        "name": "respond_text",
        "description": "Return analysis/suggestions (not an email)",
        "input_schema": {
            "type": "object",
            "properties": {
                "response": {"type": "string"}
            },
            "required": ["response"]
        }
    }
]
```

## Usage Examples

| User Request | Tool Used |
|--------------|-----------|
| "scrivi a Mario un'offerta" | `write_email` |
| "What can I answer to this guy?" | `respond_text` |
| "cerca info su Acme Corp" | `search_memory` → `respond_text` |
| "reply to task 3" | gather context → `write_email` |

## Commands

```
/agent email train              # Learn writing style from sent emails
/agent email run "instructions" # Execute agent
/agent email show               # View trained prompt
/agent email reset              # Delete trained prompt
```

## Key Features

1. **Context Gathering**: Uses `EmailContextGatherer` to collect PERSON, COMPANY, TEMPLATE blobs
2. **Threading Support**: Adds in_reply_to, references, thread_id for replies
3. **Draft Auto-save**: Automatically saves composed emails as drafts
4. **Backwards Compatibility**: Keeps `compose()` method for existing tool usage
