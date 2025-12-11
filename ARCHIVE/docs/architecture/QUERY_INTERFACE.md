# Query Interface Design - Avatar Architecture Evolution

**Version:** 1.0.0
**Author:** Zylch Team
**Date:** December 2025

---

## Executive Summary

This document defines the Query Interface for Zylch's Avatar Architecture—a **fast, free, and intelligent** system for retrieving avatar data WITHOUT unnecessary LLM calls. The goal is to make common queries (tasks, contact info, recent interactions) instant and cost-free while reserving LLM calls for complex synthesis and reasoning.

**Key Principles:**
- **Pre-computed > On-demand > LLM** (cost/latency hierarchy)
- **Avatar = Cached Intelligence** (not just data storage)
- **Query patterns determine architecture** (UI flows dictate API design)

---

## Table of Contents

1. [Avatar Retrieval API](#avatar-retrieval-api)
2. [Query Patterns](#query-patterns)
3. [LLM Call Boundaries](#llm-call-boundaries)
4. [Pre-Computed vs On-Demand](#pre-computed-vs-on-demand)
5. [Caching Strategy](#caching-strategy)
6. [Implementation Examples](#implementation-examples)
7. [Performance Benchmarks](#performance-benchmarks)

---

## Avatar Retrieval API

### Core Interface

```python
class AvatarQueryInterface:
    """Fast, zero-LLM avatar retrieval interface."""

    # ===== EXACT LOOKUP (0 LLM calls, <1ms) =====

    def get_avatar(
        self,
        user_id: str,
        contact_id: str
    ) -> Avatar:
        """Retrieve complete avatar profile.

        Returns:
            Avatar object with all pre-computed fields

        Cost: 0 LLM calls
        Latency: <1ms (SQLite SELECT)
        """

    def get_avatar_by_email(
        self,
        user_id: str,
        email: str
    ) -> Optional[Avatar]:
        """Lookup avatar by email address.

        Returns:
            Avatar if found, None otherwise

        Cost: 0 LLM calls
        Latency: <1ms (indexed lookup)
        """

    def get_avatar_by_phone(
        self,
        user_id: str,
        phone: str
    ) -> Optional[Avatar]:
        """Lookup avatar by phone number.

        Returns:
            Avatar if found, None otherwise

        Cost: 0 LLM calls
        Latency: <1ms (normalized phone index)
        """

    def search_avatars_by_name(
        self,
        user_id: str,
        name_query: str,
        limit: int = 10
    ) -> List[Avatar]:
        """Fuzzy search avatars by display name.

        Cost: 0 LLM calls
        Latency: <5ms (LIKE query with trigram index)
        """

    # ===== FILTERED QUERIES (0 LLM calls, <10ms) =====

    def get_recent_interactions(
        self,
        user_id: str,
        limit: int = 20,
        days_back: int = 7
    ) -> List[AvatarInteractionSummary]:
        """Get avatars with recent interactions, sorted by recency.

        Returns:
            List of {avatar, last_interaction, interaction_count}

        Cost: 0 LLM calls
        Latency: <10ms (pre-computed last_interaction field)
        """

    def get_tasks_by_avatar(
        self,
        user_id: str,
        contact_id: str,
        status: Optional[str] = None  # "open", "waiting", "closed"
    ) -> List[TaskSummary]:
        """Get all tasks related to a specific contact.

        Returns:
            List of task summaries (pre-computed from email threads)

        Cost: 0 LLM calls
        Latency: <5ms (foreign key join)
        """

    def get_all_tasks(
        self,
        user_id: str,
        status: Optional[str] = None,
        min_score: Optional[int] = None,
        limit: int = 50
    ) -> List[TaskSummary]:
        """Get all tasks across all contacts, sorted by score/recency.

        Returns:
            List of task summaries with embedded avatar info

        Cost: 0 LLM calls
        Latency: <10ms (indexed query on tasks table)
        """

    # ===== RELATIONSHIP QUERIES (0 LLM calls, <5ms) =====

    def get_relationship_strength(
        self,
        user_id: str,
        contact_id: str
    ) -> RelationshipMetrics:
        """Get pre-computed relationship metrics.

        Returns:
            {
                strength: 0-1,  # Pre-computed score
                recency_days: int,
                frequency_score: 0-1,
                response_latency: ResponseLatency,
                sentiment_trend: "positive"|"neutral"|"negative"
            }

        Cost: 0 LLM calls
        Latency: <1ms (avatar field access)
        """

    def get_communication_preferences(
        self,
        user_id: str,
        contact_id: str
    ) -> CommunicationProfile:
        """Get avatar's communication preferences.

        Returns:
            {
                preferred_channel: "email"|"whatsapp"|"phone",
                preferred_tone: "formal"|"casual"|"professional",
                preferred_language: str,
                typical_response_time: ResponseLatency
            }

        Cost: 0 LLM calls
        Latency: <1ms (avatar field access)
        """

    # ===== SEMANTIC SEARCH (0 LLM calls, <10ms) =====

    def search_avatars_semantic(
        self,
        user_id: str,
        query: str,
        limit: int = 10
    ) -> List[Avatar]:
        """Semantic search across avatar profiles (using ZylchMemory).

        Example: "contacts who respond slowly to invoices"

        Cost: 0 LLM calls (uses cached embeddings)
        Latency: <10ms (HNSW vector search)
        """

    def search_tasks_semantic(
        self,
        user_id: str,
        query: str,
        limit: int = 20
    ) -> List[TaskSummary]:
        """Semantic search across task descriptions.

        Example: "urgent payment issues"

        Cost: 0 LLM calls
        Latency: <10ms (vector search on task 'view' field)
        """
```

### Avatar Object Schema

```python
@dataclass
class Avatar:
    """Complete avatar profile (all fields pre-computed)."""

    # Identity
    contact_id: str
    user_id: str
    display_name: str
    identifiers: List[str]  # [emails, phones]

    # Communication Profile (PRE-COMPUTED)
    preferred_channel: str  # "email", "whatsapp", "phone"
    preferred_tone: str     # "formal", "casual", "professional"
    preferred_language: str
    response_latency: ResponseLatency  # Median/p90 response times

    # Behavioral Patterns (AGGREGATED)
    patterns_by_channel: Dict[str, List[Pattern]]
    aggregated_preferences: Dict[str, Any]

    # Relationship Metrics (PRE-COMPUTED)
    first_interaction: datetime
    last_interaction: datetime
    interaction_count: int
    relationship_strength: float  # 0-1 (frequency × recency)

    # Task Summary (DENORMALIZED for speed)
    open_tasks_count: int
    urgent_tasks_count: int  # score >= 8
    last_task_date: Optional[datetime]

    # Confidence & Quality
    profile_confidence: float  # How reliable is this avatar
    last_updated: datetime

    # Metadata
    created_at: datetime
    updated_at: datetime


@dataclass
class TaskSummary:
    """Minimal task info (denormalized for fast queries)."""

    task_id: str
    contact_id: str
    contact_name: str
    contact_email: str

    # Pre-computed task fields
    view: str  # Narrative summary (Italian)
    status: str  # "open", "waiting", "closed"
    score: int  # 1-10 urgency
    action: str  # Next action (Italian)

    # Metadata
    thread_count: int
    last_updated: datetime

    # Avatar link (for efficient joins)
    avatar: Optional[Avatar] = None  # Populated if needed


@dataclass
class ResponseLatency:
    """Pre-computed response patterns."""

    median_hours: float
    p90_hours: float
    sample_size: int

    # Context-aware predictions
    by_channel: Dict[str, float]  # email vs whatsapp
    by_day_of_week: Dict[int, float]  # 0=Monday
    by_hour_of_day: Dict[int, float]  # 0-23

    # Derived flags
    is_slow_responder: bool  # p90 > 48 hours
    is_inconsistent: bool    # high variance


@dataclass
class RelationshipMetrics:
    """Pre-computed relationship health."""

    strength: float  # 0-1, based on frequency × recency
    recency_days: int
    frequency_score: float  # interactions per month
    response_latency: ResponseLatency
    sentiment_trend: str  # "positive", "neutral", "negative"
```

---

## Query Patterns

### Pattern 1: `/tasks` Command

**User request:** "Show me my tasks"

**Query flow:**
```python
async def handle_tasks_command(user_id: str) -> str:
    """
    Goal: Display task list WITHOUT any LLM calls.

    Data source: Pre-computed tasks table (populated by task_manager.py)
    Cost: 0 LLM calls
    Latency: <10ms
    """

    # Step 1: Retrieve open tasks (sorted by score)
    tasks = avatar_query.get_all_tasks(
        user_id=user_id,
        status="open",
        limit=50
    )

    # Step 2: Group by urgency
    urgent = [t for t in tasks if t.score >= 8]
    medium = [t for t in tasks if 5 <= t.score < 8]
    low = [t for t in tasks if t.score < 5]

    # Step 3: Format output (Markdown)
    output = ["**📋 Your Tasks**\n"]

    if urgent:
        output.append(f"🔴 **URGENT ({len(urgent)})**")
        for task in urgent[:10]:
            output.append(
                f"• **{task.contact_name}** (score {task.score}/10)\n"
                f"  _{task.view}_\n"
                f"  ➜ {task.action}"
            )
        output.append("")

    if medium:
        output.append(f"🟡 **Medium Priority ({len(medium)})**")
        for task in medium[:10]:
            output.append(f"• {task.contact_name}: {task.action}")
        output.append("")

    if low:
        output.append(f"🟢 Low Priority: {len(low)} tasks")

    return "\n".join(output)
```

**Decision matrix:**
- ✅ **Use pre-computed tasks** (already analyzed by Sonnet during `/gaps`)
- ❌ **Don't re-analyze threads** (waste of API calls)
- ✅ **Simple formatting** (no LLM needed for display logic)

---

### Pattern 2: "Info on Luigi"

**User request:** "Tell me about Luigi"

**Query flow:**
```python
async def handle_contact_info(user_id: str, name_query: str) -> str:
    """
    Goal: Display contact profile WITHOUT LLM calls.

    Cost: 0 LLM calls (unless synthesis needed)
    Latency: <5ms
    """

    # Step 1: Search by name
    matches = avatar_query.search_avatars_by_name(
        user_id=user_id,
        name_query=name_query,
        limit=5
    )

    if not matches:
        # Fallback: Semantic search
        matches = avatar_query.search_avatars_semantic(
            user_id=user_id,
            query=name_query,
            limit=5
        )

    if not matches:
        return f"❌ No contact found matching '{name_query}'"

    # If multiple matches, ask user to disambiguate
    if len(matches) > 1:
        return format_disambiguation_prompt(matches)

    # Step 2: Get full avatar
    avatar = matches[0]

    # Step 3: Get related tasks
    tasks = avatar_query.get_tasks_by_avatar(
        user_id=user_id,
        contact_id=avatar.contact_id,
        status="open"
    )

    # Step 4: Get relationship metrics
    metrics = avatar_query.get_relationship_strength(
        user_id=user_id,
        contact_id=avatar.contact_id
    )

    # Step 5: Format output (NO LLM CALLS)
    output = [
        f"**👤 {avatar.display_name}**\n",
        f"📧 {', '.join(avatar.identifiers)}",
        f"📞 {avatar.phone if hasattr(avatar, 'phone') else 'N/A'}\n",

        "**Communication Profile:**",
        f"• Preferred channel: {avatar.preferred_channel}",
        f"• Tone: {avatar.preferred_tone}",
        f"• Response time: ~{avatar.response_latency.median_hours:.1f} hours (median)\n",

        "**Relationship:**",
        f"• Strength: {metrics.strength:.0%}",
        f"• Last contact: {metrics.recency_days} days ago",
        f"• Interactions: {avatar.interaction_count}\n"
    ]

    if tasks:
        output.append(f"**Open Tasks ({len(tasks)}):**")
        for task in tasks[:3]:
            output.append(f"• {task.action} (score {task.score}/10)")
    else:
        output.append("✅ No open tasks")

    return "\n".join(output)
```

**Decision matrix:**
- ✅ **Pre-computed avatar** (relationship metrics, response latency)
- ✅ **Task lookup** (already stored in DB)
- ❌ **Don't synthesize narrative** unless user explicitly asks ("explain relationship")
- 💡 **LLM trigger:** If user says "explain my relationship with Luigi" → then call LLM

---

### Pattern 3: Recent Interactions

**User request:** "Who did I talk to this week?"

**Query flow:**
```python
async def handle_recent_interactions(user_id: str, days_back: int = 7) -> str:
    """
    Goal: Show recent contacts WITHOUT LLM.

    Cost: 0 LLM calls
    Latency: <10ms
    """

    # Step 1: Get recent avatars
    interactions = avatar_query.get_recent_interactions(
        user_id=user_id,
        days_back=days_back,
        limit=20
    )

    # Step 2: Format by channel
    by_channel = defaultdict(list)
    for item in interactions:
        channel = item.avatar.preferred_channel
        by_channel[channel].append(item)

    # Step 3: Output
    output = [f"**📅 Recent Interactions (last {days_back} days)**\n"]

    for channel in ["email", "whatsapp", "phone"]:
        if channel in by_channel:
            items = by_channel[channel]
            output.append(f"**{channel.title()} ({len(items)}):**")
            for item in items[:10]:
                avatar = item.avatar
                output.append(
                    f"• {avatar.display_name} "
                    f"({item.interaction_count}× this week, "
                    f"last {item.hours_since_last:.0f}h ago)"
                )
            output.append("")

    return "\n".join(output)
```

**Decision matrix:**
- ✅ **Pre-sorted by recency** (last_interaction field indexed)
- ✅ **Channel grouping** (avatar.preferred_channel)
- ❌ **No analysis needed** (raw facts only)

---

### Pattern 4: Semantic Task Search

**User request:** "Show me urgent payment issues"

**Query flow:**
```python
async def handle_semantic_task_search(user_id: str, query: str) -> str:
    """
    Goal: Semantic search WITHOUT new LLM calls.

    Cost: 0 LLM calls (uses cached embeddings)
    Latency: <10ms (HNSW search)
    """

    # Step 1: Vector search on task 'view' field
    tasks = avatar_query.search_tasks_semantic(
        user_id=user_id,
        query=query,  # "urgent payment issues"
        limit=20
    )

    # Step 2: Filter by urgency (if explicit)
    if "urgent" in query.lower():
        tasks = [t for t in tasks if t.score >= 8]

    # Step 3: Format output
    output = [f"**🔍 Tasks matching '{query}'**\n"]

    if not tasks:
        output.append("✅ No matching tasks found")
    else:
        for task in tasks[:10]:
            output.append(
                f"• **{task.contact_name}** (score {task.score}/10)\n"
                f"  {task.view}\n"
                f"  ➜ {task.action}\n"
            )

    return "\n".join(output)
```

**Decision matrix:**
- ✅ **Vector search** (HNSW on pre-computed embeddings)
- ✅ **No new embeddings** (query embedded once, cached)
- ❌ **No synthesis** (return raw task summaries)

---

## LLM Call Boundaries

### When to AVOID LLM Calls

**Rule of thumb:** If the answer can be computed from existing data, DON'T call LLM.

| Query Type | Use LLM? | Why? |
|------------|----------|------|
| "Show tasks" | ❌ No | Pre-computed in tasks table |
| "Info on Luigi" | ❌ No | Avatar profile already exists |
| "Who emailed me today?" | ❌ No | Query last_interaction field |
| "Urgent payment tasks" | ❌ No | Vector search + score filter |
| "Contacts who respond slowly" | ❌ No | Query response_latency.p90 > threshold |
| "Recent WhatsApp contacts" | ❌ No | Filter by preferred_channel |
| Task summaries | ❌ No | Already analyzed by Sonnet during `/gaps` |
| Relationship strength | ❌ No | Pre-computed metric (frequency × recency) |

### When to USE LLM Calls

**Only for synthesis, reasoning, or generation tasks.**

| Query Type | Use LLM? | Why? |
|------------|----------|------|
| "Explain my relationship with Luigi" | ✅ Yes | Synthesis across interaction history |
| "Why is this task urgent?" | ✅ Yes | Reasoning about task context |
| "Draft email to Luigi about invoice" | ✅ Yes | Content generation |
| "Who should I follow up with?" | ✅ Yes | Multi-factor decision (urgency + recency + strength) |
| "Summarize my week" | ✅ Yes | Cross-avatar synthesis |
| "Predict when Luigi will reply" | ⚠️ Maybe | Could use ML model instead of LLM |

### Cost/Latency Trade-offs

| Operation | Cost | Latency | When to Use |
|-----------|------|---------|-------------|
| **SQLite query** | $0 | <1ms | Always (exact lookups) |
| **HNSW vector search** | $0 | <10ms | Semantic search, pattern matching |
| **Pre-computed field** | $0 | <1ms | Frequently accessed metrics |
| **On-demand computation** | $0 | <100ms | Infrequent queries (e.g., network graph) |
| **Claude Haiku** | $0.25/MTok | ~500ms | Simple synthesis |
| **Claude Sonnet** | $3/MTok | ~1s | Complex reasoning |

**Decision matrix:**
```
If query answerable by:
  ├─ Pre-computed field? → Use it (best)
  ├─ Simple SQL query? → Execute it
  ├─ Vector search? → Use HNSW
  ├─ On-demand computation < 100ms? → Compute it
  └─ Else → LLM call (last resort)
```

---

## Pre-Computed vs On-Demand

### Pre-Computed Fields (in Avatar)

**When to pre-compute:**
- Frequently accessed (>10x per session)
- Expensive to compute on-demand (>100ms)
- Infrequently changes (<1x per day)

| Field | Computation | Update Frequency | Justification |
|-------|-------------|------------------|---------------|
| `relationship_strength` | `frequency × recency × sentiment` | Daily | Expensive calculation, accessed often |
| `response_latency` | Median/p90 of response times | Weekly | Statistical computation, stable metric |
| `preferred_channel` | Most-used channel (email/whatsapp/phone) | Weekly | Simple aggregation, high query rate |
| `preferred_tone` | Weighted average of tone patterns | Weekly | Pattern analysis, accessed per-message |
| `open_tasks_count` | `COUNT(*)` where status=open | Real-time | Fast query, denormalized for speed |
| `last_interaction` | `MAX(timestamp)` | Real-time | Index-backed, critical for sorting |

### On-Demand Computation

**When to compute on-demand:**
- Rarely accessed (<1x per session)
- Cheap to compute (<10ms)
- Highly dynamic (changes frequently)

| Field | Why On-Demand? | Latency |
|-------|----------------|---------|
| Network graph (mutual contacts) | Rarely accessed, expensive storage | ~50ms |
| Sentiment analysis (last 5 messages) | Rarely accessed, changes rapidly | ~20ms |
| Time-to-respond prediction (next reply) | Context-dependent, not universal | ~10ms |
| Common topics (keyword extraction) | Better via semantic search than storage | ~15ms |

### Update Strategies

```python
class AvatarUpdateManager:
    """Manages when to update pre-computed fields."""

    def on_new_interaction(self, contact_id: str, interaction_data: Dict):
        """Real-time update triggers."""

        # Immediate updates (cheap, critical)
        self._update_last_interaction(contact_id, interaction_data['timestamp'])
        self._increment_interaction_count(contact_id)

        # Async updates (expensive, defer to background job)
        self._queue_relationship_strength_update(contact_id)
        self._queue_response_latency_update(contact_id)

    def daily_batch_update(self):
        """Batch update expensive metrics (cron job)."""

        # Recompute for all avatars with interactions in last 30 days
        active_avatars = self._get_recently_active_avatars(days=30)

        for avatar in active_avatars:
            self._recompute_relationship_strength(avatar.contact_id)
            self._recompute_response_latency(avatar.contact_id)
            self._recompute_preferred_channel(avatar.contact_id)
            self._recompute_preferred_tone(avatar.contact_id)

    def on_task_status_change(self, task_id: str):
        """Update denormalized task counts."""

        task = get_task(task_id)
        avatar = get_avatar(task.contact_id)

        # Recompute task counts (fast query)
        avatar.open_tasks_count = self._count_open_tasks(task.contact_id)
        avatar.urgent_tasks_count = self._count_urgent_tasks(task.contact_id)

        save_avatar(avatar)
```

---

## Caching Strategy

### Three-Tier Cache

```
┌─────────────────────────────────────────────────────────────────┐
│  Tier 1: In-Memory (Python dict)                                │
│  - Hot avatars (accessed in last 5 min)                         │
│  - Max 100 avatars                                              │
│  - LRU eviction                                                 │
│  - Latency: <0.1ms                                              │
└──────────────────────────────┬──────────────────────────────────┘
                               ↓ (cache miss)
┌─────────────────────────────────────────────────────────────────┐
│  Tier 2: SQLite (avatars table)                                 │
│  - All avatars (persistent)                                     │
│  - Indexed by contact_id, email, phone                          │
│  - Latency: <1ms                                                │
└──────────────────────────────┬──────────────────────────────────┘
                               ↓ (avatar doesn't exist)
┌─────────────────────────────────────────────────────────────────┐
│  Tier 3: Build on Demand                                        │
│  - Query patterns table                                         │
│  - Aggregate interaction history                                │
│  - Store in Tier 2                                              │
│  - Latency: ~100ms (one-time cost)                              │
└─────────────────────────────────────────────────────────────────┘
```

### Cache Invalidation

**Triggers:**
- New interaction → Invalidate avatar's in-memory cache
- Task status change → Invalidate related avatar
- Pattern update → Invalidate all avatars in namespace (rare)

**Strategy:**
```python
class AvatarCache:
    def __init__(self):
        self._cache: Dict[str, Avatar] = {}
        self._access_times: Dict[str, datetime] = {}
        self._max_size = 100

    def get(self, contact_id: str) -> Optional[Avatar]:
        """Get from cache or None."""
        if contact_id in self._cache:
            self._access_times[contact_id] = datetime.now()
            return self._cache[contact_id]
        return None

    def set(self, contact_id: str, avatar: Avatar):
        """Add to cache (LRU eviction)."""
        if len(self._cache) >= self._max_size:
            # Evict least recently used
            lru_id = min(self._access_times, key=self._access_times.get)
            del self._cache[lru_id]
            del self._access_times[lru_id]

        self._cache[contact_id] = avatar
        self._access_times[contact_id] = datetime.now()

    def invalidate(self, contact_id: str):
        """Remove from cache (force reload)."""
        self._cache.pop(contact_id, None)
        self._access_times.pop(contact_id, None)
```

---

## Implementation Examples

### Example 1: Efficient Task Display

**Before (WRONG - current task_manager.py):**
```python
# ❌ BAD: Calls Sonnet for EVERY contact on EVERY /tasks command
def get_tasks():
    for contact_email, threads in contact_threads.items():
        # 🔥 EXPENSIVE: Sonnet call per contact
        task = analyze_contact_task(contact_email, threads)
        tasks.append(task)

    return tasks  # Cost: $0.10 per command (20 contacts × $0.005)
```

**After (CORRECT - using pre-computed avatars):**
```python
# ✅ GOOD: Pre-computed tasks, zero API calls
def get_tasks(user_id: str, status: str = "open"):
    # Single SQL query, <10ms
    tasks = db.execute("""
        SELECT t.*, a.display_name, a.preferred_channel
        FROM tasks t
        JOIN avatars a ON t.contact_id = a.contact_id
        WHERE t.user_id = ? AND t.status = ?
        ORDER BY t.score DESC, t.last_updated DESC
        LIMIT 50
    """, (user_id, status))

    return tasks  # Cost: $0 (no LLM calls)
```

**Performance gain:**
- Latency: 1000ms → 10ms (100x faster)
- Cost: $0.10 → $0 (free)

---

### Example 2: Contact Info Retrieval

**Implementation:**
```python
class AvatarQueryService:
    def __init__(self):
        self.cache = AvatarCache()
        self.db = sqlite3.connect("zylch_memory.db")

    def get_avatar(self, user_id: str, contact_id: str) -> Avatar:
        """Fast avatar retrieval with 3-tier caching."""

        # Tier 1: In-memory cache
        cached = self.cache.get(contact_id)
        if cached:
            return cached

        # Tier 2: SQLite
        row = self.db.execute("""
            SELECT * FROM avatars
            WHERE user_id = ? AND contact_id = ?
        """, (user_id, contact_id)).fetchone()

        if row:
            avatar = Avatar.from_db_row(row)
            self.cache.set(contact_id, avatar)
            return avatar

        # Tier 3: Build on demand (first time)
        avatar = self._build_avatar(user_id, contact_id)
        self._save_avatar(avatar)
        self.cache.set(contact_id, avatar)
        return avatar

    def _build_avatar(self, user_id: str, contact_id: str) -> Avatar:
        """Build avatar from patterns + interaction history."""

        # Aggregate patterns from ZylchMemory
        patterns = memory.retrieve_memories(
            namespace=f"user:{user_id}:contact:{contact_id}",
            category=None,
            limit=100
        )

        # Compute metrics
        interactions = self._get_interaction_history(contact_id)
        response_latency = self._compute_response_latency(interactions)
        relationship_strength = self._compute_relationship_strength(interactions)
        preferred_channel = self._compute_preferred_channel(patterns)

        return Avatar(
            contact_id=contact_id,
            user_id=user_id,
            # ... populate all fields
            response_latency=response_latency,
            relationship_strength=relationship_strength,
            preferred_channel=preferred_channel
        )
```

---

### Example 3: Semantic Task Search

**Implementation:**
```python
class TaskSearchService:
    def __init__(self):
        self.memory = ZylchMemory()

    def search_tasks_semantic(
        self,
        user_id: str,
        query: str,
        limit: int = 20
    ) -> List[TaskSummary]:
        """Semantic search using ZylchMemory (0 LLM calls)."""

        # Step 1: Embed query (cached if repeated)
        query_vector = self.memory.embedding_engine.encode(query)

        # Step 2: HNSW search on tasks namespace
        namespace = f"user:{user_id}:tasks"
        results = self.memory._search_namespace(
            namespace=namespace,
            query_vector=query_vector,
            skill="task",
            limit=limit,
            min_confidence=0.0
        )

        # Step 3: Hydrate with task data
        tasks = []
        for result in results:
            task_id = result['id']
            task = self._get_task_summary(task_id)
            task.similarity = result['similarity']
            tasks.append(task)

        # Step 4: Sort by similarity × score
        tasks.sort(key=lambda t: t.similarity * (t.score / 10), reverse=True)

        return tasks[:limit]
```

**Key insight:** Vector search uses **cached embeddings**, so no LLM calls needed.

---

## Performance Benchmarks

### Target Metrics

| Operation | Target Latency | Current (task_manager.py) | Improvement |
|-----------|----------------|---------------------------|-------------|
| Get all tasks | <10ms | ~5000ms (20 Sonnet calls) | **500x faster** |
| Get avatar by ID | <1ms | N/A (doesn't exist) | New feature |
| Search avatars by name | <5ms | N/A | New feature |
| Semantic task search | <10ms | N/A | New feature |
| Recent interactions | <10ms | N/A | New feature |
| Relationship metrics | <1ms | ~200ms (computed on-demand) | **200x faster** |

### Cost Analysis

**Current (task_manager.py):**
- `/tasks` command: 20 contacts × $0.005 (Sonnet) = **$0.10 per command**
- User with 100 contacts: **$0.50 per `/tasks`**
- Daily usage (5x `/tasks`): **$2.50/day = $75/month**

**Proposed (Avatar Query Interface):**
- `/tasks` command: 0 LLM calls = **$0**
- Pre-computation cost: 1 Sonnet call per contact per week = **$0.02/week = $0.08/month**
- Savings: **99% cost reduction**

### Scalability

| Users | Avatars | SQLite Size | Query Latency | Cost per User per Month |
|-------|---------|-------------|---------------|-------------------------|
| 1 | 100 | ~5 MB | <5ms | $0.08 |
| 10 | 1,000 | ~50 MB | <10ms | $0.08 |
| 100 | 10,000 | ~500 MB | <15ms | $0.08 |
| 1,000 | 100,000 | ~5 GB | <20ms | $0.08 |

**Key insight:** Cost is **constant per user** because pre-computation happens once per week, regardless of query frequency.

---

## Decision Matrix: When to Call LLM

```
┌─────────────────────────────────────────────────────────────────┐
│                        Query Decision Tree                       │
└─────────────────────────────────────────────────────────────────┘

Question: Does the answer require...

├─ Exact lookup? (ID, email, phone)
│  └─ ✅ Use: get_avatar() or get_avatar_by_email()
│     Cost: $0, Latency: <1ms
│
├─ Filtering/sorting? (status, score, recency)
│  └─ ✅ Use: get_all_tasks(status=..., min_score=...)
│     Cost: $0, Latency: <10ms
│
├─ Semantic search? ("urgent payment issues")
│  └─ ✅ Use: search_tasks_semantic(query=...)
│     Cost: $0, Latency: <10ms (HNSW + cached embeddings)
│
├─ Aggregation? (relationship strength, response time)
│  ├─ Pre-computed field exists?
│  │  └─ ✅ Use: avatar.relationship_strength
│  │     Cost: $0, Latency: <1ms
│  └─ Not pre-computed?
│     └─ ✅ Compute on-demand: _compute_metric()
│        Cost: $0, Latency: <100ms
│
├─ Synthesis? ("Explain my relationship with Luigi")
│  └─ ⚠️ LLM CALL: Use Haiku for simple, Sonnet for complex
│     Cost: $0.25-$3/MTok, Latency: 500ms-1s
│
├─ Generation? ("Draft email to Luigi")
│  └─ ⚠️ LLM CALL: Use Sonnet with avatar context
│     Cost: $3/MTok, Latency: ~1s
│
└─ Complex reasoning? ("Who should I follow up with?")
   └─ ⚠️ LLM CALL: Multi-factor decision
      Cost: $3/MTok, Latency: ~1s
```

---

## Conclusion

The Avatar Query Interface transforms Zylch from a **reactive LLM wrapper** into a **proactive intelligence system** by:

1. **Pre-computing** expensive metrics (relationship strength, response latency)
2. **Caching** frequently accessed data (avatars, tasks)
3. **Indexing** for fast lookups (email, phone, name)
4. **Vector search** for semantic queries (without new embeddings)
5. **Deferring** LLM calls to synthesis/generation only

**Result:**
- 99% cost reduction for common queries
- 100-500x latency improvement
- Better UX (instant responses)
- Scalable to 100k+ avatars per user

**Next steps:**
1. Implement `AvatarQueryInterface` class
2. Migrate `/tasks` command to use pre-computed tasks
3. Add avatar detail view in CLI/frontend
4. Build semantic search endpoints
5. Benchmark and optimize

---

**End of Query Interface Design**
