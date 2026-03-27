---
description: |
  Tech stack, coding standards, dependency rules, and imperatives for Zylch development.
  Python 3.11+, FastAPI, SQLAlchemy ORM, PostgreSQL 16 with pgvector, Firebase Auth.
---

# System Rules

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Python | 3.11+ |
| Web Framework | FastAPI | 0.104+ |
| ORM | SQLAlchemy | 2.0+ |
| Database | PostgreSQL (Scaleway Managed) | 16, with pgvector + uuid-ossp |
| Migrations | Alembic | 1.13+ |
| Auth | Firebase Admin SDK | 6.0+ |
| AI/LLM | aisuite (multi-provider: OpenAI, Scaleway/Mistral, Anthropic) + Anthropic SDK (direct, for MrCall) | aisuite 0.1.14+, anthropic 0.39+ |
| Vector Search | pgvector (384-dim) + HNSW | 0.3+ |
| Full-Text Search | PostgreSQL tsvector/FTS | built-in |
| Embeddings | sentence-transformers (ONNX backend, no torch) | 3.0+ |
| HTTP Client | httpx | 0.25+ |
| Config | Pydantic Settings | 2.0+ |
| Email | Google Gmail API, Microsoft Graph API | - |
| Calendar | Google Calendar API | - |
| SMS | Vonage | 3.0+ |
| Email Campaigns | SendGrid | 6.11+ |
| CRM | Pipedrive REST API | - |
| Telephony | StarChat/MrCall API | - |
| Scheduling | APScheduler | 3.10+ |
| Formatter | Black | 23.0+ |
| Linter | Ruff | 0.1+ |
| Tests | pytest + pytest-asyncio | 7.0+ |
| Container | Docker (Python 3.11-slim) | - |
| CI/CD | GitLab CI, self-hosted ARM64 runner on Scaleway | - |
| Orchestration | Kubernetes (Scaleway Kapsule, ARM64 nodes) | - |

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
- Return generic error messages to users, log detailed errors server-side
- Use `exc_info=True` for unexpected exceptions

### Logging (Mandatory)
- Every command/feature MUST have debug logging
- Log: inputs/params received, every function call with input AND output, intermediate and final values
- Pattern: `logger.debug(f"[/command] function(param={param}) -> result={result}")`
- NEVER log tokens or secrets — only "present"/"absent"
- NEVER truncate output in log messages (no `[:8]`, `[:50]`, etc.)

### API Patterns
- All API routes use FastAPI `APIRouter`
- Request/response models use Pydantic `BaseModel`
- Standard response format: `{"success": bool, "data": ..., "message": str}`
- Firebase Auth middleware for authenticated endpoints
- CORS configured via `settings.cors_allowed_origins`

### Tool Pattern
- Tools inherit from `Tool` base class in `zylch/tools/base.py`
- Each tool has `name`, `description`, `input_schema`, and `execute()` method
- Tools are registered via `ToolFactory` in `zylch/tools/factory.py`
- `SessionState` provides runtime context (owner_id, business_id, modes)

### Agent Pattern
- Agents inherit from `BaseAgent` in `zylch/agents/base_agent.py`
- Trainers in `zylch/agents/trainers/` handle learning from user data
- Agents use `LLMClient` (aisuite wrapper) for model calls. MrCall agent uses Anthropic SDK directly for web search + streaming
- Storage via `SupabaseStorage` (SQLAlchemy-based, name is legacy)
- Structured output via `tool_use` for reliable JSON

## Dependency Rules

### Layer Direction
```
Config (config.py)
  -> Storage (storage/)
    -> Tools (tools/)
      -> Agents (agents/)
        -> Services (services/)
          -> API Routes (api/routes/)
```

### Import Rules
- `config.py` imports nothing from `zylch/`
- `storage/` imports only from `config`
- `tools/` imports from `config`, `storage`
- `agents/` imports from `config`, `storage`, `tools`, `llm`, `memory`
- `services/` imports from anything except `api/`
- `api/routes/` imports from `services/`, `storage/`, `config`
- `memory/` is a cross-cutting concern, importable by tools and agents

### Data Storage
- ALL data in PostgreSQL via SQLAlchemy ORM — NO local filesystem for data
- Models defined in `zylch/storage/models.py` (29+ models)
- Schema migrations via Alembic (`alembic/versions/`)
- OAuth tokens encrypted at rest (Fernet encryption)
- Multi-tenant isolation via `owner_id` column on every table

## Imperatives

1. NEVER store data on local filesystem — PostgreSQL only
2. NEVER hardcode secrets — use environment variables via Pydantic Settings
3. NEVER truncate output in code (no `[:8]`, `[:50]`, `[:100]` slicing for display)
4. NEVER commit credentials to git
5. ALWAYS include `owner_id` filtering on every database query (multi-tenant isolation)
6. ALWAYS use Alembic migrations for schema changes
7. ALWAYS include debug logging in every new feature
8. ALWAYS use parameterized queries (SQLAlchemy handles this)
9. ALWAYS validate user input with Pydantic models at API boundaries
10. Files MUST stay under 500 lines
11. MrCall/StarChat endpoints MUST include `realm` parameter in path
12. Prefer `POST .../search` endpoints over `GET` for MrCall resource retrieval
