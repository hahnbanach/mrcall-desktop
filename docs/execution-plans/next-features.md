# Next Features
status: active

## Goal
Planned improvements ranked by impact. Each needs analysis before implementation.

## Backlog

### User Profile + Documents Folder
- `zylch init` asks for personal data after channels: full name, codice fiscale, date of birth, address, IBAN, phone
- Stored as a PERSON memory blob for the user themselves (searchable by LLM)
- Editable: `zylch init` → edit → shows current values, user updates
- Documents folder: `~/.zylch/profiles/{email}/documents/`
- User drops PDFs, ID cards, visure, contracts there
- `run_python` tool has access to this path
- LLM told in system prompt: "User documents available in {documents_path}"
- Training step: after init, optionally scan documents folder and extract key data into memory

### Agentic Task Solving (tool_use loop) — DONE
- ~~Current solve is single-shot text generation~~
- Implemented: multi-turn tool_use loop in `task_interactive.py`
- Tools: search_memory, search_emails, draft_email, run_python
- Approval gate on destructive tools (draft_email, run_python)
- Read-only tools (search_memory, search_emails) auto-execute
- Next: add download_attachment, send_email, send_sms tools

### CalDAV Calendar Integration
- Planned channel, not yet implemented
- Sync calendar events, detect meeting follow-ups
- Task detection already has `calendar_context` placeholder
- Affects: new `zylch/calendar/` module, models, sync_service

### WhatsApp QR Reset in Init
- `zylch init` → reset WA → doesn't actually delete whatsapp.db
- Fix: `os.remove(wa_db)` before reconnect in setup wizard

### Task Deduplication
- 34 tasks include duplicates (e.g. 5x "call back Pietro Giana")
- Dedup by contact_email: keep highest urgency, merge sources
- Could run as part of dream prune phase

### Windows Task Scheduler for automatic updates
- `_setup_crontab` uses `crontab` which doesn't exist on Windows
- Need `schtasks.exe` equivalent for Windows Task Scheduler
- Low priority: most users are Mac/Linux

### Stale Code Cleanup
- `zylch/intelligence/` — empty, delete
- `zylch/webhook/` — empty, delete
- `zylch/ml/anonymizer.py` — investigate usage
- `zylch/router/intent_classifier.py` — investigate usage
- `zylch/assistant/` — investigate usage
- `command_handlers.py` (5137 lines) — split by domain
- `gmail_tools.py` (988 lines) — split into search/draft/send

### Lint Fix
- 63 Black reformats, 114 Ruff errors (91 auto-fixable)
- One-time: `black zylch/ && ruff check --fix zylch/`

### Test Suite
- `tests/` directory entirely stale (old SaaS architecture)
- Priority: test process pipeline, task interactive, dream gates
- Pattern: pytest with real SQLite (no mocks per user preference)

### Settings Singleton Reload
- `config.py` creates `settings = Settings()` at import time
- Fixed in `activate_profile` but other code paths may cache stale settings
- Audit all `from zylch.config import settings` usage

## Open Questions
- Agentic solve: should it auto-execute non-destructive actions (search, read) and only ask approval for writes (send, delete)?
- Task dedup: merge at detection time or as post-processing?
- CalDAV: which library? caldav (Python) or direct HTTP?
