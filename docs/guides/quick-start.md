---
description: |
  Quick start for Zylch standalone: local CLI sales intelligence tool.
  Install via pip/pipx, configure with zylch init, sync emails, get tasks.
---

# Zylch Quick Start

## What is Zylch?

Local AI-powered sales intelligence assistant. Connects to your email (IMAP), detects tasks, maintains relationship memory, and helps you write emails. Runs on your machine, no server needed.

## Install

```bash
# Option 1: pipx (recommended)
pipx install .

# Option 2: pip dev mode
pip install -e .
```

## Setup

```bash
zylch init
```

The wizard asks for:
1. **Email address** (e.g., user@gmail.com)
2. **App password** (not your regular password — generate in provider settings)
3. **LLM provider** (Anthropic or OpenAI)
4. **API key** for the LLM provider

Config saved to `~/.zylch/.env`. IMAP/SMTP servers auto-detected from email domain.

## First Use

```bash
# Sync your emails
zylch sync

# See actionable tasks
zylch tasks

# Start interactive chat
zylch
```

### Interactive Chat Examples

```
You: /sync
     -> Syncs latest emails via IMAP

You: /tasks
     -> Shows tasks requiring action (4-level urgency)

You: chi e' mario.rossi@example.com?
     -> Searches memory + email archive for context

You: scrivi una email a jane@example.com per il follow-up
     -> Drafts email using relationship context
```

## Requirements

- Python 3.11+
- An email account with IMAP access (Gmail, Outlook, Yahoo, iCloud)
- An app password (for Gmail: Google Account > Security > App Passwords)
- An LLM API key (Anthropic or OpenAI)

## Troubleshooting

### "IMAP login failed"
- Use an **app password**, not your regular password
- Gmail: enable 2FA first, then create app password
- Check IMAP is enabled in email settings

### "LLM API key not configured"
- Run `zylch init` again, or edit `~/.zylch/.env` directly

### Import errors
- Ensure you installed: `pip install -e .`
- Check Python version: `python --version` (needs 3.11+)

## Next Steps

- [CLI Commands](cli-commands.md) — full command reference
- [Architecture](../ARCHITECTURE.md) — system overview
