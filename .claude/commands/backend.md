---
description: Load zylch backend context and memory for API/server development work
---

Execute immediately. No questions.

NAMESPACE: zylch

MEMORY CONTEXT:
Query these namespaces:
- zylch (backend decisions, API design)
- zylch-memory (blob/memory architecture)
- default (general context)

READ FIRST:
- .claude/ARCHITECTURE.md
- .claude/DEVELOPMENT_PLAN.md
- zylch/main.py (FastAPI app entry)
- zylch/api/routes.py (API endpoints)
- zylch/services/chat_service.py (core chat logic)

KEY FILES:
- main.py: FastAPI app, middleware, startup
- api/routes.py: All REST endpoints
- services/chat_service.py: Chat processing, tool orchestration
- services/command_handlers.py: Slash command handling
- agent/prompts.py: System prompts, persona
- tools/*.py: Email, calendar, contacts integrations
- storage/storage.py: Database operations

REMEMBER:
- All business logic lives HERE (not in CLI or frontend)
- Supabase Postgres for all server data
- Firebase Auth for multi-tenant authentication
- Email content stored LOCAL-FIRST (client-side encrypted)
- Only AI summaries stored in Supabase

What do you need to work on?
