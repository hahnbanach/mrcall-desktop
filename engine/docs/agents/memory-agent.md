---
description: |
  Processes incoming emails to extract relationship facts, storing in entity-centric blobs with
  automatic reconsolidation. Training uses thread-based email fetching (20 threads, last email
  per thread only) to avoid context window overflow.
---

# Memory Agent

Extracts facts from emails and stores them in entity-centric blobs with reconsolidation.

## Purpose

Process incoming emails to extract relationship information about contacts, storing in blobs: an entity already known is updated rather than duplicated, and consolidation folds the duplicates left behind.

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
    """Collects each channel's sources and takes them through the harness.

    Flow, for every channel:
    1. Fetch the source and render it (envelope and body, or the call's text)
    2. Hand the rendered text, the admitted stage and the extraction closure to
       ``ingestion.ingest``, which pays for extraction under the source's own
       grant, persists the manifest and decides every extracted entity through
       the mnemonic role and the retaining commit
    3. Mark the source processed only when the answer says every child is
       terminal — committed, or deliberately skipped
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

## Updating instead of duplicating

Each extracted entity is one child event of its source's operation
(`zylch/memory/mnemonic/ingestion.py`). The mnemonic role is shown at most 3
candidates — the identity-index matches for the entity's own identifiers, never
the sender's, and hybrid-search results — and decides UPDATE, CREATE, SKIP or
REVIEW; the validator refuses a second CREATE of an entity a candidate already
corroborates, and the harness commits in one transaction
([mnemonic-decisions.md](../features/mnemonic-decisions.md)). While the merge
gate is unhealthy the role is shown no candidate, so every entity becomes a
fresh memory.

The candidates come from the company store, so the worker matches against
the entities every colleague's mail produced, not only this account's
(scope in [`../features/entity-memory-system.md`](../features/entity-memory-system.md)).

A second, company-wide pass — consolidation, `zylch/memory/consolidation.py` —
clusters the entity family by shared `person_identifiers` rows (union-find, the
stated `Name:` as fallback), asks the role about each pair that the
validator's own identity rule could accept, and commits a MERGE through the
harness: the donor's links, the identifiers the merged text states and an
alias move to the keeper, and both texts are kept as versions. It also applies
the version-retention policy and reports the sinks. The daemon runs it at the
end of every update's memory stage when the shared store changed since the
last sweep started (a join, a merge, a new entity or identifier); the Settings
→ Maintenance button and `zylch memory-sweep` force it. One sweep per company
at a time — the other daemons answer "another engine is sweeping".

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
For each entity (one child event):
     |
     +-> candidates: identity-index matches + hybrid search -> at most 3
     |
     +-> the mnemonic role decides; the validator checks
     |         |
     |         +-> UPDATE a candidate / CREATE a new memory: one commit
     |         |
     |         +-> SKIP / REVIEW: recorded, nothing written
     |
     v
mark_email_processed() once every child is terminal
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
| `zylch/workers/memory.py` | MemoryWorker implementation |
| `zylch/memory/mnemonic/ingestion.py` | One source, one parent operation, one child per entity |
| `zylch/memory/consolidation.py` | Consolidation: retention, sinks, duplicate pairs |
| `zylch/memory/llm_merge.py` | The merge-routed client pairs are decided with, and the merge-gate canary |
| `zylch/memory/hybrid_search.py` | HybridSearchEngine for finding candidates |
| `zylch/memory/blob_storage.py` | BlobStorage for persistence |

## Related

- [Entity Memory System](../features/entity-memory-system.md) - Blob storage details
- [Emailer Agent](emailer-agent.md) - Uses blobs for email composition
- [Task Agent](task-agent.md) - Uses blobs for task context
