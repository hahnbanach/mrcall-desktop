---
description: |
  Index of Zylch agents that process data and generate content via LLM.
  All agents use LLMClient (aisuite wrapper), Storage (SQLAlchemy/SQLite),
  and tool_use for structured JSON output.
---

# Zylch Agents

Agents that process data and generate content using LLM.

## Available Agents

| Agent | File | Purpose |
|-------|------|---------|
| [Emailer Agent](emailer-agent.md) | `zylch/agents/emailer_agent.py` | Compose emails with context from memory |
| [Memory Agent](memory-agent.md) | `zylch/agents/memory_agent.py` | Extract entities from emails into memory blobs |
| [Task Agent](task-agent.md) | `zylch/agents/task_agent.py` | Detect tasks from emails |

## Architecture

All agents share common patterns:

- **LLM Access**: Use `LLMClient` (aisuite wrapper, Anthropic/OpenAI)
- **Data Storage**: Access `Storage` (SQLAlchemy/SQLite)
- **Tool Exposure**: Registered via `ToolFactory` for LLM tool_use
- **Structured Output**: Use `tool_use` for reliable JSON output
- **Trainers**: Prompt generation in `zylch/agents/trainers/`

```
User Request -> Tool (factory.py) -> Agent -> LLMClient -> Response
                                      |
                                   Storage (SQLite)
```

## Common Dependencies

```python
from zylch.llm import LLMClient
from zylch.storage import Storage
from zylch.memory import BlobStorage, HybridSearchEngine, EmbeddingEngine
```

## Related

- [Architecture](../ARCHITECTURE.md) - System context
- [Entity Memory System](../features/entity-memory-system.md) - Blob storage
- [Task Management](../features/task-management.md) - Task system
