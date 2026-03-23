# Zylch AI - Multi-Channel Sales Intelligence System

Pre-alpha AI assistant for email, calendar, CRM, and telephony management. Python/FastAPI/PostgreSQL.

## Documentation

The directory ./docs/ is continuosly updated through the commands /doc-*. 

Whenever you have a question, check docs/README.md in order to understand how the documentation is organized.

After context compaction, run /doc-intrasession before resuming work!

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
