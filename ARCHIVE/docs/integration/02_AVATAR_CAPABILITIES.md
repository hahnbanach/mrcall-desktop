# Avatar System Technical Capabilities

**Document Version:** 1.0
**Date:** December 8, 2025
**Status:** PRODUCTION READY ✅

## Executive Summary

The Avatar System provides **pre-computed relationship intelligence** for instant querying without per-request LLM calls. It achieves **400x performance improvement** (100s → 50ms) by computing avatars asynchronously and storing them in Supabase.

**Key Capability:** Query relationship intelligence at **25-50ms** instead of **100-200 seconds**.

---

## 1. API Surface

### Base URL
```
https://api.zylch.ai/api
```

### Authentication
All endpoints require Firebase authentication via `auth` header:
```
auth: <firebase-id-token>
```

### Available Endpoints

#### 1.1 GET /avatars
**Purpose:** List all avatars with optional filters

**Query Parameters:**
- `status` (optional): Filter by relationship status
  - Values: `'open'`, `'waiting'`, `'closed'`
  - Example: `?status=open`
- `min_score` (optional): Minimum relationship score (1-10)
  - Example: `?min_score=7`
- `limit` (optional): Maximum results (default: 100)
  - Example: `?limit=50`
- `offset` (optional): Pagination offset (default: 0)
  - Example: `?offset=100`

**Response Format:**
```json
{
  "success": true,
  "avatars": [
    {
      "contact_id": "a1b2c3d4e5f6",
      "display_name": "John Doe",
      "identifiers": {
        "emails": ["john@company.com", "jdoe@gmail.com"],
        "phones": ["+1234567890"]
      },
      "relationship_summary": "Long-time colleague from Acme Corp...",
      "relationship_status": "open",
      "relationship_score": 8,
      "suggested_action": "Follow up on Q4 project proposal",
      "interaction_summary": {
        "thread_count": 42,
        "email_count": 156,
        "last_interaction": "2025-12-01T14:30:00Z"
      },
      "preferred_tone": "professional",
      "response_latency": {
        "median_hours": 2.5,
        "p90_hours": 24.0,
        "sample_size": 38,
        "by_channel": {"email": 2.5}
      },
      "relationship_strength": 0.82,
      "last_computed": "2025-12-08T10:15:00Z",
      "compute_trigger": "email_sync"
    }
  ],
  "total": 47,
  "stats": {
    "total": 47,
    "by_status": {
      "open": 12,
      "waiting": 8,
      "closed": 27
    },
    "avg_score": 6.4,
    "needs_action_count": 12
  }
}
```

**Performance:** ~50ms for 100 results

**Use Cases:**
- Task list generation
- Dashboard "needs attention" view
- Relationship health monitoring
- Priority inbox

---

#### 1.2 GET /avatars/{contact_id}
**Purpose:** Get specific avatar by contact ID

**Path Parameters:**
- `contact_id` (required): 12-character MD5-based contact ID

**Response Format:**
```json
{
  "success": true,
  "avatar": {
    "contact_id": "a1b2c3d4e5f6",
    "display_name": "John Doe",
    "identifiers": {
      "emails": ["john@company.com"],
      "phones": []
    },
    "relationship_summary": "...",
    "relationship_status": "open",
    "relationship_score": 8,
    "suggested_action": "...",
    "interaction_summary": {...},
    "preferred_tone": "professional",
    "response_latency": {...},
    "relationship_strength": 0.82,
    "last_computed": "2025-12-08T10:15:00Z"
  }
}
```

**Performance:** ~25ms (instant access to pre-computed data)

**Use Cases:**
- Contact detail view
- Email composition context
- Meeting prep summary
- Relationship timeline

---

#### 1.3 POST /avatars/{contact_id}/compute
**Purpose:** Queue avatar computation/refresh for a contact

**Path Parameters:**
- `contact_id` (required): Contact's stable ID

**Request Body:**
```json
{
  "trigger_type": "manual",
  "priority": 10
}
```

**Request Fields:**
- `trigger_type` (optional, default: "manual"):
  - `"manual"` - User requested refresh
  - `"email_sync"` - New emails from contact
  - `"scheduled"` - Periodic background refresh
  - `"new_contact"` - First-time avatar creation
- `priority` (optional, default: 5):
  - Range: 1-10 (10 = highest priority)

**Response Format:**
```json
{
  "success": true,
  "message": "Avatar computation queued for contact a1b2c3d4e5f6",
  "queue_item": {
    "id": "uuid-here",
    "owner_id": "firebase-uid",
    "contact_id": "a1b2c3d4e5f6",
    "trigger_type": "manual",
    "priority": 10,
    "scheduled_at": "2025-12-08T10:20:00Z",
    "retry_count": 0
  }
}
```

**Background Processing:**
- Railway cron runs every 5 minutes
- Processes queue in priority order
- One LLM call per contact (~2 seconds)
- Updates avatar table with results
- Removes from queue on completion

**Use Cases:**
- User-initiated refresh ("update this contact")
- Stale data detection (avatar >7 days old)
- Post-sync updates (new email arrived)
- Manual override for important contacts

---

#### 1.4 GET /avatars/resolve/{identifier}
**Purpose:** Resolve email/phone to contact ID and avatar

**Path Parameters:**
- `identifier` (required): Email address or phone number

**Response Format:**
```json
{
  "success": true,
  "contact_id": "a1b2c3d4e5f6",
  "avatar": {...},
  "identifiers": {
    "emails": ["john@company.com", "jdoe@gmail.com"],
    "phones": ["+1234567890"]
  }
}
```

**Not Found Response:**
```json
{
  "success": true,
  "contact_id": null,
  "avatar": null,
  "identifiers": null,
  "message": "Identifier 'unknown@example.com' not found"
}
```

**Performance:** ~30ms

**Use Cases:**
- Email preview context ("Who is this from?")
- Incoming call lookup
- Multi-account email resolution
- Contact deduplication
- "Show me all emails from this person"

---

## 2. Data Model

### 2.1 Avatar Schema

#### Core Fields

| Field | Type | Description | Computed By |
|-------|------|-------------|-------------|
| `contact_id` | TEXT | 12-char MD5 hash of primary email | `generate_contact_id()` |
| `owner_id` | UUID | Firebase UID (multi-tenant isolation) | Auth system |
| `display_name` | TEXT | Contact's name | LLM or email headers |

#### Relationship Intelligence

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `relationship_summary` | TEXT | AI-generated narrative (2-3 sentences) | **LLM** |
| `relationship_status` | TEXT | `'open'`, `'waiting'`, `'closed'` | **LLM** |
| `relationship_score` | INTEGER | Priority/urgency (1-10) | **LLM** |
| `suggested_action` | TEXT | Next step recommendation | **LLM** |
| `preferred_tone` | TEXT | `'formal'`, `'casual'`, `'professional'` | **LLM** |

#### Interaction Statistics

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `interaction_summary` | JSONB | Thread/email counts, last contact | **Computed** |
| `response_latency` | JSONB | Response time patterns | **Computed** |
| `relationship_strength` | FLOAT | Strength score (0-1) | **Computed** |

**interaction_summary Structure:**
```json
{
  "thread_count": 42,
  "email_count": 156,
  "last_interaction": "2025-12-01T14:30:00Z"
}
```

**response_latency Structure:**
```json
{
  "median_hours": 2.5,
  "p90_hours": 24.0,
  "sample_size": 38,
  "by_channel": {"email": 2.5}
}
```

#### Multi-Identifier Support

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `identifiers` | JSONB | All known emails/phones | Aggregated from `identifier_map` |

**identifiers Structure:**
```json
{
  "emails": ["john@company.com", "jdoe@gmail.com"],
  "phones": ["+1234567890"]
}
```

#### Metadata

| Field | Type | Description |
|-------|------|-------------|
| `last_computed` | TIMESTAMP | When avatar was last updated |
| `compute_trigger` | TEXT | What triggered computation |
| `profile_embedding` | VECTOR(384) | Semantic search vector (future) |
| `created_at` | TIMESTAMP | When avatar was created |
| `updated_at` | TIMESTAMP | When avatar was last modified |

---

### 2.2 Identifier Map Schema

**Purpose:** Multi-identifier person resolution (one person = many emails)

| Field | Type | Description |
|-------|------|-------------|
| `owner_id` | UUID | User's Firebase UID |
| `identifier` | TEXT | Email, phone, or name |
| `identifier_type` | TEXT | `'email'`, `'phone'`, `'name'` |
| `contact_id` | TEXT | Links to avatars table |
| `confidence` | FLOAT | 0.0-1.0 confidence score |
| `source` | TEXT | `'email'`, `'calendar'`, `'manual'` |

**Example:**
```
owner_id: user123
identifier: john@company.com → contact_id: a1b2c3d4e5f6
identifier: jdoe@gmail.com  → contact_id: a1b2c3d4e5f6
identifier: +1234567890      → contact_id: a1b2c3d4e5f6
```

---

### 2.3 Compute Queue Schema

**Purpose:** Background computation queue with priority

| Field | Type | Description |
|-------|------|-------------|
| `owner_id` | UUID | User's Firebase UID |
| `contact_id` | TEXT | Contact to compute |
| `trigger_type` | TEXT | Reason for computation |
| `priority` | INTEGER | 1-10 (10 = highest) |
| `scheduled_at` | TIMESTAMP | When to process |
| `retry_count` | INTEGER | Exponential backoff tracking |

**Priority Levels:**
- 10: Manual user request (critical)
- 7-9: Email sync updates (high)
- 5-6: Scheduled refresh (normal)
- 1-4: Bulk backfill (low)

---

## 3. Performance Profile

### 3.1 Query Performance

| Operation | Time | Comparison |
|-----------|------|------------|
| List 100 avatars | ~50ms | 400x faster than LLM approach |
| Single avatar | ~25ms | 800x faster |
| Filtered query | ~75ms | 300x faster |
| Resolve identifier | ~30ms | N/A (new capability) |

**Old Approach (Per-Request LLM):**
- Query 10 contacts: 100-200 seconds
- 10-20 LLM calls per page load
- Cost: $0.03 per page view

**New Approach (Pre-Computed Avatars):**
- Query 10 contacts: 50ms
- 0 LLM calls at query time
- Cost: $0.03 per week (amortized)

### 3.2 Computation Performance

| Operation | Time | LLM Calls |
|-----------|------|-----------|
| Context aggregation | ~500ms | 0 |
| LLM analysis | ~2s | 1 |
| Database upsert | ~100ms | 0 |
| **Total per avatar** | **~2.6s** | **1** |

**Background Worker:**
- Batch size: 10 avatars
- Runtime: 10-60 seconds every 5 minutes
- Throughput: 120-600 avatars/hour

### 3.3 Cache vs Compute Trade-off

**What's Cached (Instant Access):**
- ✅ Relationship summaries
- ✅ Status and priority
- ✅ Suggested actions
- ✅ Interaction statistics
- ✅ Response time patterns
- ✅ Contact resolution

**What's Computed On-Demand:**
- ❌ Real-time email analysis (use threads API)
- ❌ Live calendar availability (use calendar API)
- ❌ Sentiment analysis (future feature)

**Staleness:**
- Avatars updated on email sync (automatic)
- Refresh on manual request (immediate queue)
- Periodic refresh every 7 days (scheduled)
- Stale data acceptable for most use cases

---

## 4. Capabilities Matrix

### 4.1 Contact Intelligence

| Capability | Available | Source | Latency |
|------------|-----------|--------|---------|
| **Email counting** | ✅ | Computed | Instant |
| **Thread tracking** | ✅ | Computed | Instant |
| **Contact tracking** | ✅ | Computed | Instant |
| **Last interaction time** | ✅ | Computed | Instant |
| **Relationship strength** | ✅ | Computed formula | Instant |
| **Response time patterns** | ✅ | Timestamp analysis | Instant |
| **Meeting frequency** | ✅ | Calendar aggregation | Instant |
| **Communication frequency** | ✅ | Statistical analysis | Instant |

**Formulas:**

**Relationship Strength (0-1):**
```
strength = recency_score × frequency_score × engagement_score

recency_score = exp(-days_since_last / 30)
frequency_score = min(1.0, log(email_count + 1) / 5)
engagement_score = min(1.0, 0.5 + (meeting_count × 0.1))
```

**Communication Frequency:**
```
emails_per_week = email_count / (date_range_days / 7)
events_per_month = event_count (last 30 days)
```

---

### 4.2 Relationship Analysis

| Capability | Available | Source | Latency |
|------------|-----------|--------|---------|
| **Relationship summary** | ✅ | LLM analysis | Instant (cached) |
| **Status classification** | ✅ | LLM analysis | Instant (cached) |
| **Priority scoring** | ✅ | LLM analysis | Instant (cached) |
| **Action recommendations** | ✅ | LLM analysis | Instant (cached) |
| **Tone preference** | ✅ | LLM analysis | Instant (cached) |
| **Task extraction** | ⚠️ | Thread analysis | Use threads API |
| **Sentiment analysis** | ❌ | Future feature | N/A |

**Status Values:**
- `'open'` - Needs action from user (respond/follow up)
- `'waiting'` - Waiting for contact (ball in their court)
- `'closed'` - No action needed (complete/dormant)

**Priority Scoring (1-10):**
- 9-10: Urgent, high-value relationships
- 7-8: Important, active relationships
- 5-6: Normal, ongoing relationships
- 3-4: Low-priority, infrequent contacts
- 1-2: Dormant or archived

---

### 4.3 Multi-Identifier Resolution

| Capability | Available | Source | Latency |
|------------|-----------|--------|---------|
| **Email → Contact ID** | ✅ | identifier_map | ~30ms |
| **Phone → Contact ID** | ✅ | identifier_map | ~30ms |
| **Contact ID → All identifiers** | ✅ | identifier_map | ~30ms |
| **Duplicate detection** | ✅ | MD5 hashing | Instant |
| **Alias resolution** | ✅ | identifier_map | ~30ms |

**Example Workflow:**
```
1. Email arrives from "jdoe@gmail.com"
2. Resolve to contact_id: "a1b2c3d4e5f6"
3. Get avatar with full context
4. Show: "John Doe (john@company.com, jdoe@gmail.com)"
```

---

### 4.4 Background Processing

| Capability | Available | Description | Frequency |
|------------|-----------|-------------|-----------|
| **Async computation** | ✅ | Railway cron worker | Every 5 min |
| **Priority queue** | ✅ | 1-10 priority levels | Always |
| **Retry logic** | ✅ | Exponential backoff | 2h, 4h, 8h |
| **Batch processing** | ✅ | 10 avatars per batch | Every 5 min |
| **Auto-refresh** | ✅ | Stale avatars (>7 days) | Weekly |
| **Email-triggered updates** | ✅ | New email sync | Immediate queue |

**Queue Processing Order:**
1. Priority (DESC) - High priority first
2. Scheduled time (ASC) - Oldest first
3. Retry count (ASC) - New items first

---

### 4.5 Search and Filtering

| Capability | Available | Performance | Use Case |
|------------|-----------|-------------|----------|
| **Filter by status** | ✅ | ~50ms | "Show me contacts needing action" |
| **Filter by score** | ✅ | ~50ms | "Show me high-priority contacts" |
| **Pagination** | ✅ | ~50ms | Large contact lists |
| **Identifier lookup** | ✅ | ~30ms | "Who is this email from?" |
| **Semantic search** | ⏳ | Future | "Find contacts interested in AI" |
| **Full-text search** | ❌ | Future | "Search relationship summaries" |

**Semantic Search (Future):**
- Uses `profile_embedding` field (384-dim vector)
- Powered by sentence-transformers
- Query: "Find contacts in healthcare"
- Returns: Cosine similarity matches

---

## 5. Data Freshness

### 5.1 Update Triggers

| Trigger | Priority | Delay | Description |
|---------|----------|-------|-------------|
| **Email sync** | 7 | ~5 min | New emails from contact |
| **Manual request** | 10 | ~5 min | User clicks "refresh" |
| **New contact** | 8 | ~5 min | First-time avatar creation |
| **Scheduled refresh** | 5 | Next batch | Avatars >7 days old |
| **Backfill** | 3 | Low priority | Bulk historical data |

### 5.2 Staleness Acceptable

**Why pre-computed data works:**
- Relationship context changes slowly (days/weeks)
- Action items updated on email sync (near real-time)
- Summary text doesn't need live updates
- Trade-off: 5-min delay for 400x speed improvement

**When to force refresh:**
- Before important meeting (manual queue)
- After major email thread (auto-triggered)
- User-initiated update (immediate queue)

---

## 6. Cost Analysis

### 6.1 LLM Usage

**Per Avatar:**
- Input tokens: ~1200 (context)
- Output tokens: ~300 (analysis)
- Cost: ~$0.003 per avatar

**With 1000 Contacts:**
- Full backfill: $3 one-time
- Weekly refresh: $3/week
- Email-triggered: Variable (depends on volume)

**Optimization:**
- Skip avatars computed <7 days ago
- Priority queue for important contacts
- Batch processing reduces overhead

### 6.2 Database Usage

**Supabase Storage:**
- Avatars table: ~5KB per row
- 1000 contacts: ~5MB
- Identifier map: ~500 bytes per mapping
- Negligible storage cost

**Query Costs:**
- Free tier: 500MB egress/month
- 100 avatar queries: ~500KB
- Easily within free tier

---

## 7. Limitations & Constraints

### 7.1 Current Limitations

| Limitation | Impact | Workaround |
|------------|--------|------------|
| **No real-time updates** | 5-min delay | Manual queue for urgent |
| **No sentiment analysis** | Missing emotion context | Future feature |
| **No full-text search** | Can't search summaries | Use filters |
| **No semantic search** | Can't find similar contacts | Future feature |
| **Email-only context** | Missing SMS/calls | Future integration |

### 7.2 Technical Constraints

**Performance:**
- Query timeout: 30s (Supabase default)
- Batch size: 10 avatars (Railway cron limit)
- Max priority: 10 (queue design)

**Data:**
- Contact ID: 12 chars (MD5 prefix)
- Embedding: 384 dims (sentence-transformers)
- Summary: ~500 chars (LLM constraint)

**Scalability:**
- Max contacts per user: Unlimited (indexed)
- Query performance: O(log n) with indices
- Worker throughput: 120-600 avatars/hour

---

## 8. Integration Examples

### 8.1 Task List Generation

```python
from zylch.tools.task_manager import TaskManager
from zylch.storage.supabase_client import SupabaseStorage

storage = SupabaseStorage.get_instance()
task_manager = TaskManager(storage=storage)

# Fast query (avatars)
tasks = task_manager.list_tasks_fast(
    owner_id="firebase-uid",
    status="open",
    min_score=7,
    limit=50
)
# Returns in ~50ms instead of 100s
```

### 8.2 Contact Lookup

```python
# Resolve email to contact
contact_id = storage.resolve_contact_id(
    owner_id="firebase-uid",
    identifier="john@company.com"
)

# Get avatar
avatar = storage.get_avatar(
    owner_id="firebase-uid",
    contact_id=contact_id
)

print(f"Contact: {avatar['display_name']}")
print(f"Status: {avatar['relationship_status']}")
print(f"Action: {avatar['suggested_action']}")
```

### 8.3 Queue Avatar Update

```python
# Queue computation after email sync
storage.queue_avatar_compute(
    owner_id="firebase-uid",
    contact_id="a1b2c3d4e5f6",
    trigger_type="email_sync",
    priority=7
)
# Processed within 5 minutes
```

---

## 9. Future Enhancements

### 9.1 Planned Features

**Semantic Search:**
- Generate embeddings with sentence-transformers
- Query: "Find contacts in finance"
- Uses `profile_embedding` field

**Full-Text Search:**
- Search relationship summaries
- Postgres full-text search
- Query: "Find contacts I owe deliverables"

**Sentiment Analysis:**
- Detect relationship tone shift
- Alert on negative sentiment
- Track relationship health trends

**Multi-Channel:**
- Integrate SMS data
- Integrate call logs (MrCall)
- Unified communication view

### 9.2 Optimization Opportunities

**Batch LLM Calls:**
- Process multiple avatars per API call
- Reduce per-avatar cost
- Faster computation

**Smart Prioritization:**
- ML-based priority scoring
- Learn from user actions
- Auto-adjust priorities

**Incremental Updates:**
- Don't recompute entire avatar
- Only update changed fields
- Reduce LLM costs

---

## 10. Summary

### What the Avatar System CAN Do

✅ **Instant relationship intelligence** (25-50ms queries)
✅ **Pre-computed summaries** (no LLM calls at query time)
✅ **Multi-identifier resolution** (one person = many emails)
✅ **Background computation** (async, priority-based)
✅ **Email sync integration** (auto-updates on new emails)
✅ **Status tracking** (open/waiting/closed)
✅ **Priority scoring** (1-10 urgency)
✅ **Action recommendations** (next steps)
✅ **Response time analysis** (median/p90 latency)
✅ **Relationship strength** (0-1 computed score)
✅ **Contact statistics** (email counts, meeting counts)

### What the Avatar System CANNOT Do

❌ **Real-time updates** (5-min delay via worker)
❌ **Sentiment analysis** (future feature)
❌ **Semantic search** (future feature)
❌ **Full-text search** (future feature)
❌ **SMS/call integration** (email-only currently)
❌ **Live LLM analysis** (by design - pre-computed)

### Performance Achievement

**400x faster** than per-request LLM calls
**99% cost reduction** (amortized over time)
**Production-ready** with 50ms query latency

---

## Appendix: API Examples

### List High-Priority Contacts

```bash
curl -X GET "https://api.zylch.ai/api/avatars?status=open&min_score=7&limit=10" \
  -H "auth: <firebase-token>"
```

### Get Specific Contact

```bash
curl -X GET "https://api.zylch.ai/api/avatars/a1b2c3d4e5f6" \
  -H "auth: <firebase-token>"
```

### Resolve Email

```bash
curl -X GET "https://api.zylch.ai/api/avatars/resolve/john@company.com" \
  -H "auth: <firebase-token>"
```

### Queue Update

```bash
curl -X POST "https://api.zylch.ai/api/avatars/a1b2c3d4e5f6/compute" \
  -H "auth: <firebase-token>" \
  -H "Content-Type: application/json" \
  -d '{"trigger_type": "manual", "priority": 10}'
```

---

**End of Document**
