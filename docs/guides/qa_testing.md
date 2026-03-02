---
description: |
  QA testing guide for Zylch's three components: Backend Server (FastAPI at zylch/), CLI Client
  (thin Python client at zylch-cli/), and Database (Supabase PostgreSQL). Covers test scenarios
  for email sync, calendar integration, AI chat, relationship gap detection, and the core value
  proposition of answering "Who haven't I responded to?" and "What gaps do I have?"
---

# Zylch QA Testing Guide

## 1. Introduction: What is Zylch?

Zylch is an AI-powered relationship intelligence platform that helps users manage their professional relationships by analyzing email and calendar data. It consists of three main components:

- **Backend Server** (`zylch/`): FastAPI server that syncs emails, analyzes relationships, and provides an AI chat interface
- **CLI Client** (`zylch-cli/`): Thin Python client for interacting with the backend via terminal
- **Database** (Supabase): PostgreSQL database storing emails, contacts, OAuth tokens, and relationship analysis

### Core Value Proposition
Zylch answers questions like:
- "Who haven't I responded to?"
- "What relationship gaps do I have?"
- "What meetings need follow-up?"

## 2. Architecture Overview (for testers)

```
┌─────────────────────────────────────────────────────────────────┐
│                         Zylch Architecture                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐     HTTP/JSON      ┌──────────────────────┐   │
│  │  CLI Client  │ ────────────────►  │    FastAPI Backend   │   │
│  │ (zylch-cli)  │                    │      (port 8000)     │   │
│  └──────────────┘                    └───────────┬──────────┘   │
│                                                  │              │
│                                     ┌───────────────────┐       │
│                                     │                   │       │
│                         ┌───────────▼────────┐ ┌────────▼─────┐ │
│                         │   Gmail API        │ │  Supabase    │ │
│                         │   Calendar API     │ │  PostgreSQL  │ │
│                         └────────────────────┘ └──────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow
1. User logs in via CLI → Firebase authentication → Session token stored in `~/.zylch/config.json`
2. User connects Google → OAuth flow:
   - Backend generates OAuth URL with Gmail/Calendar scopes
   - User consents in browser
   - Backend receives authorization code, exchanges for tokens
   - Tokens encrypted with `ENCRYPTION_KEY` and stored in Supabase `oauth_tokens` table (per `owner_id`)
3. User runs `/sync` → Backend:
   - Retrieves encrypted tokens from Supabase
   - Decrypts tokens using `ENCRYPTION_KEY`
   - Fetches emails from Gmail API
   - Stores emails in Supabase `emails` table with `owner_id` (Row-Level Security)
4. Memory Agent processes emails → Extracts facts → Stores in memory blobs
5. Task Agent processes emails → Detects tasks → Stores in `task_items` with sources
6. User runs `/tasks` → Returns tasks sorted by urgency (high → medium → low)

### Key Database Tables
| Table | Purpose |
|-------|---------|
| `emails` | Raw email data (from_email, subject, body_plain, thread_id) |
| `oauth_tokens` | Encrypted OAuth credentials (Google, Microsoft, Anthropic keys) |
| `sync_state` | Tracks last sync history_id for incremental sync |
| `task_items` | Task items with sources JSONB for data traceability |
| `email_triage` | Email priority classification (urgent/normal/low/noise) |
| `scheduled_jobs` | Scheduled reminders and timed actions |
| `blobs` | Vector-based memory storage (pg_vector) |

## 3. Prerequisites

### Required Software
- Python 3.11+
- Node.js 18+ (for Firebase emulator, optional)
- Git
- A Google account with Gmail enabled
- Anthropic API key (get from https://console.anthropic.com/)

### Environment Variables (Backend)
Create `.env` in your zylch directory with:

```bash
# =============================================================================
# REQUIRED: Core Configuration
# =============================================================================

# Supabase (Multi-Tenant Database)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key

# Firebase Authentication
FIREBASE_PROJECT_ID=zylch-dev
FIREBASE_API_KEY=AIzaSy...your-firebase-api-key
FIREBASE_AUTH_DOMAIN=your-project-id.firebaseapp.com
FIREBASE_SERVICE_ACCOUNT_BASE64=base64-encoded-service-account-json

# Google OAuth (System-Level)
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-your-client-secret

# Encryption Key (for OAuth tokens)
ENCRYPTION_KEY=your-fernet-encryption-key

# =============================================================================
# OPTIONAL: Advanced Configuration
# =============================================================================

# Webhook Server (for SendGrid email tracking)
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8000
WEBHOOK_PUBLIC_URL=http://localhost

# CORS Settings (if using web frontend)
CORS_ALLOWED_ORIGINS=http://localhost:8080,http://localhost:3000

# Model Configuration (one model per provider)
ANTHROPIC_MODEL=claude-sonnet-4-20250514
OPENAI_MODEL=gpt-4o
MISTRAL_MODEL=mistral-large-latest
DEFAULT_MODEL=anthropic

# Optional: Log Level
LOG_LEVEL=DEBUG
```

**Notes**:
- **Multi-tenant architecture**: User OAuth tokens stored in Supabase `oauth_tokens` table
- **No more credential files**: `GOOGLE_CREDENTIALS_PATH` and `GOOGLE_APPLICATION_CREDENTIALS` are deprecated
- **Per-user credentials**: Users connect via `/connect google` which stores tokens in database
- **System OAuth**: `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` used for OAuth flow
- **Firebase auth**: Service account now base64-encoded in env var (not file path)
- **Encryption**: `ENCRYPTION_KEY` used to encrypt sensitive data in Supabase

### Environment Variables (CLI)
The CLI auto-configures on first run. Config stored at `~/.zylch/config.json`.

### CLI Profile File
The CLI supports a profile file at `~/.zylch/profile` that runs commands automatically after login (similar to `.bashrc`).

**Default content:**
```bash
# Zylch CLI Profile
# Commands here run at startup (after login)
# Lines starting with # are comments

# Show connection status at startup
/connect
```

**Customization examples:**
```bash
# Always sync on login
/sync

# Show gaps after sync
/gaps

# Model is configured via env vars (ANTHROPIC_MODEL, etc.)
```

The profile runs after successful `/login` and shows output for each command.

## 4. Setup Steps (Local Testing)

**Note on Ports**:
- **Local testing**: Use port `9000` (all examples in this guide)
- **Webhook server**: Defaults to port `8000` (can override with `WEBHOOK_PORT` env var)
- **Production**: Configure via environment variables or Railway/Docker settings

### Step 1: Launch Backend Locally

```bash
# Terminal 1: Start the backend server
cd /path/to/your/zylch
source venv/bin/activate
uvicorn zylch.api.main:app --reload --port 8000
```

**Expected Output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [12345]
INFO:     Started server process [12346]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

**Behind the scenes:**
- FastAPI loads routes from `zylch/api/routes/` (sync.py, chat.py, auth.py, etc.)
- Supabase client initializes connection to PostgreSQL
- Firebase Admin SDK loads for token verification

### Step 2: Enter the CLI

```bash
# Terminal 2: Launch CLI
cd /Users/mal/hb/zylch-cli
source venv/bin/activate
python -m zylch_cli.cli
```

**Expected Output:**
```
✅ Server is running

╭──────────────────────────── Zylch ─────────────────────────────╮
│ Zylch AI Chat                                                  │
│                                                                │
│ Chat with your AI assistant.                                   │
│                                                                │
│ Input:                                                         │
│   Enter          Send message                                  │
│   Ctrl+J         New line                                      │
│   Paste          Multiline text supported                      │
│                                                                │
│ Commands:                                                      │
│   /login     Login to Zylch                                    │
│   /logout    Logout from Zylch                                 │
│   /connect   Connect services                                  │
│   /status    Show connection status                            │
│   /help      Show all commands                                 │
│   /quit      Exit Zylch                                        │
╰────────────────────────────────────────────────────────────────╯

Status:
  ❌ Not logged in → /login
```

**Behind the scenes:**
- CLI reads config from `~/.zylch/config.json`
- Makes health check to `http://localhost:8000/health`
- Initializes prompt_toolkit for interactive input

### Step 3: Login

```
You: /login
```

**Expected Output:**
```
╭──────────────────────────── Login ────────────────────────────╮
│ Zylch CLI Login                                                │
│                                                                │
│ Your browser will open for authentication.                     │
│ Please sign in and authorize the application.                  │
╰────────────────────────────────────────────────────────────────╯
```

Browser opens → Sign in with Google → Redirect back

```
✅ Logged in as yourname@gmail.com

Running profile...
Zylch: [shows connection status from /connect]
```

**Behind the scenes:**
1. CLI starts local callback server on port 8765
2. Opens browser to `http://localhost:8000/api/auth/login?cli_callback=http://localhost:8765`
3. Backend redirects to Firebase auth
4. User signs in with Google
5. Backend receives Firebase token, generates session
6. Callback returns to CLI with session token
7. CLI stores token in `~/.zylch/config.json`
8. CLI runs `~/.zylch/profile` commands (default: `/connect`)

### Step 4: Try to Sync (WILL FAIL)

```
You: /sync
```

**Expected Error:**
```
Running /sync...

Zylch: ❌ Gmail not configured. Please authenticate with Google first via /connect google.
```

**Why it fails:**
- Firebase login authenticates you to Zylch
- But Gmail API requires separate OAuth consent
- No Google OAuth token exists in `oauth_tokens` table yet

### Step 5: Connect Services

```
You: /connect
```

**Expected Output:**
```
╭────────────────────── Integrations ───────────────────────────╮
│ Your Connections                                               │
│                                                                │
│ Use /connect {provider} to connect                             │
│                                                                │
│ ❌ Available (Not Connected):                                  │
│ 1. Google (Gmail + Calendar)  [google]                         │
│ 2. Microsoft (Outlook)  [microsoft]                            │
│ 3. Anthropic AI  [anthropic]                                   │
│                                                                │
│ ⏳ Coming Soon:                                                │
│ 4. Vonage SMS  [vonage]                                        │
│ 5. Pipedrive CRM  [pipedrive]                                  │
╰────────────────────────────────────────────────────────────────╯
```

**Connect Google:**
```
You: /connect google
```

Browser opens → Select Google account → Grant Gmail/Calendar permissions

**Expected Output:**
```
✅ Google connected successfully!
Connected as: yourname@gmail.com

You can now sync your Gmail and Calendar.
```

**Connect Anthropic (required for AI chat):**
```
You: /connect anthropic
```

```
╭────────────────── Anthropic API Key ──────────────────────────╮
│ Connect Anthropic API                                          │
│                                                                │
│ Zylch uses Claude AI for chat. You need your own API key.      │
│                                                                │
│ Get your API key at: https://console.anthropic.com/            │
╰────────────────────────────────────────────────────────────────╯

Enter your Anthropic API key: sk-ant-api...

✅ Anthropic API key saved!
```

**Behind the scenes:**
- Google OAuth: Backend generates authorization URL with Gmail/Calendar scopes
- User consents → Google returns authorization code
- Backend exchanges code for tokens
- Tokens encrypted and stored in `oauth_tokens.credentials` (JSONB)
- Anthropic key stored similarly with `provider='anthropic'`

### Step 6: Run Sync Successfully

```
You: /sync
```

**Expected Output:**
```
Running /sync...

Zylch: ✅ Sync complete!

📧 Emails: 127 new emails synced (30 days)
📅 Calendar: 23 events synced (60 days)
👥 Contacts: 45 unique contacts found

Memory Agent processing 127 emails...
  - Extracted 12 phone numbers
  - Extracted 8 LinkedIn profiles

⏱ 12.3s total (11.8s server)
```

**Behind the scenes:**
1. `SyncService.run_full_sync()` called
2. `GmailClient.sync_emails()`:
   - Checks `sync_state` table for last `history_id`
   - If first sync: fetches last 30 days of emails
   - If incremental: uses Gmail history API for changes since last sync
   - Emails stored in `emails` table with `owner_id` scope
3. `GoogleCalendarClient.sync_events()`:
   - Fetches events from primary calendar (last 30 days, next 60 days)
   - Stored in `calendar_events` table
4. Memory Agent processes new emails:
   - Uses regex to extract phone numbers (US: `(555) 123-4567`, international: `+44 20 7946 0958`)
   - Uses regex to extract LinkedIn URLs (`linkedin.com/in/username`)
   - Creates entries in `identifier_map` table
   - Optionally uses LLM to extract relationship context

**Verify in database (via Supabase dashboard or SQL):**

```sql
-- Check emails were synced
SELECT COUNT(*) as email_count FROM emails WHERE owner_id = 'YOUR_OWNER_ID';
-- Expected: > 0

-- Check sync state updated
SELECT * FROM sync_state WHERE owner_id = 'YOUR_OWNER_ID';
-- Expected: history_id populated, last_sync recent

-- Check identifiers extracted
SELECT * FROM identifier_map WHERE owner_id = 'YOUR_OWNER_ID' LIMIT 10;
-- Expected: Rows with identifier_type = 'email', 'phone', or 'linkedin'
```

### Step 7: View Memory

```
You: /memory --list
```

**Expected Output:**
```
Zylch: Your behavioral memories:

📝 Contacts (12 entries)
  - john.doe@example.com: Phone +15551234567, LinkedIn linkedin.com/in/johndoe
  - jane.smith@acme.co: discussing project collaboration
  ...

📝 Relationships (8 entries)
  - john.doe@example.com: "Working on Q4 partnership"
  - jane.smith@acme.co: "follow-up meeting scheduled"
  ...
```

**Behind the scenes:**
- Memory entries stored in `zylch_memory` table (using ZylchMemory class)
- Phone/LinkedIn from `identifier_map`
- Relationship context from Memory Agent's LLM extraction

### Step 8: View Gaps (Action Items)

```
You: /gaps
```

**Expected Output:**
```
Zylch: 📋 Relationship Gaps Analysis

🔴 Email Tasks (3 items):
1. John Doe (john.doe@example.com)
   - 2 threads awaiting response
   - Last interaction: 5 days ago
   - Action: Reply to partnership proposal

2. Jane Smith (jane.smith@acme.co)
   - 1 thread awaiting response
   - Last interaction: 3 days ago
   - Action: Confirm meeting time

🟡 Meeting Follow-ups (2 items):
1. Mike Johnson - Project Review (2 days ago)
   - No follow-up email sent after meeting
   - Action: Send meeting notes

🟠 Silent Contacts (1 item):
1. Sarah Williams (sarah@startup.io)
   - 15 total interactions, 12 days silent
   - Action: Check in on project status
```

**Behind the scenes:**
1. `GapService.analyze_gaps()` called
2. `RelationshipAnalyzer.analyze_all_gaps()`:
   - Queries `task_items` for tasks with action required
   - Queries `calendar_events` for external meetings without follow-up emails within 48 hours
   - Queries `emails` for contacts with high interaction count but no recent activity
3. Results stored in `relationship_gaps` table
4. Formatted and returned to CLI

**Verify in database:**

```sql
-- Check gaps were created
SELECT gap_type, contact_email, details, priority
FROM relationship_gaps
WHERE owner_id = 'YOUR_OWNER_ID' AND resolved_at IS NULL
ORDER BY priority DESC;
```

## 5. Manual Worker Testing (Production = Cron)

In production, the Memory Agent runs as a cron job. For testing, run manually:

```bash
# Terminal 3: Run Memory Agent manually
cd /Users/mal/hb/zylch
source venv/bin/activate

# Process unprocessed emails for a specific user
python -c "
import asyncio
from zylch.workers.memory_worker import MemoryWorker
from zylch.storage.supabase_client import SupabaseStorage
from zylch_memory.zylch_memory import ZylchMemory

async def run():
    storage = SupabaseStorage.get_instance()
    memory = ZylchMemory()
    worker = MemoryWorker(storage, memory)

    # Get unprocessed emails
    emails = storage.get_unprocessed_emails('YOUR_OWNER_ID', limit=10)
    print(f'Found {len(emails)} unprocessed emails')

    for email in emails:
        await worker.process_email(email['id'], 'YOUR_OWNER_ID')

asyncio.run(run())
"
```

**Expected Output:**
```
Found 10 unprocessed emails
INFO:zylch.workers.memory_worker:Processing email abc123 for owner xyz789
INFO:zylch.workers.memory_worker:Extracted phones from email abc123: ['+15551234567']
INFO:zylch.workers.memory_worker:Stored phone identifier: +15551234567 -> contact_def456
...
```

## 6. Test Scenarios

### Scenario 1: New Email Arrives

**Setup:**
1. Send yourself a test email from another account
2. Run `/sync`

**Expected:**
- New email appears in `emails` table
- If email contains phone/LinkedIn, entries created in `identifier_map`
- Thread analysis updated if reply expected

**Verification:**
```sql
SELECT gmail_id, from_email, subject, snippet
FROM emails
WHERE owner_id = 'YOUR_OWNER_ID'
ORDER BY date_timestamp DESC
LIMIT 5;
```

### Scenario 2: Phone Number in Email

**Setup:**
1. Send yourself an email containing: "My number is (555) 123-4567"
2. Run `/sync`
3. Check memory

**Expected:**
```
You: /memory --list
```
Should show: `Phone: +15551234567` associated with sender's contact

**Verification:**
```sql
SELECT identifier, identifier_type, contact_id, confidence
FROM identifier_map
WHERE owner_id = 'YOUR_OWNER_ID'
AND identifier_type = 'phone';
-- Expected: +15551234567 with confidence 0.9
```

### Scenario 3: LinkedIn URL in Email

**Setup:**
1. Send yourself an email containing: "Connect with me: linkedin.com/in/testuser"
2. Run `/sync`

**Expected:**
`identifier_map` contains LinkedIn URL normalized to `linkedin.com/in/testuser`

**Verification:**
```sql
SELECT identifier, identifier_type, contact_id, confidence
FROM identifier_map
WHERE owner_id = 'YOUR_OWNER_ID'
AND identifier_type = 'linkedin';
-- Expected: linkedin.com/in/testuser with confidence 1.0
```

### Scenario 4: Task Status Changes

**Setup:**
1. Have an email thread with action required
2. Run `/sync` and `/agent task process email`
3. Run `/tasks`

**Expected:**
- Task appears sorted by urgency
- Task shows action_required = true

**Verification:**
```sql
SELECT id, email_id, urgency, suggested_action, action_required
FROM task_items
WHERE owner_id = 'YOUR_OWNER_ID'
ORDER BY urgency;
```

## 7. Email Read Tracking Tests

Email read tracking enables Zylch to detect when recipients open emails, providing intelligence for follow-up timing. There are two tracking methods:

1. **SendGrid Webhooks** (PRIMARY) - For batch emails sent via SendGrid
2. **Custom Tracking Pixel** (SECONDARY) - For individual emails

### Scenario 1: SendGrid Webhook Email Tracking

**Goal**: Verify SendGrid webhook correctly records email open event

**Setup:**

1. **Simulate SendGrid webhook** (testing without actual SendGrid):
   ```bash
   curl -X POST http://localhost:9000/api/webhooks/sendgrid \
     -H "Content-Type: application/json" \
     -H "X-Twilio-Email-Event-Webhook-Timestamp: 1702389000" \
     -H "X-Twilio-Email-Event-Webhook-Signature: test_sig" \
     -d '[{
       "event": "open",
       "email": "recipient@test.com",
       "sg_message_id": "sendgrid_test_abc123",
       "timestamp": 1702389000,
       "useragent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0)",
       "ip": "192.168.1.1"
     }]'
   ```

**Expected Output:**
```json
{"status": "success", "processed": 1, "total": 1}
```

**Behind the scenes:**
1. Webhook handler receives SendGrid event
2. Looks up `sendgrid_message_id` in `sendgrid_message_mapping` table
3. If mapping exists, records read event in `email_read_events`
4. Updates `emails.read_events` JSONB column with summary

**Verification - Check read event recorded:**
```sql
SELECT
    sendgrid_message_id,
    recipient_email,
    tracking_source,
    read_count,
    first_read_at,
    last_read_at,
    user_agents,
    ip_addresses
FROM email_read_events
WHERE owner_id = 'YOUR_OWNER_ID'
AND tracking_source = 'sendgrid_webhook'
ORDER BY created_at DESC
LIMIT 5;
```

**Expected Result:**
```
sendgrid_message_id    | recipient_email    | tracking_source  | read_count | first_read_at       | last_read_at        | user_agents                           | ip_addresses
-----------------------|--------------------|------------------|-----------|---------------------|---------------------|---------------------------------------|-------------
sendgrid_test_abc123   | recipient@test.com | sendgrid_webhook | 1         | 2025-12-12 10:30:00 | 2025-12-12 10:30:00 | {Mozilla/5.0 (iPhone...)}            | {192.168.1.1}
```

**Verification - Check mapping table:**
```sql
SELECT
    sendgrid_message_id,
    message_id,
    recipient_email,
    created_at
FROM sendgrid_message_mapping
WHERE owner_id = 'YOUR_OWNER_ID'
ORDER BY created_at DESC
LIMIT 3;
```

**Notes:**
- SendGrid signature verification can be bypassed in development (set `SENDGRID_WEBHOOK_PUBLIC_KEY` to empty)
- In production, webhook signature must be valid (ECDSA verification)
- Webhook typically arrives within 1-5 seconds of email open
- Multiple opens increment `read_count` and update `last_read_at`

### Scenario 2: Custom Tracking Pixel

**Goal**: Verify custom tracking pixel records email opens

**Setup:**

1. **Simulate pixel load** (as if recipient opened email):
   ```bash
   curl -i "http://localhost:9000/api/track/pixel/owner123_msg456_abc123_xyz789" \
     -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
   ```

**Expected Response:**
```
HTTP/1.1 200 OK
Content-Type: image/gif
Content-Length: 43
Cache-Control: no-store, no-cache, must-revalidate
Pragma: no-cache
Expires: 0

R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7
(Base64-encoded 1x1 transparent GIF)
```

**Behind the scenes:**
1. Pixel endpoint extracts `tracking_id` from URL
2. Parses tracking ID to get `owner_id`, `message_id`, recipient
3. Records read event in `email_read_events` table
4. Returns 1x1 transparent GIF (43 bytes)
5. Processing happens in background task (non-blocking)

**Verification - Check read event recorded:**
```sql
SELECT
    tracking_id,
    message_id,
    recipient_email,
    tracking_source,
    read_count,
    first_read_at,
    last_read_at,
    user_agents
FROM email_read_events
WHERE tracking_source = 'custom_pixel'
AND owner_id = 'YOUR_OWNER_ID'
ORDER BY created_at DESC
LIMIT 1;
```

**Expected Result:**
```
tracking_id                      | message_id | recipient_email    | tracking_source | read_count | first_read_at       | last_read_at        | user_agents
---------------------------------|------------|--------------------|-----------------|-----------|--------------------|---------------------|--------------
owner123_msg456_abc123_xyz789    | msg456     | recipient@test.com | custom_pixel    | 1         | 2025-12-12 11:00:00 | 2025-12-12 11:00:00 | {Mozilla/5.0...}
```

**Notes:**
- Pixel format: `{owner_id}_{message_id}_{random_8chars}_{random_6chars}`
- Cache headers prevent caching to ensure accurate read tracking
- Some email clients block images - pixel won't load in those cases
- Privacy: IP addresses not collected by default for custom pixels

### Scenario 3: Read Tracking in /gaps Command

**Goal**: Verify read indicators appear in relationship gaps

**Setup:**

1. **Create test read event** (use Scenario 1 or 2 above)

2. **Create test email with read_events** (simulating what the system does):
   ```sql
   -- Insert test email
   INSERT INTO emails (id, owner_id, from_email, to_email, subject, date, date_timestamp, read_events)
   VALUES (
     'test_msg_001',
     'YOUR_OWNER_ID',
     'you@example.com',
     'john.doe@example.com',
     'Partnership Proposal',
     '2025-12-08',
     '2025-12-08 10:00:00',
     '[{"recipient":"john.doe@example.com","read_count":2,"first_read_at":"2025-12-08T10:30:00Z","last_read_at":"2025-12-10T14:00:00Z"}]'::jsonb
   );
   ```

3. **Run gaps command:**
   ```
   You: /gaps
   ```

**Expected Output:**
```
Zylch: 📋 Relationship Gaps Analysis

🔴 Email Tasks (2 items):
1. John Doe (john.doe@example.com) 📧✓ (read 4d ago)
   - Last interaction: 5 days ago
   - Action: Follow up on partnership proposal

2. Jane Smith (jane@company.com) 📧❌ (unread 7d)
   - Last interaction: 7 days ago
   - Action: Gentle reminder - they haven't read yet
```

**Behind the scenes:**
- Read events stored in `emails.read_events` JSONB
- Task system can use read status to inform urgency decisions
- Display indicators:
  - `📧❌ (unread Xd)` - Email sent X days ago, not opened
  - `📧✓ (read Xd ago)` - Email was opened X days ago

**Verification - Check emails.read_events JSONB:**
```sql
SELECT
    id,
    from_email,
    to_email,
    subject,
    date,
    read_events
FROM emails
WHERE owner_id = 'YOUR_OWNER_ID'
AND read_events IS NOT NULL
AND read_events != '[]'::jsonb
ORDER BY date_timestamp DESC
LIMIT 3;
```

**Expected Result:**
```
id          | from_email        | to_email              | subject              | date       | read_events
------------|-------------------|-----------------------|----------------------|------------|----------------------------------------------------------
test_msg_001| you@example.com   | john.doe@example.com  | Partnership Proposal | 2025-12-08 | [{"recipient":"john.doe@example.com","read_count":2,...}]
```

### Scenario 4: Test Data Cleanup

**After testing, clean up test data:**

```sql
-- WARNING: Only run in development/testing environment

-- Delete test read events
DELETE FROM email_read_events
WHERE owner_id = 'YOUR_OWNER_ID'
AND (
    message_id LIKE 'test_%'
    OR created_at > NOW() - INTERVAL '1 hour'
);

-- Delete test mappings
DELETE FROM sendgrid_message_mapping
WHERE owner_id = 'YOUR_OWNER_ID'
AND (
    message_id LIKE 'test_%'
    OR created_at > NOW() - INTERVAL '1 hour'
);

-- Clear read_events from test emails
UPDATE emails
SET read_events = '[]'::jsonb
WHERE owner_id = 'YOUR_OWNER_ID'
AND (
    id LIKE 'test_%'
    OR date > NOW() - INTERVAL '1 hour'
);

-- Delete test emails
DELETE FROM emails
WHERE owner_id = 'YOUR_OWNER_ID'
AND id LIKE 'test_%';

-- Verify cleanup
SELECT 'email_read_events' as table_name, COUNT(*) as remaining
FROM email_read_events
WHERE owner_id = 'YOUR_OWNER_ID' AND message_id LIKE 'test_%'
UNION ALL
SELECT 'sendgrid_message_mapping', COUNT(*)
FROM sendgrid_message_mapping
WHERE owner_id = 'YOUR_OWNER_ID' AND message_id LIKE 'test_%'
UNION ALL
SELECT 'emails', COUNT(*)
FROM emails
WHERE owner_id = 'YOUR_OWNER_ID' AND id LIKE 'test_%';
-- Expected: All zeros
```

## 8. Troubleshooting

### Issue: /sync returns 0 emails

**Symptoms:**
```
Zylch: ✅ Sync complete!
📧 Emails: 0 new emails synced
```

**Possible Causes & Solutions:**

1. **No new emails since last sync:**
   - Check `sync_state.history_id` - if set, only fetches changes
   - Force full sync: `/sync --full` (not implemented yet - delete sync_state row)

2. **Gmail API quota exhausted:**
   - Check Google Cloud Console for API usage
   - Wait 24 hours for quota reset

3. **Token expired:**
   ```
   You: /connect google
   ```
   Re-authenticate with Google

**Debug:**
```sql
SELECT * FROM sync_state WHERE owner_id = 'YOUR_OWNER_ID';
-- Check last_sync and history_id
```

### Issue: No identifiers in identifier_map

**Symptoms:**
Emails synced but no phone/LinkedIn extracted

**Possible Causes:**

1. **Memory Agent hasn't run:**
   - In local testing, Memory Agent doesn't auto-run
   - Run manually (see Section 5)

2. **Emails don't contain identifiers:**
   - Check email content for phone patterns
   - Memory Agent uses regex, not AI, for extraction

3. **Regex patterns don't match:**
   - US phones: `(555) 123-4567`, `555-123-4567`, `+15551234567`
   - LinkedIn: `linkedin.com/in/username` or `linkedin.com/pub/username`

**Debug:**
```sql
-- Check if emails have body content
SELECT id, from_email, body_plain, snippet
FROM emails
WHERE owner_id = 'YOUR_OWNER_ID'
AND (body_plain LIKE '%555%' OR body_plain LIKE '%linkedin%')
LIMIT 5;
```

### Issue: No tasks in task_items table

**Symptoms:**
Emails are synced but `/tasks` shows nothing

**Cause:**
Task processing runs separately from sync

**Solution:**
Run `/agent task process email` after sync to detect tasks from emails.

### Issue: /gaps shows nothing

**Symptoms:**
```
Zylch: 📋 No relationship gaps found.
```

**Possible Causes:**

1. **No sync yet:**
   - Run `/sync` first

2. **No actionable threads:**
   - All threads are responded to
   - No meetings without follow-up

3. **Gap analysis not run:**
   - `/gaps` triggers analysis
   - Check `relationship_gaps` table

**Debug:**
```sql
-- Check task items with action required
SELECT id, contact_email, action_required, urgency, suggested_action
FROM task_items
WHERE owner_id = 'YOUR_OWNER_ID'
AND action_required = true;

-- Check if gaps were stored
SELECT * FROM relationship_gaps WHERE owner_id = 'YOUR_OWNER_ID';
```

## 9. Performance Benchmarks

### Expected Timings

| Operation | First Run | Incremental |
|-----------|-----------|-------------|
| `/sync` (100 emails) | 10-15s | 2-5s |
| `/sync` (1000 emails) | 60-90s | 5-10s |
| `/gaps` | 5-10s | 2-5s |
| Memory Agent (per email) | 50-100ms | N/A |

### Expected Costs (per sync)

| Component | Cost |
|-----------|------|
| Gmail API | Free (quota-limited) |
| Supabase DB | ~$0.01 per 1000 rows |
| LLM (relationship context) | depends on model |
| LLM (gap analysis) | depends on model |

## 10. Success Criteria

After testing, you should be able to:

- [ ] Start the backend server without errors
- [ ] Launch the CLI and see "Server is running"
- [ ] Login via browser OAuth flow
- [ ] Connect Google account successfully
- [ ] Connect Anthropic API key
- [ ] Run `/sync` and see emails synced
- [ ] Run `/memory --list` and see extracted contacts
- [ ] Run `/gaps` and see relationship gaps (if any exist)
- [ ] Query Supabase and verify data in tables:
  - `emails` has rows with your `owner_id`
  - `oauth_tokens` has encrypted Google credentials
  - `sync_state` has last sync timestamp
  - `identifier_map` has email/phone/LinkedIn entries
- [ ] Chat with AI about your emails: "Who do I need to respond to?"

## 11. Common Commands Reference

| Command | Description |
|---------|-------------|
| `/login` | Authenticate with Firebase |
| `/logout` | Clear session |
| `/connect` | Show connected services |
| `/connect google` | Connect Gmail/Calendar |
| `/connect anthropic` | Set Anthropic API key |
| `/connect --reset` | Disconnect all services |
| `/sync` | Sync emails and calendar |
| `/sync 7` | Sync last 7 days only |
| `/gaps` | Show relationship gaps |
| `/memory --list` | Show extracted memories |
| `/memory --stats` | Show memory statistics |
| `/status` | Show CLI connection status |
| `/help` | Show all commands |
| `/quit` | Exit CLI |

## 12. Backend API Endpoints (for API testing)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | No | Health check |
| `/api/auth/login` | GET | No | Initiate OAuth login |
| `/api/sync/start` | POST | Yes | Start full sync |
| `/api/sync/emails` | POST | Yes | Sync emails only |
| `/api/sync/calendar` | POST | Yes | Sync calendar only |
| `/api/sync/status` | GET | Yes | Get sync status |
| `/api/chat/message` | POST | Yes | Send chat message |
| `/api/connections/status` | GET | Yes | Get connected services |

**Example cURL:**
```bash
# Health check
curl http://localhost:8000/health

# Start sync (requires auth token)
curl -X POST http://localhost:8000/api/sync/start \
  -H "Authorization: Bearer YOUR_FIREBASE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"days": 30}'
```

---

*Last updated: 2024-12*
*Zylch version: 1.0.0*
