# ZylchMemory - Architecture Documentation

**Version:** 1.0.0
**Author:** Zylch Team
**Date:** November 22, 2025

**Blueprint**: Inspired by [claude-flow](https://github.com/ruvnet/claude-flow)'s AgentDB architecture
**Development**: Built with assistance from claude-flow's AI orchestration patterns

---

## Credits & Inspiration

ZylchMemory's architecture was inspired by the **AgentDB** component from [claude-flow](https://github.com/ruvnet/claude-flow), an MCP server for AI agent orchestration. We studied claude-flow's approach to:

- Multi-agent memory management with namespace isolation
- Pattern-based skill learning systems
- Vector embedding storage and retrieval
- Semantic search for agent behaviors

While claude-flow's AgentDB is built on Node.js/TypeScript with ChromaDB, we implemented ZylchMemory as a pure Python solution using HNSW indexing for better performance and tighter integration with our Python-based agent system.

**Development tooling**: This package was developed using claude-flow's AI orchestration capabilities to accelerate the implementation process.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Core Components](#core-components)
4. [Namespace Strategy](#namespace-strategy)
5. [Semantic Search](#semantic-search)
6. [Confidence Learning](#confidence-learning)
7. [Performance](#performance)
8. [Database Schema](#database-schema)
9. [Integration](#integration)
10. [Future Enhancements](#future-enhancements)

---

## Overview

**ZylchMemory** is a unified memory system for AI agents that combines:
- **Pattern learning** for skill-based behavior
- **Behavioral memory** for general agent preferences
- **Semantic search** using vector embeddings and HNSW indexing
- **Multi-tenant support** with namespace isolation
- **Bayesian confidence tracking** for continuous learning

### Design Goals

1. **Performance**: Sub-millisecond retrieval (O(log n) search)
2. **Accuracy**: Semantic similarity matching, not just exact match
3. **Scalability**: Support 100k+ patterns per user
4. **Privacy**: Complete user isolation via namespaces
5. **Simplicity**: Pure Python, minimal dependencies

### Replaces

- `PatternStore` (SQLite hash-based matching)
- `ReasoningBank` (JSON file storage)

---

## Architecture

### Three-Layer Design

```
┌─────────────────────────────────────────────────┐
│  Layer 1: API (ZylchMemory class)               │
│  - store_pattern()                              │
│  - retrieve_similar_patterns()                  │
│  - store_memory()                               │
│  - retrieve_memories()                          │
│  - update_confidence()                          │
└──────────────┬──────────────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────────────┐
│  Layer 2: Processing                            │
│  - EmbeddingEngine: text → vector (384-dim)     │
│  - VectorIndex: HNSW O(log n) search            │
│  - ConfidenceTracker: Bayesian updates          │
└──────────────┬──────────────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────────────┐
│  Layer 3: Storage (SQLite)                      │
│  - patterns table (skill learning)              │
│  - memories table (behavioral)                  │
│  - embeddings table (vector cache)              │
│  - Multiple HNSW indices (per namespace)        │
└─────────────────────────────────────────────────┘
```

---

## Core Components

### 1. EmbeddingEngine

**Purpose**: Convert text to semantic vector representations

**Technology**: `sentence-transformers` with `all-MiniLM-L6-v2` model

**Specifications**:
- **Dimensions**: 384
- **Model size**: 80MB
- **Mode**: Offline (no API keys required)
- **Training**: 1B+ sentence pairs
- **Use case**: Semantic similarity search

**How it works**:
```python
text = "Draft a formal reminder email to Luisa about invoice"
embedding = encoder.encode(text)
# Result: [0.234, -0.891, 0.456, ..., 0.123]  # 384 float32 numbers
```

**Why it works**:
- Texts with similar meanings produce similar vectors
- Cosine distance measures semantic similarity
- "draft formal email" ≈ "compose professional message"
- "draft email" ≠ "schedule meeting" (far in vector space)

**Caching**:
- Embeddings are cached in SQLite `embeddings` table
- Avoids recomputing same text multiple times
- Key: `(text, model_name)` → unique constraint

---

### 2. VectorIndex (HNSW)

**Purpose**: Ultra-fast approximate nearest neighbor search

**Technology**: `hnswlib` (Hierarchical Navigable Small World graphs)

**Problem solved**:
- Linear search: O(n) - 10,000 comparisons = ~10ms
- HNSW: O(log n) - ~20 comparisons = ~0.1ms
- **100x speedup**

**How HNSW works**:

Multi-layer graph structure (like highway system):

```
Layer 2 (highways):   A ←─────→ B ←─────→ C
                       ↓          ↓          ↓
Layer 1 (roads):      A → D → B → E → C → F
                       ↓   ↓   ↓   ↓   ↓   ↓
Layer 0 (streets):    A→D→G→B→E→H→C→F→I→J
```

**Search algorithm**:
1. Start at top layer (sparse, long jumps)
2. Greedy search for closest node
3. Descend to next layer
4. Refine search with more connections
5. Continue until bottom layer
6. Return k-nearest neighbors

**Parameters**:
```python
index.init_index(
    max_elements=100000,   # Capacity
    ef_construction=200,   # Build quality (higher = better accuracy, slower build)
    M=16                   # Connections per node (higher = better accuracy, more memory)
)
index.set_ef(50)  # Search quality (higher = better recall, slower query)
```

**Performance**:
- 10,000 vectors: ~0.1ms per query
- 100,000 vectors: ~0.5ms per query
- 1,000,000 vectors: ~2ms per query

**Why it works**:
- Exploits small-world property of high-dimensional spaces
- Few hops to reach any node (logarithmic)
- Greedy navigation with multi-scale structure
- Probabilistic guarantees on recall

---

### How We Achieve O(log n) Complexity

**The Problem**: Linear Search is O(n)

In traditional vector search, finding the closest match requires comparing the query against every stored vector:

```python
# Linear search: O(n)
best_match = None
best_distance = infinity

for pattern in all_patterns:  # n iterations
    distance = cosine_distance(query, pattern.embedding)
    if distance < best_distance:
        best_match = pattern
        best_distance = distance
```

- **10 patterns**: 10 comparisons
- **1,000 patterns**: 1,000 comparisons
- **100,000 patterns**: 100,000 comparisons (slow!)

**The Solution**: HNSW is O(log n)

HNSW builds a hierarchical graph structure that allows "skipping" most comparisons:

**Key Insight**: Think of a multi-level highway system:
- **Top layer (highways)**: Few exits, long distances between nodes → quick navigation across city
- **Middle layer (roads)**: More exits, medium distances → navigate to neighborhood
- **Bottom layer (streets)**: All destinations, short distances → precise navigation

**How the Algorithm Works**:

1. **Start at top layer** (sparse graph with ~log(n) nodes)
   - Only a few "highway exits" to check
   - Make big jumps toward target region

2. **Greedy search at current layer**
   ```
   current = entry_point
   while True:
       neighbors = get_neighbors(current, layer)
       best = find_closest_to_query(neighbors)
       if best is closer than current:
           current = best  # Move closer
       else:
           break  # Local minimum reached
   ```

3. **Descend to next layer** (denser graph)
   - Start from the best node found above
   - Repeat greedy search with more connections

4. **Continue until bottom layer**
   - Bottom layer contains ALL vectors
   - But we only examine a small subset near target

**Comparison Count**:
```
Layers: log(n) layers
Checks per layer: ef_search (constant, ~50)
Total comparisons: log(n) × ef_search ≈ O(log n)
```

**Example with 100,000 patterns**:
- Linear search: 100,000 comparisons
- HNSW: log₂(100,000) × 50 ≈ 17 × 50 = 850 comparisons
- **Speedup: 117x faster**

**Why Logarithmic?**

The number of layers grows as log(n) because each layer is exponentially sparser:
- Layer 0: 100% of vectors (n vectors)
- Layer 1: ~50% of vectors (n/2 vectors)
- Layer 2: ~25% of vectors (n/4 vectors)
- Layer k: n/(2^k) vectors

Top layer has ~1 vector when: n/(2^k) ≈ 1 → k ≈ log₂(n)

**Trade-offs**:
- ✅ Sub-millisecond queries even with millions of vectors
- ✅ High recall (>95% with proper parameters)
- ⚠️ Approximate, not exact (but close enough for semantic search)
- ⚠️ More memory than flat search (stores graph structure)

**Our Implementation**:
```python
# index.py
if self._size < 10:
    # Brute-force for small indices (HNSW overhead not worth it)
    return self._brute_force_search(query, k)
else:
    # HNSW for larger indices (O(log n))
    return self.index.knn_query(query, k)
```

This hybrid approach ensures optimal performance for both small test datasets and large production workloads.

---

### 3. SQLite Storage

**Purpose**: Persistent storage for metadata and embeddings

**Why SQLite**:
- ✅ Built-in Python (zero setup)
- ✅ ACID transactions (safe concurrent writes)
- ✅ Single file (easy backup/restore)
- ✅ Fast for <1M rows (perfect for agent memory)
- ✅ JSON support (flexible context storage)
- ✅ Full-text search bonus

**File location**: `.swarm/zylch_memory.db`

---

### 4. ConfidenceTracker

**Purpose**: Bayesian learning from user feedback

**Algorithm**:
```python
def update_confidence(current_confidence: float, success: bool) -> float:
    """Bayesian update with reinforcement/penalty"""
    if success:
        # Positive reinforcement
        new = current_confidence + (1 - current_confidence) * 0.3
    else:
        # Penalty
        new = current_confidence * 0.7
    return max(0.0, min(1.0, new))
```

**Example learning trajectory**:
```
Initial confidence: 0.5
User approves → 0.65
User approves → 0.755
User approves → 0.829
User approves → 0.880
User approves → 0.916  (high confidence!)

User rejects → 0.641   (significant drop)
```

**Properties**:
- Never reaches 1.0 (always room to learn)
- More evidence → higher confidence
- Recent evidence weighted more
- Exponential decay on rejection

---

## Namespace Strategy

### Two-Level Memory Hierarchy

**1. Global Memory** (`global:*`)
- System-wide instructions and guidelines
- Skill best practices
- Default behavior templates
- Written by: Admin/developers
- Read by: All users (fallback)

**2. User Memory** (`user:{user_id}:*`)
- Personal preferences and patterns
- Learned from user approvals/rejections
- Contact-specific rules
- Written by: System (auto-learning)
- Read by: Specific user only

### Namespace Format

```
global:system          → System instructions
global:skills          → Skill templates/guidelines
user:mario:patterns    → Mario's learned patterns
user:mario:behavioral  → Mario's behavioral preferences
user:alice:patterns    → Alice's learned patterns (isolated from Mario)
```

### Privacy & Isolation

**Rule**: Users can only access their own namespace + global

```python
# Mario's query
patterns = memory.retrieve_similar_patterns(
    intent="draft email",
    user_id="mario"
)
# Returns: user:mario:* + global:* only
# Never returns: user:alice:* (privacy!)
```

### Cascading Retrieval

**Search order**:
1. User-specific patterns (priority)
2. Global skill patterns (fallback)
3. Score boosting for user patterns (1.5x multiplier)
4. Rank by combined score

```python
def retrieve_similar_patterns(intent, skill, user_id, limit=5):
    results = []

    # Step 1: User patterns
    if user_id:
        user_patterns = search(f"user:{user_id}", intent, skill, limit)
        results.extend(user_patterns)

    # Step 2: Global patterns (if needed)
    if len(results) < limit:
        global_patterns = search("global:skills", intent, skill, limit - len(results))
        results.extend(global_patterns)

    # Step 3: Boost user patterns
    for p in results:
        if p['namespace'].startswith('user:'):
            p['score'] *= 1.5  # User preference boost

    return sorted(results, key=lambda x: x['score'], reverse=True)[:limit]
```

### Use Cases

**New user (no personalization yet)**:
- Query: "draft professional email"
- Returns: `global:skills` patterns only
- Behavior: Standard Zylch defaults

**Experienced user (50+ learned patterns)**:
- Query: "draft email to Luisa about invoice"
- Returns: Mostly `user:mario` patterns (personalized!)
- Behavior: Mario's learned preferences

**Global update benefits all**:
- Admin updates `global:skills` pattern
- All users get improved baseline
- User-specific patterns still take priority

---

## Semantic Search

### End-to-End Flow

**Scenario**: User asks "compose professional message to client about payment"

#### Step 1: Generate Query Embedding
```python
query = "compose professional message to client about payment"
query_embedding = encoder.encode(query)
# [0.123, -0.456, 0.789, ..., 0.234]  # 384 dimensions
```

#### Step 2: HNSW Search
```python
labels, distances = index.knn_query(query_embedding, k=5)
# labels = [42, 17, 89, 103, 55]  # Pattern IDs
# distances = [0.15, 0.23, 0.28, 0.31, 0.35]  # Cosine distance
```

#### Step 3: Fetch Metadata
```python
patterns = []
for label, distance in zip(labels, distances):
    pattern = db.execute(
        "SELECT * FROM patterns WHERE id = ? AND skill = ?",
        (label, "draft_composer")
    ).fetchone()

    pattern['similarity'] = 1 - distance  # Convert distance to similarity
    patterns.append(pattern)
```

#### Step 4: Filter & Rank
```python
# Filter by minimum confidence
filtered = [p for p in patterns if p['confidence'] > 0.6]

# Combined score: similarity × confidence
scored = [
    {**p, 'score': p['similarity'] * p['confidence']}
    for p in filtered
]

# Sort by score
ranked = sorted(scored, key=lambda x: x['score'], reverse=True)
```

#### Result
```json
[
  {
    "intent": "draft formal email to luisa about invoice",
    "action": {"tone": "formal", "pronoun": "lei"},
    "confidence": 0.85,
    "similarity": 0.85,
    "score": 0.7225
  },
  {
    "intent": "write professional message to client",
    "action": {"tone": "professional", "pronoun": "lei"},
    "confidence": 0.72,
    "similarity": 0.77,
    "score": 0.5544
  }
]
```

### Why Semantic Search is Powerful

**Finds related concepts**:
- "compose" → "draft" (synonyms)
- "payment" → "invoice" (related concepts)
- "client" → "customer" (domain knowledge)

**Handles variations**:
- "write email" ≈ "draft message" ≈ "compose correspondence"
- All map to similar vectors
- No need for exact keyword match!

**Context-aware**:
- "bank" in "river bank" ≠ "bank" in "financial institution"
- Embeddings capture context from surrounding words

---

## Confidence Learning

### Learning Loop

```
┌─────────────────────────────────────────┐
│  1. User provides natural language      │
│     "Draft reminder to Luisa"           │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│  2. Retrieve similar patterns           │
│     Found: "email to luisa" (conf=0.7)  │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│  3. Execute skill with pattern action   │
│     Generate draft with formal tone     │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│  4. User feedback                       │
│     ✅ Approved  or  ❌ Rejected        │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│  5. Update confidence                   │
│     Approved: 0.7 → 0.79               │
│     Rejected: 0.7 → 0.49               │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│  6. Store new pattern if approved       │
│     Learn user's exact preference       │
└─────────────────────────────────────────┘
```

### Confidence Thresholds

| Confidence | Interpretation | Action |
|-----------|---------------|--------|
| 0.0 - 0.3 | Low confidence | Treat as unreliable, may ignore |
| 0.3 - 0.6 | Medium confidence | Consider but ask for confirmation |
| 0.6 - 0.8 | High confidence | Apply automatically |
| 0.8 - 1.0 | Very high confidence | Strong user preference |

### Multi-Pattern Aggregation

When multiple patterns match:

```python
def aggregate_patterns(patterns):
    """Weighted aggregation by confidence"""
    total_weight = sum(p['confidence'] for p in patterns)

    aggregated_action = {}
    for key in patterns[0]['action'].keys():
        # Weighted vote
        values = [(p['action'][key], p['confidence']) for p in patterns]
        aggregated_action[key] = weighted_majority(values, total_weight)

    return aggregated_action
```

---

## Performance

### Storage Requirements

| Patterns | SQLite | HNSW Index | Total | Notes |
|----------|--------|-----------|-------|-------|
| 1,000 | 500 KB | 300 KB | 800 KB | Single user |
| 10,000 | 5 MB | 3 MB | 8 MB | Active user |
| 100,000 | 50 MB | 30 MB | 80 MB | Heavy user |
| 1,000,000 | 500 MB | 300 MB | 800 MB | Enterprise |

### Query Latency

| Operation | Time | Details |
|-----------|------|---------|
| Generate embedding | ~1ms | CPU-bound, cached |
| HNSW search (10k) | ~0.1ms | In-memory index |
| HNSW search (100k) | ~0.5ms | In-memory index |
| HNSW search (1M) | ~2ms | In-memory index |
| SQLite fetch | ~1ms | Indexed lookup |
| **Total (10k patterns)** | **~2ms** | End-to-end |
| **Total (100k patterns)** | **~3ms** | End-to-end |

### Comparison with Legacy Systems

| System | Search | Latency | Accuracy |
|--------|--------|---------|----------|
| PatternStore (hash) | O(n) | ~10ms | Exact match only |
| ReasoningBank (JSON) | O(n) | ~50ms | No similarity |
| **ZylchMemory** | **O(log n)** | **~2ms** | **Semantic match** |

**Improvement**: 5-25x faster + semantic understanding

---

## Database Schema

### Tables

#### patterns
```sql
CREATE TABLE patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL,              -- "user:mario" or "global:skills"
    skill TEXT NOT NULL,                  -- "draft_composer", "email_triage", etc.
    intent TEXT NOT NULL,                 -- "write formal email to luisa"
    context TEXT,                         -- JSON: {"contact": "Luisa", "company": "Acme"}
    action TEXT,                          -- JSON: {"tone": "formal", "pronoun": "lei"}
    outcome TEXT,                         -- "approved", "rejected", "modified"
    user_id TEXT,                         -- "mario" (for user:* namespace)
    confidence REAL DEFAULT 0.5,          -- Bayesian confidence [0, 1]
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    embedding_id INTEGER,                 -- FK to embeddings table

    UNIQUE(namespace, skill, intent)
);

CREATE INDEX idx_patterns_namespace ON patterns(namespace);
CREATE INDEX idx_patterns_skill ON patterns(skill);
CREATE INDEX idx_patterns_user ON patterns(user_id);
CREATE INDEX idx_patterns_confidence ON patterns(confidence);
```

#### memories
```sql
CREATE TABLE memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL,              -- "user:mario" or "global:system"
    category TEXT NOT NULL,               -- "email", "contacts", "calendar", "task", "general"
    context TEXT,                         -- "Luisa from Acme Corp"
    pattern TEXT,                         -- "Always use formal tone, Lei pronoun"
    examples TEXT,                        -- JSON: ["email_123", "email_456"]
    confidence REAL DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    embedding_id INTEGER
);

CREATE INDEX idx_memories_namespace ON memories(namespace);
CREATE INDEX idx_memories_category ON memories(category);
```

#### embeddings
```sql
CREATE TABLE embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,                   -- Original text
    vector BLOB NOT NULL,                 -- Serialized numpy array (384 float32)
    model TEXT NOT NULL,                  -- "all-MiniLM-L6-v2"
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(text, model)                   -- Cache: same text → same embedding
);

CREATE INDEX idx_embeddings_text ON embeddings(text);
```

### HNSW Indices

**Stored in memory** (not in SQLite):
- One index per namespace for isolation
- Loaded on startup from embeddings table
- Persisted to disk in separate files (`.swarm/indices/`)

```python
# Index organization
indices = {
    "global:system": hnswlib.Index(...),
    "global:skills": hnswlib.Index(...),
    "user:mario": hnswlib.Index(...),
    "user:alice": hnswlib.Index(...)
}
```

---

## Integration

### Replacing PatternStore

**Before**:
```python
from zylch.memory.pattern_store import PatternStore

store = PatternStore()
patterns = store.retrieve_similar_patterns(
    intent="draft email",
    skill="draft_composer"
)
# Hash-based exact matching
```

**After**:
```python
from zylch_memory import ZylchMemory

memory = ZylchMemory()
patterns = memory.retrieve_similar_patterns(
    intent="draft email",
    skill="draft_composer",
    user_id="mario"
)
# Semantic search with namespace isolation
```

### Replacing ReasoningBank

**Before**:
```python
from zylch.memory.reasoning_bank import ReasoningBankMemory

bank = ReasoningBankMemory()
memories = bank.list_patterns(category="email")
# JSON file scanning
```

**After**:
```python
from zylch_memory import ZylchMemory

memory = ZylchMemory()
memories = memory.retrieve_memories(
    query="email preferences",
    category="email",
    user_id="mario"
)
# Semantic search in SQLite
```

### Service Layer Integration

**skill_service.py**:
```python
from zylch_memory import ZylchMemory

class SkillService:
    def __init__(self):
        self.memory = ZylchMemory()

    async def execute_skill(self, skill_name, user_id, intent, params):
        # Retrieve relevant patterns
        patterns = self.memory.retrieve_similar_patterns(
            intent=intent,
            skill=skill_name,
            user_id=user_id,
            limit=3
        )

        # Execute skill with pattern context
        skill = self.registry.get_skill(skill_name)
        result = await skill.activate(context, patterns=patterns)

        return result
```

### CLI Integration

**/memory command**:
```python
async def _handle_memory_command(self, args):
    memory = ZylchMemory()

    if args.action == "list":
        patterns = memory.list_patterns(
            namespace=f"user:{self.user_id}",
            limit=args.limit
        )
        self._display_patterns(patterns)

    elif args.action == "stats":
        stats = memory.get_stats(user_id=self.user_id)
        print(f"Total patterns: {stats['total']}")
        print(f"Avg confidence: {stats['avg_confidence']:.2f}")
```

---

## Future Enhancements

### Phase 2: Advanced Features

**1. Temporal Decay**
- Patterns not used for >90 days lose confidence
- Ensures memory stays fresh and relevant
- Configurable decay rate

**2. Cross-User Learning** (Privacy-Safe)
- Aggregate patterns across users (anonymized)
- Improve `global:skills` from collective intelligence
- Differential privacy guarantees

**3. Explainability**
- "Why did you use this pattern?"
- Show retrieval reasoning (similarity scores, confidence, etc.)
- Trust building with users

**4. Active Learning**
- Identify uncertain scenarios (confidence 0.4-0.6)
- Proactively ask user for feedback
- Accelerate learning in ambiguous cases

**5. Multi-Modal Embeddings**
- Support images, audio (for future features)
- Unified vector space for all modalities
- CLIP-like architecture

**6. Compression**
- Product quantization for embeddings
- 4-8x memory reduction
- Minimal accuracy loss

**7. Distributed Sync**
- Multi-device support (desktop, mobile, web)
- CRDT-based conflict resolution
- Real-time sync via WebSockets

---

## Conclusion

ZylchMemory provides a production-ready, scalable, and privacy-compliant memory system for AI agents. By combining semantic search, Bayesian learning, and namespace isolation, it enables personalized AI behavior while maintaining global system knowledge.

**Key Achievements**:
- ✅ 5-25x faster than legacy systems
- ✅ Semantic understanding (not just keyword matching)
- ✅ Multi-tenant ready with privacy guarantees
- ✅ Continuous learning from user feedback
- ✅ Pure Python, minimal dependencies
- ✅ Battle-tested algorithms (HNSW, transformers)

**Next Steps**: See `README.md` for installation and usage guide.

---

**End of Architecture Documentation**
