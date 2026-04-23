---
description: |
  Email archive system: IMAP incremental sync to SQLite, FTS search,
  thread grouping. All emails preserved locally. <1 second daily sync.
---

# Email Archive System

**Status**: Working (standalone)

## Overview

Complete email archiving system with IMAP incremental sync, full-text search, and thread grouping. Emails stored permanently in SQLite.

### Key Features
- **Incremental sync**: IMAP SINCE-based sync, fast daily updates
- **Full-text search**: SQLite FTS (LIKE fallback for person names)
- **Complete history**: All emails preserved locally
- **Auto-sync**: Triggers on first chat message if last sync >24h

## Architecture

```
IMAP Server (Gmail, Outlook, Yahoo, iCloud)
     │
     ▼
Email Archive Manager (zylch/tools/email_archive.py)
  • Initial sync: fetch N months (one-time)
  • Incremental sync: IMAP SINCE date
  • Auto-detect IMAP/SMTP server from email domain
     │
     ▼
SQLite (~/.zylch/zylch.db)
  • emails table with FTS index
  • Thread grouping via thread_id
  • Embeddings for semantic search
```

## Usage

```bash
# Sync emails via IMAP
zylch sync

# In interactive chat
/sync              # Full sync
/email search <query>  # Search archived emails
```

## Configuration

All via `~/.zylch/.env` (set up by `zylch init`):

```bash
EMAIL_ADDRESS=user@gmail.com
EMAIL_PASSWORD=xxxx-xxxx-xxxx-xxxx  # App password
IMAP_SERVER=imap.gmail.com          # Auto-detected
SMTP_SERVER=smtp.gmail.com          # Auto-detected
```

## Auto-Detect Presets

The IMAP client auto-detects server settings from email domain:

| Provider | IMAP Server | SMTP Server |
|----------|-------------|-------------|
| Gmail | imap.gmail.com:993 | smtp.gmail.com:587 |
| Outlook | outlook.office365.com:993 | smtp.office365.com:587 |
| Yahoo | imap.mail.yahoo.com:993 | smtp.mail.yahoo.com:587 |
| iCloud | imap.mail.me.com:993 | smtp.mail.me.com:587 |

## Search

Two search modes:
- **FTS**: SQLite full-text search on subject, body, snippet
- **LIKE fallback**: For person name queries (from_name, from_email)

## Performance

- **Incremental sync**: seconds (SINCE-based, only new emails)
- **Search**: <100ms (FTS index)
- **Storage**: ~5 MB per 500 emails

## Files

| File | Purpose |
|------|---------|
| `zylch/email/imap_client.py` | IMAP/SMTP client with auto-detect |
| `zylch/tools/email_archive.py` | Archive manager (sync, search) |
| `zylch/tools/email_sync.py` | EmailSyncManager (incremental sync) |
| `zylch/tools/email_sync_tools.py` | LLM tool definitions for email sync |
| `zylch/tools/gmail_tools.py` | Email search/draft/send tools |
