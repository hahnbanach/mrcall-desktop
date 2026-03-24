---
description: |
  Current state of Zylch development as of 2026-03-19. What works, what's in progress,
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
- MrCall agent + orchestrator for assistant configuration
- Feature-level variable management via StarChat API
- Training system with selective retraining
- Sandbox mode for isolated configuration sessions

### User Interfaces
- CLI at `~/hb/zylch-cli` (Python/Textual, thin client)
- MrCall Dashboard at `~/hb/mrcall-dashboard` (Vue 3/PrimeVue)
- FastAPI REST API (primary backend)
- `frontend/` directory is dormant (Vue 3 prototype, not active)

### Documentation Harness
- `CLAUDE.md` structured as concise index (~50 lines) with pointers to all docs
- `docs/ARCHITECTURE.md` based on code ground truth (215 lines)
- `docs/active-context.md` tracks current project state
- `docs/quality-grades.md` per-module quality assessment
- `docs/execution-plans/` directory for workstream tracking

## Completed This Session (2026-03-19)

### StarChat Variable Rename & Cleanup (~/hb/starchat, branch v9.16)
- Debugged `category_map` in `zylch/tools/mrcall/config_tools.py` — identified wrong variable names (`OSCAR_INBOUND_WELCOME_MESSAGE_PROMPT` does not exist, correct name is `INBOUND_WELCOME_MESSAGE_PROMPT`), missing welcome variables, and a modifiable logic bug (line 149 requires both `modifiable` AND `advanced`)
- Investigated the StarChat variable system via `~/hb/starchat/docs/business-variables-guide.md` and `assistant-configuration-guide.md`
- Analyzed decision table Scala code (`setInitialMessageOrInstructions.sc`) to understand welcome message generation flow (AI prompt vs templated parts)
- Supported variable renames in starchat (committed as `8a24fe18a`):
  - `OSCAR_INBOUND_TOGGLE_INITIAL_MESSAGE_WITH_PROMPT` -> `ENABLE_INBOUND_WELCOME_MESSAGE_PROMPT`
  - `OSCAR_OUTBOUND_TOGGLE_INITIAL_MESSAGE_WITH_PROMPT` -> `ENABLE_OUTBOUND_WELCOME_MESSAGE_PROMPT`
  - `OSCAR_OUTBOUND_WELCOME_MESSAGE_TEXT` -> `OUTBOUND_WELCOME_MESSAGE_TEXT`
  - `SHOW_CONVERSATION_INSTRUCTIONS` -> `ENABLE_CONVERSATION_PROMPT`
  - `CONVERSATION_INSTRUCTIONS` -> `CONVERSATION_PROMPT`
  - Plus WhatsApp and contact variable renames
- Diagnosed CSV upload FK constraint error (`__PERSONALIZE_ANSWERS__` missing from `business_variable.csv`) from starchat pod logs
- Created `~/hb/starchat/scripts/migrations/rename-variables-test.sql` — SQL migration for renaming JSONB keys in `business.variables` and `contact.variables`
- Created `~/hb/starchat/docs/operational/kubernetes-logs.md` — guide for accessing pod logs
- Updated `~/hb/starchat/docs/README.md` — added kubernetes-logs entry

### Zylch (this repo)
- No code changes this session. Analysis only — `category_map` fix not yet applied

## Uncommitted Changes (Zylch)

- None (clean working tree on `main`)

## Uncommitted Changes (StarChat ~/hb/starchat, branch v9.16)

- Additional decision table Scala renames (CONVERSATION_PROMPT, RECURRENT_CALLER, etc.)
- Deleted `decision-tables/variables/get-logs.sh`
- CSV upload not yet successful (FK constraint on `__PERSONALIZE_ANSWERS__` needs fixing first)

## Completed (Session 2026-03-24)

- **Human-friendly configure responses**: After a `configure_*` tool call, a second LLM call generates a plain-language summary instead of showing raw variable names/values. Updated: `mrcall_agent.py` (`_summarize_changes`), `mrcall_orchestrator_agent.py` (`_format_result`), `command_handlers.py` (`_handle_mrcall_agent_run`)
- **Dry-run mode for dashboard**: When invoked from the MrCall dashboard, configure tools validate and summarize but don't apply changes to StarChat. Changes returned as `pending_changes` in API response metadata
- **Save/Discard button**: Dashboard accumulates pending changes in frontend memory. Save button appears in sidebar with count badge. Clicking Save calls `POST /api/mrcall/apply-changes` to batch-apply all changes. Discard clears without applying
- **New endpoint**: `POST /api/mrcall/apply-changes` — receives `{business_id, changes: [{variable_name, new_value}]}`, applies to StarChat
- **Refactored configure dispatch**: Simplified 9 repetitive if/elif blocks in `_handle_tool_response` into single `block.name.startswith('configure_')` check
- **Fixed provider for local testing**: `SYSTEM_LLM_PROVIDER=scaleway` needs working Scaleway Generative API. For local dev, temporarily switch to `anthropic` in `.env.mrcall`

## What Is In Progress

- **MrCall variable cleanup**: `category_map` in `config_tools.py` needs fixing with correct variable names after starchat renames land
- Background job system (job_executor, locking)

## Immediate Next Steps

- Fix `__PERSONALIZE_ANSWERS__` FK mismatch in starchat CSVs, re-run upload script
- Run `rename-variables-test.sql` migration against mrcall-test DB
- Fix `category_map` in `zylch/tools/mrcall/config_tools.py` with correct post-rename variable names
- Fix modifiable logic bug on `config_tools.py:149` (`and` should likely not require `advanced`)
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
