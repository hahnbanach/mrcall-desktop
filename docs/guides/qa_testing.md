# Zylch QA Testing Guide

**Target Audience**: New programmer hired to test Zylch (knows NOTHING about the product)

**Purpose**: This guide provides step-by-step instructions for testing Zylch's full functionality, from setup to production validation.

---

## 1. Introduction: What is Zylch?

Zylch is an AI-powered relationship intelligence system that helps professionals manage email communications and relationships. It uses a **Von Neumann Memory Architecture** where emails flow through two AI agents:

**Core Data Flow**:
```
Communication Channel (Email for now) → Memory Agent → Memory → CRM Agent → Avatar
```

1. **Memory Agent**: Extracts contact identifiers (phone numbers, LinkedIn URLs) from emails and stores them in structured memory
2. **CRM Agent**: Computes relationship status, priority scores, and suggested actions for each contact
3. **Avatar**: The final computed view of a contact with all relationship intelligence

**Key Concept**: Zylch treats contacts as "avatars" - intelligent representations that aggregate all communication history and compute actionable insights.

---

## 2. Architecture Overview (for testers)

### System Components

**Backend**:
- **Technology**: Python FastAPI server
- **Location**: `/Users/mal/hb/zylch/`
- **Port**: 8000 (default)
- **Entry Point**: `zylch/api/main.py`

**CLI**:
- **Technology**: Python interactive shell (thin client)
- **Location**: `/Users/mal/hb/zylch-cli/`
- **Entry Point**: `./zylch` (bash launcher script)
- **Communication**: HTTP API to backend

**Database**: Supabase (PostgreSQL)

**Key Tables**:
- `emails` - Email archive (from Gmail API)
- `identifier_map` - Contact identifiers (Memory: phone, email, LinkedIn)
- `avatars` - Computed relationship intelligence (volatile view)
- `oauth_tokens` - OAuth credentials (encrypted)
- `sync_state` - Sync history tracking

**Workers** (Background Agents):
- **Memory Worker**: Processes unprocessed emails → extracts identifiers → stores in `identifier_map` + ZylchMemory
- **CRM Worker**: Computes avatars for affected contacts → stores in `avatars` table

**Production Mode**: Workers run on cron (every 5-10 minutes)

**Testing Mode**: Workers run manually (see Section 5)

---

## 3. Prerequisites

Before testing, ensure you have:

- **Python 3.10+** installed
- **Supabase account** with database set up
- **Google OAuth credentials** (Gmail API access)
- **Anthropic API key** (Claude access)
- **Git** for repository access

---

## 4. Setup Steps (Local Testing)

### Step 1: Launch Backend Locally

```bash
# Navigate to backend directory
cd /Users/mal/hb/zylch

# Activate virtual environment
source .venv/bin/activate  # or venv/bin/activate

# Install dependencies (first time only)
pip install -e .

# Set up environment variables
# Create .env file with:
# ANTHROPIC_API_KEY=sk-ant-...
# SUPABASE_URL=https://your-project.supabase.co
# SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
# GOOGLE_CREDENTIALS_PATH=credentials/google_oauth.json

# Start the backend server
uvicorn zylch.api.main:app --reload --port 8000 --host 0.0.0.0
```

**Expected Output**:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

**Verify Backend Running**:
```bash
curl http://localhost:8000/health
# Should return: {"status":"healthy"}
```

---

### Step 2: Enter the CLI

Open a **NEW terminal window**:

```bash
# Navigate to CLI directory
cd /Users/mal/hb/zylch-cli

# Activate CLI virtual environment
source venv/bin/activate

# Launch CLI
./zylch
# OR
python -m zylch_cli.cli
```

**Expected Output**:
```
Welcome to Zylch CLI
Type /help for commands
>
```

---

### Step 3: Login

**Authentication Flow**:
1. CLI needs a Firebase UID (owner_id) to access multi-tenant data
2. In test mode, you can use a test UID or your Firebase token
3. Token is stored in `~/.zylch/cli_config.json`

```bash
# In CLI prompt
> /login

# Paste your Firebase token when prompted
# (Get from backend logs or Firebase console)
# Token format: eyJhbGciOiJSUzI1NiIsImtpZCI6Ij...
```

**Expected Output**:
```
✅ Login Successful
Owner ID: firebase_uid_abc123
```

Session with tokens is saved to ~/.zylch/cli_config.json

**What Happens Behind the Scenes**:
1. CLI sends token to backend `/api/auth/login`
2. Backend validates token with Firebase
3. Backend returns `owner_id` (Firebase UID)
4. CLI stores `owner_id` + `session_token` locally
5. All subsequent API calls include this session token

**Alternative (For Testing)**:
If you don't have Firebase set up, you can manually edit `~/.zylch/cli_config.json`:
```json
{
  "owner_id": "test_owner_123",
  "session_token": "test_session_token",
  "server_url": "http://localhost:8000"
}
```

---

### Step 4: Try to Sync (WILL FAIL)

```bash
> /sync
```

**Expected Error**:
```
❌ Error: Gmail not connected
Please connect your Gmail account first.
```

**Why It Fails**:
- Backend needs Gmail OAuth token to fetch emails
- Token is stored in Supabase `oauth_tokens` table (unified `credentials` JSONB column)
- Must complete OAuth flow first

---

### Step 5: Connect Gmail

```bash
> /connect google
```

**OAuth Flow** (December 2025 - Secure CLI Flow):

1. **CLI Spawns Local Callback Server**:
   - CLI starts temporary HTTP server on random port (e.g., `http://localhost:8766/callback`)
   - This receives the OAuth redirect after authentication

2. **Browser Opens Automatically**:
   - CLI opens Google OAuth consent screen in your browser
   - URL includes CSRF protection state token stored in `oauth_states` database table
   - State token is unique per session and expires after 10 minutes

3. **Grant Permissions**:
   - Select your Gmail account
   - Grant permissions: "Read email", "Send email", "Modify drafts", "Read/write calendar"
   - Click "Allow"

4. **Callback Flow**:
   ```
   Google redirects → Backend /api/auth/google/callback
                   ↓
   Backend validates state token (CSRF protection)
                   ↓
   Backend exchanges authorization code for tokens
                   ↓
   Backend saves to oauth_tokens.credentials JSONB (encrypted)
                   ↓
   Backend redirects → CLI local callback server
                   ↓
   CLI displays success message
   ```

5. **Expected Output**:
   ```
   ✅ Google connected successfully!
   Connected as: your.email@gmail.com

   You can now sync your Gmail and Calendar.
   ```

6. **Verify Connection**:
   ```bash
   # In CLI
   > /connect
   ```

   **Expected Output**:
   ```
   ╭─────────────────── Integrations ───────────────────╮
   │ Your Connections                                   │
   │                                                    │
   │ ✅ Connected:                                      │
   │ 1. Google (Gmail & Calendar) - your.email@gmail.com│
   │                                                    │
   │ ❌ Available (Not Connected):                      │
   │ 2. Anthropic API (BYOK)  [anthropic]               │
   │ 3. Microsoft (Outlook & Calendar)  [microsoft]     │
   │ ...                                                │
   ╰────────────────────────────────────────────────────╯
   ```

**What Gets Stored**:
- Table: `oauth_tokens`
- Provider: `google` (short key matching `integration_providers.provider_key`)
- Credentials: JSONB column with encrypted token data:
  ```json
  {
    "google": {
      "token_data": "base64_pickled_google_credentials",
      "provider": "google",
      "email": "your.email@gmail.com"
    }
  }
  ```
- Encryption: Entire JSONB encrypted with Fernet before storage

**Security Features**:
- ✅ CSRF protection via database-backed state tokens
- ✅ Multi-instance safe (state stored in Supabase, not memory)
- ✅ One-time use state tokens (auto-deleted after validation)
- ✅ Encrypted credential storage (Fernet AES-128-CBC + HMAC)
- ✅ No credentials in URL (only `token=success` in redirect)

---

### Step 6: Run Sync Successfully

```bash
# Sync last 7 days
> /sync 7
```

**What Happens Behind the Scenes**:

1. **Email Sync** (`sync_service.run_full_sync()` in `zylch/services/sync_service.py:365`)
   - Backend calls Gmail API: `gmail.users().messages().list()`
   - Fetches emails from last 7 days
   - For each email:
     - Parses headers: From, To, Cc, Subject, Date
     - Extracts body (plain text + HTML)
     - Generates unique `gmail_id` and `thread_id`
   - Stores in `emails` table (Supabase)
   - Returns count: `+X new, -Y deleted`

2. **Memory Agent Phase** (automatically runs after email sync):
   - **Goal**: Extract contact identifiers from email content
   - **Process**:
     a. Query `emails` table for unprocessed emails (see `get_unprocessed_emails` in `supabase_client.py:1565`)
     b. For each email:
        - **Phone Extraction**: Regex patterns for US/international phones (see `extract_phone_numbers` in `memory_worker.py:49`)
          - Patterns: `(555) 123-4567`, `+1-555-123-4567`, `+44 20 7946 0958`
          - Normalize to E.164 format: `+15551234567`
        - **LinkedIn Extraction**: Regex for LinkedIn URLs (see `extract_linkedin_urls` in `memory_worker.py:123`)
          - Pattern: `linkedin.com/in/username`
          - Normalize to: `linkedin.com/in/username`
        - **Relationship Context** (OPTIONAL): Use Claude Haiku to extract 1-sentence summary (see `_extract_relationship_context` in `memory_worker.py:464`)
     c. Store identifiers in TWO places:
        - **`identifier_map` table**: Fast O(1) lookup (owner_id, identifier, identifier_type, contact_id, confidence)
        - **ZylchMemory**: Semantic memory with vector embeddings (namespace: `contact:{contact_id}`)
   - **Time**: ~8-10 seconds for 10 emails
   - **Cost**: ~$0.001 (Haiku only for relationship context)

3. **CRM Agent Phase** (runs after Memory Agent):
   - **Goal**: Compute avatar intelligence for affected contacts
   - **Process**:
     a. Query `identifier_map` for unique `contact_id`s from recent emails
     b. For each contact:
        - Get recent email threads (last 30 days)
        - Determine **status**:
          - `open`: Contact sent last email (you need to respond)
          - `waiting`: You sent last email (waiting for their response)
          - `closed`: Conversation marked as complete or no response pattern
        - Calculate **priority** (1-10 score):
          - Urgency component: Based on days since last contact (>7 days = +4, >3 days = +2)
          - Importance component: Relationship strength (email volume) + topic importance
          - Formula: `min(10, max(1, 2 + urgency + importance))`
        - Generate **suggested action** using Claude Haiku (see `_generate_action` in `crm_worker.py:227`):
          - Max 80 characters
          - Specific, actionable (not vague "follow up")
        - Get **display name** from memory patterns or email
        - Build **relationship summary** from memory context
     c. Store avatar in `avatars` table (owner_id, contact_id, display_name, relationship_status, relationship_score, suggested_action, etc.)
   - **Time**: ~4-6 seconds for 5 contacts
   - **Cost**: ~$0.001 (Haiku for action generation)

4. **Total Time**: ~15-20 seconds for 10 emails + 5 contacts

**Expected Output**:
```
🔄 Sync Complete

✅ Email: +10 new, -0 deleted
🔄 Avatars: 5 contacts queued for analysis
ℹ️  Incremental sync - fetching changes since 2025-12-10
   If you want to go further back, run /sync --reset first

✅ Memory Agent: Processed 10 emails in 8.3s
✅ CRM Agent: Computed 5 avatars in 4.7s

✅ Done! Run /gaps to see your action items.
```

---

### What to Verify:

#### Check `emails` Table (Supabase):
```sql
SELECT COUNT(*) FROM emails WHERE owner_id = 'YOUR_OWNER_ID';
-- Expected: 10 (or number of emails synced)

SELECT id, from_email, subject, date
FROM emails
WHERE owner_id = 'YOUR_OWNER_ID'
ORDER BY date DESC
LIMIT 5;
```

**Expected Result**:
```
 id                                   | from_email              | subject               | date
--------------------------------------+-------------------------+-----------------------+---------------------
 email_abc123...                      | john@example.com        | Re: Budget Approval   | 2025-12-10 09:30:00
 email_def456...                      | sarah@client.com        | Partnership Disc...   | 2025-12-09 14:20:00
```

#### Check `identifier_map` Table (Memory):
```sql
SELECT identifier, identifier_type, contact_id, confidence, source
FROM identifier_map
WHERE owner_id = 'YOUR_OWNER_ID'
ORDER BY updated_at DESC;
```

**Expected Result**:
```
 identifier                 | identifier_type | contact_id        | confidence | source
----------------------------+-----------------+-------------------+------------+---------------
 +15551234567               | phone           | contact_abc123... | 0.9        | memory_worker
 linkedin.com/in/johnsmith  | linkedin        | contact_abc123... | 1.0        | memory_worker
 john@example.com           | email           | contact_abc123... | 1.0        | email_sync
```

**Notes**:
- Phone numbers are normalized to E.164 format (`+15551234567`)
- LinkedIn URLs are normalized to `linkedin.com/in/username`
- Confidence scores: 1.0 (perfect), 0.9 (high), 0.5 (suspicious), 0.0 (blacklisted)

#### Check `avatars` Table (Computed View):
```sql
SELECT
  contact_id,
  display_name,
  relationship_status,
  relationship_score,
  suggested_action,
  last_computed
FROM avatars
WHERE owner_id = 'YOUR_OWNER_ID'
ORDER BY relationship_score DESC;
```

**Expected Result**:
```
 contact_id        | display_name   | relationship_status | relationship_score | suggested_action            | last_computed
-------------------+----------------+---------------------+--------------------+-----------------------------+---------------------
 contact_abc123... | John Smith     | open                | 9                  | Respond to budget proposal  | 2025-12-10 10:05:00
 contact_def456... | Sarah Chen     | waiting             | 7                  | Follow up if no response... | 2025-12-10 10:05:00
```

**Avatar Status Logic**:
- `open`: Last email from contact (you need to respond)
- `waiting`: Last email from you (waiting for their response)
- `closed`: Conversation complete or no response pattern

**Priority Scoring (1-10)**:
- **8-10**: High priority (recent, important contacts)
- **5-7**: Medium priority (moderate urgency)
- **3-4**: Low priority (older conversations)

---

### Step 7: View Memory (Namespaces)

Memory is organized by namespace: `contact:{email_address}`

**Check via SQL**:
```sql
-- View all namespaces for your contacts
SELECT DISTINCT namespace
FROM zylch_memory
WHERE owner_id = 'YOUR_OWNER_ID';
```

**Expected Output**:
```
namespace
---------------------------
contact:john@example.com
contact:sarah@client.com
contact:mike@partner.com
```

**View Memory for Specific Contact**:
```sql
SELECT namespace, category, context, pattern, confidence
FROM zylch_memory
WHERE owner_id = 'YOUR_OWNER_ID'
  AND namespace = 'contact:john@example.com'
ORDER BY created_at DESC;
```

**Expected Output**:
```
namespace                   | category | context                        | pattern                  | confidence
----------------------------+----------+--------------------------------+--------------------------+------------
contact:john@example.com    | contacts | Phone number for contact...    | Phone: +15551234567      | 0.9
contact:john@example.com    | contacts | LinkedIn profile for contact...| LinkedIn: linkedin.com...| 1.0
```

---

### Step 8: View Gaps (Action Items)

```bash
> /gaps
```

**What Happens Behind the Scenes**:
1. Backend queries `avatars` table:
   ```sql
   SELECT * FROM avatars
   WHERE owner_id = 'YOUR_OWNER_ID'
     AND relationship_status IN ('open', 'waiting')
   ORDER BY relationship_score DESC;
   ```
2. Groups by priority:
   - High (8-10)
   - Medium (5-7)
   - Low (3-4)
3. For each gap, shows:
   - Contact name
   - Last email subject/snippet
   - Days since last contact
   - Suggested action

**Expected Output**:
```
⚠️ Relationship Gaps (5 total)

🔴 High Priority (Score 9):
• John Smith - Re: Budget Approval
  Last message: 2 days ago
  Action: Review and approve Q4 budget proposal

🔴 High Priority (Score 8):
• Sarah Chen - Partnership Discussion
  Last message: 3 days ago
  Action: Follow up on contract terms

🟡 Medium Priority (Score 7):
• Mike Johnson - Project Update
  Last message: 5 days ago
  Action: Schedule next sync meeting

🟢 Low Priority (Score 4):
• Lisa Brown - Newsletter Feedback
  Last message: 10 days ago
  Action: Provide feedback on draft

🟢 Low Priority (Score 3):
• David Wilson - Intro Request
  Last message: 14 days ago
  Action: Make introduction to team
```

**Verify via SQL**:
```sql
SELECT
  contact_id,
  display_name,
  relationship_status,
  relationship_score,
  suggested_action,
  last_computed
FROM avatars
WHERE owner_id = 'YOUR_OWNER_ID'
ORDER BY relationship_score DESC;
```

---

## 5. Manual Worker Testing (Production = Cron)

In production, workers run automatically via cron. For testing, run manually:

### Memory Worker (Manual)

**Purpose**: Process unprocessed emails to extract identifiers

```bash
cd /Users/mal/hb/zylch
source .venv/bin/activate
python -m zylch.workers.memory_worker
```

**What It Does**:
1. Queries `emails` table for unprocessed emails
2. Extracts phone numbers, LinkedIn URLs
3. Stores in `identifier_map` + ZylchMemory
4. Logs progress

**Expected Output**:
```
INFO - Processing batch of 10 emails for owner test_owner_123
INFO - Extracted phones from email email_abc123: ['+15551234567']
INFO - Stored phone identifier: +15551234567 -> contact_abc123
INFO - Batch processing complete: 10 emails
```

**Verify**:
```sql
SELECT COUNT(*) FROM identifier_map WHERE owner_id = 'YOUR_OWNER_ID';
-- Should increase after running worker
```

---

### CRM Worker (Manual)

**Purpose**: Recompute avatars for affected contacts

```bash
cd /Users/mal/hb/zylch
source .venv/bin/activate
python -m zylch.workers.crm_worker
```

**What It Does**:
1. Queries affected contacts from `identifier_map`
2. For each contact:
   - Computes status (open/waiting/closed)
   - Calculates priority (1-10)
   - Generates suggested action
3. Updates `avatars` table

**Expected Output**:
```
INFO - Computing avatars for 5 contacts (owner: test_owner_123)
INFO - Computing avatar for contact contact_abc123 (owner: test_owner_123)
INFO - ✓ Avatar computed for contact_abc123: status=open, priority=9
INFO - Batch complete: 5 succeeded, 0 failed
```

**Verify**:
```sql
SELECT contact_id, relationship_status, relationship_score
FROM avatars
WHERE owner_id = 'YOUR_OWNER_ID'
ORDER BY last_computed DESC;
-- Should show recently updated timestamps
```

---

## 6. Test Scenarios

### Scenario 1: New Email Arrives

**Goal**: Verify end-to-end pipeline

1. **Send test email** to yourself (or use Gmail web interface to compose)
2. **Run sync**:
   ```bash
   > /sync
   ```
3. **Verify Memory Agent** extracted identifiers:
   ```sql
   SELECT * FROM identifier_map
   WHERE owner_id = 'YOUR_OWNER_ID'
   ORDER BY updated_at DESC
   LIMIT 5;
   ```
4. **Verify CRM Agent** created/updated avatar:
   ```sql
   SELECT * FROM avatars
   WHERE owner_id = 'YOUR_OWNER_ID'
   ORDER BY last_computed DESC
   LIMIT 1;
   ```
5. **Check gaps**:
   ```bash
   > /gaps
   ```
   Should show new item if email requires action

---

### Scenario 2: Phone Number in Email

**Goal**: Test phone number extraction

1. **Send email with phone** in signature:
   ```
   Best regards,
   John Smith
   Phone: (555) 123-4567
   ```
2. **Run sync**: `/sync`
3. **Check identifier_map**:
   ```sql
   SELECT * FROM identifier_map
   WHERE identifier LIKE '+%'
     AND owner_id = 'YOUR_OWNER_ID';
   ```
4. **Verify normalization**:
   - Input: `(555) 123-4567`
   - Stored: `+15551234567` (E.164 format)

**Test Additional Formats**:
- `555-123-4567` → `+15551234567`
- `+1 (555) 123-4567` → `+15551234567`
- `+44 20 7946 0958` → `+442079460958`

---

### Scenario 3: LinkedIn URL in Email

**Goal**: Test LinkedIn extraction

1. **Send email with LinkedIn** in signature:
   ```
   Connect on LinkedIn:
   https://www.linkedin.com/in/johnsmith
   ```
2. **Run sync**: `/sync`
3. **Check identifier_map**:
   ```sql
   SELECT * FROM identifier_map
   WHERE identifier_type = 'linkedin'
     AND owner_id = 'YOUR_OWNER_ID';
   ```
4. **Verify normalization**:
   - Input: `https://www.linkedin.com/in/johnsmith`
   - Stored: `linkedin.com/in/johnsmith`

---

### Scenario 4: Avatar Status Changes

**Goal**: Test status transition (open → waiting)

1. **Initial state**: Contact sent you email (status = `open`)
   ```sql
   SELECT contact_id, relationship_status
   FROM avatars
   WHERE display_name = 'John Smith';
   -- Result: open
   ```
2. **Reply to email** (via Gmail or send manually)
3. **Run sync**: `/sync`
4. **Check updated status**:
   ```sql
   SELECT contact_id, relationship_status, relationship_score
   FROM avatars
   WHERE display_name = 'John Smith';
   -- Result: waiting (you sent last email)
   ```
5. **Verify priority recalculated**:
   - Priority may decrease (waiting is less urgent than open)

---

## 7. Database Deep Dive

### Key Tables to Inspect

#### `emails` (Email Archive):
```sql
SELECT
  id,
  from_email,
  subject,
  date,
  LEFT(body_plain, 100) AS body_preview
FROM emails
WHERE owner_id = 'YOUR_OWNER_ID'
ORDER BY date DESC
LIMIT 5;
```

**Schema**:
- `id` (UUID): Primary key
- `owner_id` (TEXT): Multi-tenant isolation
- `gmail_id` (TEXT): Gmail message ID
- `thread_id` (TEXT): Gmail thread ID
- `from_email` (TEXT): Sender email
- `to_emails` (TEXT): Comma-separated recipients
- `cc_emails` (TEXT): Comma-separated CC
- `subject` (TEXT): Email subject
- `date` (TIMESTAMP): Email date
- `date_timestamp` (INTEGER): Unix timestamp for sorting
- `snippet` (TEXT): Preview text (100 chars)
- `body_plain` (TEXT): Plain text body
- `body_html` (TEXT): HTML body
- `labels` (JSONB): Gmail labels

---

#### `identifier_map` (Memory):
```sql
SELECT
  identifier,
  identifier_type,
  contact_id,
  confidence,
  source,
  created_at
FROM identifier_map
WHERE owner_id = 'YOUR_OWNER_ID'
ORDER BY created_at DESC;
```

**Schema**:
- `owner_id` (TEXT): Multi-tenant isolation
- `identifier` (TEXT): Email, phone, or LinkedIn URL
- `identifier_type` (TEXT): 'email', 'phone', 'linkedin'
- `contact_id` (TEXT): Stable MD5 hash of primary email
- `confidence` (FLOAT): 0.0-1.0 confidence score
- `source` (TEXT): 'email_sync', 'memory_worker', 'manual'
- `created_at` (TIMESTAMP): When identifier was discovered

**Confidence Scoring**:
- `1.0`: Perfect (personal email, explicit LinkedIn URL)
- `0.9`: High (extracted phone number)
- `0.8`: Business email (company domain)
- `0.5`: Suspicious (info@, support@, hello@)
- `0.0`: Blacklisted (noreply@, automated@)

---

#### `avatars` (Computed View):
```sql
SELECT
  contact_id,
  display_name,
  relationship_summary,
  relationship_status,
  relationship_score,
  suggested_action,
  interaction_summary,
  last_computed
FROM avatars
WHERE owner_id = 'YOUR_OWNER_ID'
ORDER BY relationship_score DESC;
```

**Schema**:
- `owner_id` (TEXT): Multi-tenant isolation
- `contact_id` (TEXT): Links to identifier_map
- `display_name` (TEXT): Contact name (from memory or email)
- `identifiers` (JSONB): All known identifiers (emails, phones, LinkedIn)
- `relationship_summary` (TEXT): 2-3 sentence summary from memory
- `relationship_status` (TEXT): 'open', 'waiting', 'closed'
- `relationship_score` (INTEGER): Priority 1-10
- `suggested_action` (TEXT): Specific next step (max 80 chars)
- `interaction_summary` (JSONB): Stats (thread_count, last_interaction, days_since_last)
- `last_computed` (TIMESTAMP): When avatar was computed

---

### Useful Queries

**Find all contacts with phone numbers**:
```sql
SELECT
  a.display_name,
  i.identifier AS phone
FROM avatars a
JOIN identifier_map i ON i.contact_id = a.contact_id
WHERE i.identifier_type = 'phone'
  AND a.owner_id = 'YOUR_OWNER_ID';
```

**Find high-priority open conversations**:
```sql
SELECT
  display_name,
  relationship_score,
  suggested_action,
  last_computed
FROM avatars
WHERE owner_id = 'YOUR_OWNER_ID'
  AND relationship_status = 'open'
  AND relationship_score >= 8
ORDER BY relationship_score DESC;
```

**Find contacts not contacted in 30+ days**:
```sql
SELECT
  display_name,
  (interaction_summary->>'days_since_last')::int AS days_since,
  relationship_status
FROM avatars
WHERE owner_id = 'YOUR_OWNER_ID'
  AND (interaction_summary->>'days_since_last')::int > 30
ORDER BY (interaction_summary->>'days_since_last')::int DESC;
```

---

## 8. Troubleshooting

### Issue: `/sync` returns 0 emails

**Cause**: Gmail history token is up-to-date (incremental sync)

**Fix**:
```bash
# Reset sync state
> /sync --reset

# Then sync with larger window
> /sync 30
```

**Explanation**: After first sync, Zylch uses Gmail's history API for incremental updates. If no new emails, returns 0. Reset clears history token and forces full re-sync.

---

### Issue: No identifiers in `identifier_map`

**Cause**: Memory Agent didn't run or failed

**Debug Steps**:
1. **Check if emails were synced**:
   ```sql
   SELECT COUNT(*) FROM emails WHERE owner_id = 'YOUR_OWNER_ID';
   ```
2. **Check worker logs**:
   ```bash
   # In backend terminal
   tail -f logs/memory_worker.log
   ```
3. **Run worker manually**:
   ```bash
   python -m zylch.workers.memory_worker
   ```

**Common Errors**:
- Email parsing failed (check `body_plain` field)
- Regex patterns didn't match (check email content)
- Database connection issues (check Supabase status)

---

### Issue: No avatars in `avatars` table

**Cause**: CRM Agent didn't run or failed

**Debug Steps**:
1. **Check if identifiers exist**:
   ```sql
   SELECT COUNT(*) FROM identifier_map WHERE owner_id = 'YOUR_OWNER_ID';
   ```
2. **Check worker logs**:
   ```bash
   tail -f logs/crm_worker.log
   ```
3. **Run worker manually**:
   ```bash
   python -m zylch.workers.crm_worker
   ```

**Common Errors**:
- No recent emails for contact (check date filters)
- Anthropic API key invalid (check `.env`)
- Memory context retrieval failed (check ZylchMemory)

---

### Issue: `/gaps` shows nothing

**Cause**: No avatars with `status='open'` or `status='waiting'`

**Debug**:
```sql
SELECT relationship_status, COUNT(*)
FROM avatars
WHERE owner_id = 'YOUR_OWNER_ID'
GROUP BY relationship_status;
```

**Possible Results**:
- All `closed`: Correct behavior (no action needed)
- No rows: CRM Agent hasn't run (see Issue above)
- All `waiting`: You sent last emails (contacts haven't replied)

**Fix**: Send test email to yourself, run `/sync`, check again.

---

### Issue: CLI can't connect to backend

**Symptom**: "Cannot reach server" error

**Debug**:
1. **Check backend is running**:
   ```bash
   curl http://localhost:8000/health
   ```
2. **Check CLI config**:
   ```bash
   cat ~/.zylch/cli_config.json
   ```
   Should have: `"server_url": "http://localhost:8000"`
3. **Check firewall**: Ensure port 8000 is open

---

## 9. Performance Benchmarks

### Expected Timings

| Operation                  | Time (Typical) | Notes                          |
|----------------------------|----------------|--------------------------------|
| `/sync` (10 emails)        | 15-20s         | Includes Memory + CRM agents   |
| Memory Agent (10 emails)   | 8-10s          | Regex + optional Haiku context |
| CRM Agent (5 contacts)     | 4-6s           | Haiku for action generation    |
| `/gaps` query              | <100ms         | Pre-computed avatars           |
| `/sync` (incremental)      | <2s            | Only fetches new changes       |

### Expected Costs (per sync)

| Component           | Model  | Cost (USD)  | Notes                     |
|---------------------|--------|-------------|---------------------------|
| Memory Agent        | Haiku  | ~$0.001     | Optional context extraction|
| CRM Agent           | Haiku  | ~$0.001     | Action generation         |
| **Total per sync**  | -      | **~$0.002** | 10 emails, 5 contacts     |

**Cost Breakdown**:
- Haiku: $0.00025 per 1K input tokens, $0.00125 per 1K output tokens
- Memory Agent: ~200 input + 50 output tokens per email
- CRM Agent: ~300 input + 100 output tokens per contact

---

## 10. Success Criteria

After completing this guide, you should be able to:

- ✅ **Start backend server** independently
- ✅ **Launch CLI** and connect to backend
- ✅ **Login** with Firebase token or test credentials
- ✅ **Connect Gmail** via OAuth flow
- ✅ **Sync emails** successfully (`/sync 7`)
- ✅ **Verify Memory Agent** extracted identifiers (check `identifier_map` table)
- ✅ **Verify CRM Agent** computed avatars (check `avatars` table)
- ✅ **View gaps** with `/gaps` command
- ✅ **Understand Memory → Avatar data flow** (Email → Memory Agent → CRM Agent → Avatar)
- ✅ **Manually trigger workers** (Memory Worker, CRM Worker)
- ✅ **Query database** to verify data (SQL queries provided)
- ✅ **Troubleshoot common issues** (sync fails, no identifiers, no avatars)

---

## 11. Advanced Testing

### Test Multi-Tenant Isolation

**Goal**: Verify data doesn't leak between owners

1. **Create two test users**:
   - User A: `owner_id = 'test_owner_a'`
   - User B: `owner_id = 'test_owner_b'`
2. **Sync data for User A**
3. **Query as User B**:
   ```sql
   SELECT COUNT(*) FROM emails WHERE owner_id = 'test_owner_b';
   -- Should be 0 (no data leakage)
   ```
4. **Query avatars**:
   ```sql
   SELECT COUNT(*) FROM avatars WHERE owner_id = 'test_owner_b';
   -- Should be 0
   ```

---

### Test Confidence Scoring

**Goal**: Verify confidence scores are accurate

1. **Create test emails with different sender types**:
   - Personal: `john.smith@gmail.com` (expected: 1.0)
   - Business: `john@acmecorp.com` (expected: 0.8)
   - Suspicious: `info@company.com` (expected: 0.5)
   - Blacklisted: `noreply@automated.com` (expected: 0.0)
2. **Run sync**: `/sync`
3. **Check confidence scores**:
   ```sql
   SELECT identifier, confidence, source
   FROM identifier_map
   WHERE owner_id = 'YOUR_OWNER_ID'
   ORDER BY confidence DESC;
   ```

---

### Test Priority Calculation

**Goal**: Verify priority formula is correct

**Formula**:
```
urgency = 4 if days_since > 7 else (2 if days_since > 3 else 0)
importance = int(relationship_strength * 2) + int(topic_importance * 2)
priority = min(10, max(1, 2 + urgency + importance))
```

**Test Cases**:
1. **Recent email (1 day), low importance**:
   - `urgency = 0`, `importance = 2` → `priority = 4`
2. **Week-old email (8 days), high importance**:
   - `urgency = 4`, `importance = 4` → `priority = 10`
3. **Very old email (30 days), medium importance**:
   - `urgency = 4`, `importance = 3` → `priority = 9`

**Verify**:
```sql
SELECT
  display_name,
  relationship_score,
  interaction_summary->>'days_since_last' AS days_since
FROM avatars
WHERE owner_id = 'YOUR_OWNER_ID'
ORDER BY relationship_score DESC;
```

---

## 12. Production Deployment Checklist

Before deploying to production:

- [ ] **Environment variables** set correctly (`.env`)
- [ ] **Supabase RLS policies** enabled (Row Level Security)
- [ ] **OAuth tokens** encrypted at rest (check `oauth_tokens` table)
- [ ] **Workers running** on cron (every 5-10 minutes)
- [ ] **Logging** configured (backend + workers)
- [ ] **Error monitoring** set up (Sentry or similar)
- [ ] **Database backups** automated (Supabase daily backups)
- [ ] **API rate limits** configured (Gmail API, Anthropic API)
- [ ] **SSL/TLS** enabled for production API
- [ ] **Multi-tenant isolation** tested (see Advanced Testing)

---

## 13. Appendix: Command Reference

### Backend Commands

```bash
# Start backend server
cd /Users/mal/hb/zylch
source .venv/bin/activate
uvicorn zylch.api.main:app --reload --port 8000

# Run Memory Worker manually
python -m zylch.workers.memory_worker

# Run CRM Worker manually
python -m zylch.workers.crm_worker

# Setup Gmail OAuth
python -m zylch.tools.gmail_oauth
```

### CLI Commands

```bash
# Launch CLI
cd /Users/mal/hb/zylch-cli
./zylch

# Login
> /login

# Sync emails (7 days)
> /sync 7

# View relationship gaps
> /gaps

# Check sync status
> /sync --status

# Reset sync state
> /sync --reset

# View help
> /help
```

### SQL Queries (Supabase)

```sql
-- Check email count
SELECT COUNT(*) FROM emails WHERE owner_id = 'YOUR_OWNER_ID';

-- View recent emails
SELECT from_email, subject, date
FROM emails
WHERE owner_id = 'YOUR_OWNER_ID'
ORDER BY date DESC
LIMIT 10;

-- Check identifier extraction
SELECT identifier, identifier_type, confidence
FROM identifier_map
WHERE owner_id = 'YOUR_OWNER_ID';

-- View computed avatars
SELECT display_name, relationship_status, relationship_score, suggested_action
FROM avatars
WHERE owner_id = 'YOUR_OWNER_ID'
ORDER BY relationship_score DESC;

-- Find unprocessed emails
SELECT id, from_email, subject
FROM emails
WHERE owner_id = 'YOUR_OWNER_ID'
  AND id NOT IN (
    SELECT UNNEST(examples) FROM zylch_memory WHERE owner_id = 'YOUR_OWNER_ID'
  )
LIMIT 10;
```

---

## 14. Next Steps

After completing QA testing:

1. **Report bugs** to development team with:
   - Steps to reproduce
   - Expected vs actual behavior
   - Relevant logs and SQL queries
2. **Document edge cases** found during testing
3. **Test production deployment** (staging environment)
4. **Train end users** on CLI commands and workflows

---

**Last Updated**: December 2025
**Tested On**: Zylch v2.0 (Von Neumann Architecture)
**Maintainer**: Zylch Development Team
