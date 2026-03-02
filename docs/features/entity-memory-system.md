---
description: |
  ZylchMemory stores everything known about an entity (person, company) in a single natural-language
  "blob" - no structured fields. When new info arrives, existing memories update via reconsolidation
  (like human memory) instead of creating duplicates. Search uses hybrid FTS + semantic vectors
  (all-MiniLM-L6-v2, 384 dims) with namespace isolation per user (user:{uid}).
---

# Entity-Centric Memory System

## Overview

The Memory System (ZylchMemory) provides persistent, entity-centric memory for AI agents with semantic search and memory reconsolidation. Unlike traditional databases that create new entries for every piece of information, ZylchMemory mimics human memory by **updating existing memories** when new information arrives, preventing memory fragmentation and maintaining coherent knowledge.

Like the human memory, Zylch remembers a "blob" about an "entity", where the entity is loosely defined as anything which can have properties and can be connected to other entities. But be aware: "properties" are **not cathegorized**, everything we know about an entity is in a single natural language field, a blob with all information.

**The thesis**: Professional relationships exist entirely in language. LLMs don't need to learn physics to model relationships—they need to remember. ZylchMemory provides the persistent memory layer that transforms stateless LLMs into assistants that accumulate relational understanding over time.

---

## Key Concepts

### Memory Reconsolidation

**How human memory works**: When you learn someone moved to a new city, you don't create a second "location" memory—you *update* the existing one. Your brain reconsolidates the memory with new information.

**How ZylchMemory works**:
1. New information arrives: "Mario moved to Milan"
2. Search for similar existing memories using hybrid search (lexical + semantic)
3. If found: **UPDATE** the existing memory with new information
4. If not found: **CREATE** a new memory

**Why this matters**:
- No duplicate memories ("Mario lives in Rome" vs "Mario lives in Milan")
- Coherent knowledge graph (one source of truth per person/topic)
- Natural memory evolution (updates reflect reality changes)
- Prevents memory bloat (100 memories vs 1000 fragmented ones)

### Namespace Architecture

Namespaces define **ownership and access**, not content type. Entity identification happens through hybrid search, not namespace structure.

| Namespace Pattern             | Purpose | Example |
|-------------------------------|---------|---------|
| `user:{user_id}`              | All memories owned by a user | `user:mario_123` |
| `org:{org_id}`                | Shared organizational knowledge | `org:acme_corp` |
| `shared:{recipient}:{sender}` | Memories explicitly shared between users | `shared:luigi:mario` |

**Why no entity sub-namespaces?**
- Entity identity lives *in* the blob content, not the namespace
- Hybrid search finds "John Doe" across all of Mario's memories
- No need for entity resolution before storage
- Prevents fragmentation when same entity appears in different contexts

**Privacy guarantee**: Users can only access their own namespaces. Cross-user access requires explicit authorization (see [Sharing System](sharing-system.md)).

### Vector Embeddings & HNSW Indexing

**Semantic search** uses vector embeddings to find similar content:

```python
# Text → Vector (384 dimensions)
"Mario likes formal emails" → [0.12, -0.34, 0.56, ..., 0.89]
"John is a very important contact to Mario" → [0.15, -0.32, 0.58, ..., 0.91]

# Cosine similarity: 0.95 (very similar!)
# → Reconsolidate instead of creating duplicate
```

**HNSW (Hierarchical Navigable Small World)** index provides:
- **150x faster** search vs brute-force
- Sub-linear search time: O(log n) vs O(n)
- Configurable accuracy/speed tradeoff
- Memory-efficient graph structure

---

## Database Schema

### Table: `blobs` (main memory storage)
```sql
CREATE TABLE blobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_id TEXT NOT NULL,  -- Firebase UID for multi-tenancy
    namespace TEXT NOT NULL,  -- e.g., "user:{uid}", "org:{org_id}", "shared:{recipient}:{sender}"
    content TEXT NOT NULL,
    embedding VECTOR(384),  -- blob-level embedding (optional, for pre-filter)
    tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    events JSONB DEFAULT '[]'::jsonb,  -- [{timestamp, description, source}]
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_blobs_owner ON blobs(owner_id);
CREATE INDEX idx_blobs_namespace ON blobs(owner_id, namespace);
CREATE INDEX idx_blobs_tsv ON blobs USING GIN(tsv);
CREATE INDEX idx_blobs_embedding ON blobs USING hnsw(embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);
CREATE INDEX idx_blobs_updated ON blobs(updated_at DESC);

-- RLS
ALTER TABLE blobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY blobs_owner_policy ON blobs
    FOR ALL USING (owner_id = current_setting('app.current_user_id', true));
```

### Table: `blob_sentences` (sentence-level granularity for precise semantic search)
```sql
CREATE TABLE blob_sentences (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    blob_id UUID NOT NULL REFERENCES blobs(id) ON DELETE CASCADE,
    owner_id TEXT NOT NULL,  -- Denormalized for RLS
    sentence_text TEXT NOT NULL,
    embedding VECTOR(384) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_sentences_blob_id ON blob_sentences(blob_id);
CREATE INDEX idx_sentences_owner ON blob_sentences(owner_id);
CREATE INDEX idx_sentences_embedding ON blob_sentences USING hnsw(embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

-- RLS
ALTER TABLE blob_sentences ENABLE ROW LEVEL SECURITY;
CREATE POLICY sentences_owner_policy ON blob_sentences
    FOR ALL USING (owner_id = current_setting('app.current_user_id', true));
```

### Hybrid Search Function
```sql
CREATE OR REPLACE FUNCTION hybrid_search_blobs(
    p_owner_id TEXT,
    p_query TEXT,
    p_query_embedding VECTOR(384),
    p_namespace TEXT DEFAULT NULL,
    p_fts_weight FLOAT DEFAULT 0.5,
    p_limit INT DEFAULT 10
)
RETURNS TABLE (
    blob_id UUID,
    content TEXT,
    namespace TEXT,
    fts_score FLOAT,
    semantic_score FLOAT,
    hybrid_score FLOAT,
    events JSONB
) AS $$
BEGIN
    RETURN QUERY
    WITH fts_results AS (
        SELECT
            b.id,
            b.content,
            b.namespace,
            b.events,
            ts_rank(b.tsv, plainto_tsquery('english', p_query)) AS fts_score
        FROM blobs b
        WHERE b.owner_id = p_owner_id
          AND (p_namespace IS NULL OR b.namespace = p_namespace)
          AND b.tsv @@ plainto_tsquery('english', p_query)
    ),
    semantic_results AS (
        SELECT
            bs.blob_id,
            MAX(1 - (bs.embedding <=> p_query_embedding)) AS max_semantic_score
        FROM blob_sentences bs
        WHERE bs.owner_id = p_owner_id
          AND bs.blob_id IN (SELECT id FROM fts_results)
        GROUP BY bs.blob_id
    )
    SELECT
        f.id AS blob_id,
        f.content,
        f.namespace,
        COALESCE(f.fts_score, 0)::FLOAT AS fts_score,
        COALESCE(s.max_semantic_score, 0)::FLOAT AS semantic_score,
        (p_fts_weight * COALESCE(f.fts_score, 0) +
         (1 - p_fts_weight) * COALESCE(s.max_semantic_score, 0))::FLOAT AS hybrid_score,
        f.events
    FROM fts_results f
    LEFT JOIN semantic_results s ON f.id = s.blob_id
    ORDER BY hybrid_score DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;
```

---

## How It Works

### 1. Hybrid Search: Combining Semantic and Lexical Retrieval

Blobs contain free-form natural language, which creates a challenge: a query like "Who is John Smith?" has weak semantic similarity with a long blob that mentions John Smith only once among many other facts. Pure vector search dilutes the signal.

**Solution**: Hybrid search combining PostgreSQL full-text search (lexical) with pgvector (semantic), operating at sentence granularity.

#### Search Strategy

| Query Pattern | FTS Weight (α) | Rationale |
|---------------|----------------|-----------|
| Named entity ("John Smith", "Newco") | 0.7 | Exact match critical |
| Conceptual ("communication style") | 0.3 | Meaning matters more |
| Mixed ("John's email preferences") | 0.5 | Both signals useful |
| Short query (1-2 words) | 0.6 | Likely a name or keyword |

**Query type detection**: Boost FTS for capitalized words, proper nouns, short queries. Boost semantic for abstract nouns, questions, longer phrases.

#### Sentence-Level Similarity Aggregation

When computing semantic similarity for a blob, we compare the query against each sentence and aggregate:

| Method | Formula | Use Case |
|--------|---------|----------|
| **Max pooling** | `max(sim_1, sim_2, ..., sim_n)` | Default. Simple, effective. |
| **Top-k mean** | `mean(top_k(similarities))` | More robust, k=3 recommended |
| **Probabilistic disjunction** | `1 - ∏(1 - sim_i)` | Optimistic. Normalize by sentence count to avoid length bias. |

---

### 2. Storing Memory (with Reconsolidation)

#### Processing Flow

```
┌────────────────────────────────────────────────────────────────────────────┐
│  INPUT                                                                     │
│  ├─ namespace: "user:mario_123"                                            │
│  ├─ new_blob: "John Doe has become a customer"                             │
│  └─ event: {timestamp: "...", description: "User said..."}                 │
└────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────────┐
│  PHASE 1: EMBEDDING GENERATION                                             │
│                                                                            │
│  1. Generate query embedding from new_blob                                 │
│     embedding = embed("John Doe has become a customer")  → Vector(384)     │
│                                                                            │
│  2. Extract searchable terms for FTS                                       │
│     terms = ["John", "Doe", "customer"]                                    │
└────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────────┐
│  PHASE 2: HYBRID SEARCH FOR EXISTING MEMORIES                              │
│                                                                            │
│  Search within namespace (and optionally related namespaces)               │
│                                                                            │
│  Step A: Full-Text Search (PostgreSQL FTS)                                 │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ SELECT id, ts_rank(tsv, query) as fts_score                        │    │
│  │ FROM blobs                                                         │    │
│  │ WHERE namespace = 'user:mario_123'                                 │    │
│  │   AND tsv @@ plainto_tsquery('italian', 'John Doe customer')       │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                            │
│  Step B: Sentence-Level Semantic Search                                    │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ For each candidate blob from Step A (or all blobs if FTS empty):   │    │
│  │                                                                    │    │
│  │   SELECT blob_id,                                                  │    │
│  │          MAX(1 - (embedding <=> $query_embedding)) as max_sim      │    │
│  │   FROM blob_sentences                                              │    │
│  │   WHERE blob_id IN (candidate_ids)                                 │    │
│  │   GROUP BY blob_id                                                 │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                            │
│  Step C: Score Combination                                                 │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ hybrid_score = α × norm(fts_score) + (1-α) × norm(semantic_score)  │    │
│  │                                                                    │    │
│  │ Where α is determined by query type:                               │    │
│  │   - "John Doe" (proper noun) → α = 0.7                             │    │
│  │   - "customer relationship" → α = 0.3                              │    │
│  └────────────────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 3: DECISION - RECONSOLIDATE OR CREATE?                               │
│                                                                             │
│  Candidates = blobs with hybrid_score > RECONSOLIDATION_THRESHOLD (0.65)    │
│                                                                             │
│  ┌─────────────────────┐         ┌─────────────────────────────────────┐    │
│  │ No candidates found │         │ One or more candidates found        │    │
│  │                     │         │                                     │    │
│  │         │           │         │         │                           │    │
│  │         ▼           │         │         ▼                           │    │
│  │   GO TO PHASE 4B    │         │   GO TO PHASE 4A                    │    │
│  │   (Create New)      │         │   (Reconsolidate)                   │    │
│  └─────────────────────┘         └─────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
┌───────────────────────────────────┐ ┌───────────────────────────────────────┐
│  PHASE 4A: RECONSOLIDATION        │ │  PHASE 4B: CREATE NEW MEMORY          │
│                                   │ │                                       │
│  1. Select best matching blob     │ │  1. Insert new blob                   │
│     (highest hybrid_score)        │ │     ┌─────────────────────────────┐   │
│                                   │ │     │ INSERT INTO blobs           │   │
│  2. LLM-assisted merge            │ │     │ (namespace, content, events)│   │
│     ┌───────────────────────┐     │ │     │ VALUES (...)                │   │
│     │ Prompt to LLM:        │     │ │     └─────────────────────────────┘   │
│     │                       │     │ │                                       │
│     │ "Merge these memories │     │ │  2. Chunk into sentences              │
│     │ into a single coherent│     │ │     sentences = split_sentences(blob) │
│     │ blob:                 │     │ │                                       │
│     │                       │     │ │  3. Generate embeddings               │
│     │ EXISTING:             │     │ │     for each sentence:                │
│     │ {old_blob}            │     │ │       embedding = embed(sentence)     │
│     │                       │     │ │                                       │
│     │ NEW INFO:             │     │ │  4. Insert sentences                  │
│     │ {new_blob}            │     │ │     ┌─────────────────────────────┐   │
│     │                       │     │ │     │ INSERT INTO blob_sentences  │   │
│     │ Rules:                │     │ │     │ (blob_id,                   │   │
│     │ - Preserve all facts  │     │ │     │  sentence_text, embedding)  │   │
│     │ - Resolve conflicts   │     │ │     └─────────────────────────────┘   │
│     │   (new info wins)     │     │ │                                       │
│     │ - Keep it concise     │     │ │                                       │
│     │ - Natural language    │     │ └───────────────────────────────────────┘
│     └───────────────────────┘     │
│                                   │
│  3. Update blob                   │
│     ┌───────────────────────┐     │
│     │ UPDATE blobs SET      │     │
│     │   content = merged,   │     │
│     │   events = events ||  │     │
│     │           new_event,  │     │
│     │   updated_at = NOW()  │     │
│     │ WHERE id = blob_id    │     │
│     └───────────────────────┘     │
│                                   │
│  4. Cascade update sentences      │
│     ┌───────────────────────┐     │
│     │ DELETE FROM           │     │
│     │   blob_sentences      │     │
│     │ WHERE blob_id = ?     │     │
│     │                       │     │
│     │ Re-chunk and re-embed │     │
│     │ (same as Phase 4B)    │     │
│     └───────────────────────┘     │
│                                   │
└───────────────────────────────────┘
```

#### Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `RECONSOLIDATION_THRESHOLD` | 0.65 | Minimum hybrid score to trigger reconsolidation |
| `FTS_WEIGHT_DEFAULT` | 0.5 | Default α for score combination |
| `FTS_WEIGHT_NAMED_ENTITY` | 0.7 | α when query contains proper nouns |
| `FTS_WEIGHT_CONCEPTUAL` | 0.3 | α for abstract/conceptual queries |
| `SENTENCE_AGGREGATION` | "max" | How to aggregate sentence similarities |
| `TOP_K` | 3 | k for top-k mean aggregation |
| `EMBEDDING_MODEL` | "all-MiniLM-L6-v2" | Model for vector embeddings |

#### Example: Reconsolidation in Action

**Existing memory:**
```json
{
  "id": "UUID888",
  "namespace": "user:mario_123",
  "content": "#Identifiers\n\nEntity type: Person.\nName: John Doe.\nEmail: john.doe@newco.com.\nLinkedIn Profile: linkedin.com/in/johndoe.\n\n#About\n\nJohn is our contact at Newco. He prefers email communication.",
  "events": {"2025-02-21": "User mentioned John works at Newco"}
}
```

**New information:** "John Doe has become a customer"

**Hybrid search results:**
- FTS score (normalized): 0.82 (matches "John Doe")
- Semantic score (max sentence): 0.71
- α = 0.7 (named entity detected)
- **Hybrid score: 0.7 × 0.82 + 0.3 × 0.71 = 0.787** > 0.65 ✓

**LLM merge prompt:**
```
Merge these memories into a single coherent blob:

EXISTING: "#Identifiers\n\nEntity type: Person.\nName: John Doe.\nEmail: john.doe@newco.com.\nLinkedIn Profile: linkedin.com/in/johndoe.\n\n#About\n\nJohn is our contact at Newco. He prefers email communication."
NEW INFO: "John Doe has become a customer"

Rules: Preserve all facts, resolve conflicts (new wins), keep concise.
```

**Merged result:**
```json
{
  "id": "UUID888",
  "content": "#Identifiers\n\nEntity type: Person.\nName: John Doe.\nEmail: john.doe@newco.com.\nLinkedIn Profile: linkedin.com/in/johndoe.\n\n#About\n\nJohn is our contact at Newco and has become a customer. He prefers email communication.",
  "events": {
    "2025-02-21": "User mentioned John works at Newco",
    "2025-12-11": "User said John Doe has become a customer"
  }
}
```

---

### 3. Retrieving Memory

**User query**: "Who is John Doe?"

**Agent calls**:
```python
memories = zylch_memory.retrieve_memories(
    query="John Doe",
    namespace="user:mario_123",
    limit=5
)
```

**Search flow**:
1. **Analyze query type**
    - "John Doe" → proper noun detected → α = 0.7

2. **Hybrid search**
    - FTS: `tsv @@ plainto_tsquery('italian', 'John Doe')`
    - Semantic: sentence-level similarity with max aggregation
    - Combine: `0.7 × fts + 0.3 × semantic`

3. **Filter and rank**
    - Filter by namespace
    - Sort by hybrid_score descending

4. **Return results**:
```python
[
    {
        "id": "UUID888",
        "namespace": "user:mario_123",
        "content": "#Identifiers\n\nEntity type: Person.\nName: John Doe.\nEmail: john.doe@newco.com.\nLinkedIn Profile: linkedin.com/in/johndoe.\n\n#About\n\nJohn is our contact at Newco and has become a customer. He prefers email communication.",
        "hybrid_score": 0.92,
        "matching_sentences": ["John is our contact at Newco and has become a customer."]
    }
]
```

---

## Implementation Components

### Core Python Modules

| File | Purpose |
|------|---------|
| `zylch_memory/text_processing.py` | Sentence splitter with abbreviation handling |
| `zylch_memory/hybrid_search.py` | Hybrid FTS + semantic search engine |
| `zylch_memory/llm_merge.py` | LLM-assisted memory reconsolidation |
| `zylch_memory/blob_storage.py` | Blob CRUD with Supabase |
| `zylch_memory/embeddings.py` | Embedding generation (all-MiniLM-L6-v2) |
| `zylch_memory/config.py` | Configuration parameters |

### Sentence Splitter

Handles:
- Abbreviations (Dr., Mr., Inc., S.r.l., etc.)
- Decimal numbers (3.14)
- Ellipsis (...)
- URLs (preserved, not split)
- Split on `.` `!` `?` only at sentence boundaries

### LLM Merge Service

```python
MERGE_PROMPT = """Merge these memories into a single coherent blob:

EXISTING MEMORY:
{existing}

NEW INFORMATION:
{new}

Rules:
1. Preserve ALL facts from both memories
2. Resolve conflicts - new information wins for time-sensitive facts (titles, locations, status)
3. Keep the result concise and well-organized
4. Use natural language prose, not bullet points
5. Maximum 500 words

Output ONLY the merged memory text, nothing else."""
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/memory/store` | Store blob (with auto-reconsolidation) |
| GET | `/api/memory/search?q=...` | Hybrid search |
| GET | `/api/memory/{blob_id}` | Get specific blob |
| PUT | `/api/memory/{blob_id}` | Update blob (with LLM merge) |
| DELETE | `/api/memory/{blob_id}` | Delete blob |
| GET | `/api/memory/` | Get statistics |

---

## Performance Considerations

- Index `blob_sentences.embedding` with HNSW for fast ANN search
- Use GIN index on `blobs.tsv` for FTS
- Consider materialized view for namespace prefixes if query patterns are predictable
- Batch sentence insertions when creating/updating blobs
- API response times < 500ms for all endpoints
- Hybrid search latency: < 200ms for 10K blobs
