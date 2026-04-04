---
description: |
  Tech stack, coding standards, dependency rules, and imperatives for Zylch standalone.
  Python 3.11+, Click CLI, SQLAlchemy ORM, SQLite, IMAP/SMTP, BYOK LLM.
---

# System Rules

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Python | 3.11+ |
| CLI Framework | Click | 8.1+ |
| ORM | SQLAlchemy | 2.0+ |
| Database | SQLite (WAL mode) | built-in |
| Auth | None (mono-user, local) | - |
| AI/LLM | aisuite (multi-provider: Anthropic, OpenAI) | aisuite 0.1.14+ |
| Vector Search | numpy cosine similarity (in-memory) | numpy 1.24+ |
| Embeddings | fastembed (ONNX backend, no PyTorch) | 0.4+ |
| HTTP Client | httpx | 0.25+ |
| Config | Pydantic Settings | 2.0+ |
| Email | IMAP/SMTP (auto-detect presets) | - |
| Telephony | StarChat/MrCall HTTP (channel adapter) | - |
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
- Log: inputs/params received, every function call with input AND output, intermediate and final values
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
- Agents use `LLMClient` (aisuite wrapper) for model calls
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
- `storage/` imports only from `config`
- `tools/` imports from `config`, `storage`
- `agents/` imports from `config`, `storage`, `tools`, `llm`, `memory`
- `services/` imports from anything except `cli/`
- `cli/` imports from `services/`, `storage/`, `config`
- `memory/` is a cross-cutting concern, importable by tools and agents

### Data Storage
- ALL data in SQLite via SQLAlchemy ORM
- Models defined in `zylch/storage/models.py` (17 models)
- Tables created via `Base.metadata.create_all()` (no Alembic)
- Credentials encrypted at rest (Fernet encryption)
- Mono-user — no `owner_id` multi-tenant isolation needed

## Imperatives

1. NEVER store data on filesystem — SQLite only (except `~/.zylch/.env` for config)
2. NEVER hardcode secrets — use environment variables via Pydantic Settings
3. NEVER truncate output in code (no `[:8]`, `[:50]`, `[:100]` slicing for display)
4. NEVER commit credentials to git
5. ALWAYS use `Base.metadata.create_all()` for schema creation (no Alembic)
6. ALWAYS include debug logging in every new feature
7. ALWAYS use parameterized queries (SQLAlchemy handles this)
8. Files MUST stay under 500 lines
9. MrCall/StarChat is a channel adapter — configuration lives in `mrcall-agent` (separate repo)
