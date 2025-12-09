# Memory System - Person-Centric Persistent Memory with Reconsolidation

## Overview

The Memory System (ZylchMemory) provides persistent, person-centric memory for AI agents with semantic search and memory reconsolidation. Unlike traditional databases that create new entries for every piece of information, ZylchMemory mimics human memory by **updating existing memories** when new information arrives, preventing memory fragmentation and maintaining coherent knowledge.

**The thesis**: Professional relationships exist entirely in language. LLMs don't need to learn physics to model relationships—they need to remember. ZylchMemory provides the persistent memory layer that transforms stateless LLMs into assistants that accumulate relational understanding over time.

## Key Concepts

### Memory Reconsolidation

**How human memory works**: When you learn someone moved to a new city, you don't create a second "location" memory—you *update* the existing one. Your brain reconsolidates the memory with new information.

**How ZylchMemory works**:
1. New information arrives: "Mario moved to Milan"
2. Search for similar existing memories using vector similarity (cosine > 0.85)
3. If found: **UPDATE** the existing memory with new information
4. If not found: **CREATE** a new memory

**Why this matters**:
- No duplicate memories ("Mario lives in Rome" vs "Mario lives in Milan")
- Coherent knowledge graph (one source of truth per person/topic)
- Natural memory evolution (updates reflect reality changes)
- Prevents memory bloat (100 memories vs 1000 fragmented ones)

### Namespace Architecture

Memories are organized into namespaces for privacy and scoping:

| Namespace Pattern | Purpose | Example |
|-------------------|---------|---------|
| `user:{user_id}` | User-specific preferences | `user:mario_123` |
| `global:skills` | System-wide patterns | `global:skills` |
| `shared:{recipient}:{sender}` | Shared intelligence | `shared:luigi_456:mario_123` |
| `team:{team_id}` | Team knowledge (future) | `team:sales_team` |

**Privacy guarantee**: Users can only access their own namespaces. Cross-user access requires explicit authorization (see [Sharing System](sharing-system.md)).

### Vector Embeddings & HNSW Indexing

**Semantic search** uses vector embeddings to find similar content:

```python
# Text → Vector (384 dimensions)
"Mario likes formal emails" → [0.12, -0.34, 0.56, ..., 0.89]
"Mario prefers professional tone" → [0.15, -0.32, 0.58, ..., 0.91]

# Cosine similarity: 0.95 (very similar!)
# → Reconsolidate instead of creating duplicate
```

**HNSW (Hierarchical Navigable Small World)** index provides:
- **150x faster** search vs brute-force
- Sub-linear search time: O(log n) vs O(n)
- Configurable accuracy/speed tradeoff
- Memory-efficient graph structure

### Categories

Memories are categorized for filtering and organization:

| Category | Purpose | Examples |
|----------|---------|----------|
| `email` | Email preferences | "Always use formal tone with clients" |
| `contacts` | Person knowledge | "Marco Ferrari is CEO of Acme Corp" |
| `calendar` | Meeting preferences | "Prefer morning meetings" |
| `task` | Task management | "Break large tasks into subtasks" |
| `general` | General preferences | "Speak Italian by default" |
| `contact_intel` | Shared contact info | "Marco signed the contract" (shared) |

## How It Works

### 1. Storing Memory (with Reconsolidation)

**User input**: "Always use formal tone when emailing clients"

**Agent calls**:
```python
memory_id = zylch_memory.store_memory(
    namespace="user:mario_123",
    category="email",
    context="Email communication style",
    pattern="Use formal tone when emailing clients",
    examples=["client@acme.com", "ceo@bigco.com"],
    confidence=0.8,
    force_new=False  # Enable reconsolidation (default)
)
```

**Processing flow**:
1. **Generate embedding** from context + pattern
   - Text: "Email communication style Use formal tone when emailing clients"
   - Embedding model: `all-MiniLM-L6-v2` (384-dim vector)
   - Cached to avoid recomputation

2. **Check for similar memories** (unless `force_new=True`)
   - Search namespace `user:mario_123`, category `email`
   - Find memories with cosine similarity > 0.85 (configurable)
   - If found: **RECONSOLIDATE** (update existing memory)
   - If not found: **CREATE NEW** memory

3. **Reconsolidation** (if similar memory exists):
   ```python
   # Found: "Use professional language in business emails" (similarity 0.92)
   # UPDATE instead of creating duplicate

   storage.update_memory(
       memory_id=existing['id'],
       pattern="Use formal tone when emailing clients",  # New pattern
       context="Email communication style",  # New context
       examples=["client@acme.com", "ceo@bigco.com"],  # Append examples
       confidence_delta=0.1,  # Boost confidence (+0.1)
       new_embedding_id=new_embedding_id  # Update embedding
   )

   # Result: Memory updated, no duplicate created
   # Confidence: 0.8 → 0.9
   ```

4. **New memory** (if no similar found):
   ```python
   memory_id = storage.store_memory(
       namespace="user:mario_123",
       category="email",
       context="Email communication style",
       pattern="Use formal tone when emailing clients",
       examples=json.dumps(["client@acme.com", "ceo@bigco.com"]),
       embedding_id=embedding_id,
       confidence=0.8
   )

   # Add to HNSW index for fast retrieval
   index.add(vector, memory_id)
   ```

### 2. Retrieving Memory

**User query**: "How should I write to the CEO?"

**Agent calls**:
```python
memories = zylch_memory.retrieve_memories(
    query="email communication style for CEO",
    category="email",
    namespace="user:mario_123",
    limit=5
)
```

**Search flow**:
1. **Generate query embedding**
   - Text: "email communication style for CEO"
   - Convert to 384-dim vector

2. **HNSW vector search**
   - Search in namespace `user:mario_123`
   - Find k=10 nearest neighbors (2x limit for filtering)
   - Returns: [(memory_id, distance), ...]

3. **Filter and rank**
   - Filter by category (`email`)
   - Filter by confidence (> 0.0, configurable)
   - Calculate score: `similarity × confidence`
   - Sort by score descending

4. **Return results**:
   ```python
   [
       {
           "id": "123",
           "namespace": "user:mario_123",
           "category": "email",
           "context": "Email communication style",
           "pattern": "Use formal tone when emailing clients",
           "examples": ["client@acme.com", "ceo@bigco.com"],
           "confidence": 0.9,
           "similarity": 0.95,
           "score": 0.855  # 0.95 × 0.9
       }
   ]
   ```

**Agent uses memory**:
```
Based on your preference for formal tone with clients, I'll draft a professional email:

Dear CEO,

I hope this message finds you well...
```

### 3. Pattern Learning

**User behavior**: Agent suggests action → User approves/rejects → Confidence updated

**Example**:
```
Agent: "Should I schedule the meeting for 9 AM?"
User: "No, I prefer afternoon meetings"

# Pattern stored:
pattern_id = zylch_memory.store_pattern(
    namespace="user:mario_123",
    skill="scheduling",
    intent="schedule meeting",
    context={"time": "9 AM"},
    action={"suggested": "9 AM"},
    outcome="rejected",
    confidence=0.3  # Low confidence (rejected)
)

# Next time:
Agent: "Should I schedule the meeting for 2 PM?"
User: "Yes, perfect"

# Confidence updated:
zylch_memory.update_confidence(
    pattern_id=pattern_id,
    success=True  # Approved → Confidence increases
)
# Confidence: 0.3 → 0.51 (Bayesian update)
```

**Bayesian confidence update**:
- **Success**: `new = current + (1 - current) × alpha` (alpha=0.3)
- **Failure**: `new = current × beta` (beta=0.7)
- Always clamped to [0, 1]

### 4. Cascading Retrieval

**User-specific patterns prioritized over global defaults**:

```python
results = zylch_memory.retrieve_similar_patterns(
    intent="schedule meeting",
    skill="scheduling",
    user_id="mario_123",
    limit=5
)
```

**Search order**:
1. **User namespace** (`user:mario_123`) with 1.5x score boost
2. **Global namespace** (`global:skills`) if fewer than limit results

**Why**: Personal preferences override system defaults.

## Implementation Details

### File References

**Core Memory System**:
- `zylch_memory/zylch_memory/core.py` - Main ZylchMemory class (486 lines)
- `zylch_memory/zylch_memory/config.py` - Configuration (109 lines)
- `zylch_memory/zylch_memory/storage.py` - SQLite storage backend (200+ lines)
- `zylch_memory/zylch_memory/embeddings.py` - Sentence-transformers integration
- `zylch_memory/zylch_memory/index.py` - HNSW vector index wrapper

**Legacy/Supporting**:
- `zylch/memory/reasoning_bank.py` - ReasoningBank integration (deprecated)
- `zylch/memory/pattern_store.py` - Pattern storage utilities

### Database Schema

**`memories` table** (SQLite):
```sql
CREATE TABLE memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL,
    category TEXT NOT NULL,
    context TEXT,
    pattern TEXT,
    examples TEXT,  -- JSON array
    confidence REAL DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    embedding_id INTEGER,  -- FK to embeddings table

    INDEX idx_memories_namespace (namespace),
    INDEX idx_memories_category (category)
);
```

**`patterns` table** (SQLite):
```sql
CREATE TABLE patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL,
    skill TEXT NOT NULL,
    intent TEXT NOT NULL,
    context TEXT,  -- JSON metadata
    action TEXT,   -- JSON action taken
    outcome TEXT,  -- "approved", "rejected", "modified"
    user_id TEXT,
    confidence REAL DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    embedding_id INTEGER,

    UNIQUE(namespace, skill, intent)
);
```

**`embeddings` table** (Embedding cache):
```sql
CREATE TABLE embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    vector BLOB NOT NULL,  -- Numpy array serialized
    model TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(text, model)
);
```

**HNSW Indices** (Separate files):
- Stored in `.swarm/indices/{namespace}.hnsw`
- One index file per namespace
- Binary format (hnswlib)
- Lazy-loaded on first access

### Key Classes

#### `ZylchMemory`

Main memory API.

**Methods**:
- `store_memory(namespace, category, context, pattern, examples, user_id, confidence, force_new)` → str
  - Store or update memory with reconsolidation
  - Returns: memory_id (existing if reconsolidated, new if created)
  - `force_new=True` disables reconsolidation (used for shared intel)

- `retrieve_memories(query, category, user_id, namespace, limit)` → List[Dict]
  - Retrieve memories using semantic search
  - Returns: List of memories with similarity scores

- `store_pattern(namespace, skill, intent, context, action, outcome, user_id, confidence)` → str
  - Store a behavior pattern
  - Returns: pattern_id

- `retrieve_similar_patterns(intent, skill, user_id, limit, min_confidence)` → List[Dict]
  - Retrieve similar patterns with cascading search (user → global)
  - Returns: List of patterns with scores

- `update_confidence(pattern_id, success)` → None
  - Update pattern confidence using Bayesian learning
  - `success=True` → Reinforcement (confidence up)
  - `success=False` → Penalty (confidence down)

**Private methods**:
- `_get_or_create_embedding(text)` → (embedding_id, vector)
  - Get cached or generate new embedding

- `_find_similar_memories(namespace, category, query_vector, threshold)` → List[Dict]
  - Find memories with cosine similarity > threshold
  - Used for reconsolidation check

- `_get_or_create_index(namespace)` → VectorIndex
  - Lazy-load HNSW index for namespace

- `_rebuild_index(namespace, index)` → None
  - Rebuild HNSW index from storage

#### `ZylchMemoryConfig`

Configuration with environment variable support.

**Key Settings**:
- `similarity_threshold` (0.85) - Cosine threshold for reconsolidation
- `confidence_boost_on_update` (0.1) - Confidence increase on reconsolidation
- `embedding_model` ("all-MiniLM-L6-v2") - Sentence-transformers model
- `embedding_dim` (384) - Vector dimensions
- `hnsw_M` (16) - HNSW graph connections per node
- `hnsw_ef_construction` (200) - Build-time accuracy parameter
- `hnsw_ef_search` (50) - Search-time accuracy parameter
- `confidence_alpha` (0.3) - Reinforcement factor for positive feedback
- `confidence_beta` (0.7) - Penalty factor for negative feedback
- `user_pattern_boost` (1.5) - Score multiplier for user patterns vs global

**Environment variables**: Prefix with `ZYLCH_MEMORY_`
```bash
export ZYLCH_MEMORY_SIMILARITY_THRESHOLD=0.90
export ZYLCH_MEMORY_EMBEDDING_MODEL="all-mpnet-base-v2"
```

## CLI Commands

### `/memory --list`
List all stored memories.

**Usage**:
```bash
# List personal memories (default)
/memory --list

# List global memories (admin)
/memory --list --global

# List all memories (personal + global)
/memory --list --all
```

### `/memory --add`
Add a new behavioral memory.

**Usage**:
```bash
/memory --add "what went wrong" "correct behavior" channel

# Examples:
/memory --add "Used tu instead of lei" "Always use lei for formal business communication" email
/memory --add "Missing timezone" "Always specify timezone in event description" calendar
/memory --add "Too formal tone" "Use casual, friendly language on WhatsApp" whatsapp
```

### `/memory --remove <id>`
Remove a memory.

**Usage**:
```bash
/memory --remove 5

# Remove global memory (admin)
/memory --remove 5 --global
```

### `/memory --stats`
Show memory statistics.

**Output**:
```
📊 Memory Statistics

Personal Memories: 42
  - email: 15
  - calendar: 8
  - contacts: 12
  - task: 7

Global Memories: 23
  - email: 10
  - calendar: 6
  - task: 7

Average Confidence: 0.74
```

## Performance Characteristics

### Memory Operations
- **Store (new memory)**: <20ms (embedding + SQLite + HNSW insert)
- **Store (reconsolidation)**: <30ms (similarity check + update)
- **Retrieve**: <50ms for typical query (HNSW search + SQLite fetch)
- **Confidence update**: <5ms (SQLite UPDATE)

### Embedding Generation
- **Cache hit**: <1ms (SQLite lookup)
- **Cache miss**: <50ms (sentence-transformers encoding)
- **Batch encoding**: ~10ms/item for 32-item batch
- **Model load time**: ~500ms (first query only)

### HNSW Index
- **Search time**: O(log n) with HNSW vs O(n) brute-force
- **Typical speedup**: 150x faster for 10K+ embeddings
- **Index build time**: <100ms for 1K memories
- **Memory overhead**: ~50 bytes per vector (M=16)

### Storage Overhead
- **Memory record**: ~500 bytes (text + metadata)
- **Embedding cache**: ~1600 bytes (text + 384-dim vector)
- **HNSW index**: ~50 bytes per node
- **Total**: ~2KB per memory (with embedding and index)

## Known Limitations

1. **HNSW index updates**: Reconsolidation doesn't update HNSW index in-place (periodic rebuild needed)
2. **No multi-namespace search**: Cannot search across multiple namespaces in one query
3. **No hierarchical namespaces**: Cannot search parent namespaces (e.g., `user:*` to find all users)
4. **No memory deletion**: Memories can be updated but not easily deleted (confidence → 0 workaround)
5. **No version history**: Memory updates overwrite previous versions (no audit trail)
6. **Local storage only**: SQLite not synced across devices (Supabase migration planned)

## Future Enhancements

### Planned (Phase I+)
- **Memory versioning**: Track changes over time with audit trail
- **Hierarchical namespaces**: Search `user:*`, `shared:luigi:*`
- **Memory expiration**: TTL for time-sensitive memories
- **Memory deletion**: Soft delete with garbage collection
- **Multi-namespace search**: Query multiple namespaces in one call

### Optimization (Phase J - Scaling)
- **Supabase migration**: Move from SQLite to Supabase for multi-device sync
- **Redis caching**: Cache hot embeddings and HNSW results
- **Incremental HNSW updates**: Update index in-place instead of rebuilding
- **Quantization**: 4-bit embeddings for 4x memory reduction
- **Batch reconsolidation**: Process multiple memories in parallel

### Intelligence Improvements
- **Cross-memory linking**: Detect relationships between memories
- **Memory importance scoring**: Prioritize frequently accessed memories
- **Automatic categorization**: AI-suggested categories based on content
- **Memory consolidation**: Periodic background job to merge similar memories
- **Conflict detection**: Identify contradictory memories for resolution

## Related Documentation

- **[Sharing System](sharing-system.md)** - Uses memory namespaces for shared intelligence
- **[Avatar Aggregation](avatar-aggregation.md)** - Person-centric architecture aligns with memory philosophy
- **[Triggers & Automation](triggers-automation.md)** - Behavioral memory vs event-driven triggers
- **[Relationship Intelligence](relationship-intelligence.md)** - Memory enriches relationship analysis
- **[Architecture](../../.claude/ARCHITECTURE.md#memory-system-philosophy)** - Memory system design philosophy

## Research Foundations

This system draws on:

**ReasoningBank** (Google Research): Strategy-level memory with success/failure learning and contrastive patterns ("Do this, not that").

**Memory Reconsolidation** (Neuroscience): Memories update rather than duplicate. Retrieval makes memories labile; reinforcement strengthens, failure weakens.

**JEPA** (LeCun, Meta AI): Representation-level prediction over pixel-level generation. Learning essential features, not raw reconstruction.

## References

**Source Code**:
- `zylch_memory/zylch_memory/core.py` - Main ZylchMemory class (486 lines)
- `zylch_memory/zylch_memory/config.py` - Configuration (109 lines)
- `zylch_memory/zylch_memory/storage.py` - SQLite storage backend
- `zylch_memory/zylch_memory/embeddings.py` - Embedding generation
- `zylch_memory/zylch_memory/index.py` - HNSW vector index wrapper

**Database**:
- SQLite at `.swarm/zylch_memory.db`
- HNSW indices at `.swarm/indices/{namespace}.hnsw`

**Technologies**:
- Sentence-transformers: https://www.sbert.net/
- HNSW: https://github.com/nmslib/hnswlib
- SQLite: https://www.sqlite.org/

---

**Last Updated**: December 2025
