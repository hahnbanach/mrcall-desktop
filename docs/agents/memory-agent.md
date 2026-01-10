# Memory Agent

Extracts facts from emails and stores them in entity-centric blobs with reconsolidation.

## Purpose

Process incoming data (emails, calendar events, Pipedrive deals) to extract relationship information about contacts, storing in blobs with automatic merging of existing knowledge.

## Training: Thread-Based Email Fetching

The memory agent trainer uses **thread-based fetching** to avoid context window overflow:

- **20 threads** (not 100 individual emails)
- **Last email per thread only** - contains quoted conversation history
- Fetches 3x limit to ensure enough unique threads after grouping

This pattern reduces prompt size from ~200k+ tokens to a manageable size while preserving full conversation context.

## Components

### MemoryWorker

Main worker class that processes events:

```python
class MemoryWorker:
    """Worker for extracting facts from emails and storing in entity-centric blobs.

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
from zylch.storage.supabase_client import SupabaseStorage
from zylch.memory import BlobStorage, HybridSearchEngine, LLMMergeService, EmbeddingEngine
```

## Data Sources

The Memory Agent processes three types of data sources:

| Source | Method | Fields Used |
|--------|--------|-------------|
| Emails | `process_email()` | from_email, to_email, subject, body_plain, date |
| Calendar | `process_calendar_event()` | summary, description, location, start_time, attendees |
| Pipedrive | `process_pipedrive_deal()` | title, person_name, org_name, value, status, stage |

## Entity Extraction

### Email Extraction

Uses user's custom prompt (trained via `/agent train email`):

```python
def _extract_entities(self, email: Dict, contact_email: str) -> List[str]:
    """Extract entities from email using LLM.

    Requires user's custom prompt (from /agent train email).
    Returns a list of entity blobs (one per entity found).
    """
    prompt_template = self._get_extraction_prompt()
    if not prompt_template:
        return []  # No prompt configured

    prompt = prompt_template.format(
        from_email=email.get("from_email", "unknown"),
        to_email=...,
        cc_email=...,
        subject=email.get("subject", "(no subject)"),
        date=email.get("date", "unknown"),
        body=body[:4000],
        contact_email=contact_email
    )
```

### Entity Delimiter

Multiple entities from a single email are separated by `---ENTITY---`:

```python
def _parse_entities(self, raw_output: str) -> List[str]:
    ENTITY_DELIMITER = "---ENTITY---"
    if ENTITY_DELIMITER in raw_output:
        parts = raw_output.split(ENTITY_DELIMITER)
    else:
        parts = [raw_output]  # Single entity
```

## Reconsolidation

When a new entity is extracted, the agent searches for existing blobs about the same entity:

```python
async def _upsert_entity(self, entity_content: str, event_desc: str, ...):
    # Get top 3 candidates above threshold
    existing_blobs = self.hybrid_search.find_candidates_for_reconsolidation(
        owner_id=self.owner_id,
        content=entity_content,
        namespace=self.namespace,
        limit=3
    )

    for existing in existing_blobs:
        # Try to merge with this candidate
        merged_content = self.llm_merge.merge(existing.content, entity_content)

        # If LLM says INSERT, entities don't match - try next
        if 'INSERT' in merged_content.upper() and len(merged_content) < 10:
            continue

        # Successful merge
        self.blob_storage.update_blob(
            blob_id=existing.blob_id,
            content=merged_content,
            ...
        )
        return

    # No suitable blob found, create new
    self.blob_storage.store_blob(...)
```

### LLM Merge Decision

The `LLMMergeService` decides whether to merge or insert:

- **Merge**: Entities match (same person/company), combine information
- **INSERT**: Entities don't match, create separate blob

## Usage

### From Background Job

```python
worker = MemoryWorker(
    storage=storage,
    owner_id=user_id,
    api_key=api_key,
    provider="anthropic"
)

# Process batch of emails
emails = storage.get_unprocessed_emails(owner_id, limit=50)
processed = await worker.process_batch(emails)

# Process calendar events
events = storage.get_unprocessed_calendar_events(owner_id, limit=50)
processed = await worker.process_calendar_batch(events)
```

### Custom Prompt Requirement

The agent requires a trained prompt before processing:

```python
if not worker.has_custom_prompt():
    return "Run /agent train email first"
```

## Flow Diagram

```
Email arrives
     │
     ▼
process_email()
     │
     ├─► _extract_entities() ─► LLM extracts PERSON/COMPANY entities
     │         │
     │         ▼
     │    _parse_entities() ─► Split by ---ENTITY---
     │
     ▼
For each entity:
     │
     ├─► find_candidates_for_reconsolidation() ─► Top 3 matches
     │
     ├─► LLMMergeService.merge() ─► Merge or INSERT?
     │         │
     │         ├─► Merge: update_blob()
     │         │
     │         └─► INSERT: Try next candidate or store_blob()
     │
     ▼
mark_email_processed()
```

## Processed Tracking

Each data source has a `processed_at` timestamp:

| Table | Column |
|-------|--------|
| `emails` | `processed_at` |
| `calendar_events` | `processed_at` |
| `pipedrive_deals` | `processed_at` |

## Files

| File | Purpose |
|------|---------|
| `zylch/agents/memory_agent.py` | MemoryWorker implementation |
| `zylch/memory/llm_merge.py` | LLMMergeService for blob merging |
| `zylch/memory/hybrid_search.py` | HybridSearchEngine for finding candidates |
| `zylch/memory/blob_storage.py` | BlobStorage for persistence |

## Entity Types

The memory agent extracts three types of entities:

### PERSON
Information about a specific individual (contact, colleague, client).
- **#IDENTIFIERS**: Name, email, phone
- **#ABOUT**: Role, company, relationship context
- **#HISTORY**: Timeline of interactions

### COMPANY
Information about an organization.
- **#IDENTIFIERS**: Company name, domain
- **#ABOUT**: Industry, services, relationship type
- **#HISTORY**: Business interactions timeline

### TEMPLATE
A **reusable response pattern** - how the user typically responds to recurring categories of inquiries.
- **#IDENTIFIERS**: Category name (e.g., "Unhandled Call Complaints Response")
- **#ABOUT**: What triggers this response, the response content/tone/style
- **#HISTORY**: Instances where this response pattern was used

**TEMPLATE Purpose**: When a new inquiry of the same type comes in, the assistant can search memory, find the TEMPLATE, and draft a similar response.

**Example TEMPLATE**:
```
#IDENTIFIERS
Entity type: TEMPLATE
Name: Unhandled Call Complaints Response

#ABOUT
Trigger: Customer asks why they received "unhandled call" notifications
Response: Italian apology explaining temporary technical issue, reassuring no action needed
Tone: Professional, reassuring
Language: Italian

#HISTORY
- 2025-01-08: Sent to Fani Motors regarding unhandled call complaints
- 2025-01-07: Sent to Studio Dotesio regarding same issue
```

## Related

- [Entity Memory System](../features/entity-memory-system.md) - Blob storage details
- [Emailer Agent](emailer-agent.md) - Uses blobs for email composition
- [Task Agent](task-agent.md) - Uses blobs for task context
