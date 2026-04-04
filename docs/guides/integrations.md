---
description: |
  Zylch integrations guide for standalone CLI. Channels: Email (IMAP),
  WhatsApp (neonize QR), MrCall (OAuth2), Telegram (bot). All configured
  via zylch init wizard or ~/.zylch/.env.
---

# Zylch Integrations Guide

**Last Updated**: April 2026

## Overview

Zylch connects to external services via local protocols — no server, no API
endpoints, no cloud middleware. All credentials are stored in `~/.zylch/.env`
(secrets) and `~/.zylch/zylch.db` (OAuth tokens). The `zylch init` wizard
walks through setup for all channels.

---

## Available Integrations

### Channels (data sources)

| Channel | Protocol | Auth | Status |
|---------|----------|------|--------|
| **Email** | IMAP/SMTP | App password | Working |
| **WhatsApp** | neonize (whatsmeow) | QR code (local) | Working |
| **MrCall** | StarChat HTTP + OAuth2 | OAuth2 PKCE | Working |
| **Calendar** | CalDAV | TBD | Planned |

### Interfaces (how you interact with Zylch)

| Interface | Protocol | Auth | Status |
|-----------|----------|------|--------|
| **CLI REPL** | Terminal | None (local) | Working |
| **Telegram bot** | Bot API (polling) | Bot token + user ID | Working |

---

## Setup via `zylch init`

The interactive wizard configures all channels in 5 steps:

```
$ zylch init

Step 1/5: LLM Provider
  → ANTHROPIC_API_KEY, SYSTEM_LLM_PROVIDER

Step 2/5: Email (IMAP)
  → EMAIL_ADDRESS, EMAIL_PASSWORD, IMAP/SMTP servers
  → Auto-detects servers for Gmail, Outlook, Yahoo, iCloud

Step 3/5: WhatsApp
  → Shows QR code inline, scan with WhatsApp on phone
  → Session stored in ~/.zylch/whatsapp.db

Step 4/5: Telegram
  → TELEGRAM_BOT_TOKEN (from @BotFather)
  → TELEGRAM_ALLOWED_USER_ID (your Telegram user ID)

Step 5/5: MrCall
  → MRCALL_CLIENT_ID, MRCALL_CLIENT_SECRET
  → Opens browser for OAuth2 consent
  → Tokens stored in oauth_tokens table
```

Re-running `zylch init` shows current values and asks for confirmation
before overwriting. Channels already connected can be skipped.

---

## Email (IMAP/SMTP)

### How to connect

1. Run `zylch init` or manually set in `~/.zylch/.env`:
   ```bash
   EMAIL_ADDRESS=you@gmail.com
   EMAIL_PASSWORD=your-app-password
   IMAP_SERVER=imap.gmail.com
   IMAP_PORT=993
   SMTP_SERVER=smtp.gmail.com
   SMTP_PORT=587
   ```
2. For Gmail: create an [App Password](https://myaccount.google.com/apppasswords)
   (requires 2FA enabled)

### Auto-detect presets

The wizard auto-detects IMAP/SMTP servers from your email domain:
- `gmail.com` → `imap.gmail.com` / `smtp.gmail.com`
- `outlook.com`, `hotmail.com` → `outlook.office365.com` / `smtp.office365.com`
- `yahoo.com` → `imap.mail.yahoo.com` / `smtp.mail.yahoo.com`
- `icloud.com` → `imap.mail.me.com` / `smtp.mail.me.com`

### Commands

```bash
/sync                  # Sync emails via IMAP
/sync status           # Show sync counts
/email search <query>  # Search by sender, subject, content
```

---

## WhatsApp (neonize)

### How to connect

1. Run `zylch init` (step 3) or use the command:
   ```
   /connect whatsapp
   ```
2. A QR code is displayed inline in the terminal
3. Open WhatsApp on your phone → Settings → Linked Devices → Link a Device
4. Scan the QR code (60s timeout)
5. Session is stored in `~/.zylch/whatsapp.db`

### How it works

- Uses **neonize** (Python wrapper of whatsmeow) for WhatsApp Web multi-device
- Runs locally — no cloud API, no WhatsApp Business API needed
- Syncs contacts and message history to SQLite on `/sync whatsapp`
- 5 LLM tools: search, conversation, send, gap analysis, unified timeline

### Commands

```bash
/connect whatsapp      # QR code login
/sync whatsapp         # Sync contacts + messages
```

### Natural language

```
You: search WhatsApp messages from Marco
You: show my WhatsApp conversation with Luisa
You: send a WhatsApp message to Marco: "ci vediamo domani"
You: which WhatsApp contacts haven't I replied to?
You: show full timeline with Marco (email + WhatsApp + calls)
```

---

## MrCall (StarChat + OAuth2)

### How to connect

1. Get your `client_id` and `client_secret` from the MrCall dashboard
2. Run `zylch init` (step 5) or manually set in `~/.zylch/.env`:
   ```bash
   MRCALL_CLIENT_ID=your-client-id
   MRCALL_CLIENT_SECRET=your-client-secret
   ```
3. The wizard opens your browser for OAuth2 consent
4. After authorizing, tokens are stored encrypted in the `oauth_tokens` table

### OAuth2 flow details

- **Authorization Code + PKCE** (SHA256 challenge)
- Local HTTP callback server on `127.0.0.1:19274`
- Browser opens MrCall consent page automatically
- 120s timeout for user to authorize
- Tokens stored in SQLite, refresh supported via `refresh_mrcall_token()`

### What it provides

- Phone call history (via StarChat API)
- Contact information
- SMS sending capability
- Call metadata for unified timeline

---

## Telegram Bot (interface)

### How to connect

1. Create a bot via [@BotFather](https://t.me/BotFather) on Telegram
2. Copy the bot token
3. Get your Telegram user ID (send `/start` to [@userinfobot](https://t.me/userinfobot))
4. Run `zylch init` (step 4) or set in `~/.zylch/.env`:
   ```bash
   TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
   TELEGRAM_ALLOWED_USER_ID=your-numeric-id
   ```
5. Start the bot: `zylch telegram`

### How it works

- Long-polling (no webhook, no public server needed)
- Bridges to the same ChatService as the CLI REPL
- All slash commands and natural language queries work
- Markdown responses converted to Telegram HTML
- Messages >4096 chars are split automatically
- **Default-deny**: if `TELEGRAM_ALLOWED_USER_ID` is not set, all requests are rejected

### Security

The bot is secured by `TELEGRAM_ALLOWED_USER_ID`. Only the specified user can
interact with it. Without this setting, the bot rejects all messages.

---

## LLM Provider (BYOK)

### Configuration

```bash
SYSTEM_LLM_PROVIDER=anthropic    # or "openai"
ANTHROPIC_API_KEY=sk-ant-...
# or
OPENAI_API_KEY=sk-...
```

Multi-provider via aisuite. Anthropic (Claude Sonnet) is the recommended and
default provider.

---

## Environment Variables Reference

All variables are set in `~/.zylch/.env` via `zylch init` or manually.

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes (if Anthropic) | Anthropic API key |
| `OPENAI_API_KEY` | Yes (if OpenAI) | OpenAI API key |
| `SYSTEM_LLM_PROVIDER` | No | `anthropic` (default) or `openai` |
| `EMAIL_ADDRESS` | For email | IMAP email address |
| `EMAIL_PASSWORD` | For email | IMAP app password |
| `IMAP_SERVER` | For email | Auto-detected from domain |
| `IMAP_PORT` | For email | Default: 993 |
| `SMTP_SERVER` | For email | Auto-detected from domain |
| `SMTP_PORT` | For email | Default: 587 |
| `TELEGRAM_BOT_TOKEN` | For Telegram | Bot token from @BotFather |
| `TELEGRAM_ALLOWED_USER_ID` | For Telegram | Your numeric Telegram user ID |
| `MRCALL_CLIENT_ID` | For MrCall | OAuth2 client ID |
| `MRCALL_CLIENT_SECRET` | For MrCall | OAuth2 client secret |

---

## Related Documentation

- [Quick Start Guide](quick-start.md) - Initial setup
- [CLI Commands](cli-commands.md) - Command reference
- [Architecture](../ARCHITECTURE.md) - System design

---

**Last Updated**: April 2026
