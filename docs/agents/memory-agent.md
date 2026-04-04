---
description: |
  Processes incoming emails to extract relationship facts, storing in entity-centric blobs with
  automatic reconsolidation. Training uses thread-based email fetching (20 threads, last email
  per thread only) to avoid context window overflow.
---

# Memory Agent

Extracts facts from emails and stores them in entity-centric blobs with reconsolidation.

## Purpose

Process incoming emails to extract relationship information about contacts, storing in blobs with automatic merging of existing knowledge.

## Training: Thread-Based Email Fetching

The memory agent trainer uses **thread-based fetching** to avoid context window overflow:

- **20 threads** (not 100 individual emails)
- **Last email per thread only** — contains quoted conversation history
- Fetches 3x limit to ensure enough unique threads after grouping
- Prioritizes **PERSON** and **COMPANY** extraction over TEMPLATEs

## Components

### MemoryWorker

```python
class MemoryWorker:
    """Extract facts from emails and store in entity-centric blobs.

    Flow:
    1. Extract facts from email about the contact
    2. Search for existing blob about this entity (hybrid search)
    3. If found: LLM-merge new facts with existing knowledge
    4. If not found: create new blob
    5. Mark email as processed
    """
```

### Dependencies

```python
from zylch.llm import LLMClient
from zylch.storage import Storage
from zylch.memory import BlobStorage, HybridSearchEngine, LLMMergeService, EmbeddingEngine
```

## Data Sources

| Source | Method | Fields Used |
|--------|--------|-------------|
| Emails | `process_email()` | from_email, to_email, subject, body_plain, date |

## Entity Extraction

Uses LLM with extraction prompt. Multiple entities from a single email separated by `---ENTITY---`.

## Reconsolidation

When a new entity is extracted, the agent searches for existing blobs:

1. Find top 3 candidates above threshold (hybrid search)
2. For each candidate, try LLM merge
3. If LLM says INSERT (entities don't match), try next candidate
4. If no suitable blob found, create new one

## Flow

```
Email arrives
     |
     v
process_email()
     |
     +-> _extract_entities() -> LLM extracts PERSON/COMPANY entities
     |         |
     |         v
     |    _parse_entities() -> Split by ---ENTITY---
     |
     v
For each entity:
     |
     +-> find_candidates_for_reconsolidation() -> Top 3 matches
     |
     +-> LLMMergeService.merge() -> Merge or INSERT?
     |         |
     |         +-> Merge: update_blob()
     |         |
     |         +-> INSERT: Try next candidate or store_blob()
     |
     v
mark_email_processed()
```

## Entity Types

### PERSON
- **#IDENTIFIERS**: Name, email, phone
- **#ABOUT**: Role, company, relationship context
- **#HISTORY**: Timeline of interactions

### COMPANY
- **#IDENTIFIERS**: Company name, domain
- **#ABOUT**: Industry, services, relationship type
- **#HISTORY**: Business interactions timeline

### TEMPLATE
Reusable response pattern. When a similar inquiry arrives, the assistant can draft a response based on the template.

## Files

| File | Purpose |
|------|---------|
| `zylch/agents/memory_agent.py` | MemoryWorker implementation |
| `zylch/memory/llm_merge.py` | LLMMergeService for blob merging |
| `zylch/memory/hybrid_search.py` | HybridSearchEngine for finding candidates |
| `zylch/memory/blob_storage.py` | BlobStorage for persistence |

## Related

- [Entity Memory System](../features/entity-memory-system.md) - Blob storage details
- [Emailer Agent](emailer-agent.md) - Uses blobs for email composition
- [Task Agent](task-agent.md) - Uses blobs for task context
