---
description: |
  Current state of Zylch development as of 2026-03-26. What works, what's in progress,
  immediate next steps, and known issues.
---

# Active Context

## What Is Built and Working

### Core Infrastructure
- PostgreSQL storage layer with 29+ SQLAlchemy ORM models
- Alembic migration system
- FastAPI HTTP API at `api.zylchai.com`
- Firebase Auth for multi-tenant authentication
- Scaleway Kubernetes deployment (ARM64)
- GitLab CI/CD with self-hosted ARM runner
- Daily Docker cleanup cron on runner (prevents disk-full build failures)

### Email Intelligence
- Gmail sync (OAuth 2.0, incremental via history_id)
- Microsoft Outlook sync (Graph API)
- Email archive with full-text search (PostgreSQL FTS)
- Email triage (AI-powered categorization)
- Auto-reply detection
- Email read tracking (SendGrid webhooks + custom pixel)
- Draft management (create, edit, send)

### Task System
- Task detection from emails and calendar events
- Person-centric task aggregation
- Priority scoring (urgency 1-10)
- Task orchestrator agent

### Memory System
- Entity-centric blob storage with vector embeddings
- Hybrid search (pgvector + FTS)
- Memory reconsolidation via LLM
- Pattern detection and storage

### Integrations
- Google Calendar (events, Meet link generation)
- Pipedrive CRM (contacts, deals)
- StarChat/MrCall (contacts, telephony config)
- SendGrid (email campaigns)
- Vonage SMS
- Web search (contact enrichment)

### MrCall Configuration
- MrCall agent with **live variable loading** (no more stale trained prompts)
- Feature-level variable management via StarChat API
- **Conversation memory** across `/agent mrcall run` calls within a session
- **Config memory**: configuration decisions persisted as entity blobs (namespace `{owner_id}:mrcall:{business_id}`)
- **Fixed templates** per feature (no LLM-generated meta-prompts for structure)
- Dry-run mode for dashboard with Save/Discard workflow
- Training system retained for Layer 2 (unified agent prompt assembly)

### User Interfaces
- CLI at `~/hb/zylch-cli` (Python/Textual, thin client)
- MrCall Dashboard at `~/hb/mrcall-dashboard` (Vue 3/PrimeVue)
- FastAPI REST API (primary backend)
- `frontend/` directory is dormant (Vue 3 prototype, not active)

### Documentation Harness
- `CLAUDE.md` structured as concise index (~50 lines) with pointers to all docs
- `docs/ARCHITECTURE.md` based on code ground truth
- `docs/active-context.md` tracks current project state
- `docs/quality-grades.md` per-module quality assessment

## Completed (Session 2026-03-26)

### MrCall Agent Refactor — Live Values + Conversation Memory

**Problem**: The configurator agent suffered from three bugs: (1) regressions when modifying variables (reverting to stale trained values), (2) lost context between `/agent mrcall run` calls, (3) losing earlier changes when making new ones. Root cause: values were baked into trained prompts at `/agent mrcall train` time and never refreshed.

**Solution** (commits `2dc1ec2`, `20a827c`):

- **Live StarChat values at runtime**: `mrcall_context.py` fetches current variable values from StarChat before every LLM call. Templates in `mrcall_templates.py` provide fixed structure/format per feature. No more LLM-generated meta-prompts for feature structure.
- **Conversation memory**: `mrcall_agent.py` maintains `conversation_history` list across multiple `run()` calls within a session. Each exchange (user message + agent response + tool results) is appended and injected into subsequent prompts. Solves "sì grazie" → context loss.
- **Config memory** (`mrcall_memory.py`): After each successful `configure_*`, a summary of the decision is stored as an entity blob (namespace `{owner_id}:mrcall:{business_id}`). On next session, these are loaded as context so the agent knows prior configuration decisions.

**New files**:
| File | Purpose |
|------|---------|
| `zylch/agents/mrcall_context.py` | Live StarChat variable fetching + prompt assembly |
| `zylch/agents/mrcall_templates.py` | Fixed feature templates (replacing LLM-generated meta-prompts) |
| `zylch/agents/mrcall_memory.py` | Config memory persistence via blob storage |

**Modified files**: `mrcall_agent.py` (conversation history, live context injection), `mrcall_orchestrator_agent.py` (pass-through of conversation state), `command_handlers.py` (session-level agent reuse), `trainers/mrcall_configurator.py` (simplified, templates moved out), `trainers/mrcall.py` (updated Layer 2 assembly).

### Infrastructure
- Daily Docker cleanup cron on GitLab runner (`0 3 * * *` — `docker system prune -af && docker builder prune -af`)

## Deployed State

- **Production** (`production` branch): deployed successfully (commit `3fd8a03`)
- **Test** (`dev` branch): deployed (commit `20a827c`), pod running (`zylch-849f875b45-t2ngr`)
- Two stale error pods on test (`zylch-566b64c44d-xtn62`, `zylch-849f875b45-46fcs`) — safe to delete

## What Is In Progress

- **MrCall variable cleanup**: `category_map` in `config_tools.py` still has wrong variable names (pre-rename)
- Background job system (job_executor, locking)

## Immediate Next Steps

- Clean up stale pods on starchat-test: `kubectl delete pod zylch-566b64c44d-xtn62 zylch-849f875b45-46fcs -n starchat-test`
- Test the refactored agent end-to-end with a real customer configuration (Super Gomme use case)
- Fix `category_map` in `zylch/tools/mrcall/config_tools.py` with correct post-rename variable names
- Fix modifiable logic bug on `config_tools.py:149` (`and` should likely not require `advanced`)
- Fix `__PERSONALIZE_ANSWERS__` FK mismatch in starchat CSVs
- Run `rename-variables-test.sql` migration against mrcall-test DB
- Billing system (Stripe subscriptions) - Phase H
- WhatsApp integration (awaiting StarChat endpoint)
- Microsoft Calendar feature parity

## Known Issues and Tech Debt

- `config_tools.py:109-125` `category_map` has wrong variable names (pre-rename names, missing variables)
- `config_tools.py:149` modifiable logic is wrong: `value.get("modifiable", False) and value.get("advanced", False)` — requires both flags true, most variables show as read-only
- `SupabaseStorage` class name is misleading (it's pure SQLAlchemy, name is legacy from Supabase era)
- `docs/agents/README.md` lists agents that don't match actual source files (references `memory_agent.py` which doesn't exist)
- Some `*_TODO.md` feature docs describe planned features that don't exist in code yet
- `frontend/` Vue 3 prototype is dormant but still in repo
- `zylch/cache/` directory exists but storage is PostgreSQL-only
- `ScheduledJob` and `ThreadAnalysis` models may be unused (legacy)
- `tools/factory.py` is 2000+ lines (exceeds 500-line rule)
- No external telemetry or monitoring (pre-alpha)
- Single replica deployment (no HA)
- Test + production share same PostgreSQL instance (different namespaces)
