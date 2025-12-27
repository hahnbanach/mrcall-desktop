# Email Read Notification - Implementation Summary

## Overview

Zylch will implement email read tracking using **two complementary approaches**:

1. **SendGrid Webhooks** (PRIMARY) - For batch emails
2. **Custom Tracking Pixel** (SECONDARY) - For individual emails

---

## Why Two Approaches?

### SendGrid Webhook (For Batch Emails)
✅ **Advantages**:
- No need to inject custom tracking pixels
- More reliable (SendGrid's infrastructure)
- Simpler implementation
- Already includes open tracking
- Better deliverability (no extra pixels)

❌ **Limitation**:
- Only works for emails sent via SendGrid

### Custom Tracking Pixel (For Individual Emails)
✅ **Advantages**:
- Works for any email sending method
- Full control over tracking
- Can be used for non-SendGrid emails

❌ **Limitations**:
- Requires pixel injection into HTML
- Less reliable (email clients may block images)
- Slightly more complex

---

## Architecture Summary

### For Batch Emails (SendGrid Webhook)

```
1. Zylch sends batch email via SendGrid
   ↓
2. SendGrid automatically adds tracking pixel
   ↓
3. Recipient opens email → SendGrid detects open
   ↓
4. SendGrid sends webhook to: POST /api/webhooks/sendgrid
   ↓
5. Zylch webhook handler:
   - Validates SendGrid signature (security)
   - Looks up sg_message_id → message_id mapping
   - Records read event in database
   ↓
6. Database updated:
   - email_read_events table (detailed)
   - messages.read_events JSON (summary)
```

### For Individual Emails (Custom Pixel)

```
1. Zylch sends email with tracking pixel injected
   ↓
2. Recipient opens email → Pixel loads
   ↓
3. Pixel request: GET /api/track/pixel/{tracking_id}
   ↓
4. Zylch pixel endpoint:
   - Validates tracking_id
   - Records read event
   - Returns 1x1 transparent GIF
   ↓
5. Database updated (same as above)
```

---

## Database Changes

### New Tables

**1. `email_read_events`** (Main tracking table)
- Stores all read events (both SendGrid and custom pixel)
- Fields: tracking_id, sendgrid_message_id, owner_id, message_id, recipient_email
- Fields: tracking_source ('sendgrid_webhook' or 'custom_pixel')
- Fields: read_count, first_read_at, last_read_at
- Fields: user_agents[], ip_addresses[], sendgrid_event_data (JSON)

**2. `sendgrid_message_mapping`** (For webhook processing)
- Maps SendGrid message IDs to Zylch message IDs
- Fields: sendgrid_message_id (PK), message_id, owner_id, recipient_email
- Used by webhook handler to look up internal message ID

### Modified Tables

**`messages`** (Add read_events column)
- Add `read_events` JSONB column
- Stores summary: `[{"recipient": "email", "read_count": 3, "first_read_at": "...", "last_read_at": "..."}]`
- Enables fast queries without joining email_read_events table

---

## API Endpoints

### 1. SendGrid Webhook (PRIMARY)
**POST /api/webhooks/sendgrid**
- Receives email event notifications from SendGrid
- Validates SendGrid signature (ECDSA)
- Processes "open" events
- Returns 200 OK within 10 seconds

### 2. Tracking Pixel (SECONDARY)
**GET /api/track/pixel/{tracking_id}**
- Serves 1x1 transparent GIF
- Records read event in background
- Always returns pixel (even on error)

### 3. Read Statistics
**GET /api/emails/{message_id}/read-stats**
- Returns detailed read statistics for a single email
- Shows per-recipient read counts and timestamps

**GET /api/emails/read-stats?days_back=30**
- Returns aggregated statistics for multiple emails
- Supports pagination

---

## Implementation Phases

### Phase 1: Database Setup (Week 1)
- Create `email_read_events` table
- Create `sendgrid_message_mapping` table
- Add `read_events` column to `messages`

### Phase 2: SendGrid Webhook (Week 1-2) - PRIMARY
- Implement webhook endpoint with signature verification
- Create message mapping logic
- Configure SendGrid webhook in dashboard
- Test webhook processing

### Phase 3: Custom Tracking Pixel (Week 2) - SECONDARY
- Implement tracking ID generation
- Create pixel endpoint
- Add pixel injection to individual emails
- Test pixel tracking

### Phase 4: Statistics API (Week 2-3)
- Create read statistics endpoints
- Add authentication and rate limiting
- Generate API documentation

### Phase 5: Testing & Deployment (Week 3-4)
- Comprehensive testing
- Security hardening
- Production deployment

---

## SendGrid Configuration Required

### Webhook Setup
1. Go to SendGrid Dashboard → Settings → Mail Settings → Event Webhook
2. Set webhook URL: `https://api.zylch.com/api/webhooks/sendgrid`
3. Enable events: **Opened** (required), Clicked, Bounced, Dropped
4. Enable **Signed Event Webhook** for security
5. Copy public key to environment: `SENDGRID_WEBHOOK_PUBLIC_KEY`

### Testing Locally
Use ngrok to test webhooks during development:
```bash
ngrok http 8000
# Set webhook URL to: https://abc123.ngrok.io/api/webhooks/sendgrid
```

---

## Key Decisions

### ✅ Use SendGrid Webhooks for Batch Emails
**Rationale**: Simpler, more reliable, no custom pixel injection needed

### ✅ Use Custom Pixel Only for Individual Emails
**Rationale**: Provides tracking for non-SendGrid emails, full control

### ✅ Store Both Detailed and Summary Data
**Rationale**: Detailed events in `email_read_events`, fast summary in `messages.read_events`

### ✅ Use ECDSA Signature Verification
**Rationale**: Prevent webhook spoofing attacks

### ✅ Return 200 OK Even on Errors
**Rationale**: Prevent SendGrid from retrying invalid data

---

## US Privacy Compliance

### Understanding Email Types & CAN-SPAM

| Email Type | Sent Via | CAN-SPAM? | Unsubscribe? |
|------------|----------|-----------|--------------|
| Personal email (Gmail/Outlook) | User's account | ❌ NO | ❌ NO |
| Bulk marketing campaign | SendGrid batch | ✅ YES | ✅ YES |
| Transactional email | SendGrid | ❌ NO | ❌ NO |

**Key**: CAN-SPAM only applies to **commercial/marketing emails**, NOT personal emails.

### Applicable Laws
- **CAN-SPAM Act**: Email marketing regulations (commercial emails only)
- **CCPA**: California Consumer Privacy Act (right to know, delete, opt-out)
- **State Privacy Laws**: Virginia CDPA, Colorado CPA, etc.

### Compliance Features

**1. Privacy Policy Disclosure**:
- Disclose email read tracking in privacy policy
- Explain what data is collected (open events, timestamps, email client info)
- Optional: Disclose IP address collection (if enabled)

**2. User Rights (CCPA)**:
- **Right to Know**: `GET /api/privacy/my-data` - Users can request their tracking data
- **Right to Delete**: `DELETE /api/privacy/delete-my-data` - Users can delete their data
- **Opt-Out**: `POST /api/privacy/opt-out` - Users can opt out of future tracking

**3. Data Retention**:
- Auto-delete tracking events after 90 days (configurable)
- Scheduled daily cleanup job

**4. CAN-SPAM Compliance** (Commercial/Marketing Emails Only):
- **NOT required for personal emails** sent via Gmail/Outlook accounts
- **Only applies to bulk marketing campaigns** (SendGrid batch emails)
- Include unsubscribe link in commercial emails
- Honor unsubscribe requests within 10 business days
- Accurate "From" headers (good practice for all emails)

**5. IP Address Collection**:
- **Disabled by default** for privacy
- Only enabled via `EMAIL_TRACKING_COLLECT_IPS=true` if needed

---

## Environment Variables

```bash
# Existing
SENDGRID_API_KEY=your_api_key

# New
SENDGRID_WEBHOOK_PUBLIC_KEY=your_ecdsa_public_key
TRACKING_PIXEL_BASE_URL=https://api.zylch.com

# Privacy (US Compliance)
EMAIL_TRACKING_COLLECT_IPS=false  # Disable IP collection by default
TRACKING_DATA_RETENTION_DAYS=90   # Auto-delete after 90 days (CCPA compliance)
```

---

## Success Metrics

**Technical**:
- Webhook processing latency < 100ms (p95)
- Pixel endpoint latency < 50ms (p95)
- Error rate < 0.1%
- Uptime > 99.9%

**Business**:
- Track read rates across all sent emails
- Per-recipient engagement metrics
- Campaign performance analytics

---

## Briefing Integration (/gaps Command)

### How Read Tracking Integrates with Intelligence

**Goal**: Notify users in `/briefing` about email read status
- "John read your email 3 days ago, time for a follow-up"
- "Mario hasn't opened your proposal (sent 5 days ago)"

### Integration Points

**1. Avatar Context Building** (`avatar_aggregator.py`)
- Add `_get_read_tracking_data()` method to query read events
- Include read tracking in `build_context()` output:
  ```python
  'read_tracking': {
      'sent_emails_count': N,
      'read_count': N,
      'unread_count': N,
      'last_sent': timestamp,
      'last_read': timestamp,
      'avg_read_delay_hours': float,
      'last_unread_email': {...}
  }
  ```

**2. Status Computation** (`crm_worker.py`)
- Enhance `_compute_status()` with read-aware logic:
  - `waiting_unread`: Email sent but not read (3+ days)
  - `waiting_acknowledged`: Email read but no response (3+ days)
  - `waiting`: Recently sent/read, give them time
  - `open`: Contact sent last, owner needs to respond

**3. Priority Boosting** (`crm_worker.py`)
- Update `_compute_priority()` to boost unread emails:
  - +2 priority: Unread for 7+ days
  - +1 priority: Unread for 3+ days
  - +1 priority: Read 5+ days ago, no response

**4. LLM Prompt Enhancement** (`crm_worker.py`)
- Add read context to `_generate_suggested_action()` prompt:
  ```
  ⚠️ IMPORTANT: Recipient has NOT read your email sent 5 days ago
  📖 Recipient READ your email 4 days ago but hasn't responded
  ```

**5. Briefing Display** (`task_formatter.py`)
- Add read tracking indicators:
  - `📧❌ (unread 5d)` - Email not opened
  - `📧✓ (read 4d ago)` - Email opened but no response

### Example Briefing Output

**Before (Current)**:
```
## 📋 Open Tasks

### 🔥 High Priority
1. **John Doe** (score 8): Follow up on proposal sent 5 days ago
```

**After (With Read Tracking)**:
```
## 📋 Open Tasks

### 🔥 High Priority
1. **John Doe** (score 9): Follow up on proposal - unread for 5 days 📧❌
2. **Mario Rossi** (score 7): Gentle reminder - they read it 4 days ago 📧✓
```

### Database Query for Read Tracking

```sql
-- Get read tracking stats for a contact
SELECT
    COUNT(*) FILTER (WHERE first_read_at IS NOT NULL) as read_count,
    COUNT(*) FILTER (WHERE first_read_at IS NULL) as unread_count,
    COUNT(*) as sent_count,
    MAX(messages.date_timestamp) as last_sent_date,
    MAX(email_read_events.first_read_at) as last_read_date,
    AVG(EXTRACT(EPOCH FROM (first_read_at - messages.date)) / 3600) as avg_read_delay_hours
FROM messages
LEFT JOIN email_read_events ON messages.id = email_read_events.message_id
WHERE messages.owner_id = $1
    AND messages.from_email = ANY($2)  -- Owner's emails
    AND messages.to_email && $3       -- Contact's emails
    AND messages.date > NOW() - INTERVAL '30 days'
```

---

## Implementation Files

| File | Modification | Purpose |
|------|--------------|---------|
| `zylch/services/avatar_aggregator.py` | Add `_get_read_tracking_data()` | Query read events |
| `zylch/services/avatar_aggregator.py` | Update `build_context()` | Include read_tracking field |
| `zylch/workers/crm_worker.py` | Update `_compute_status()` | Read-aware status logic |
| `zylch/workers/crm_worker.py` | Update `_compute_priority()` | Priority boost for unread |
| `zylch/workers/crm_worker.py` | Update `_generate_suggested_action()` | Enhanced LLM prompt |
| `zylch/services/task_formatter.py` | Add read indicators | Display 📧❌ / 📧✓ |
| `zylch/api/routes/webhooks.py` | New file | SendGrid webhook handler |
| `zylch/api/routes/tracking.py` | New file | Tracking pixel endpoint |
| `zylch/storage/supabase_client.py` | Add methods | Read tracking queries |

---

## Next Steps

1. ✅ Review and approve proposal
2. ✅ Design briefing integration
3. ⏳ Start Phase 1 (Database Setup)
4. ⏳ Implement avatar integration
5. ⏳ Configure SendGrid webhook
6. ⏳ Test end-to-end flow

---

## Questions?

- **Full Proposal**: See `email-read-tracking.md` for detailed technical specifications
- **Briefing Integration**: See above for avatar system integration details
