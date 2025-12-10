# Avatar Aggregation - Person-Centric Contact Intelligence

## Overview

The Avatar Aggregation system builds comprehensive person-centric intelligence by aggregating data from multiple communication sources (emails, calendar events) without making expensive LLM calls. It performs pure data aggregation and statistical analysis to create rich contact profiles.

## Key Concepts

### Person-Centric Architecture

**A person is NOT an email address.** A person can have:
- Multiple email addresses (work, personal, aliases)
- Multiple phone numbers (mobile, office, WhatsApp)
- Multiple names (formal name, nickname, company role)

The avatar system reflects this reality by using a **contact ID** that links all identifiers for the same person.

### Contact ID Generation

Each contact gets a stable 12-character ID (MD5 hash prefix) based on their primary identifier:

```python
contact_id = generate_contact_id(email="john@example.com")
# Returns: "5d41402abc4b"  # First 12 chars of MD5 hash
```

**Key benefits**:
- Deterministic: Same email always generates same ID
- Privacy-preserving: No PII in the ID itself
- Collision-resistant: MD5 truncated to 12 chars (~68 billion combinations)

### Identifier Map

The `identifier_map` table links all identifiers to a contact:

| owner_id | contact_id | identifier_type | identifier | created_at |
|----------|------------|----------------|------------|------------|
| user123 | 5d41402abc4b | email | john@example.com | 2025-12-01 |
| user123 | 5d41402abc4b | email | john.doe@company.com | 2025-12-02 |
| user123 | 5d41402abc4b | phone | +1234567890 | 2025-12-03 |

**When querying**: "Find all emails for John" → Lookup all identifiers for contact `5d41402abc4b` → Query emails matching ANY identifier.

## What Avatar Aggregation Does

### 1. Data Collection (No LLM)

The `AvatarAggregator` class builds context by querying Supabase tables:

**Sources**:
- **Emails**: Recent emails (last 50, within 30 days) from `emails` table
- **Calendar**: Recent meetings (last 20, within 30 days) from `calendar_events` table
- **Identifiers**: All email/phone mappings from `identifier_map` table

**Performance**: Pure SQL queries, no external API calls, <100ms response time

### 2. Statistical Analysis

Computes metrics using deterministic math (no AI):

#### Response Latency
Analyzes email thread timestamps to calculate:
- **Median response time**: How quickly contact typically replies
- **P90 response time**: 90th percentile (slowest responses)
- **Sample size**: Number of measured responses

**Algorithm**:
```python
for each thread:
    for each pair of consecutive emails:
        if current.from_email == contact_email:
            time_diff = current.timestamp - previous.timestamp
            response_times.append(time_diff_hours)

median = np.median(response_times)
p90 = np.percentile(response_times, 90)
```

**Filters outliers**: Response times >30 days excluded (likely stale threads)

#### Communication Frequency
- **Emails per week**: Average based on date range of recent emails
- **Events per month**: Count of calendar meetings in last 30 days
- **Last contact**: Days since most recent email

#### Relationship Strength (0-1 score)
Combines three factors:
- **Recency**: Exponential decay over 30 days (`exp(-days_since_last / 30)`)
- **Frequency**: Logarithmic scale of email count (`log(1 + count) / 5`)
- **Engagement**: Meetings boost strength (`0.5 + events * 0.1`, capped at 1.0)

**Formula**: `strength = recency * frequency * engagement`

**Example scores**:
- `0.9`: Very active contact (emails daily, recent meeting)
- `0.5`: Moderate contact (weekly emails, occasional meetings)
- `0.1`: Weak contact (monthly emails, no recent meetings)
- `0.0`: Dormant contact (no communication in 60+ days)

### 3. Context Assembly

Returns aggregated context dict ready for avatar generation:

```python
{
    'contact_id': '5d41402abc4b',
    'identifiers': {
        'emails': ['john@example.com', 'john.doe@company.com'],
        'phones': ['+1234567890']
    },
    'display_name': 'John Doe',
    'thread_count': 15,
    'email_count': 42,
    'threads': [  # Last 10 threads for LLM context
        {
            'thread_id': 'thread_1',
            'subject': 'Re: Project Update',
            'snippet': 'Thanks for the update...',
            'from_email': 'john@example.com',
            'from_name': 'John Doe',
            'date': '2025-12-07T10:30:00Z',
            'body_plain': 'Full email body...'
        },
        # ... 9 more threads
    ],
    'calendar_events': [  # Last 5 meetings
        {
            'event_id': 'event_1',
            'summary': 'Weekly sync with John',
            'start_time': '2025-12-06T14:00:00Z',
            'end_time': '2025-12-06T15:00:00Z',
            'attendees': ['john@example.com', 'team@company.com']
        },
        # ... 4 more events
    ],
    'response_latency': {
        'median_hours': 2.5,
        'p90_hours': 8.0,
        'sample_size': 23,
        'by_channel': {'email': 2.5}
    },
    'communication_frequency': {
        'emails_per_week': 3.2,
        'events_per_month': 4,
        'last_contact_days_ago': 1
    },
    'relationship_strength': 0.87
}
```

## Implementation Details

### File Reference
**Source**: `zylch/services/avatar_aggregator.py` (382 lines)

### Key Classes

#### `AvatarAggregator`
Main aggregation service.

**Methods**:
- `build_context(owner_id, contact_id)` → Dict
  - Aggregates all data for contact
  - Returns context ready for LLM avatar generation

**Private methods**:
- `_get_identifiers(owner_id, contact_id)` → List[Dict]
  - Fetches all emails/phones for contact from `identifier_map`

- `_get_recent_emails(owner_id, emails, cutoff_date, limit)` → List[Dict]
  - Queries `emails` table for recent threads
  - Filters to emails involving contact (from/to/cc)

- `_get_calendar_events(owner_id, emails, cutoff_date, limit)` → List[Dict]
  - Queries `calendar_events` table
  - Filters to events where contact is attendee

- `_compute_response_latency(owner_id, contact_id, emails)` → Optional[Dict]
  - Calculates response time patterns from thread timestamps
  - Returns median, P90, sample size

- `_compute_frequency(threads, events)` → Dict
  - Calculates emails/week, events/month, last contact

- `_compute_relationship_strength(threads, events)` → float
  - Returns 0-1 score based on recency, frequency, engagement

- `_extract_name(threads, identifiers)` → str
  - Returns most common `from_name` from threads
  - Falls back to email prefix if no name found

- `_empty_context(contact_id)` → Dict
  - Returns empty context when no data exists

#### Utility Functions

**`normalize_identifier(value, identifier_type)`**:
- Normalizes identifiers for stable hashing
- Email: lowercase + strip
- Phone: remove all non-digits
- Name: lowercase + strip

**`generate_contact_id(email, phone, name)`**:
- Generates 12-char contact ID from primary identifier
- Returns MD5 hash prefix

### Database Schema

**`identifier_map` table**:
```sql
CREATE TABLE identifier_map (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  owner_id TEXT NOT NULL,
  contact_id TEXT NOT NULL,  -- 12-char MD5 hash
  identifier_type TEXT NOT NULL,  -- 'email', 'phone', 'name'
  identifier TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(owner_id, contact_id, identifier_type, identifier)
);

CREATE INDEX idx_identifier_lookup ON identifier_map(owner_id, identifier_type, identifier);
CREATE INDEX idx_contact_lookup ON identifier_map(owner_id, contact_id);
```

## Usage Example

### Von Neumann Architecture Integration

**IMPORTANT**: In the new Von Neumann Memory Architecture, avatar aggregation is orchestrated by specialized agents:

**Flow**:
1. **Memory Agent** extracts identifiers from synced data → stores in `identifier_map`
2. **CRM Agent** calls `AvatarAggregator.build_context()` → gets aggregated context
3. **CRM Agent** generates avatar via LLM → stores in `avatars` table

### Direct Usage (for testing/debugging)

The avatar aggregator can be used directly:

```python
from zylch.services.avatar_aggregator import AvatarAggregator
from zylch.storage.supabase_client import SupabaseStorage

# Initialize
storage = SupabaseStorage(owner_id="user123")
aggregator = AvatarAggregator(storage)

# Build context for contact
contact_id = "5d41402abc4b"
context = aggregator.build_context(owner_id="user123", contact_id=contact_id)

# Context ready for avatar generation (separate LLM call)
print(f"Contact: {context['display_name']}")
print(f"Emails/week: {context['communication_frequency']['emails_per_week']}")
print(f"Relationship strength: {context['relationship_strength']}")
```

### Adding New Identifier

When a new email/phone is discovered:

```python
from zylch.services.avatar_aggregator import generate_contact_id, normalize_identifier

# New email discovered
new_email = "john.doe@company.com"
contact_id = generate_contact_id(email=new_email)  # "5d41402abc4b"

# Store in identifier_map
storage.client.table('identifier_map').insert({
    'owner_id': 'user123',
    'contact_id': contact_id,
    'identifier_type': 'email',
    'identifier': normalize_identifier(new_email, 'email')
}).execute()

# Now avatar aggregator will include this email when building context
```

## Performance Characteristics

### Query Performance
- **Identifier lookup**: <10ms (indexed by `owner_id`, `identifier`)
- **Email fetch**: <50ms (indexed by `owner_id`, `date_timestamp`)
- **Calendar fetch**: <30ms (indexed by `owner_id`, `start_time`)
- **Total context build**: <100ms for typical contact

### Data Volume Limits
- **Emails**: Fetches last 50 emails within 30 days
- **Calendar**: Fetches last 20 events within 30 days
- **Response latency**: Analyzes up to 50 threads

**Rationale**: Recent data is most relevant for relationship intelligence. Historical data preserved but not used for avatar context.

### Memory Usage
- Context dict: ~10KB per contact (10 threads + 5 events)
- Cached in memory: No (built on-demand per request)
- Database query results: Released immediately after processing

## Integration with Avatar Generation

### Von Neumann Memory Architecture Integration

**IMPORTANT**: Avatar aggregation now integrates with the **Von Neumann Memory Agent** architecture:

**Architecture Flow**:
```
Raw data → Memory Agent (extracts/stores identifiers) → CRM Agent (computes avatars) → Avatar aggregation (pulls computed state)
```

**Three-Stage Process**:

**Stage 1: Memory Agent** (Identifier extraction and storage)
```
Raw emails/events → Memory Agent → identifier_map table
```
- Memory Agent extracts all identifiers (emails, phones, names)
- Stores normalized identifiers in `identifier_map`
- Maintains contact_id linkages automatically

**Stage 2: CRM Agent** (Avatar computation, uses LLM)
```
Identifier context → CRM Agent + Claude Haiku → avatars table
```
- CRM Agent fetches context via AvatarAggregator
- Generates avatar intelligence using LLM
- Stores in `avatars` table with pg_vector

**Stage 3: Aggregation** (This service, no LLM)
```
Stored identifiers + Raw data → AvatarAggregator → Aggregated context
```
- Pulls identifiers from Memory Agent's storage
- Aggregates communication data deterministically
- Returns context ready for CRM Agent

**Separation rationale**:
- Memory Agent handles identifier management (deterministic)
- Aggregation is deterministic, fast, free
- Avatar generation uses LLM via CRM Agent, slower, costs money
- Aggregation can be cached/pre-computed
- Avatar generation only when context changes

### Avatar Schema

The generated avatar (from Stage 2) includes:

```json
{
  "contact_id": "5d41402abc4b",
  "display_name": "John Doe",
  "relationship_type": "client",
  "communication_style": "formal",
  "topics_of_interest": ["product updates", "technical questions"],
  "suggested_next_actions": ["Follow up on proposal", "Schedule demo"],
  "relationship_strength": 0.87,
  "last_interaction": "2025-12-07T10:30:00Z",
  "aggregation_timestamp": "2025-12-08T09:00:00Z"
}
```

**Stored in**: `avatars` table (Supabase pg_vector for semantic search)

## Known Limitations

1. **30-day window**: Only considers recent data (configurable in code)
2. **Email-centric**: Optimized for email, calendar; WhatsApp/phone not yet integrated
3. **No duplicate detection**: Assumes identifier_map correctly links all identifiers
4. **Statistical only**: No sentiment analysis or content understanding (that's in Stage 2)
5. **No caching**: Context rebuilt on every request (future: cache with TTL)

## Future Enhancements

### Planned (Phase I.5+)
- **Microsoft Calendar**: Include Outlook events in aggregation
- **WhatsApp Integration**: Add WhatsApp message threads when StarChat API available
- **Phone Call Logs**: Integrate MrCall telephony data
- **Response latency by channel**: Separate stats for email, WhatsApp, phone

### Optimization (Phase J - Scaling)
- **Context caching**: Cache aggregated context with 1-hour TTL
- **Incremental updates**: Update context on new email instead of full rebuild
- **Batch processing**: Aggregate multiple contacts in parallel
- **Redis caching**: Cache identifier lookups for O(1) performance

### Intelligence Improvements
- **Interaction patterns**: Detect time-of-day preferences
- **Topic clustering**: Group threads by semantic topic
- **Network analysis**: Identify shared contacts and relationships
- **Sentiment tracking**: Analyze tone changes over time (requires LLM)

## Related Documentation

- **[Memory System](memory-system.md)** - Person-centric memory with reconsolidation
- **[Relationship Intelligence](relationship-intelligence.md)** - Gap detection using avatars
- **[Email Archive](email-archive.md)** - Source data for avatar aggregation
- **[Calendar Integration](calendar-integration.md)** - Meeting data source
- **[Architecture](../../.claude/ARCHITECTURE.md#memory-system-philosophy)** - Person-centric design philosophy

## References

**Source Code**:
- `zylch/services/avatar_aggregator.py` - Main aggregation service (382 lines)
- `zylch/agents/memory_agent.py` - Von Neumann Memory Agent (extracts/stores identifiers)
- `zylch/agents/crm_agent.py` - CRM Agent (computes avatars using aggregated context)
- `zylch/storage/supabase_client.py` - Database access layer

**Note**: The original `avatar_compute_worker.py` has been replaced by the **Von Neumann Memory Architecture**. Avatar computation is now handled by the **CRM Agent** (`crm_agent.py`), which pulls identifier data from the **Memory Agent** (`memory_agent.py`) and uses `AvatarAggregator` to build context.

**Database Tables**:
- `identifier_map` - Email/phone to contact_id mapping
- `emails` - Email archive
- `calendar_events` - Calendar meetings
- `avatars` - Generated contact intelligence (pg_vector)

---

**Last Updated**: December 2025 (Updated for Von Neumann Memory Architecture)
