---
description: |
  Credential storage for Zylch standalone: all secrets in ~/.zylch/.env via Pydantic Settings.
  BYOK model for LLM keys. Email app passwords for IMAP. OAuth tokens encrypted with Fernet
  in SQLite oauth_tokens table.
---

# Credentials Management

## Storage Policy

- **System config**: `~/.zylch/.env` (Pydantic Settings)
- **OAuth tokens**: SQLite `oauth_tokens` table, encrypted with Fernet
- **No filesystem fallback**: if config is missing, wizard prompts user

## Credential Types

| Type | Storage | Example |
|------|---------|---------|
| Email password | `~/.zylch/.env` | App password for IMAP |
| LLM API key | `~/.zylch/.env` | Anthropic/OpenAI key |
| OAuth tokens | SQLite (encrypted) | Future CalDAV tokens |
| StarChat auth | `~/.zylch/.env` | MrCall channel credentials |

## BYOK Model

Users provide their own API keys. Keys are never hardcoded and never leave the local machine.

## Setup Flow

```
zylch init
  -> Prompts for email, password, LLM provider, API key
  -> Writes ~/.zylch/.env
  -> Auto-detects IMAP/SMTP from email domain
```

## Encryption

OAuth tokens in `oauth_tokens` table are encrypted with Fernet (`zylch/utils/encryption.py`). The encryption key is derived from the machine-specific config.

## Files

| File | Purpose |
|------|---------|
| `zylch/config.py` | Pydantic Settings loading from `~/.zylch/.env` |
| `zylch/utils/encryption.py` | Fernet encryption for stored credentials |
| `zylch/cli/setup.py` | `zylch init` wizard |
| `zylch/api/token_storage.py` | Token storage compatibility shim |
