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

/*MARIO CHANGED */

| Namespace Pattern             | Purpose | Example |
|-------------------------------|---------|---------|
| `user:{user_id}`              | User-specific preferences | `user:mario_123` |
| `contact:{contact_id}`        | Informations about a contact | `contact:john_456` |
| `shared:{recipient}:{sender}` | Shared intelligence | `shared:luigi_456:mario_123` |

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

### Categories  <= /*MARIO: DELETED, NOT USED!!!!*/

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
/*MARIO: THIS HAS BEEN SIMPLIFIED*/
```python
memory_id = zylch_memory.store_memory(
    namespace="user:mario_123",    
    context="Email communication style",
    pattern="Use formal tone when emailing clients",
    event={"2025-12-11T22:05:43.234UTC": "The user said to me that we should use only 'Lei' when writing in Italian"} # /*MARIO this is new */
)
```

**Processing flow**:
1. **Generate embedding** from context and pattern separately /*MARIO: IT WAS context + pattern */
    - context: "Email communication style" 
    - pattern: "Use formal tone when emailing clients"
    - Embedding model: `all-MiniLM-L6-v2` (384-dim vector)
    - Cached to avoid recomputation

2. **Check for similar memories**
    - Search namespace `user:mario_123`
    - Find memories with cosine similarity > 0.85 (configurable) in context
    - ==> Call Haiku to check if there is a pattern to be changed: for instance "Use friendly tone" that must become "Use formal tone" /*MARIO THIS IS NEW */
    - If found: **RECONSOLIDATE** (update existing memory)
    - If not found: **CREATE NEW** memory

3. **Reconsolidation** (if similar memory exists):
   ```python
   # Found context "Email communication" (similarity 0.92)
   # UPDATE instead of creating duplicate
   # /*MARIO let's say that the old entry was: 
   #  namespace="user:mario_123",    
   #  context="communication style",
   #  pattern="Use friendly tone",
   # {"2025-02-21T12:25:11.234UTC": "The user told me to write to the contact anna@company.co, who is a customer, and to use friendly tone"} 
   # this is an example of memory being updated with a different pattern: first Zylch had the impression it should have used 'tu', then it was clearly instructed to use 'Lei'. That's why, before 2025-12-11T22:05, the pattern was 'Use friendly tone'! */
   
   storage.update_memory(
       memory_id=existing['id'],
       pattern="Use formal tone when emailing clients",  # New pattern
       context="Email communication style",  # New context
       confidence_delta=0.1,  # Boost confidence (+0.1)
       new_embedding_id=new_embedding_id,  # Update embedding
       new_event={"2025-12-11T22:05:43.234UTC": "The user said to me that we should use only 'Lei' when writing in Italian"}
   )

   # Result: Memory updated, no duplicate created
   # Confidence: 0.8 → 0.9
   ```

4. **New memory** (if no similar found):
   ```python
   memory_id = storage.store_memory(
       namespace="user:mario_123",
       context="Email communication style",
       pattern="Use formal tone when emailing clients",
       embedding_id=embedding_id,
       confidence=0.8,
       events=[{"2025-12-11T22:05:43.234UTC": "The user said to me that we should use only 'Lei' when writing in Italian"},{"datetime": "2025-02-21T12:25:11.234UTC", "event": "The user told me to write to the contact anna@company.co, who is a customer, and to use friendly tone"}]
   )

   # Add to HNSW index for fast retrieval
   index.add(vector, memory_id)
   ```

### 2. Retrieving Memory

**User query**: "How should I write to the CEO?"

**Agent calls**:
```python
memories = zylch_memory.retrieve_memories(
    query="email communication style for John Smith, CEO",
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
           "context": "Email communication style",
           "pattern": "Use formal tone when emailing clients",
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

### 3. Pattern Learning  /*MARIO  NOT YET, DELETE!!!! */
/*MARIO  DELETED */

**User behavior**: Agent suggests action → User approves/rejects → Confidence updated

**Example**:
```
Agent: "Should I schedule the meeting next Monday for 9 AM?"
User: "No, on Monday I prefer afternoon meetings, pls put that in memory!"

# Pattern stored:
pattern_id = zylch_memory.store_pattern(
    namespace="user:mario_123",
    context="Scheduling meeting",
    pattern="
    outcome="rejected",
    confidence=0.3  # Low confidence (rejected)
)

# Next time:
Agent: "Should I schedule the meeting for Monday morning?"
User: "NO! As said, meeting on Monday should be in the afternoon, put that in memory pls"

# Search pattern
....
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

### 4. Cascading Retrieval  /*MARIO  DELETED */

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
/*MARIO REMAKE THIS COMPLETELY!!!! 

WE NEED MIGRATION SQL QUERIES AS WELL

*/
