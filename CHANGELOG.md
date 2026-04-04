# Changelog

## [0.1.0] - 2026-04-01

### Standalone Transformation
- **Complete rewrite** from SaaS to local CLI tool
- PostgreSQL replaced with SQLite (WAL mode, 13 models)
- Gmail OAuth replaced with IMAP/SMTP (auto-detect presets)
- FastAPI/Firebase removed, Click CLI added (init, sync, tasks, status, REPL)
- pgvector replaced with fastembed (ONNX, 384-dim) + numpy cosine similarity
- Packaging via pyproject.toml for pip/pipx install
- All config via `~/.zylch/.env` (Pydantic Settings)

### Features
- Email archive with IMAP incremental sync and FTS search
- Entity-centric memory with hybrid search and LLM reconsolidation
- Task detection (4-level urgency: CRITICAL, HIGH, MEDIUM, LOW)
- Incremental task prompt auto-generated after sync
- MrCall/StarChat channel adapter (contacts, calls, SMS)
- BYOK multi-provider LLM (Anthropic, OpenAI) via aisuite
- Semantic command matching via fastembed (no LLM API calls)
- Auto-sync on first chat message if last sync >24h

### Removed (SaaS-only)
- MrCall configurator agent (moved to mrcall-agent repo)
- Firebase authentication
- FastAPI server and REST API
- PostgreSQL, Alembic migrations
- Multi-tenant architecture (owner_id isolation)
- SendGrid, Vonage, Pipedrive integrations
- Docker/K8s deployment
- Sharing system
