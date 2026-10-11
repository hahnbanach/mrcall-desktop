---
description: |
  Tech stack, coding standards, dependency rules, and imperatives for Zylch standalone.
  Python 3.11+, Click CLI, SQLAlchemy ORM, SQLite, IMAP/SMTP, neonize, BYOK LLM.
---

# System Rules

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Python | 3.11+ |
| CLI Framework | Click | 8.1+ |
| ORM | SQLAlchemy | 2.0+ |
| Database | SQLite (WAL mode): the profile `zylch.db` + one memory store per company key | built-in |
| Auth | Verified Firebase identity; UID-keyed local or hosted profile | - |
| AI/LLM | Direct SDK (Anthropic, OpenAI) | anthropic 0.39+, openai 1.0+ |
| Vector Search | numpy cosine similarity (in-memory) | numpy 1.24+ |
| Embeddings | fastembed (ONNX backend, no PyTorch) | 0.4+ |
| HTTP Client | httpx | 0.28+ |
| Config | Pydantic Settings | 2.0+ |
| Email | IMAP/SMTP (auto-detect presets) | - |
| WhatsApp | neonize (whatsmeow Go wrapper) | 0.3.15+ |
| Telegram | python-telegram-bot | 22.0+ |
| Telephony | StarChat/MrCall HTTP with Firebase identity | - |
| Terminal UI | Rich | 13.0+ |
| Scheduling | APScheduler | 3.10+ |
| Encryption | cryptography (Fernet) | 41.0+ |
| HTML Parsing | beautifulsoup4 | 4.12+ |
| Formatter | Black | 23.0+ |
| Linter | Ruff | 0.1+ |
| Tests | pytest | 7.0+ |

## Coding Standards

### Python Style
- Line length: 100 (enforced by Black + Ruff)
- Target version: Python 3.11
- Type hints on all function signatures
- Google-style docstrings
- Import order: stdlib, third-party, local (separated by blank lines)

### Naming
- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions/methods: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Database tables: `snake_case` (plural)
- Database columns: `snake_case`

### Error Handling
- Catch specific exceptions, not bare `except`
- Log errors with `logger.error(f"...: {e}")`
- Return user-friendly error messages to terminal
- Use `exc_info=True` for unexpected exceptions

### Logging (Mandatory)
- Every command/feature MUST have debug logging
- Log: inputs/params, function call with input AND output, final values
- Pattern: `logger.debug(f"[/command] function(param={param}) -> result={result}")`
- NEVER log tokens or secrets — only "present"/"absent"
- NEVER truncate output in log messages (no `[:8]`, `[:50]`, etc.)

### Tool Pattern
- Tools inherit from `Tool` base class in `zylch/tools/base.py`
- Each tool has `name`, `description`, `input_schema`, and `execute()` method
- Tools are registered via `ToolFactory` in `zylch/tools/factory.py`
- `SessionState` provides runtime context

### Agent Pattern
- Agents inherit from `BaseAgent` in `zylch/agents/base_agent.py`
- Trainers in `zylch/agents/trainers/` handle prompt generation
- Agents use `LLMClient` (direct SDK calls) for model calls
- Storage via `Storage` class (SQLAlchemy-based)
- Structured output via `tool_use` for reliable JSON

## Dependency Rules

### Layer Direction
```
Config (config.py)
  -> Storage (storage/)
    -> Tools (tools/)
      -> Agents (agents/)
        -> Services (services/)
          -> CLI (cli/)
```

### Import Rules
- `config.py` imports nothing from `zylch/`
- `storage/` owns persistence and model helpers. The scoped assignment draft guard is an explicit service-policy hook at the actual write boundary; it must preserve unscoped storage behavior.
- `tools/` imports from `config`, `storage`
- `agents/` imports from `config`, `storage`, `tools`, `llm`, `memory`
- `services/` imports from anything except `cli/`
- `cli/` imports from `services/`, `storage/`, `config`
- `memory/` is a cross-cutting concern, importable by tools and agents
- `whatsapp/` imports from `storage` only
- `telegram/` imports from `services/`

### Data Storage
- ALL data in SQLite via SQLAlchemy ORM
- Core models live in `zylch/storage/models.py`; additional domains register their own model modules.
- New tables use `Base.metadata.create_all()`; existing schemas use the idempotent migration runner in `storage/migrations.py` (no Alembic).
- Credential persistence follows [cross-cutting identity contracts](../../docs/cross-cutting-contracts.md); Firebase ID tokens stay in memory.
- Private profile tables retain their owner predicates; company tables bind to the selected company store. Ordinary task owner IDs are legacy mailbox emails, not human assignees. Hosted isolation also uses a separate Unix user per profile.
- Company assignment writes require verified identity, current trusted membership and an independently signed exact operation; caller audit text and generic chat approval cannot authorize them.

## Imperatives

1. Store application records in SQLite. Profile configuration, encrypted mailbox secrets and privileged assignment trust/signing files follow their documented filesystem contracts.
2. NEVER hardcode secrets — use environment variables via Pydantic Settings
3. NEVER truncate output in code (no `[:8]`, `[:50]`, `[:100]` slicing for display)
4. NEVER commit credentials to git
5. Use registered models for additive tables and the existing migration runner for changes to existing schemas; no Alembic.
6. ALWAYS include debug logging in every new feature
7. ALWAYS use parameterized queries (SQLAlchemy handles this)
8. Files MUST stay under 500 lines
9. Profile name matching MUST be exact — no substring, fuzzy, or partial match
10. MrCall/StarChat is a channel adapter — configuration lives in `mrcall-agent` (separate repo)
