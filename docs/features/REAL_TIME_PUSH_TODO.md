---
description: |
  [TODO - Medium Priority] Replace batch sync (every 5 min or manual /sync) with zero-latency
  Gmail push via Google Pub/Sub. Currently gap analysis runs only after sync. Target: instant
  email detection via Pub/Sub webhook, real-time relationship gap analysis, push notifications
  for urgent contacts. Use case: sales reps get instant alerts when clients reply.
---

# Real-Time Gmail Push Notifications - Future Development

## Status
🟡 **MEDIUM PRIORITY** - Zero-Latency Intelligence

## Business Impact

**User Pain Point**:
- **Current**: Batch sync every 5 minutes (or manual `/sync`)
- **Problem**: 0-5 minute delay in detecting new emails
- **Impact**: Missed urgent opportunities, slow response time

**Why Important**:
- **Instant relationship gaps**: Detect unanswered emails in real-time
- **Competitive advantage**: Faster than checking Gmail manually
- **User retention**: Real-time features create stickiness
- **Premium positioning**: Real-time = pro feature

**Use Cases**:
- Sales rep gets instant notification when client replies
- Executive gets alerted immediately for VIP contacts
- Customer support team notified in real-time for urgent inquiries
- Immediate gap analysis when new email arrives

## Current State

### What Exists
- ✅ **Batch sync**: Email sync every 5 minutes via cron
- ✅ **Manual sync**: `/sync` command triggers immediate sync
- ✅ **Gap analysis**: Relationship gap detection after sync
- ✅ **Email archive**: Full history with Gmail History API

### What's Missing
- ❌ **Real-time push**: No Gmail Pub/Sub integration
- ❌ **Webhook endpoint**: No endpoint to receive push notifications
- ❌ **Instant sync**: No triggered sync on email arrival
- ❌ **Real-time gaps**: No immediate gap analysis
- ❌ **WebSocket**: No live updates to frontend

### Current Sync Flow
```
User → Manual /sync OR Cron (every 5 min) →
Gmail API → Pull new emails →
Local cache → Gap analysis →
Show in dashboard

Latency: 0-5 minutes
```

### Target Real-Time Flow
```
Gmail → Pub/Sub push →
Webhook endpoint → Incremental sync (1 email) →
Gap analysis → WebSocket push →
Frontend update

Latency: <5 seconds
```

## Planned Features

### 1. Gmail Pub/Sub Integration

**Gmail Push Notifications**:
Gmail supports push notifications via Google Cloud Pub/Sub. When a new email arrives, Gmail publishes a notification to a Pub/Sub topic.

**Architecture**:
```
Gmail Mailbox → Pub/Sub Topic → Subscription → Webhook Endpoint → Zylch Backend
```

**Setup Steps**:
1. Create Google Cloud Pub/Sub topic
2. Configure Gmail watch (tell Gmail to publish to topic)
3. Create Pub/Sub subscription (pull or push to webhook)
4. Handle webhook notifications

**Google Cloud Console Setup**:
```bash
# 1. Create Pub/Sub topic
gcloud pubsub topics create gmail-notifications

# 2. Grant Gmail permission to publish
gcloud pubsub topics add-iam-policy-binding gmail-notifications \
  --member=serviceAccount:gmail-api-push@system.gserviceaccount.com \
  --role=roles/pubsub.publisher

# 3. Create push subscription
gcloud pubsub subscriptions create zylch-gmail-push \
  --topic=gmail-notifications \
  --push-endpoint=https://api.zylchai.com/api/webhooks/gmail-push \
  --ack-deadline=60
```

### 2. Gmail Watch Request

**Start Watching Mailbox**:
```python
from googleapiclient.discovery import build

async def start_gmail_watch(user_email: str, gmail_service):
    """Tell Gmail to send push notifications for this user's mailbox"""

    request = {
        'labelIds': ['INBOX'],  # Watch inbox only (or omit for all mail)
        'topicName': 'projects/zylch-ai/topics/gmail-notifications'
    }

    # Watch expires after 7 days max - need to renew
    response = gmail_service.users().watch(userId='me', body=request).execute()

    # Store watch details
    await supabase.table('gmail_watches').upsert({
        'user_id': user_email,
        'history_id': response['historyId'],
        'expiration': datetime.fromtimestamp(int(response['expiration']) / 1000)
    }).execute()

    return response
```

**Renew Watch (Every 6 Days)**:
```python
async def renew_all_watches():
    """Renew all Gmail watches before they expire"""

    # Get watches expiring soon
    expiring_soon = await supabase.table('gmail_watches').select('*').lt(
        'expiration', datetime.now() + timedelta(days=1)
    ).execute()

    for watch in expiring_soon.data:
        gmail_service = get_gmail_service(watch['user_id'])
        await start_gmail_watch(watch['user_id'], gmail_service)
```

### 3. Webhook Endpoint

**Receive Push Notifications**:
```python
from fastapi import Request
import base64
import json

@app.post("/api/webhooks/gmail-push")
async def gmail_push_webhook(request: Request):
    """Receive Gmail push notification from Pub/Sub"""

    # Parse Pub/Sub message
    body = await request.json()
    message = body['message']

    # Decode data
    data = base64.b64decode(message['data']).decode('utf-8')
    notification = json.loads(data)

    email_address = notification['emailAddress']
    history_id = notification['historyId']

    # Trigger incremental sync for this user
    await trigger_incremental_sync(email_address, history_id)

    # Acknowledge receipt (200 OK)
    return {'status': 'success'}
```

### 4. Incremental Sync (Single Email)

**Efficient Sync Using History API**:
```python
async def trigger_incremental_sync(user_email: str, new_history_id: int):
    """Sync only new emails since last known history ID"""

    # Get last synced history ID
    watch = await supabase.table('gmail_watches').select('*').eq(
        'user_id', user_email
    ).single().execute()

    last_history_id = watch.data['history_id']

    if new_history_id <= last_history_id:
        return  # No new changes

    # Fetch history (only changes since last sync)
    gmail_service = get_gmail_service(user_email)
    history = gmail_service.users().history().list(
        userId='me',
        startHistoryId=last_history_id,
        historyTypes=['messageAdded']
    ).execute()

    # Process new messages
    new_messages = []
    for record in history.get('history', []):
        for msg_data in record.get('messagesAdded', []):
            message_id = msg_data['message']['id']
            new_messages.append(message_id)

    # Fetch full message details
    for msg_id in new_messages:
        await fetch_and_store_email(user_email, msg_id)

    # Update history ID
    await supabase.table('gmail_watches').update({
        'history_id': new_history_id
    }).eq('user_id', user_email).execute()

    # Trigger gap re-analysis
    await analyze_gaps_for_user(user_email)

    # Push update to frontend via WebSocket
    await broadcast_update(user_email, {
        'type': 'new_emails',
        'count': len(new_messages)
    })
```

### 5. WebSocket for Live Frontend Updates

**WebSocket Endpoint**:
```python
from fastapi import WebSocket, WebSocketDisconnect

# Store active WebSocket connections
active_connections: dict[str, list[WebSocket]] = {}

@app.websocket("/ws/updates")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """WebSocket connection for real-time updates"""

    await websocket.accept()

    # Add to active connections
    if user_id not in active_connections:
        active_connections[user_id] = []
    active_connections[user_id].append(websocket)

    try:
        while True:
            # Keep connection alive
            data = await websocket.receive_text()

            if data == 'ping':
                await websocket.send_text('pong')

    except WebSocketDisconnect:
        # Remove from active connections
        active_connections[user_id].remove(websocket)


async def broadcast_update(user_id: str, update: dict):
    """Send update to all active WebSocket connections for user"""

    if user_id in active_connections:
        for websocket in active_connections[user_id]:
            await websocket.send_json(update)
```

**Frontend (Vue 3)**:
```typescript
// Establish WebSocket connection
const ws = new WebSocket(`wss://api.zylchai.com/ws/updates?user_id=${userId}`)

ws.onmessage = (event) => {
  const update = JSON.parse(event.data)

  if (update.type === 'new_emails') {
    // Refresh gaps view
    refreshGaps()

    // Show toast notification
    toast.success(`${update.count} new email(s) received`)
  } else if (update.type === 'new_gap') {
    // Add new gap to list
    gaps.value.unshift(update.gap)
  }
}

// Keep connection alive
setInterval(() => {
  ws.send('ping')
}, 30000)  // Every 30 seconds
```

### 6. Real-Time Gap Detection

**Immediate Analysis**:
```python
async def analyze_gaps_for_user(user_email: str):
    """Run gap analysis immediately after new emails"""

    # Run gap analysis
    gap_service = GapService(user_email)
    new_gaps = await gap_service.analyze_gaps(days_back=7)

    # Find NEWLY DETECTED gaps (not previously shown)
    existing_gap_ids = await get_existing_gap_ids(user_email)
    truly_new_gaps = [
        gap for gap in new_gaps
        if gap['id'] not in existing_gap_ids
    ]

    # Push new gaps to frontend
    for gap in truly_new_gaps:
        await broadcast_update(user_email, {
            'type': 'new_gap',
            'gap': gap
        })

        # Optional: Send push notification to mobile
        await send_push_notification(user_email, {
            'title': 'New Relationship Gap',
            'body': f"{gap['contact_name']}'s email awaiting response"
        })
```

## Technical Requirements

### Backend Dependencies
```bash
# Google Cloud Pub/Sub client
pip install google-cloud-pubsub>=2.18.0

# WebSocket support
pip install websockets>=12.0
```

### Google Cloud Setup
```bash
# Enable Pub/Sub API
gcloud services enable pubsub.googleapis.com

# Create service account for Pub/Sub
gcloud iam service-accounts create zylch-pubsub \
  --display-name="Zylch Pub/Sub Service Account"

# Grant permissions
gcloud projects add-iam-policy-binding zylch-ai \
  --member="serviceAccount:zylch-pubsub@zylch-ai.iam.gserviceaccount.com" \
  --role="roles/pubsub.subscriber"
```

### Environment Variables
```bash
# Pub/Sub configuration
GOOGLE_CLOUD_PROJECT_ID=zylch-ai
GMAIL_PUBSUB_TOPIC=projects/zylch-ai/topics/gmail-notifications
GMAIL_PUBSUB_SUBSCRIPTION=zylch-gmail-push

# WebSocket
WEBSOCKET_URL=wss://api.zylchai.com/ws/updates
```

### Database Schema
```sql
-- Track Gmail watch status
CREATE TABLE gmail_watches (
  user_id TEXT PRIMARY KEY REFERENCES users(id),
  history_id BIGINT NOT NULL,
  expiration TIMESTAMP NOT NULL,
  last_renewed_at TIMESTAMP DEFAULT NOW(),
  created_at TIMESTAMP DEFAULT NOW()
);

-- Track shown gaps (to detect NEW gaps)
CREATE TABLE shown_gaps (
  gap_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  shown_at TIMESTAMP DEFAULT NOW(),
  INDEX idx_user_gaps (user_id, shown_at DESC)
);
```

## Implementation Phases

### Phase 1: Pub/Sub Setup (Week 1)
**Duration**: 2-3 days
**Tasks**:
1. Set up Google Cloud Pub/Sub topic and subscription
2. Configure Gmail API permissions
3. Create webhook endpoint to receive notifications
4. Test with manual Gmail watch request
5. Verify notifications arrive at webhook

### Phase 2: Incremental Sync (Week 1-2)
**Duration**: 3-4 days
**Tasks**:
1. Implement Gmail History API incremental sync
2. Store and update history IDs
3. Fetch only new emails (not full re-sync)
4. Test sync latency (<5 seconds)

### Phase 3: WebSocket (Week 2)
**Duration**: 2-3 days
**Tasks**:
1. Implement WebSocket endpoint
2. Manage active connections per user
3. Broadcast updates on new emails/gaps
4. Test with frontend (Vue 3)

### Phase 4: Real-Time Gap Analysis (Week 2)
**Duration**: 2 days
**Tasks**:
1. Trigger gap analysis on email arrival
2. Detect truly new gaps (not duplicates)
3. Push to frontend via WebSocket
4. Test end-to-end latency

### Phase 5: Watch Renewal (Week 3)
**Duration**: 1-2 days
**Tasks**:
1. Implement watch renewal cron (every 6 days)
2. Handle watch expiration gracefully
3. Re-establish watches for all users
4. Monitor watch health

### Phase 6: Testing & Monitoring (Week 3)
**Duration**: 2-3 days
**Tasks**:
1. Load test webhook endpoint (handle 1000+ users)
2. Monitor Pub/Sub latency
3. Test failover (what if webhook is down?)
4. Add alerting for watch failures

## Success Metrics

### Technical Metrics
- **Push Latency**: <5 seconds from email arrival to frontend update
- **Sync Accuracy**: 100% of emails captured (no missed emails)
- **WebSocket Uptime**: >99.9% connection uptime
- **Watch Renewal**: 100% of watches renewed before expiration

### Business Metrics
- **User Engagement**: 2x increase in daily active users
- **Response Time**: Users respond 40% faster to emails
- **Retention**: Real-time users have 30% higher retention

### User Experience Metrics
- **Perceived Speed**: Users report "instant" email detection
- **User Satisfaction**: >4.7/5 stars for real-time feature
- **Feature Adoption**: >60% of users enable real-time push

## Related Documentation

- **Gmail Push Notifications Analysis**: `docs/OLD/gmail-push-notifications-analysis.md` (archived research)
- **Email Archive**: `docs/features/email-archive.md` - Gmail History API integration
- **Gap Analysis**: `docs/features/relationship-intelligence.md` - Real-time gap detection

## Open Questions

1. **Rate Limits**: What are Gmail's push notification rate limits?
   - **Research**: Estimate 10,000 notifications/day per project

2. **Cost**: Does Google Cloud Pub/Sub have significant costs?
   - **Answer**: First 10GB/month free, then $0.40/GB (~$50/month for 10,000 users)

3. **Scalability**: Can Pub/Sub handle 100,000+ users?
   - **Answer**: Yes, Pub/Sub is designed for millions of messages

4. **Fallback**: What if Pub/Sub is down?
   - **Solution**: Fall back to batch sync every 5 minutes

5. **Privacy**: Do we store Pub/Sub message contents?
   - **Answer**: No, Pub/Sub only contains history ID, we fetch full email via API

---

**Priority**: 🟡 **MEDIUM - Premium Feature for Real-Time Intelligence**

**Owner**: Backend Team (Mario)

**Dependencies**:
- Google Cloud Pub/Sub access
- Gmail API watch permission
- WebSocket infrastructure

**Next Steps**:
1. Research Gmail push notifications best practices
2. Set up Pub/Sub in development environment
3. Test webhook latency
4. Prototype real-time gap detection

**Estimated Timeline**: 3 weeks

**Last Updated**: December 2025
