# Von Neumann Memory Architecture - Implementation Plan

## Executive Summary

This document defines the implementation of Zylch's Von Neumann memory architecture where Memory is the single source of truth and Avatar/CRM is a computed, volatile view.

**Architecture:**
```
Email/Calendar/WhatsApp → Memory Agent → MEMORY → CRM Agent → AVATAR
```

**Key Principle:** All knowledge flows through Memory first. Avatar state is computed from Memory + timestamps and can be recalculated at any time.

---

## Section 1: Memory Agent Design

### 1.1 Core Responsibilities

The Memory Agent is the **write path** from I/O to Memory storage.

**What it does:**
- Extracts stable facts from emails, calendar, WhatsApp
- Writes knowledge to Memory (with reconsolidation)
- Identifies contact information (phones, LinkedIn)
- Detects communication preferences (language, tone)
- Records past events as immutable facts

**What it does NOT do:**
- Compute status/priority (that's CRM Agent's job)
- Make actionable recommendations (that's CRM Agent's job)
- Generate "tasks" or "next actions" (that's CRM Agent's job)

### 1.2 Extraction Rules

#### Contact Information

From email bodies, signatures, and headers:

```python
# Valid Memory content
✓ "Tiziano D'Agostino works at Tesia Snc"
✓ "Phone: +39-348-1234567"
✓ "LinkedIn: linkedin.com/in/tiziano-dagostino"
✓ "Uses Italian in professional communications"
✓ "Prefers formal but cordial tone"
```

**Extraction Methods:**
- **Regex patterns** for phone numbers (E.164, US/Canada, International)
- **LinkedIn URL detection** from email bodies
- **Language detection** from email content
- **Tone analysis** from Claude-powered NLP

**Storage:**
```python
# Store in Memory
memory.store_memory(
    namespace="contact:{email}",
    category="contacts",
    pattern="Phone: +39-348-1234567",
    confidence=0.9
)

# Store in identifier_map for O(1) lookup
storage.upsert_identifier(
    owner_id=owner_id,
    identifier="+393481234567",
    identifier_type="phone",
    contact_id=email
)
```

#### Event Recording

Record past events as immutable facts:

```python
✓ "On 2025-12-03, Tiziano sent email about partnership proposal"
✓ "Meeting held on 2025-11-15: 'Q4 Planning Session'"
✓ "Last email from Tiziano: 2025-12-03"
```

**Characteristics:**
- Use past tense (events are historical)
- Include timestamp (for temporal context)
- Store in `category="events"` in Memory

#### Relationship Knowledge

Extract semantic relationship context:

```python
✓ "Interested in MrCall partnership (mentioned in 3 emails)"
✓ "Works with Mario on technical integrations"
✓ "Typically responds within 24 hours"
```

**Storage:**
- `category="relationships"` in Memory
- Updated via reconsolidation (similar memories are merged)
- Confidence score increases with repeated mentions

### 1.3 Owner Profile

**Special Case:** The owner's preferences are stored in Memory.

```python
namespace: "user:{owner_id}"
category: "preferences"
pattern: "Mario writes emails primarily in Italian"
pattern: "Mario prefers formal tone with executives"
pattern: "Mario typically schedules meetings at 10am"
```

**Auto-detection:**
1. **Language**: Detect from sent emails in `email_archive`
2. **Tone**: Analyze formal/casual patterns in sent emails
3. **Timezone**: Infer from email send times and calendar events
4. **Signature**: Extract from sent emails

**Triggered on first `/sync` after registration.**

### 1.4 Integration with ZylchMemory

```python
# Memory Agent API
memory.store_memory(
    namespace: str,           # "contact:{email}" or "user:{owner_id}"
    category: str,            # "contacts", "events", "relationships", "preferences"
    context: str,             # Descriptive context
    pattern: str,             # The actual knowledge
    examples: List[str],      # Supporting examples (email IDs)
    confidence: float = 0.5   # Initial confidence
) -> str                      # Returns memory_id
```

**Reconsolidation:**
- When storing similar content (cosine > 0.85), ZylchMemory **updates** existing memory instead of creating duplicates
- Prevents conflicting parallel memories
- Mirrors human memory reconsolidation

### 1.5 Trigger Logic

**Hybrid Approach:**

1. **During `/sync`**: Batch process all unprocessed emails (primary path)
2. **On critical emails**: Real-time processing for flagged emails, VIP contacts (future)
3. **On user query**: On-demand processing if no Memory data exists (future)

**Initial implementation: `/sync` batch processing only.**

---

## Section 2: CRM Agent Design

### 2.1 Core Responsibilities

The CRM Agent is the **read path** from Memory to Avatar/CRM (Working Memory).

**What it does:**
- Reads Memory content about contacts
- Reads timestamps from `email_archive` (last email date, direction)
- **Computes** status (open/waiting/closed)
- **Computes** priority (1-10)
- **Generates** suggested action
- Writes to `avatars` table (volatile, can be recalculated)

**What it does NOT do:**
- Extract information from emails (that's Memory Agent's job)
- Store long-term knowledge (that goes in Memory)

### 2.2 Status Computation

Status is computed from **last email direction** + **Memory context**.

```python
def compute_status(last_email_from_owner: bool, memory_context: Dict) -> str:
    """
    Compute relationship status.

    Rules:
    - "open": Contact sent last email → owner needs to respond
    - "waiting": Owner sent last email → waiting for contact's response
    - "closed": Conversation concluded OR no pending items
    """
    if last_email_from_owner:
        # Owner is waiting for contact
        return "waiting"
    else:
        # Contact sent last email → owner needs to respond
        # Check Memory for "no response needed" patterns
        if memory_context.get('no_response_needed'):
            return "closed"
        return "open"
```

**Data sources:**
- `email_archive.last_email_direction` (inbound/outbound)
- `email_archive.last_email_date`
- Memory patterns (e.g., "conversation concluded", "informational email")

### 2.3 Priority Computation

Priority = **urgency** + **importance** + **staleness**

```python
def compute_priority(
    days_since: int,
    relationship_strength: float,
    topic_importance: float
) -> int:
    """
    Compute priority score (1-10).

    Factors:
    1. Urgency: Days since last contact
    2. Importance: Relationship strength, topic
    3. Base score: Always at least 2 for open items

    Returns:
        1-10 score (10 = most urgent)
    """
    # Urgency component (0-4 points)
    if days_since > 7:
        urgency = 4
    elif days_since > 3:
        urgency = 2
    else:
        urgency = 0

    # Importance component (0-4 points)
    importance = int(relationship_strength * 2) + int(topic_importance * 2)

    # Base score
    base = 2

    priority = base + urgency + importance
    return min(10, max(1, priority))
```

**Data sources:**
- `email_archive` (timestamps, email count)
- Memory (relationship strength, topic tags)
- Calendar (meeting frequency)

### 2.4 Action Generation

Suggested actions are **specific** and **actionable**.

**Good actions:**
```
✓ "Reply about partnership proposal (sent 3 days ago)"
✓ "Schedule follow-up meeting (discussed in last email)"
✓ "Send requested documentation"
```

**Bad actions (too vague):**
```
✗ "Follow up"
✗ "Check in"
✗ "Review"
```

**Implementation:**
```python
def generate_action(status: str, memory_context: Dict, email_snippet: str) -> str:
    """Generate specific action using Claude."""
    if status == "closed":
        return None  # No action needed

    prompt = f"""
    Based on this context, what should the owner do next?

    Status: {status}
    Last email: {email_snippet[:200]}
    Relationship context: {memory_context['summary']}

    Provide ONE specific action (max 80 chars).
    """

    # Call Claude for action generation (using user's API key)
    return claude_response.strip()
```

### 2.5 Trigger Logic

**Sequential within `/sync` pipeline:**

```python
# /sync flow
1. Email sync (incremental via Gmail History API)
2. Memory Agent (extract knowledge from new emails)
3. CRM Agent (compute Avatar state from Memory)
4. Display results to user
```

CRM Agent runs **after** Memory Agent completes to ensure Avatar is based on latest Memory.

---

## Section 3: Integration Design

### 3.1 /sync Flow

**Complete Pipeline:**

```python
# zylch/services/sync_service.py
async def run_full_sync(owner_id: str, days_back: int = 30):
    """Full sync pipeline: Email → Memory → CRM → Display."""

    # 1. Email sync (existing)
    await sync_emails(owner_id, days_back)

    # 2. Memory Agent: Extract knowledge
    memory_worker = MemoryWorker(storage, zylch_memory)
    new_emails = get_unprocessed_emails(owner_id)
    await memory_worker.process_batch(new_emails)

    # 3. CRM Agent: Compute Avatar state
    crm_worker = CRMWorker(storage, zylch_memory, anthropic_client)
    affected_contacts = get_affected_contacts(new_emails)
    await crm_worker.compute_batch(affected_contacts)

    # 4. Display results (existing)
    display_gaps(owner_id)
```

**Performance:**

| Stage | Time |
|-------|------|
| Email sync | 1-2s |
| Memory Agent (10 emails) | ~10s |
| CRM Agent (10 contacts) | ~5s |
| **Total** | **~17s** |

**Optimizations:**
- Batch LLM calls (10 emails per Claude request)
- Use Haiku for extraction (cheaper, faster)
- Cache embeddings (ZylchMemory already does this)

### 3.2 Memory Agent Implementation

```python
# zylch/workers/memory_agent.py
class MemoryWorker:
    def __init__(self, storage: SupabaseStorage, memory: ZylchMemory):
        self.storage = storage
        self.memory = memory

    async def process_email(self, email_id: str, owner_id: str):
        """Extract knowledge from email and store in Memory."""
        # 1. Fetch email from email_archive
        email = self.storage.get_email_by_id(email_id)

        # 2. Extract contact info (regex + Claude)
        phones = extract_phone_numbers(email['body_plain'])
        linkedin = extract_linkedin_urls(email['body_plain'])

        # 3. Call Claude for relationship context (optional)
        relationship_context = await self._extract_relationship_context(email)

        # 4. Store in Memory (with reconsolidation)
        contact_id = email['from_email']

        if phones:
            self.memory.store_memory(
                namespace=f"contact:{contact_id}",
                category="contacts",
                context=f"Contact info for {contact_id}",
                pattern=f"Phone: {', '.join(phones)}",
                examples=[email_id],
                confidence=0.9
            )

            # Update identifier_map (O(1) lookup)
            for phone in phones:
                self.storage.upsert_identifier(
                    owner_id=owner_id,
                    identifier=normalize_phone(phone),
                    identifier_type='phone',
                    contact_id=contact_id,
                    source='memory_agent'
                )

        if linkedin:
            self.memory.store_memory(
                namespace=f"contact:{contact_id}",
                category="contacts",
                context=f"LinkedIn profile for {contact_id}",
                pattern=f"LinkedIn: {linkedin[0]}",
                examples=[email_id],
                confidence=1.0
            )

        # 5. Store relationship context
        if relationship_context:
            self.memory.store_memory(
                namespace=f"contact:{contact_id}",
                category="relationships",
                context=f"Relationship with {contact_id}",
                pattern=relationship_context,
                examples=[email_id],
                confidence=0.7
            )
```

### 3.3 CRM Agent Implementation

```python
# zylch/workers/crm_worker.py
class CRMWorker:
    def __init__(self, storage: SupabaseStorage, memory: ZylchMemory, anthropic_client):
        self.storage = storage
        self.memory = memory
        self.anthropic = anthropic_client

    async def compute_avatar(self, contact_id: str, owner_id: str):
        """Compute Avatar state from Memory + timestamps."""
        # 1. Read Memory
        memory_patterns = self.memory.retrieve_memories(
            query=contact_id,
            namespace=f"contact:{contact_id}",
            limit=10
        )

        # 2. Read email_archive for timestamps
        email_stats = self.storage.get_email_stats(owner_id, contact_id)
        # Returns: {
        #   'last_email_from_owner': bool,
        #   'days_since_last_contact': int,
        #   'relationship_strength': float,
        #   'last_email_snippet': str
        # }

        # 3. Compute status
        status = self._compute_status(
            last_email_from_owner=email_stats['last_email_from_owner'],
            memory_context=memory_patterns
        )

        # 4. Compute priority
        priority = self._compute_priority(
            days_since=email_stats['days_since_last_contact'],
            relationship_strength=email_stats['relationship_strength'],
            topic_importance=self._get_topic_importance(memory_patterns)
        )

        # 5. Generate action
        action = await self._generate_action(
            status=status,
            memory_context=memory_patterns,
            email_snippet=email_stats['last_email_snippet']
        )

        # 6. Write to avatars table
        self.storage.upsert_avatar(
            owner_id=owner_id,
            contact_id=contact_id,
            display_name=self._get_display_name(memory_patterns, contact_id),
            relationship_summary=self._build_summary(memory_patterns),
            status=status,
            priority=priority,
            action=action,
            last_computed=datetime.now(timezone.utc)
        )

    def _compute_status(self, last_email_from_owner: bool, memory_context: List) -> str:
        """Compute status from email direction."""
        if last_email_from_owner:
            return "waiting"
        else:
            # Check if no response needed
            for mem in memory_context:
                if 'no response' in mem['pattern'].lower():
                    return "closed"
            return "open"

    def _compute_priority(
        self,
        days_since: int,
        relationship_strength: float,
        topic_importance: float
    ) -> int:
        """Compute priority score (1-10)."""
        # Urgency (0-4)
        urgency = 4 if days_since > 7 else (2 if days_since > 3 else 0)

        # Importance (0-4)
        importance = int(relationship_strength * 2) + int(topic_importance * 2)

        # Base score
        priority = 2 + urgency + importance
        return min(10, max(1, priority))

    async def _generate_action(
        self,
        status: str,
        memory_context: List,
        email_snippet: str
    ) -> Optional[str]:
        """Generate specific action using Claude."""
        if status == "closed":
            return None

        # Build context for Claude
        context_str = "\n".join([m['pattern'] for m in memory_context[:3]])

        prompt = f"""Based on this context, suggest ONE specific action (max 80 chars):

Status: {status}
Last email: {email_snippet[:200]}
Context: {context_str}

Action:"""

        response = self.anthropic.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )

        return response.content[0].text.strip()
```

### 3.4 File Organization

**New files to create:**
```
zylch/workers/
  ├── memory_worker.py        # Memory Agent implementation
  └── crm_worker.py           # CRM Agent implementation
```

**Files to modify:**
```
zylch/services/
  └── sync_service.py         # Add Memory Agent → CRM Agent pipeline

zylch/storage/
  └── supabase_client.py      # Add get_email_stats(), upsert_identifier()
```

**Files to delete/archive:**
```
zylch/workers/
  └── avatar_compute_worker.py  # Old direct-from-emails approach
```

---

## Section 4: Testing Strategy

### 4.1 Unit Tests

**Memory Agent:**
```python
# tests/workers/test_memory_worker.py
def test_extract_phone_numbers():
    text = "Call me at +1-415-555-1234 or 415.555.5678"
    phones = extract_phone_numbers(text)
    assert "+14155551234" in phones
    assert "+14155555678" in phones

def test_reconsolidation():
    """Test that updating phone number reconsolidates existing memory."""
    memory.store_memory(
        namespace="contact:test@example.com",
        category="contacts",
        pattern="Phone: +1234567890"
    )

    memory.store_memory(
        namespace="contact:test@example.com",
        category="contacts",
        pattern="Phone: +9876543210"
    )

    # Should have only ONE memory (reconsolidated)
    memories = memory.retrieve_memories(
        query="phone",
        namespace="contact:test@example.com"
    )
    assert len(memories) == 1
    assert "+9876543210" in memories[0]['pattern']
```

**CRM Agent:**
```python
# tests/workers/test_crm_worker.py
def test_compute_status_open():
    """Contact sent last email → status should be 'open'."""
    status = compute_status(last_email_from_owner=False, memory_context=[])
    assert status == "open"

def test_compute_status_waiting():
    """Owner sent last email → status should be 'waiting'."""
    status = compute_status(last_email_from_owner=True, memory_context=[])
    assert status == "waiting"

def test_compute_priority():
    """7+ days + high relationship strength → priority should be high."""
    priority = compute_priority(
        days_since=8,
        relationship_strength=0.9,
        topic_importance=0.8
    )
    assert priority >= 8

def test_compute_priority_bounds():
    """Priority should be bounded 1-10."""
    priority = compute_priority(
        days_since=30,
        relationship_strength=1.0,
        topic_importance=1.0
    )
    assert 1 <= priority <= 10
```

### 4.2 Integration Tests

```python
# tests/integration/test_von_neumann_flow.py
async def test_full_pipeline():
    """Test Email → Memory → CRM → Avatar flow."""
    # 1. Insert test email
    email_id = insert_test_email(
        owner_id="test_owner",
        from_email="tizio@example.com",
        body="My phone is +39-348-1234567"
    )

    # 2. Run Memory Agent
    memory_worker = MemoryWorker(storage, memory)
    await memory_worker.process_email(email_id, "test_owner")

    # 3. Verify Memory
    memories = memory.retrieve_memories(
        query="phone",
        namespace="contact:tizio@example.com"
    )
    assert len(memories) > 0
    assert "+393481234567" in memories[0]['pattern']

    # 4. Run CRM Agent
    crm_worker = CRMWorker(storage, memory, anthropic_client)
    await crm_worker.compute_avatar("tizio@example.com", "test_owner")

    # 5. Verify Avatar
    avatar = storage.get_avatar("test_owner", "tizio@example.com")
    assert avatar['status'] == "open"
    assert avatar['priority'] >= 5
    assert avatar['action'] is not None
```

### 4.3 End-to-End Tests

```python
# tests/e2e/test_sync.py
async def test_sync_creates_memory_and_avatars():
    """Test that /sync creates both Memory and Avatar entries."""
    # Insert test emails
    insert_test_emails(owner_id="test_owner", count=5)

    # Run /sync
    result = await sync_service.run_full_sync(
        owner_id="test_owner",
        days_back=7
    )

    # Verify Memory populated
    all_memories = memory.retrieve_memories(
        query="",
        namespace="contact:*",
        limit=100
    )
    assert len(all_memories) > 0

    # Verify Avatars created
    avatars = storage.get_all_avatars("test_owner")
    assert len(avatars) > 0

    # Verify gaps
    gaps = storage.get_relationship_gaps("test_owner")
    assert len(gaps) > 0
```

---

## Section 5: Performance Optimization

### 5.1 Batch Processing

**Memory Agent:**
- Process 10 emails per Claude API call
- Use Haiku for extraction (10x cheaper than Sonnet)
- Cache embeddings (already implemented in ZylchMemory)

**CRM Agent:**
- Compute avatars in parallel for affected contacts
- Reuse Memory queries across contacts (batch retrieval)

### 5.2 Caching Strategy

**identifier_map table:**
- O(1) lookup from phone/email to contact_id
- Avoids expensive remote API calls (Gmail takes 10+ seconds)
- TTL: 7 days (refresh if stale)

**ZylchMemory embeddings:**
- Automatic caching in `embeddings` table
- Prevents re-computing embeddings for same text

---

## Section 6: Success Metrics

### 6.1 Technical Metrics

- **Memory coverage**: 100% of contacts have Memory entries after `/sync`
- **Identifier coverage**: All phones/LinkedIn stored in `identifier_map`
- **CRM accuracy**: Avatar status matches last email direction (95%+ accuracy)
- **Performance**: `/sync` completes in <20s for 30-day window
- **Consistency**: Memory and Avatar timestamps within 1 min

### 6.2 Cost Metrics

- **LLM cost**: <$1 per user per month
  - Haiku: $0.25 per million input tokens
  - 10 emails/day * 30 days * 500 tokens/email = 150k tokens/month
  - Cost: ~$0.04/month for extraction

---

## Section 7: Implementation Timeline

### Week 1-2: Memory Agent
- Implement `MemoryWorker` class
- Add extraction logic (regex + Claude)
- Test reconsolidation
- Integrate with `/sync`

### Week 3-4: CRM Agent
- Implement `CRMWorker` class
- Add status/priority computation
- Add action generation
- Test with real data

### Week 5: Integration & Testing
- Wire Memory Agent → CRM Agent pipeline
- E2E testing with real Gmail accounts
- Performance tuning

### Week 6: Polish & Deploy
- Documentation
- Error handling
- Monitoring/logging
- Deploy to staging

**Total: 6 weeks from start to production**

---

## Section 8: Open Questions

1. **Should Memory Agent use Claude or just regex for phone/LinkedIn extraction?**
   - Claude: More accurate, higher cost (~$0.003/email)
   - Regex: Faster, cheaper, less accurate
   - **Recommendation**: Regex for phones/LinkedIn, Claude for relationship context

2. **Should we extract owner profile on first `/sync` or manual setup?**
   - Auto: Convenient, may be inaccurate
   - Manual: Accurate, requires user effort
   - **Recommendation**: Auto-detect with manual override in settings

3. **How to handle extraction errors (e.g., invalid phone numbers)?**
   - Option A: Store anyway, let user correct
   - Option B: Skip invalid data
   - **Recommendation**: Store with lower confidence (0.5), allow user correction

4. **Should CRM Agent call Claude for every avatar computation?**
   - Yes: More accurate actions, higher cost
   - No: Template-based actions, cheaper
   - **Recommendation**: Use Claude with Haiku (cheap enough at $0.001/request)

---

## Appendix: SQL Queries

### Get Email Stats for CRM Agent

```sql
-- zylch/storage/supabase_client.py: get_email_stats()
WITH owner_emails AS (
    SELECT ARRAY_AGG(DISTINCT from_email)
    FROM email_archive
    WHERE owner_id = $1 AND from_email = ANY($2)
),
contact_stats AS (
    SELECT
        COUNT(*) as email_count,
        MAX(date) as last_email_date,
        MAX(CASE WHEN from_email = ANY(SELECT * FROM owner_emails)
            THEN date END) as last_owner_email,
        MAX(CASE WHEN from_email != ALL(SELECT * FROM owner_emails)
            THEN date END) as last_contact_email,
        MAX(CASE WHEN from_email = ANY(SELECT * FROM owner_emails)
            THEN snippet END) as last_email_snippet
    FROM email_archive
    WHERE owner_id = $1
      AND (from_email = $3 OR $3 = ANY(to_emails))
)
SELECT
    email_count,
    EXTRACT(DAYS FROM NOW() - last_email_date) as days_since_last_contact,
    (last_owner_email > last_contact_email) as last_email_from_owner,
    last_email_snippet,
    -- Relationship strength: emails per week over last 90 days
    (SELECT COUNT(*) FROM email_archive
     WHERE owner_id = $1
       AND (from_email = $3 OR $3 = ANY(to_emails))
       AND date > NOW() - INTERVAL '90 days'
    ) / 13.0 as relationship_strength
FROM contact_stats;
```

---

## Conclusion

This implementation plan establishes Zylch's Von Neumann architecture from scratch:

**Data Flow:**
```
I/O → Memory Agent → Memory → CRM Agent → Avatar
```

**Key Benefits:**
1. **Memory is single source of truth** for all knowledge
2. **Avatar is computed view** (can be recalculated anytime)
3. **Clean separation of concerns** (extraction vs computation)
4. **Semantic search enabled** (pg_vector for Memory queries)

**Next Steps:**
1. Review and approve this plan
2. Begin Week 1 implementation (Memory Agent)
3. Iterate based on real data testing
