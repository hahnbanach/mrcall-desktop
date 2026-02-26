# Zylch Agents

Backend agents that process data and generate content using LLM.

## Available Agents

| Agent | File | Purpose |
|-------|------|---------|
| [Emailer Agent](emailer-agent.md) | `zylch/agents/emailer_agent.py` | Compose emails with context from memory |
| [Memory Agent](memory-agent.md) | `zylch/agents/memory_agent.py` | Extract entities from emails into memory blobs |
| [Task Agent](task-agent.md) | `zylch/agents/task_agent.py` | Detect tasks from emails and calendar |

## Architecture

All agents share common patterns:

- **LLM Access**: Use `LLMClient` (LiteLLM wrapper) for model calls
- **Data Storage**: Access `SupabaseStorage` for persistence
- **Tool Exposure**: Registered via `ToolFactory` for Claude to call
- **Structured Output**: Use `tool_use` for reliable JSON output

```
User Request → Tool (factory.py) → Agent → LLMClient → Response
                                     ↓
                              SupabaseStorage
```

## Common Dependencies

```python
from zylch.llm import LLMClient
from zylch.storage.supabase_client import SupabaseStorage
from zylch.memory import HybridSearchEngine, EmbeddingEngine
```

## Related Documentation

- [Architecture](../ARCHITECTURE.md) - System context
- [Entity Memory System](../features/entity-memory-system.md) - Blob storage
- [Task Management](../features/task-management.md) - Task items table
