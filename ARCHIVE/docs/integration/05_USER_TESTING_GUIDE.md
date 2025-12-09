# Zylch Avatar System - External User Testing Guide

**Version:** 1.0
**Date:** December 8, 2025
**Status:** Ready for Testing

Welcome! This guide will help you set up and test Zylch's new **Avatar System** - a revolutionary approach to relationship intelligence that's **400x faster** than traditional LLM-based systems.

---

## What is the Avatar System?

The Avatar System pre-computes "avatars" (smart profiles) for each person you communicate with, providing:

- **Instant relationship summaries** (no waiting for AI)
- **Action priorities** (who needs attention)
- **Communication preferences** (tone, response patterns)
- **Multi-identifier resolution** (one person, many emails/phones)

**Performance:** ~50ms query time vs 20+ seconds for on-demand LLM analysis.

---

## Prerequisites

Before you begin, ensure you have:

- [ ] **Supabase Account** - [Sign up free](https://supabase.com)
- [ ] **Firebase Project** - [Create project](https://console.firebase.google.com)
- [ ] **Google Cloud Project** - For Gmail API access
- [ ] **Python 3.10+** - Check with `python3 --version`
- [ ] **Anthropic API Key** - [Get key](https://console.anthropic.com)
- [ ] **Basic Terminal Knowledge** - Comfortable running commands

**Estimated Setup Time:** 30-45 minutes

---

## Part 1: Database Setup (Supabase)

### Step 1: Create Supabase Project

1. Go to [https://supabase.com/dashboard](https://supabase.com/dashboard)
2. Click **"New project"**
3. Set project name: `zylch-avatar` (or your choice)
4. Set database password: **Save this somewhere safe!**
5. Choose region closest to you
6. Click **"Create new project"**
7. Wait 2-3 minutes for provisioning

**Success Indicator:** You see the project dashboard with green "Active" status.

---

### Step 2: Run Database Schema

1. In your Supabase project, navigate to **SQL Editor** (left sidebar)
2. Click **"New query"**
3. Open the schema file: `/Users/mal/hb/zylch/docs/migration/supabase_schema.sql`
4. Copy the **ENTIRE** file contents
5. Paste into SQL Editor
6. Click **"Run"** (bottom right)
7. Wait 5-10 seconds

**Success Indicator:** You see "Success. No rows returned" message.

**Troubleshooting:**
- If you see errors about existing tables, that's OK - run the migration next
- If you see "permission denied", check you're using the right project

---

### Step 3: Run Avatar Migration

1. Still in SQL Editor, click **"New query"**
2. Open migration file: `/Users/mal/hb/zylch/docs/migration/001_add_avatar_fields.sql`
3. Copy entire file
4. Paste into SQL Editor
5. Click **"Run"**
6. You should see verification messages:

```
NOTICE:  === Migration Verification ===
NOTICE:  Avatar columns added: 6 of 6
NOTICE:  identifier_map table: EXISTS
NOTICE:  avatar_compute_queue table: EXISTS
NOTICE:  ✓ Migration successful!
```

**Success Indicator:** See "✓ Migration successful!" in the output.

---

### Step 4: Verify Tables Exist

1. Navigate to **Table Editor** (left sidebar)
2. Confirm you see these tables:
   - ✓ `emails`
   - ✓ `avatars`
   - ✓ `identifier_map`
   - ✓ `avatar_compute_queue`
   - ✓ `sync_state`
   - ✓ `calendar_events`
   - ✓ `oauth_tokens`
   - ✓ `thread_analysis`

**Success Indicator:** All 8 tables are visible in Table Editor.

---

### Step 5: Get Supabase Credentials

1. Go to **Settings** → **API** (left sidebar)
2. Copy these values to a text file:

```
Project URL: https://[your-project].supabase.co
anon public key: eyJhbG... (long string)
service_role key: eyJhbG... (different long string)
```

**Important:** Save the `service_role` key - you'll need it for the backend.

---

## Part 2: Firebase Setup

### Step 1: Create Firebase Project

1. Go to [https://console.firebase.google.com](https://console.firebase.google.com)
2. Click **"Add project"**
3. Name it: `zylch-avatar` (or match your Supabase name)
4. Disable Google Analytics (not needed for testing)
5. Click **"Create project"**
6. Wait for provisioning

---

### Step 2: Enable Authentication

1. In Firebase Console, click **"Authentication"** (left sidebar)
2. Click **"Get started"**
3. Click **"Sign-in method"** tab
4. Enable **"Email/Password"**
5. Click **"Save"**

**Success Indicator:** Email/Password shows as "Enabled" in sign-in methods.

---

### Step 3: Add Test User

1. Click **"Users"** tab
2. Click **"Add user"**
3. Email: `test@example.com`
4. Password: `TestPassword123!` (or your choice)
5. Click **"Add user"**

**Save your test credentials:**
```
Email: test@example.com
Password: TestPassword123!
```

---

### Step 4: Create Service Account

1. Go to **Project Settings** (gear icon → Project settings)
2. Click **"Service accounts"** tab
3. Click **"Generate new private key"**
4. Save the JSON file as `firebase-service-account.json`
5. **Keep this file secure** - it grants admin access

**Success Indicator:** You have a JSON file with `type: "service_account"`.

---

### Step 5: Get Firebase Web Credentials

1. Still in Project Settings
2. Scroll to **"Your apps"**
3. Click web icon **"</>"** (add web app)
4. Register app name: `zylch-web`
5. Copy these values:

```javascript
apiKey: "AIza..."
authDomain: "your-project.firebaseapp.com"
projectId: "your-project-id"
```

---

## Part 3: Google Cloud / Gmail API Setup

### Step 1: Create Google Cloud Project

1. Go to [https://console.cloud.google.com](https://console.cloud.google.com)
2. Create new project: `zylch-avatar`
3. Wait for creation

---

### Step 2: Enable Gmail API

1. In Google Cloud Console, search for **"Gmail API"**
2. Click on Gmail API
3. Click **"Enable"**
4. Wait 30 seconds

**Repeat for Google Calendar API:**
1. Search **"Google Calendar API"**
2. Click and **"Enable"**

---

### Step 3: Create OAuth Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **"Configure consent screen"**
3. Choose **"External"**
4. Fill in:
   - App name: `Zylch Avatar Test`
   - User support email: Your email
   - Developer contact: Your email
5. Click **"Save and continue"**
6. Scopes: Click **"Add or remove scopes"**
7. Add these scopes:
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/calendar.readonly`
8. Click **"Save and continue"**
9. Test users: Add your Gmail address
10. Click **"Save and continue"**

---

### Step 4: Create OAuth Client

1. Still in **Credentials**
2. Click **"Create credentials"** → **"OAuth client ID"**
3. Application type: **"Desktop app"**
4. Name: `Zylch Desktop Client`
5. Click **"Create"**
6. **Download JSON** - save as `google_oauth.json`

**Success Indicator:** You have a JSON file with `client_id` and `client_secret`.

---

## Part 4: Project Setup

### Step 1: Clone Repository

```bash
cd ~/projects
git clone https://github.com/yourusername/zylch.git
cd zylch
```

**Or** if you received a ZIP:
```bash
unzip zylch-avatar.zip
cd zylch-avatar
```

---

### Step 2: Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

**Success Indicator:** Your prompt shows `(venv)` prefix.

---

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

This takes 2-5 minutes. Watch for errors.

**Success Indicator:** No red error messages about missing packages.

---

### Step 4: Create Credentials Directory

```bash
mkdir -p credentials
mv ~/Downloads/google_oauth.json credentials/
mv ~/Downloads/firebase-service-account.json credentials/
```

**Verify:**
```bash
ls credentials/
```
Should show:
- `google_oauth.json`
- `firebase-service-account.json`

---

### Step 5: Create .env File

Create file `.env` in project root:

```bash
nano .env
```

Paste this template and fill in YOUR values:

```env
# Logging
LOG_LEVEL=INFO

# Anthropic
ANTHROPIC_API_KEY=sk-ant-api03-...  # Your Anthropic key

# Model Configuration
DEFAULT_MODEL=claude-sonnet-4-20250514
CLASSIFICATION_MODEL=claude-3-5-haiku-20241022

# Supabase
SUPABASE_URL=https://[your-project].supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbG...  # From Supabase Settings → API

# Firebase Service Account
FIREBASE_SERVICE_ACCOUNT_PATH=credentials/firebase-service-account.json
FIREBASE_PROJECT_ID=your-project-id  # From Firebase project settings

# Firebase Web SDK (for CLI login)
FIREBASE_API_KEY=AIza...  # From Firebase web app config
FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com

# Google OAuth
GOOGLE_CREDENTIALS_PATH=credentials/google_oauth.json
GOOGLE_TOKEN_PATH=/Users/yourusername/.zylch/credentials/google

# Gmail
GMAIL_ACCOUNTS=your.email@gmail.com
```

**Save:** Ctrl+X, Y, Enter

**Verify:**
```bash
cat .env | grep SUPABASE_URL
```
Should show your Supabase URL.

---

## Part 5: First Run - Registration

### Step 1: Initialize CLI

```bash
python3 -m zylch.cli.main
```

You should see the Zylch welcome screen.

---

### Step 2: Authenticate with Firebase

Since you already have a test user:

1. Run the CLI
2. Choose **"Login"** option
3. A browser window will open
4. Sign in with:
   - Email: `test@example.com`
   - Password: `TestPassword123!`
5. Browser shows "Authentication successful!"
6. Return to terminal

**Success Indicator:** Terminal shows "✓ Logged in as test@example.com"

---

### Step 3: Authorize Gmail Access

1. CLI prompts: "Authorize Gmail access?"
2. Press Enter
3. Browser opens Google OAuth screen
4. Choose your Gmail account
5. Click **"Allow"** (you may see warnings - this is OK for testing)
6. Browser shows "Authorization successful!"
7. Return to terminal

**Success Indicator:** Terminal shows "✓ Gmail authorized for your.email@gmail.com"

---

### Step 4: First Email Sync

The CLI will automatically start syncing:

```
Syncing Gmail...
  Fetching emails: 0/1000
  Fetching emails: 100/1000
  ...
  ✓ Synced 1000 emails in 45.2s

Storing in Supabase...
  ✓ Stored 998 emails (2 duplicates skipped)
```

**Expected Time:** 1-3 minutes for first 1000 emails

**Success Indicator:** No errors, emails stored in Supabase.

---

### Step 5: Verify Database Population

1. Go to Supabase **Table Editor**
2. Click **"emails"** table
3. You should see rows with:
   - `owner_id` (your Firebase UID)
   - `gmail_id`
   - `subject`
   - `from_email`
   - `date`

**Success Indicator:** At least 10+ emails visible in table.

---

## Part 6: Core Avatar Workflow

### Step 1: Trigger Avatar Generation

In Zylch CLI:

```bash
zylch avatars compute-all
```

Or programmatically:

```python
from zylch.storage.supabase_client import SupabaseStorage

storage = SupabaseStorage.get_instance()
owner_id = "your-firebase-uid"

# Queue avatar computation for a contact
storage.queue_avatar_compute(
    owner_id=owner_id,
    contact_id="abc123def456",
    trigger_type="manual",
    priority=8
)
```

**What happens:**
1. System identifies unique contacts from emails
2. Adds them to `avatar_compute_queue`
3. Worker processes queue (every 5 minutes)

---

### Step 2: Run Avatar Worker

Normally this runs as a Railway cron job. For testing, run manually:

```bash
python3 -m zylch.workers.avatar_compute_worker
```

**Expected Output:**
```
Avatar Compute Worker Starting
Processing 10 avatars...
  Processing avatar: abc123def456 (trigger: manual)
  ✓ Updated avatar for abc123def456 in 2.3s
  Processing avatar: def456ghi789 (trigger: manual)
  ✓ Updated avatar for def456ghi789 in 1.9s
  ...
Batch complete: 10 avatars updated
Avatar Compute Worker Complete
```

**Success Indicator:** See "✓ Updated avatar" messages, no errors.

---

### Step 3: Query Avatars via API

Test the REST API:

```bash
# Get Firebase token first (from CLI login)
export FIREBASE_TOKEN="your-id-token-here"

# List all avatars
curl -X GET "http://localhost:8000/api/avatars" \
  -H "auth: $FIREBASE_TOKEN"

# Get specific avatar
curl -X GET "http://localhost:8000/api/avatars/abc123def456" \
  -H "auth: $FIREBASE_TOKEN"

# Resolve email to avatar
curl -X GET "http://localhost:8000/api/avatars/resolve/john.doe@example.com" \
  -H "auth: $FIREBASE_TOKEN"
```

**Expected Response:**
```json
{
  "success": true,
  "avatar": {
    "contact_id": "abc123def456",
    "display_name": "John Doe",
    "relationship_summary": "Frequent collaborator on Project X...",
    "relationship_status": "open",
    "relationship_score": 8,
    "suggested_action": "Follow up on Q4 proposal",
    "identifiers": {
      "emails": ["john.doe@company.com", "jdoe@gmail.com"],
      "phones": []
    },
    "interaction_summary": {
      "thread_count": 15,
      "email_count": 47,
      "last_interaction": "2025-12-07T10:30:00Z"
    },
    "preferred_tone": "professional",
    "response_latency": {
      "median_hours": 4.5,
      "p90_hours": 24.0
    },
    "relationship_strength": 0.82
  }
}
```

---

### Step 4: Performance Testing

Test query speed:

```bash
# Install httpie for timing
pip install httpie

# Measure query time
time http GET "http://localhost:8000/api/avatars" \
  auth:"$FIREBASE_TOKEN"
```

**Expected Timings:**
- **Cold query:** 100-200ms (first query, database warming up)
- **Warm query:** 25-75ms (subsequent queries)

**Success Indicator:** Warm queries under 100ms

**Compare to old system:**
- Old system (per-request LLM): 15-30 seconds
- New system (avatar): 0.05 seconds
- **Speed improvement: 400x faster!**

---

## Part 7: Testing Workflow

### Test Case 1: Multi-Identifier Resolution

**Goal:** Verify one person with multiple emails gets one avatar.

**Steps:**

1. Send emails to yourself from two different accounts:
   - `personal@gmail.com`
   - `work@company.com`

2. Sync emails:
   ```bash
   zylch sync gmail
   ```

3. Check identifier mapping:
   ```sql
   SELECT * FROM identifier_map WHERE contact_id = 'abc123';
   ```

4. Should see both emails mapped to same `contact_id`

**Success:** Both identifiers resolve to same avatar.

---

### Test Case 2: Avatar Staleness

**Goal:** Verify avatars auto-refresh based on importance.

**Steps:**

1. Create high-priority avatar:
   ```python
   # This should refresh every 12 hours
   storage.store_avatar(owner_id, {
       'contact_id': 'xyz789',
       'relationship_score': 9,
       'last_computed': '2025-12-07T00:00:00Z'
   })
   ```

2. Run staleness query:
   ```sql
   SELECT * FROM get_stale_avatars('your-owner-id', 24);
   ```

3. Should return contacts needing updates

**Success:** High-priority contacts flagged after 12 hours, low-priority after 168 hours.

---

### Test Case 3: Queue Priority

**Goal:** Verify high-priority contacts processed first.

**Steps:**

1. Queue two avatars:
   ```python
   # Low priority
   storage.queue_avatar_compute(owner_id, 'contact1', priority=3)

   # High priority
   storage.queue_avatar_compute(owner_id, 'contact2', priority=9)
   ```

2. Run worker:
   ```bash
   python3 -m zylch.workers.avatar_compute_worker
   ```

3. Check processing order in logs

**Success:** High-priority contact processed first.

---

### Test Case 4: Conversation Status Detection

**Goal:** Verify status (open/waiting/closed) is accurate.

**Setup:**

Create test scenarios:

1. **Open** - You haven't replied to their last email
   - Contact emails you
   - You don't respond
   - Avatar should be `status: "open"`

2. **Waiting** - You replied, waiting for them
   - You email them
   - They haven't responded
   - Avatar should be `status: "waiting"`

3. **Closed** - Conversation complete
   - No pending emails
   - Avatar should be `status: "closed"`

**Verify:**
```bash
curl http://localhost:8000/api/avatars?status=open -H "auth: $TOKEN"
```

**Success:** Correct status for each scenario.

---

## Part 8: Differences from Old System

### What's Faster

| Operation | Old System | New System | Improvement |
|-----------|-----------|------------|-------------|
| Get relationship context | 15-30s | 0.05s | **400x faster** |
| List all contacts needing action | 5-10min | 0.1s | **3000x faster** |
| Find person by email | 2-5s | 0.03s | **100x faster** |

### What's Slower

| Operation | Old System | New System | Notes |
|-----------|-----------|------------|-------|
| First-time avatar creation | Instant | 2-3s | One-time cost, then cached |
| Email sync | ~45s | ~60s | +33% due to identifier extraction |

### What's Changed

1. **No more per-request LLM calls**
   - Old: Every task retrieval calls Claude
   - New: Pre-computed avatars, instant access

2. **Multi-identifier resolution**
   - Old: Separate entries for each email
   - New: One person = one avatar, multiple identifiers

3. **Proactive staleness detection**
   - Old: Manual refresh only
   - New: Auto-queues updates based on importance

4. **Background processing**
   - Old: Synchronous, blocks CLI
   - New: Async queue, Railway cron worker

---

## Part 9: Known Limitations

### Current Limitations

1. **Initial Avatar Generation**
   - First 1000 contacts: ~30-45 minutes
   - Reason: One LLM call per avatar
   - Workaround: Runs in background, use CLI normally

2. **Embedding Search**
   - Semantic search not yet implemented
   - TODO: `profile_embedding` field exists but not populated
   - Workaround: Use status/score filters instead

3. **Real-time Updates**
   - Avatar updates: Every 5 minutes (cron)
   - High-priority: Every 12 hours
   - Low-priority: Every 7 days

4. **Mobile Support**
   - CLI-only for now
   - Dashboard integration: Coming soon

### Performance Bottlenecks

1. **Large Email Archives**
   - First sync of 10k+ emails: 5-10 minutes
   - Subsequent syncs: 30-60 seconds

2. **Concurrent Worker Runs**
   - One worker instance at a time
   - Parallel processing: Not yet implemented

---

## Part 10: Troubleshooting

### Common Errors

#### Error: "Supabase connection failed"

**Symptoms:**
```
Error: Could not connect to Supabase
```

**Fix:**
1. Check `.env` has correct `SUPABASE_URL`
2. Verify `SUPABASE_SERVICE_ROLE_KEY` (not `anon` key)
3. Test connection:
   ```bash
   curl https://[your-project].supabase.co/rest/v1/
   ```

---

#### Error: "Firebase authentication failed"

**Symptoms:**
```
Error: Invalid Firebase token
```

**Fix:**
1. Re-login via CLI
2. Check `FIREBASE_API_KEY` in `.env`
3. Verify test user exists in Firebase Console

---

#### Error: "Gmail API quota exceeded"

**Symptoms:**
```
Error: Rate limit exceeded
```

**Fix:**
1. Wait 1 minute
2. Gmail API limits: 250 quota units/user/second
3. For testing, sync in batches:
   ```bash
   zylch sync gmail --limit 100
   ```

---

#### Error: "No avatars generated"

**Symptoms:**
- Queue is empty
- No avatars in database

**Debug Steps:**

1. Check email sync worked:
   ```sql
   SELECT COUNT(*) FROM emails WHERE owner_id = 'your-uid';
   ```

2. Check queue populated:
   ```sql
   SELECT COUNT(*) FROM avatar_compute_queue WHERE owner_id = 'your-uid';
   ```

3. Manually queue avatar:
   ```python
   from zylch.storage.supabase_client import SupabaseStorage
   storage = SupabaseStorage.get_instance()

   # Get a contact_id from emails
   emails = storage.client.table('emails').select('from_email').limit(1).execute()
   email = emails.data[0]['from_email']

   from zylch.services.avatar_aggregator import generate_contact_id
   contact_id = generate_contact_id(email=email)

   storage.queue_avatar_compute('your-owner-id', contact_id, 'manual', 10)
   ```

4. Run worker manually:
   ```bash
   python3 -m zylch.workers.avatar_compute_worker
   ```

---

#### Error: "Worker fails with Anthropic error"

**Symptoms:**
```
Error: Invalid API key
```

**Fix:**
1. Check `.env` has `ANTHROPIC_API_KEY=sk-ant-...`
2. Test API key:
   ```bash
   curl https://api.anthropic.com/v1/messages \
     -H "x-api-key: $ANTHROPIC_API_KEY" \
     -H "anthropic-version: 2023-06-01" \
     -H "content-type: application/json" \
     -d '{"model":"claude-3-5-haiku-20241022","max_tokens":10,"messages":[{"role":"user","content":"Hi"}]}'
   ```

---

### Debug Logging

Enable verbose logging:

```bash
# In .env
LOG_LEVEL=DEBUG

# Or when running worker
LOG_LEVEL=DEBUG python3 -m zylch.workers.avatar_compute_worker
```

**Check Logs:**
```bash
tail -f logs/worker.log
```

---

### Reset Everything

If you need to start fresh:

```bash
# WARNING: Deletes all data!

# 1. Clear Supabase tables
# Go to Supabase SQL Editor, run:
DELETE FROM avatar_compute_queue;
DELETE FROM identifier_map;
DELETE FROM avatars;
DELETE FROM emails;

# 2. Remove local credentials
rm -rf ~/.zylch/credentials/

# 3. Re-run setup from Part 5
```

---

## Part 11: Support

### Getting Help

**Bug Reports:**
- GitHub Issues: https://github.com/yourusername/zylch/issues
- Include:
  - Error message (full traceback)
  - `.env` (with secrets REMOVED)
  - Python version: `python3 --version`
  - OS: `uname -a`

**Questions:**
- Discord: [Join server]
- Email: support@zylch.ai

**Performance Issues:**
- Attach logs: `logs/worker.log`
- Include timing data from Part 6, Step 4

---

## Appendix A: Complete Environment Variables

```env
# === Logging ===
LOG_LEVEL=INFO

# === Anthropic ===
ANTHROPIC_API_KEY=sk-ant-api03-...

# === Model Configuration ===
DEFAULT_MODEL=claude-sonnet-4-20250514
CLASSIFICATION_MODEL=claude-3-5-haiku-20241022
EXECUTIVE_MODEL=claude-opus-4-20250514

# === Supabase ===
SUPABASE_URL=https://[project].supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbG...

# === Firebase ===
# Service Account (backend)
FIREBASE_SERVICE_ACCOUNT_PATH=credentials/firebase-service-account.json
FIREBASE_PROJECT_ID=your-project-id

# Web SDK (CLI login)
FIREBASE_API_KEY=AIza...
FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com

# === Google OAuth ===
GOOGLE_CREDENTIALS_PATH=credentials/google_oauth.json
GOOGLE_TOKEN_PATH=/Users/yourusername/.zylch/credentials/google

# === Gmail ===
GMAIL_ACCOUNTS=your.email@gmail.com

# === Calendar ===
CALENDAR_ID=primary
```

---

## Appendix B: Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      Zylch Avatar System                     │
└─────────────────────────────────────────────────────────────┘

┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│  Gmail API   │─────>│ Email Sync   │─────>│  Supabase    │
└──────────────┘      └──────────────┘      │   emails     │
                                             └──────────────┘
                                                     │
                                                     ▼
                      ┌──────────────────────────────────────┐
                      │   Identifier Extraction              │
                      │   (from_email → contact_id)          │
                      └──────────────────────────────────────┘
                                                     │
                                                     ▼
                      ┌──────────────────────────────────────┐
                      │   Queue Avatar Computation           │
                      │   (avatar_compute_queue)             │
                      └──────────────────────────────────────┘
                                                     │
                                                     ▼
┌──────────────┐      ┌──────────────────────────────────────┐
│ Railway Cron │─────>│   Avatar Worker                      │
│ (5 minutes)  │      │   1. Aggregate data (no LLM)        │
└──────────────┘      │   2. Call Claude once                │
                      │   3. Store avatar                     │
                      │   4. Remove from queue               │
                      └──────────────────────────────────────┘
                                                     │
                                                     ▼
                      ┌──────────────────────────────────────┐
                      │   avatars table                      │
                      │   - Pre-computed summaries           │
                      │   - Instant queries (~50ms)          │
                      └──────────────────────────────────────┘
                                                     │
                                                     ▼
                      ┌──────────────────────────────────────┐
                      │   REST API                           │
                      │   GET /api/avatars                   │
                      │   GET /api/avatars/{id}              │
                      │   GET /api/avatars/resolve/{email}   │
                      └──────────────────────────────────────┘
```

---

## Appendix C: Testing Checklist

Use this for systematic testing:

### Database Setup
- [ ] Supabase project created
- [ ] Schema installed (10 tables)
- [ ] Migration run (6 avatar fields added)
- [ ] Tables visible in Table Editor
- [ ] Service role key obtained

### Firebase Setup
- [ ] Firebase project created
- [ ] Email/Password auth enabled
- [ ] Test user created
- [ ] Service account downloaded
- [ ] Web credentials obtained

### Google Cloud Setup
- [ ] Project created
- [ ] Gmail API enabled
- [ ] Calendar API enabled
- [ ] OAuth consent screen configured
- [ ] OAuth client created
- [ ] Credentials JSON downloaded

### Project Setup
- [ ] Repository cloned
- [ ] Virtual environment created
- [ ] Dependencies installed
- [ ] Credentials files in place
- [ ] .env file created and configured

### First Run
- [ ] Firebase login successful
- [ ] Gmail authorization successful
- [ ] First email sync completed
- [ ] Emails visible in Supabase

### Avatar System
- [ ] Avatar computation queued
- [ ] Worker run successful
- [ ] Avatars visible in database
- [ ] API queries working
- [ ] Response times < 100ms

### Advanced Testing
- [ ] Multi-identifier resolution tested
- [ ] Staleness detection working
- [ ] Queue priority verified
- [ ] Status detection accurate

---

## Conclusion

You've successfully set up and tested the Zylch Avatar System! 🎉

**Key Takeaways:**

✅ **400x faster** than old system
✅ **Pre-computed intelligence** for instant access
✅ **Multi-identifier resolution** for accurate person tracking
✅ **Background processing** keeps everything up-to-date

**Next Steps:**

1. Test with your real email archive
2. Experiment with API queries
3. Report any bugs or performance issues
4. Share feedback on the testing experience

**Remember:** This is a testing version - some features are still in development. Your feedback is invaluable for improving the system!

---

**Questions?** Contact us at support@zylch.ai or open a GitHub issue.

**Happy Testing!** 🚀
