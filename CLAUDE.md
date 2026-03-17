# Zylch AI - Multi-Channel Sales Intelligence System

Pre-alpha AI assistant for email, calendar, CRM, and telephony management. Python/FastAPI/PostgreSQL.

## Documentation Index

| Document | Summary |
|----------|---------|
| [docs/architecture.md](docs/architecture.md) | System map, data flow, infrastructure, cross-cutting concerns |
| [docs/system-rules.md](docs/system-rules.md) | Tech stack, coding standards, dependency rules, imperatives |
| [docs/active-context.md](docs/active-context.md) | What works, what's in progress, next steps, known issues |
| [docs/quality-grades.md](docs/quality-grades.md) | Per-module test coverage, docs completeness, conformance |
| [docs/CONVENTIONS.md](docs/CONVENTIONS.md) | Code style, MrCall integration rules, patterns |
| [docs/features/](docs/features/) | Feature documentation (email, memory, tasks, MrCall, etc.) |
| [docs/agents/](docs/agents/) | Agent architecture and per-agent docs |
| [docs/guides/](docs/guides/) | Setup guides (Gmail OAuth, deployment, CLI) |
| [docs/execution-plans/](docs/execution-plans/) | Active implementation plans |
| [docs/harness-backlog.md](docs/harness-backlog.md) | Enforcement gaps and tooling debt |

## Quick Reference

```bash
# Build & Run
pip install -e .                              # Install in dev mode
uvicorn zylch.api.main:app --reload           # Start API server
alembic upgrade head                          # Run DB migrations

# Test
python -m pytest tests/ -v                    # Run all tests
python -m pytest tests/test_agent.py -v       # Run specific test

# Lint & Format
black --check zylch/ tests/                   # Check formatting
ruff check zylch/ tests/                      # Lint

# Deploy (via GitLab CI)
# Push to `dev` branch → auto-deploy to starchat-test
# Push to `production` branch → auto-deploy to starchat-production
```

## Critical Rules

- **NO OUTPUT TRUNCATION**: Never use `[:8]`, `[:50]`, `[:100]` slicing for display. Show FULL values.
- **DEBUG LOGGING MANDATORY**: Every feature must log inputs, calls, and results. Pattern: `logger.debug(f"[/cmd] func(param={param}) -> result={result}")`
- **NEVER log secrets**: Only "present"/"absent".
- **CONCURRENT OPERATIONS**: Batch all independent operations in a single message.
- **NO ROOT FILES**: Never save working files to root. Use: `/zylch` (source), `/tests` (tests), `/docs` (docs), `/scripts` (scripts).
- **FILES < 500 LINES**: Keep modules small and focused.
- **NO HARDCODED SECRETS**: Use environment variables via Pydantic Settings.
- **POSTGRESQL ONLY**: No local filesystem for data storage.
