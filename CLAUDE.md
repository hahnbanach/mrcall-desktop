# Claude Instructions for Zylch AI

## RULE ZERO: Check Memory First

**BEFORE reading any file, BEFORE using Glob/Grep, ALWAYS check claude-flow memory:**

```
mcp__claude-flow__memory_usage(action="list", namespace="zylch")
```

This contains:
- File locations (no need to Glob for ARCHITECTURE.md, etc.)
- Implementation details
- Design decisions
- Critical patterns

**If the information is in memory → USE IT. Don't waste time reading files.**

This is the same "LOCAL MEMORY FIRST" principle we use for Zylch contacts!

---

## Critical Rules

1. **Questions vs Tasks**: If user asks a QUESTION (ends with "?"), provide an ANSWER - do NOT start coding unless explicitly requested
2. Do what has been asked; nothing more, nothing less
3. NEVER create files unless absolutely necessary for achieving the goal
4. ALWAYS prefer editing existing files to creating new ones
5. NEVER proactively create documentation files (*.md) or README files
6. Only create documentation if explicitly requested by the user

## File Organization

**Organize files properly:**
- Source code → `zylch/`
- Tests → `tests/`
- Documentation → `docs/`
- Config → Root or `.env`
- Cache → `cache/`

**NEVER save working files, tests, or markdown to the root folder**

## Project Context

- Python project with FastAPI backend
- Uses Anthropic Claude API (Sonnet, Haiku, Opus models)
- Multi-user system with Firebase JWT authentication
- Email/Calendar intelligence with Gmail/Google Calendar APIs
- SQLite for email archive, JSON for intelligence cache
- Check `claude-flow` memory (namespace: `zylch`) for implementation details

## CRITICAL: ZYLCH IS PERSON-CENTRIC

**A person can have multiple emails, multiple phones, multiple aliases.**

The system is centered on PEOPLE/CONTACTS, NOT on email addresses:
- Namespace structure: `{owner}:{assistant}:contacts` (single namespace for all contacts)
- Identifier map: `cache/identifier_map.json` maps email/phone/name → memory_id
- One person = one memory_id, but can have many identifiers pointing to it

**Local Memory First Pattern:**
1. ALWAYS call `search_local_memory` FIRST when user asks about a person
2. If data is fresh (< 7 days): USE IT, skip remote API calls
3. If data is stale or not found: proceed with remote searches
4. When saving: `save_contact` saves to StarChat AND ZylchMemory AND identifier_map

This saves 10+ seconds and API costs on every contact lookup!

## When in Doubt

1. Check claude-flow memory: `mcp__claude-flow__memory_search(namespace="zylch")`
2. Read `.claude/` directory for detailed guidelines (when created)
3. Ask user for clarification instead of making assumptions
4. If question mark at end of user message → ANSWER, don't code
