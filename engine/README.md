# Zylch — Sales Intelligence

Zylch connects your email, WhatsApp, and phone — detects what you need to do, remembers your contacts, and helps you get things done. Runs locally on your machine.

## Install

```bash
# One-line install (no Python needed)
curl -sL https://raw.githubusercontent.com/malemi/zylch/main/scripts/install.sh | bash

# Or via pip (requires Python 3.11+)
pip install zylch
```

Windows:
```powershell
irm https://raw.githubusercontent.com/malemi/zylch/main/scripts/install.ps1 | iex
```

## Setup

```bash
zylch init
```

The wizard walks through: LLM provider, email, WhatsApp, Telegram, MrCall, personal data, document folders, automatic updates.

## Usage

```bash
zylch                              # Interactive — shows tasks, lets you act
zylch -p user@example.com update   # Sync + analyze + detect tasks
zylch -p user@example.com tasks    # Show action items
zylch profiles                     # List profiles
```

### Interactive Task Review

```
Task 1/7 (HIGH)
  Silvia Baroni (silvia.baroni@milanocentro.eu)
  Pay overdue insurance policy...

  1) Skip — analyze later
  2) Close it — already done
  3) I trust you — solve it!
  4) Let's discuss that
  e) Exit and let's chat
```

When you choose "solve", Zylch searches your memory and emails, drafts replies, and can send them — with your approval.

## Channels

| Channel | What it does |
|---------|-------------|
| **Email** | IMAP/SMTP — syncs inbox + sent, auto-detects Gmail/Outlook/Yahoo |
| **WhatsApp** | QR code login — syncs messages, sends replies |
| **MrCall** | Phone calls + SMS via StarChat/OAuth2 |
| **Telegram** | Bot interface — use Zylch from your phone |
| **Calendar** | Planned (CalDAV) |

## What it does

- **Detects tasks** from your emails and messages — tells you what needs action
- **Remembers contacts** across all channels — knows who said what, when
- **Solves tasks** — searches, drafts emails, fills forms, makes calls
- **Learns your style** — trains on your emails to match your tone
- **Runs locally** — all data in SQLite on your machine, your API keys

## Architecture

- Local CLI (click) + SQLite + BYOK LLM (Anthropic/OpenAI)
- fastembed (ONNX) for embeddings, numpy for vector search
- No server, no Docker, no cloud database

See [docs/](docs/README.md) for full documentation.

## License

Proprietary
