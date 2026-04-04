---
description: |
  Entity-centric memory: everything about an entity stored in a single natural-language blob.
  New info triggers reconsolidation (update, not duplicate). Hybrid search: SQLite text LIKE +
  fastembed cosine similarity (384-dim, numpy). No pgvector, no HNSW — in-memory brute-force.
---

# Entity-Centric Memory System

## Overview

The Memory System stores persistent, entity-centric knowledge for AI agents with semantic search and memory reconsolidation. Unlike traditional databases, it **updates existing memories** when new information arrives, preventing fragmentation.

Everything about an entity is in a single natural-language "blob" — no structured fields, no categories. Properties live in free-form text.

**The thesis**: Professional relationships exist in language. LLMs don't need physics — they need memory. This system provides persistent memory that accumulates relational understanding over time.

## Key Concepts

### Memory Reconsolidation

Like human memory: when you learn someone moved to Milan, you update the existing memory, not create a second one.

1. New information arrives: "Mario moved to Milan"
2. Hybrid search for similar existing memories
3. If found: **UPDATE** via LLM merge
4. If not found: **CREATE** new blob

### Hybrid Search

Blobs contain free-form text, so pure vector search dilutes the signal. Solution: combine text matching with semantic similarity.

| Query Pattern | Strategy | Rationale |
|---------------|----------|-----------|
| Named entity ("John Smith") | Text LIKE weighted higher | Exact match critical |
| Conceptual ("communication style") | Semantic weighted higher | Meaning matters more |
| Mixed ("John's email preferences") | Balanced | Both signals useful |

**Implementation** (standalone):
- **Text search**: SQLite LIKE queries on blob content
- **Semantic search**: fastembed (ONNX, 384-dim) embeddings stored as BLOB in SQLite, loaded into numpy arrays, cosine similarity computed in-memory
- **No pgvector, no HNSW**: brute-force cosine similarity via numpy (fast enough for single-user scale)

### Entity Types

**PERSON**: Individual contact information
- `#IDENTIFIERS`: Name, email, phone
- `#ABOUT`: Role, company, relationship
- `#HISTORY`: Interaction timeline

**COMPANY**: Organization information
- `#IDENTIFIERS`: Name, domain
- `#ABOUT`: Industry, services
- `#HISTORY`: Business interactions

**TEMPLATE**: Reusable response pattern — how the user typically responds to recurring inquiry types. Enables the assistant to draft similar responses for new inquiries.

## Reconsolidation Flow

```
New info arrives
     │
     ▼
Generate embedding (fastembed)
     │
     ▼
Hybrid search: text LIKE + cosine similarity
     │
     ├── Score > threshold (0.65) ──► LLM merge with best match
     │                                   │
     │                                   ▼
     │                              Update blob + re-embed sentences
     │
     └── No match ──► Create new blob + embed sentences
```

### LLM Merge

```
Merge these memories into a single coherent blob:

EXISTING: {old_blob}
NEW INFO: {new_blob}

Rules:
1. Preserve ALL facts
2. Resolve conflicts (new info wins)
3. Keep concise, natural language
```

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `RECONSOLIDATION_THRESHOLD` | 0.65 | Min score to trigger merge |
| `EMBEDDING_MODEL` | all-MiniLM-L6-v2 | fastembed model (ONNX) |
| Embedding dimensions | 384 | Vector size |

## Files

| File | Purpose |
|------|---------|
| `zylch/memory/blob_storage.py` | Blob CRUD (embeddings as BLOB in SQLite) |
| `zylch/memory/embeddings.py` | fastembed wrapper (ONNX, 384-dim) |
| `zylch/memory/hybrid_search.py` | InMemoryVectorIndex + text search |
| `zylch/memory/llm_merge.py` | LLM-assisted reconsolidation |
| `zylch/memory/text_processing.py` | Sentence splitting, text normalization |
| `zylch/memory/pattern_detection.py` | Pattern extraction |
| `zylch/memory/config.py` | Memory configuration |
