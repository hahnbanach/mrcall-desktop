# ZylchMemory - Architecture Documentation

**Version:** 2.0.0  
**Author:** Zylch Team  
**Date:** December 2025

**Blueprint**: Inspired by [claude-flow](https://github.com/ruvnet/claude-flow)'s AgentDB architecture  
**Development**: Built with assistance from claude-flow's AI orchestration patterns

---

## Table of Contents

1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Core Components](#core-components)
4. [Namespace Architecture](#namespace-architecture)
5. [Avatar Aggregation Layer](#avatar-aggregation-layer)
6. [Semantic Search Pipeline](#semantic-search-pipeline)
7. [Confidence & Learning](#confidence--learning)
8. [Memory Lifecycle](#memory-lifecycle)
9. [Database Schema](#database-schema)
10. [Performance](#performance)
11. [Integration Patterns](#integration-patterns)
12. [Roadmap](#roadmap)

---

## Overview

**ZylchMemory** is the persistent memory layer for AI agents, designed to transform stateless LLMs into assistants that accumulate relational understanding over time.

### Design Goals

| Goal | Implementation |
|------|----------------|
| **Performance** | O(log n) retrieval via HNSW indexing |
| **Semantic Understanding** | Vector embeddings capture meaning, not just keywords |
| **Privacy** | Complete user isolation via hierarchical namespaces |
| **Scalability** | 100k+ patterns per user, multi-tenant ready |
| **Learning** | Bayesian confidence tracking from feedback |
| **Simplicity** | Pure Python, minimal dependencies, single SQLite file |

### Replaces

- `PatternStore` (SQLite hash-based matching → O(n), exact match only)
- `ReasoningBank` (JSON file storage → slow, no semantic search)

---

## System Architecture

### Four-Layer Design

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1: API                                                   │
│  ZylchMemory class                                              │
│  ├── store_pattern()      → skill-based patterns                │
│  ├── store_memory()       → behavioral rules                    │
│  ├── retrieve_similar_patterns()                                │
│  ├── retrieve_memories()                                        │
│  ├── update_confidence()                                        │
│  └── get_avatar()         → aggregated contact representation   │
└──────────────────────────────┬──────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│  Layer 2: Avatar Aggregation                                    │
│  AvatarEngine class                                             │
│  ├── aggregate_contact_patterns()                               │
│  ├── compute_communication_profile()                            │
│  ├── merge_cross_channel_insights()                             │
│  └── export_avatar() / import_avatar()                          │
└──────────────────────────────┬──────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│  Layer 3: Processing                                            │
│  ├── EmbeddingEngine    → text → vector (384-dim)               │
│  ├── VectorIndex        → HNSW O(log n) search                  │
│  ├── ConfidenceTracker  → Bayesian updates                      │
│  └── LifecycleManager   → TTL, decay, garbage collection        │
└──────────────────────────────┬──────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│  Layer 4: Storage                                               │
│  SQLite (.swarm/zylch_memory.db)                                │
│  ├── patterns table         (skill learning)                    │
│  ├── memories table         (behavioral rules)                  │
│  ├── embeddings table       (vector cache)                      │
│  ├── avatars table          (aggregated contact profiles)       │
│  └── lifecycle table        (access tracking, TTL metadata)     │
│                                                                 │
│  HNSW Indices (.swarm/indices/)                                 │
│  └── One index per namespace for isolation                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. EmbeddingEngine

**Purpose**: Convert text to semantic vector representations

**Technology**: `sentence-transformers` with `all-MiniLM-L6-v2`

| Spec | Value |
|------|-------|
| Dimensions | 384 |
| Model size | 80MB |
| Mode | Offline (no API keys) |
| Training | 1B+ sentence pairs |

**How it works**:
```python
text = "Draft a formal reminder email to Luisa about invoice"
embedding = encoder.encode(text)
# Result: [0.234, -0.891, 0.456, ..., 0.123]  # 384 float32
```

**Semantic similarity**: Texts with similar meanings produce similar vectors. Cosine distance measures semantic closeness.

**Caching**: Embeddings cached in SQLite `embeddings` table. Key: `(text, model_name)` → avoids recomputation.

---

### 2. VectorIndex (HNSW)

**Purpose**: O(log n) approximate nearest neighbor search

**Technology**: `hnswlib` (Hierarchical Navigable Small World graphs)

**Performance comparison**:

| Method | Complexity | 10k patterns | 100k patterns |
|--------|------------|--------------|---------------|
| Linear scan | O(n) | ~10ms | ~100ms |
| HNSW | O(log n) | ~0.1ms | ~0.5ms |

**How HNSW works** (highway analogy):

```
Layer 2 (highways):   A ←─────→ B ←─────→ C       (few nodes, long jumps)
                       ↓          ↓          ↓
Layer 1 (roads):      A → D → B → E → C → F      (more nodes, medium jumps)
                       ↓   ↓   ↓   ↓   ↓   ↓
Layer 0 (streets):    A→D→G→B→E→H→C→F→I→J        (all nodes, precise)
```

**Search algorithm**:
1. Start at top layer (sparse)
2. Greedy search toward query
3. Descend to next layer
4. Repeat until bottom layer
5. Return k-nearest neighbors

**Parameters**:
```python
index.init_index(
    max_elements=100000,
    ef_construction=200,  # Build quality
    M=16                  # Connections per node
)
index.set_ef(50)  # Search quality
```

**Hybrid approach** (our implementation):
```python
if self._size < 10:
    return self._brute_force_search(query, k)  # Small: brute force
else:
    return self.index.knn_query(query, k)      # Large: HNSW
```

---

### 3. ConfidenceTracker

**Purpose**: Bayesian learning from user feedback

**Algorithm**:
```python
def update_confidence(current: float, success: bool) -> float:
    if success:
        return current + (1 - current) * 0.3  # Reinforce
    else:
        return current * 0.7                   # Penalize
```

**Learning trajectory**:
```
Initial:  0.50
Approve:  0.65 → 0.76 → 0.83 → 0.88 → 0.92
Reject:   0.64  (significant drop from 0.92)
```

**Properties**:
- Never reaches 1.0 (always room to learn)
- Recent evidence weighted more heavily
- Exponential decay on rejection

---

### 4. LifecycleManager

**Purpose**: Memory hygiene—TTL, decay, garbage collection

**Components**:

| Component | Function |
|-----------|----------|
| Access tracker | Records last retrieval time |
| TTL enforcer | Marks stale patterns for review |
| Decay function | Reduces confidence over time if unused |
| GC runner | Removes low-confidence, stale patterns |

**Decay formula**:
```python
def apply_temporal_decay(pattern, now):
    days_since_use = (now - pattern.last_accessed).days
    if days_since_use > 90:
        decay_factor = 0.99 ** (days_since_use - 90)
        pattern.confidence *= decay_factor
```

**Garbage collection rules**:
```python
def should_gc(pattern):
    return (
        pattern.confidence < 0.2 and
        pattern.times_applied < 3 and
        days_since_created(pattern) > 30
    )
```

---

## Namespace Architecture

### Three-Level Hierarchy

```
┌─────────────────────────────────────────────────────────────────┐
│  Level 1: Global                                                │
│  global:system     → System instructions                        │
│  global:skills     → Skill templates, best practices            │
│  global:defaults   → Default behaviors                          │
└─────────────────────────────────────────────────────────────────┘
                               ↓ (fallback)
┌─────────────────────────────────────────────────────────────────┐
│  Level 2: User                                                  │
│  user:{user_id}:patterns    → Learned skill patterns            │
│  user:{user_id}:behavioral  → Channel-based rules               │
│  user:{user_id}:preferences → General preferences               │
└─────────────────────────────────────────────────────────────────┘
                               ↓ (priority)
┌─────────────────────────────────────────────────────────────────┐
│  Level 3: Contact                                               │
│  user:{user_id}:contact:{contact_id}:patterns                   │
│  user:{user_id}:contact:{contact_id}:profile                    │
│  user:{user_id}:contact:{contact_id}:history                    │
└─────────────────────────────────────────────────────────────────┘
```

### Namespace Format

```
global:system                           → System-wide instructions
global:skills                           → Skill templates
user:mario                              → Mario's general patterns
user:mario:behavioral:email             → Mario's email channel rules
user:mario:behavioral:whatsapp          → Mario's WhatsApp channel rules
user:mario:contact:luisa                → Mario's patterns for Luisa
user:mario:contact:luisa:profile        → Aggregated avatar for Luisa
user:mario:contact:acme_corp            → Company-level patterns
```

### Contact Identification

**Contact ID generation**:
```python
def generate_contact_id(email: str = None, name: str = None, phone: str = None) -> str:
    """Generate stable contact ID from available identifiers"""
    if email:
        return hashlib.md5(email.lower().encode()).hexdigest()[:12]
    elif phone:
        normalized = re.sub(r'[^\d]', '', phone)
        return hashlib.md5(normalized.encode()).hexdigest()[:12]
    else:
        normalized = name.lower().strip()
        return hashlib.md5(normalized.encode()).hexdigest()[:12]
```

**Contact merging** (when same person has multiple identifiers):
```python
def merge_contacts(primary_id: str, secondary_id: str):
    """Merge secondary contact into primary, preserving all patterns"""
    # Move all patterns from secondary namespace to primary
    db.execute("""
        UPDATE patterns 
        SET namespace = REPLACE(namespace, :old, :new)
        WHERE namespace LIKE :old_pattern
    """, {
        'old': f'contact:{secondary_id}',
        'new': f'contact:{primary_id}',
        'old_pattern': f'%contact:{secondary_id}%'
    })
    
    # Recalculate avatar for merged contact
    avatar_engine.rebuild_avatar(primary_id)
```

### Cascading Retrieval

**Search priority**:
1. Contact-specific patterns (if contact_id provided)
2. User patterns
3. Global patterns (fallback)

**Score boosting**:
```python
def retrieve_with_cascade(intent, skill, user_id, contact_id=None, limit=5):
    results = []
    
    # Priority 1: Contact-specific (highest boost)
    if contact_id:
        contact_ns = f"user:{user_id}:contact:{contact_id}"
        contact_patterns = search(contact_ns, intent, skill, limit)
        for p in contact_patterns:
            p['score'] *= 2.0  # Contact-specific boost
        results.extend(contact_patterns)
    
    # Priority 2: User patterns
    if len(results) < limit:
        user_ns = f"user:{user_id}"
        user_patterns = search(user_ns, intent, skill, limit - len(results))
        for p in user_patterns:
            p['score'] *= 1.5  # User boost
        results.extend(user_patterns)
    
    # Priority 3: Global fallback
    if len(results) < limit:
        global_patterns = search("global:skills", intent, skill, limit - len(results))
        results.extend(global_patterns)
    
    return sorted(results, key=lambda x: x['score'], reverse=True)[:limit]
```

### Privacy & Isolation

**Hard rule**: Users can only access their own namespace + global

```python
def validate_namespace_access(user_id: str, namespace: str) -> bool:
    if namespace.startswith("global:"):
        return True  # Global readable by all
    if namespace.startswith(f"user:{user_id}"):
        return True  # Own namespace
    return False  # Denied
```

**Index isolation**: Separate HNSW index per user namespace
```python
indices = {
    "global:skills": hnswlib.Index(...),
    "user:mario": hnswlib.Index(...),
    "user:alice": hnswlib.Index(...),  # Completely separate
}
```

---

## Avatar Aggregation Layer

The Avatar layer synthesizes patterns across channels into coherent contact representations.

### Avatar Structure

```python
@dataclass
class Avatar:
    contact_id: str
    user_id: str
    
    # Identity
    display_name: str
    identifiers: List[str]  # emails, phones
    
    # Communication profile
    preferred_channel: str  # "email", "whatsapp", etc.
    preferred_tone: str     # "formal", "casual", "professional"
    preferred_language: str
    response_latency: ResponseLatency  # typical response time
    
    # Behavioral patterns
    patterns_by_channel: Dict[str, List[Pattern]]
    aggregated_preferences: Dict[str, Any]
    
    # Relationship metadata
    first_interaction: datetime
    last_interaction: datetime
    interaction_count: int
    relationship_strength: float  # 0-1, based on frequency/recency
    
    # Confidence
    profile_confidence: float  # How reliable is this avatar
    last_updated: datetime
```

### Response Latency Model

```python
@dataclass
class ResponseLatency:
    median_hours: float
    p90_hours: float
    sample_size: int
    by_channel: Dict[str, float]  # Per-channel breakdown
    by_day_of_week: Dict[int, float]  # 0=Monday
    by_hour_of_day: Dict[int, float]  # 0-23
```

**Calculation**:
```python
def compute_response_latency(contact_id: str) -> ResponseLatency:
    """Analyze email/message threads to compute response patterns"""
    threads = get_threads_with_contact(contact_id)
    
    response_times = []
    for thread in threads:
        for i, msg in enumerate(thread.messages[1:], 1):
            if msg.sender == contact_id:
                prev_msg = thread.messages[i-1]
                delta = msg.timestamp - prev_msg.timestamp
                response_times.append(delta.total_seconds() / 3600)
    
    return ResponseLatency(
        median_hours=np.median(response_times),
        p90_hours=np.percentile(response_times, 90),
        sample_size=len(response_times),
        by_channel=compute_by_channel(threads),
        by_day_of_week=compute_by_day(response_times),
        by_hour_of_day=compute_by_hour(response_times)
    )
```

### Avatar Aggregation

```python
class AvatarEngine:
    def aggregate_contact_patterns(self, user_id: str, contact_id: str) -> Avatar:
        """Build avatar from all patterns related to a contact"""
        
        # Gather patterns from all channels
        patterns = {}
        for channel in CHANNELS:
            ns = f"user:{user_id}:contact:{contact_id}:behavioral:{channel}"
            patterns[channel] = self.memory.list_patterns(namespace=ns)
        
        # Compute aggregated preferences
        preferences = self._compute_preferences(patterns)
        
        # Compute communication profile
        profile = self._compute_communication_profile(contact_id, patterns)
        
        # Compute relationship strength
        strength = self._compute_relationship_strength(contact_id)
        
        return Avatar(
            contact_id=contact_id,
            user_id=user_id,
            patterns_by_channel=patterns,
            aggregated_preferences=preferences,
            preferred_channel=profile['preferred_channel'],
            preferred_tone=profile['preferred_tone'],
            response_latency=profile['response_latency'],
            relationship_strength=strength,
            profile_confidence=self._compute_confidence(patterns)
        )
    
    def _compute_preferences(self, patterns: Dict[str, List]) -> Dict:
        """Weighted aggregation across channels"""
        all_patterns = []
        for channel, channel_patterns in patterns.items():
            for p in channel_patterns:
                p['channel'] = channel
                all_patterns.append(p)
        
        # Group by preference key, weighted by confidence
        preferences = {}
        for key in ['tone', 'pronoun', 'language', 'formality']:
            values = [(p['action'].get(key), p['confidence']) 
                      for p in all_patterns if key in p.get('action', {})]
            if values:
                preferences[key] = weighted_majority(values)
        
        return preferences
```

### Avatar Export/Import (Enterprise Feature)

**Use case**: Employee onboarding—inherit predecessor's relational knowledge

```python
def export_avatar(user_id: str, contact_id: str) -> bytes:
    """Export avatar for sharing/transfer"""
    avatar = get_avatar(user_id, contact_id)
    patterns = list_patterns(namespace=f"user:{user_id}:contact:{contact_id}")
    
    export_data = {
        'avatar': asdict(avatar),
        'patterns': patterns,
        'exported_at': datetime.utcnow().isoformat(),
        'version': '2.0'
    }
    
    return gzip.compress(json.dumps(export_data).encode())

def import_avatar(user_id: str, data: bytes, contact_id: str = None):
    """Import avatar into user's namespace"""
    export_data = json.loads(gzip.decompress(data))
    
    # Use original contact_id or override
    target_contact_id = contact_id or export_data['avatar']['contact_id']
    target_ns = f"user:{user_id}:contact:{target_contact_id}"
    
    # Import patterns with reduced confidence (inherited, not learned)
    for pattern in export_data['patterns']:
        pattern['confidence'] *= 0.7  # Inheritance discount
        pattern['namespace'] = target_ns
        store_pattern(**pattern)
    
    # Rebuild avatar
    avatar_engine.rebuild_avatar(target_contact_id)
```

---

## Semantic Search Pipeline

### End-to-End Flow

**Query**: "compose professional message to client about payment"

```
┌─────────────────────────────────────────────────────────────────┐
│  Step 1: Embed Query                                            │
│  "compose professional message..." → [0.12, -0.45, 0.78, ...]   │
│  Time: ~1ms (cached if repeated)                                │
└──────────────────────────────┬──────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│  Step 2: HNSW Search (per namespace)                            │
│  Contact namespace: 2 results                                   │
│  User namespace: 3 results                                      │
│  Global namespace: 2 results (fallback)                         │
│  Time: ~0.3ms                                                   │
└──────────────────────────────┬──────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│  Step 3: Fetch Metadata from SQLite                             │
│  JOIN patterns ON embedding_id                                  │
│  Time: ~1ms                                                     │
└──────────────────────────────┬──────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│  Step 4: Score & Rank                                           │
│  score = similarity × confidence × namespace_boost              │
│  Filter: confidence > min_threshold                             │
│  Sort: descending by score                                      │
└──────────────────────────────┬──────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│  Result                                                         │
│  [                                                              │
│    {intent: "email to luisa about invoice",                     │
│     action: {tone: "formal"}, score: 0.85},                     │
│    {intent: "professional message to client",                   │
│     action: {tone: "professional"}, score: 0.72}                │
│  ]                                                              │
└─────────────────────────────────────────────────────────────────┘
```

**Total latency**: ~2-3ms

### Semantic Matching Power

| Query | Matches | Why |
|-------|---------|-----|
| "compose message" | "draft email" | Synonyms in embedding space |
| "payment reminder" | "invoice followup" | Related concepts |
| "client" | "customer", "Luisa" | Domain knowledge + contact association |

---

## Confidence & Learning

### Learning Loop

```
User request → Retrieve patterns → Execute skill → User feedback → Update confidence
      ↑                                                                    │
      └────────────────────────────────────────────────────────────────────┘
```

### Confidence Thresholds

| Range | Interpretation | System Behavior |
|-------|----------------|-----------------|
| 0.0 - 0.2 | Unreliable | Candidate for GC |
| 0.2 - 0.4 | Low confidence | Excluded from retrieval |
| 0.4 - 0.6 | Medium | Include but may ask confirmation |
| 0.6 - 0.8 | High | Apply automatically |
| 0.8 - 1.0 | Very high | Strong user preference |

### Multi-Pattern Aggregation

When multiple patterns match, aggregate by weighted vote:

```python
def aggregate_actions(patterns: List[Pattern]) -> Dict:
    """Weighted aggregation when multiple patterns apply"""
    weights = {p['id']: p['confidence'] * p['similarity'] for p in patterns}
    total_weight = sum(weights.values())
    
    aggregated = {}
    for key in get_all_action_keys(patterns):
        votes = defaultdict(float)
        for p in patterns:
            if key in p['action']:
                votes[p['action'][key]] += weights[p['id']]
        
        # Winner takes all
        aggregated[key] = max(votes.items(), key=lambda x: x[1])[0]
    
    return aggregated
```

---

## Memory Lifecycle

### Pattern States

```
┌─────────┐     approve      ┌─────────┐     high usage     ┌─────────┐
│  NEW    │ ────────────────→│ ACTIVE  │ ─────────────────→ │ STABLE  │
│ (0.5)   │                  │ (0.5-0.8)│                    │ (0.8+)  │
└─────────┘                  └─────────┘                    └─────────┘
     │                            │                              │
     │ reject                     │ no usage (90d)               │ no usage (180d)
     ↓                            ↓                              ↓
┌─────────┐                  ┌─────────┐                    ┌─────────┐
│ DECLINED│                  │ STALE   │                    │ ARCHIVED│
│ (<0.3)  │                  │ decaying│                    │ frozen  │
└─────────┘                  └─────────┘                    └─────────┘
     │                            │
     │ times_applied < 3          │ confidence < 0.2
     ↓                            ↓
┌─────────────────────────────────────────────────────────────────────┐
│                        GARBAGE COLLECTED                            │
└─────────────────────────────────────────────────────────────────────┘
```

### Lifecycle Rules

```python
LIFECYCLE_CONFIG = {
    'stale_threshold_days': 90,      # No access → start decay
    'archive_threshold_days': 180,   # No access → archive
    'gc_min_confidence': 0.2,        # Below this → GC candidate
    'gc_min_applications': 3,        # Must be applied N times to survive
    'gc_grace_period_days': 30,      # New patterns protected
    'decay_rate': 0.99,              # Daily decay multiplier after stale
}
```

### Lifecycle Manager

```python
class LifecycleManager:
    def run_daily_maintenance(self):
        """Run as daily cron job"""
        self._apply_temporal_decay()
        self._mark_stale_patterns()
        self._archive_old_patterns()
        self._garbage_collect()
        self._rebuild_stale_avatars()
    
    def _apply_temporal_decay(self):
        """Reduce confidence for unused patterns"""
        stale = self.db.execute("""
            SELECT id, confidence, last_accessed 
            FROM patterns 
            WHERE julianday('now') - julianday(last_accessed) > ?
        """, (LIFECYCLE_CONFIG['stale_threshold_days'],))
        
        for pattern in stale:
            days_stale = (now() - pattern.last_accessed).days
            decay = LIFECYCLE_CONFIG['decay_rate'] ** days_stale
            new_confidence = pattern.confidence * decay
            self.db.execute(
                "UPDATE patterns SET confidence = ? WHERE id = ?",
                (new_confidence, pattern.id)
            )
    
    def _garbage_collect(self):
        """Remove patterns that failed to prove useful"""
        self.db.execute("""
            DELETE FROM patterns 
            WHERE confidence < ?
              AND times_applied < ?
              AND julianday('now') - julianday(created_at) > ?
        """, (
            LIFECYCLE_CONFIG['gc_min_confidence'],
            LIFECYCLE_CONFIG['gc_min_applications'],
            LIFECYCLE_CONFIG['gc_grace_period_days']
        ))
```

---

## Database Schema

### Tables

#### patterns
```sql
CREATE TABLE patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL,
    skill TEXT NOT NULL,
    intent TEXT NOT NULL,
    context TEXT,                    -- JSON
    action TEXT,                     -- JSON
    outcome TEXT,
    user_id TEXT,
    contact_id TEXT,                 -- NEW: for per-contact patterns
    confidence REAL DEFAULT 0.5,
    times_applied INTEGER DEFAULT 0,
    times_successful INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_accessed TIMESTAMP,         -- NEW: for lifecycle tracking
    embedding_id INTEGER,
    state TEXT DEFAULT 'active',     -- NEW: active, stale, archived
    
    UNIQUE(namespace, skill, intent)
);

CREATE INDEX idx_patterns_namespace ON patterns(namespace);
CREATE INDEX idx_patterns_skill ON patterns(skill);
CREATE INDEX idx_patterns_user ON patterns(user_id);
CREATE INDEX idx_patterns_contact ON patterns(contact_id);
CREATE INDEX idx_patterns_confidence ON patterns(confidence);
CREATE INDEX idx_patterns_state ON patterns(state);
CREATE INDEX idx_patterns_last_accessed ON patterns(last_accessed);
```

#### memories
```sql
CREATE TABLE memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL,
    category TEXT NOT NULL,          -- email, calendar, whatsapp, mrcall, task
    context TEXT,
    pattern TEXT,
    examples TEXT,                   -- JSON array
    confidence REAL DEFAULT 0.5,
    times_applied INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_accessed TIMESTAMP,
    embedding_id INTEGER,
    state TEXT DEFAULT 'active'
);

CREATE INDEX idx_memories_namespace ON memories(namespace);
CREATE INDEX idx_memories_category ON memories(category);
```

#### avatars
```sql
CREATE TABLE avatars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    display_name TEXT,
    identifiers TEXT,                -- JSON array of emails/phones
    preferred_channel TEXT,
    preferred_tone TEXT,
    preferred_language TEXT,
    response_latency TEXT,           -- JSON: ResponseLatency object
    aggregated_preferences TEXT,     -- JSON
    relationship_strength REAL,
    first_interaction TIMESTAMP,
    last_interaction TIMESTAMP,
    interaction_count INTEGER DEFAULT 0,
    profile_confidence REAL DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(user_id, contact_id)
);

CREATE INDEX idx_avatars_user ON avatars(user_id);
CREATE INDEX idx_avatars_contact ON avatars(contact_id);
```

#### embeddings
```sql
CREATE TABLE embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    vector BLOB NOT NULL,            -- Serialized numpy array
    model TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(text, model)
);

CREATE INDEX idx_embeddings_text ON embeddings(text);
```

### HNSW Index Files

```
.swarm/indices/
├── global_skills.hnsw
├── user_mario.hnsw
├── user_mario_contact_luisa.hnsw
├── user_alice.hnsw
└── ...
```

**Index lifecycle**:
- Created on first pattern in namespace
- Loaded into memory on startup
- Persisted after each modification
- Deleted when namespace is empty

---

## Performance

### Storage Requirements

| Scale | Patterns | SQLite | HNSW Indices | Total |
|-------|----------|--------|--------------|-------|
| Single user | 1,000 | 500 KB | 300 KB | ~1 MB |
| Active user | 10,000 | 5 MB | 3 MB | ~8 MB |
| Heavy user | 100,000 | 50 MB | 30 MB | ~80 MB |
| Enterprise | 1,000,000 | 500 MB | 300 MB | ~800 MB |

### Query Latency

| Operation | 10k patterns | 100k patterns | 1M patterns |
|-----------|--------------|---------------|-------------|
| Embed query | ~1ms | ~1ms | ~1ms |
| HNSW search | ~0.1ms | ~0.5ms | ~2ms |
| SQLite fetch | ~1ms | ~1ms | ~2ms |
| **Total** | **~2ms** | **~3ms** | **~5ms** |

### Comparison with Legacy

| System | Search | Latency (10k) | Semantic |
|--------|--------|---------------|----------|
| PatternStore | O(n) | ~10ms | No |
| ReasoningBank | O(n) | ~50ms | No |
| **ZylchMemory** | **O(log n)** | **~2ms** | **Yes** |

---

## Integration Patterns

### Skill Service Integration

```python
class SkillService:
    def __init__(self):
        self.memory = ZylchMemory()
    
    async def execute_skill(self, skill_name, user_id, intent, contact_id=None):
        # Retrieve with contact context
        patterns = self.memory.retrieve_similar_patterns(
            intent=intent,
            skill=skill_name,
            user_id=user_id,
            contact_id=contact_id,
            limit=3
        )
        
        # Get avatar if contact specified
        avatar = None
        if contact_id:
            avatar = self.memory.get_avatar(user_id, contact_id)
        
        # Execute skill with pattern + avatar context
        skill = self.registry.get_skill(skill_name)
        result = await skill.activate(
            context=build_context(patterns, avatar),
            user_id=user_id
        )
        
        return result
    
    async def record_feedback(self, pattern_id, success, user_id, contact_id=None):
        # Update pattern confidence
        self.memory.update_confidence(pattern_id, success)
        
        # Rebuild avatar if contact-specific
        if contact_id:
            self.memory.avatar_engine.rebuild_avatar(user_id, contact_id)
```

### CLI Integration

```python
@command("/memory")
async def memory_command(args):
    memory = ZylchMemory()
    
    if args.action == "list":
        patterns = memory.list_patterns(
            namespace=f"user:{user_id}",
            limit=args.limit
        )
        display_patterns(patterns)
    
    elif args.action == "avatar":
        avatar = memory.get_avatar(user_id, args.contact_id)
        display_avatar(avatar)
    
    elif args.action == "export":
        data = memory.export_avatar(user_id, args.contact_id)
        save_file(f"{args.contact_id}_avatar.zylch", data)
    
    elif args.action == "import":
        data = read_file(args.file)
        memory.import_avatar(user_id, data, args.contact_id)
```

### Event Hooks

```python
# Register lifecycle hooks
memory.on_pattern_created(lambda p: log_analytics("pattern_created", p))
memory.on_confidence_updated(lambda p, old, new: 
    log_analytics("confidence_change", {"delta": new - old}))
memory.on_avatar_updated(lambda a: 
    notify_sync_service(a.user_id, a.contact_id))
memory.on_garbage_collected(lambda patterns: 
    log_analytics("gc", {"count": len(patterns)}))
```

---

## Roadmap

### v2.1 - Avatar Intelligence
- [ ] Response time prediction (when will they reply?)
- [ ] Optimal contact time suggestion
- [ ] Relationship health scoring
- [ ] Network graph visualization

### v2.2 - Enterprise Features
- [ ] Team-level avatars (shared across organization)
- [ ] Role-based avatar inheritance
- [ ] Audit logging for compliance
- [ ] Avatar versioning and rollback

### v2.3 - Advanced Learning
- [ ] Active learning (ask for feedback on uncertain cases)
- [ ] Cross-user learning (anonymized, differential privacy)
- [ ] Automatic pattern discovery from interaction logs
- [ ] Contradiction detection and resolution

### v2.4 - Performance
- [ ] Product quantization for embedding compression
- [ ] Tiered storage (hot/warm/cold)
- [ ] Distributed sync (multi-device)
- [ ] Real-time WebSocket updates

---

## Conclusion

ZylchMemory v2.0 provides:

- **Hierarchical namespaces** for user + contact isolation
- **Avatar aggregation** for person-centric intelligence
- **Memory lifecycle** management for system hygiene
- **O(log n) semantic search** via HNSW
- **Bayesian learning** from user feedback

The architecture is designed to evolve from channel-based behavioral memory toward full relational avatars that capture the nuance of professional relationships.

---

**End of Architecture Documentation**
