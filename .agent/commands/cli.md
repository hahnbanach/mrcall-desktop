---
description: Load zylch-cli context and memory for CLI development work
---

Execute immediately. No questions.

NAMESPACE: zylch-cli

MEMORY CONTEXT:
Query these namespaces:
- zylch (backend API the CLI calls)
- zylch-cli (CLI-specific decisions)

READ FIRST:
- ../zylch-cli/README.md
- ../zylch-cli/SETUP.md
- ../zylch-cli/zylch_cli/cli.py (main CLI logic)
- ../zylch-cli/zylch_cli/api_client.py (backend integration)

KEY FILES:
- cli.py: Commands, chat loop, slash handlers
- api_client.py: HTTP calls to api.zylchai.com
- oauth_handler.py: Firebase/Google OAuth flow
- local_storage.py: Modifier queue, local state
- config.py: CLI configuration

REMEMBER:
- CLI is a THIN CLIENT (no business logic)
- All intelligence lives on the backend
- OAuth tokens stored in Supabase (not local)

What do you need to work on?
