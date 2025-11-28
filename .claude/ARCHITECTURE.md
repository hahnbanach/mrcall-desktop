# Zylch Architecture

## System Overview

Zylch is an AI-powered email assistant that provides relationship intelligence, task management, and automated email workflows through multiple interfaces (CLI, HTTP API).

## Core Components

### 1. Agent System (`zylch/agent/`)
- **Purpose**: Orchestrates AI conversations with tool access
- **Key Files**:
  - `core.py`: Main agent logic, tool orchestration
  - `models.py`: Agent data models
  - `prompts.py`: System prompts and templates

### 2. Tools (`zylch/tools/`)
Modular tools for agent capabilities:
- **Email**: Gmail API wrapper, draft management, sending
- **Archive**: SQLite-backed permanent email storage with FTS5 search
- **Calendar**: Google Calendar integration with Meet links
- **Tasks**: Email-to-task extraction, relationship gap analysis
- **CRM**: Pipedrive integration (optional)
- **Contacts**: StarChat/MrCall integration

**Key Pattern**: Tools are stateless classes with `execute()` method

### 3. Two-Tier Email System

**Tier 1: Archive (`email_archive.py` + `email_archive_backend.py`)**
- **Purpose**: Permanent storage of ALL emails
- **Technology**: SQLite with FTS5 full-text search
- **Sync**: Gmail History API (incremental, <1s)
- **Features**: Complete history, never loses data

**Tier 2: Intelligence Cache (`email_sync.py`)**
- **Purpose**: AI-analyzed threads for relationship intelligence
- **Technology**: JSON cache (`threads.json`)
- **Window**: 30-day rolling window
- **Features**: AI enrichment, task extraction, gap analysis

**Data Flow**:
```
Gmail → Archive (permanent) → Intelligence Cache (analyzed) → Gap Analysis
```

### 4. Service Layer (`zylch/services/`)

**Purpose**: Business logic shared between CLI and API (no duplication)

**Key Services**:
- **SyncService**: Email/calendar synchronization
  - `sync_emails()`, `sync_calendar()`, `run_full_sync()`
- **GapService**: Relationship gap analysis
  - `analyze_gaps()`, `get_gaps_summary()`, `get_email_tasks()`
- **ChatService**: Conversational AI (wraps CLI for tool access)
- **ArchiveService**: Email archive operations

**Pattern**: CLI and API both use the same service layer functions

```python
# CLI uses:
sync_service.run_full_sync(days_back=30)

# API exposes:
POST /api/sync/full {"days_back": 30}
# → calls sync_service.run_full_sync(days_back=30)
```

### 5. API Layer (`zylch/api/`)

**Structure**:
```
routes/        # FastAPI endpoints
services/      # Business logic layer (shared with CLI)
```

**Key APIs**:
- `/api/chat` - Conversational AI endpoint (wraps CLI)
- `/api/archive` - Email archive operations
- `/api/sync` - Email/calendar sync
- `/api/gaps` - Relationship gap analysis

### 6. CLI (`zylch/cli/main.py`)
Interactive command-line interface:
- `/sync` - Morning workflow (archive + intelligence + calendar + gaps)
- `/gaps` - Show relationship gaps
- `/archive` - Archive management
- `/memory` - Memory system
- Natural conversation with agent

## Key Architectural Decisions

### Decision 1: Two-Tier Email Caching

**Problem**: Old system re-fetched 600+ emails every sync (15-30 min), lost history outside 30-day window

**Solution**:
- **Archive**: Permanent SQLite storage (all emails forever)
- **Intelligence Cache**: 30-day analyzed window (AI-enriched)

**Benefits**:
- 100x faster sync (<1s vs 15-30min)
- Complete history preserved
- Efficient AI analysis (only recent emails)

### Decision 2: Person-Centric Task Detection

**Problem**: Thread-based gaps miss follow-ups across multiple threads

**Solution**: Aggregate threads by contact email, detect tasks at person level

**Implementation** (`relationship_analyzer.py:find_email_tasks()`):
```python
# Group threads by contact
person_threads = {}
for thread in threads:
    contact_email = extract_contact(thread)
    person_threads[contact_email].append(thread)

# Detect tasks per person
for contact_email, threads in person_threads.items():
    last_thread = max(threads, key=lambda t: t['last_email']['date'])
    needs_action = detect_task(last_thread, person_context=threads)
```

### Decision 3: Manual Closure Persistence

**Problem**: User-closed threads reopened after sync

**Solution**: `manually_closed` flag in thread data
- Set by `mark_threads_closed_by_subject()`
- Preserved during sync (NEVER re-analyze manually closed threads)
- Respected by gap analysis

### Decision 4: Auto-Sync After Email Send

**Problem**: Gap analysis outdated after sending emails

**Solution**: Trigger incremental sync after `send_gmail_draft`
- Adds 1-3s latency to email send (acceptable)
- Keeps cache current automatically
- Implementation in `factory.py:_SendDraftTool`

### Decision 5: Chat API Wraps CLI

**Problem**: Duplicating tool initialization for HTTP API

**Solution**: `ChatService` wraps `ZylchAICLI` class
- Reuses all tool initialization
- No code duplication
- Single source of truth

**Trade-off**: Inherits CLI dependencies (memory system, StarChat)

## Data Storage

### Persistent Storage
- **Archive DB**: `cache/emails/archive.db` (SQLite)
- **Intelligence Cache**: `cache/emails/threads.json` (JSON)
- **Calendar Cache**: `cache/calendar/` (JSON)
- **OAuth Tokens**: `credentials/gmail_tokens/` (pickle)

### Configuration
- **Environment**: `.env` file
- **Defaults**: `zylch/config.py` (Pydantic settings)

## External Integrations

### Google APIs
- **Gmail**: Read, send, drafts (OAuth 2.0)
- **Calendar**: Events, Meet links (OAuth 2.0)
- **Auth**: Shared credentials for Gmail + Calendar

### Anthropic Claude
- **Models**:
  - Haiku: Fast classification (~$0.92/1K emails)
  - Sonnet: Default analysis (~$7/1K emails)
  - Opus: Executive communications (high cost)
- **Features**: Tool use, prompt caching

### Optional Integrations
- **Pipedrive**: CRM sync
- **StarChat/MrCall**: Contact management, WhatsApp integration (pending API endpoint)
- **SendGrid**: Bulk email (not currently used)

### WhatsApp Integration (Pending)

**Status**: Tool structure ready, awaiting StarChat REST API endpoint

**Architecture**:
- Tool: `_GetWhatsAppContactsTool` in `factory.py`
- Client method: `StarChatClient.get_whatsapp_contacts()`
- Required endpoint: `GET /mrcall/v1/crm/whatsapp/{businessId}/messages`
- Authentication: StarChat BasicAuth (NEVER direct database access)

**Implementation**:
1. Tool registered and ready to use
2. Returns empty list with message until StarChat provides endpoint
3. See `STARCHAT_REQUESTS.md` Request #3 for API specification

**Critical Security Rule**:
- **NEVER** bypass StarChat authentication with direct PostgreSQL access
- **ALWAYS** use StarChat REST API endpoints with proper authentication
- All data access must go through authenticated API calls

## Security & Privacy

### Authentication
- **Local**: Gmail OAuth tokens stored locally
- **API**: No authentication (development mode)

### Data Privacy
- All email data stored locally
- No data sent to third parties (except Claude for analysis)
- SQLite database encrypted if filesystem encrypted

## Performance Characteristics

### Email Operations
- **Initial archive sync**: ~2 min (one-time, 500 emails)
- **Incremental sync**: <1s (Gmail History API)
- **Intelligence cache build**: ~30s (30-day window)
- **Email search**: <100ms (FTS5 index)

### API Response Times
- **Chat message**: 2-5s (depends on tool usage)
- **Archive search**: 100-300ms
- **Gap analysis**: 1-3s

## Scalability Considerations

### Current Limits
- **Emails**: Tested with 500 messages, scales to millions with SQLite
- **Threads**: 30-day intelligence window (~250-300 threads typical)
- **Concurrent API**: Single worker (development)

### Future Scaling
- **Archive**: Migrate to PostgreSQL for multi-user
- **API**: Add workers, load balancer
- **Cache**: Redis for session management
- **Search**: Consider Elasticsearch for advanced queries

## Error Handling

### Gmail API Errors
- **History ID expired**: Automatic fallback to date-based sync
- **Rate limits**: Exponential backoff (handled by google-api-python-client)
- **Auth expiry**: Automatic token refresh

### Database Errors
- **Archive corruption**: Manual re-initialization required
- **SQLite locks**: Use WAL mode for concurrent access

## Development Patterns

### Tool Development
1. Create class in `zylch/tools/`
2. Implement `execute()` method
3. Register in `factory.py:create_all_tools()`
4. Add to agent's available tools

### API Endpoint Development
1. Create Pydantic models in `api/routes/`
2. Implement business logic in `services/`
3. Register router in `api/main.py`
4. Test with `/docs` (Swagger UI)

### Testing Strategy
- **Unit tests**: Tool logic (pytest)
- **Integration tests**: API endpoints (pytest + TestClient)
- **Manual tests**: CLI commands, real Gmail account

## Memory System Philosophy

### Core Principle: Zylch is Person-Centric

**A person is NOT an email address.** A person can have:
- Multiple email addresses (work, personal, aliases)
- Multiple phone numbers (mobile, office, WhatsApp)
- Multiple names (formal name, nickname, company role)

The memory system must reflect this reality. When you ask "who is Luigi?", Zylch should find the person regardless of which identifier you use.

### How Human Memory Works (and Zylch Should Too)

Human memory has three phases:
1. **Encoding**: New information arrives
2. **Consolidation**: Information integrates with existing memories
3. **Reconsolidation**: When you recall a memory AND receive new info, you UPDATE the existing memory

Humans don't create parallel conflicting memories. If someone gives you a new phone number, you update your mental model of that person - you don't keep two "phone number memories" in your head.

**Zylch must work the same way.**

### The Problem We Solved

Before: `store_memory()` always did INSERT. If you stored:
1. "Tizio's phone is 348..."
2. Later: "Tizio's phone is 339..." (new number)

You'd have TWO memories that could conflict during retrieval. The system might return the old number!

### The Solution: Memory Reconsolidation

When storing a new memory:
1. Generate embedding for the new content
2. Search existing memories for semantic similarity (cosine > 0.85 threshold)
3. If similar memory exists → **UPDATE** it (reconsolidate)
4. If no similar memory → **INSERT** new memory

This mirrors human memory reconsolidation.

### Two-Layer Memory Architecture

**Layer 1: Identifier Map Cache (`zylch/cache/identifier_map.py`)**
- **Purpose**: O(1) lookup from any identifier to person
- **Technology**: JSON file with normalized identifiers
- **Key insight**: Maps email/phone/name → memory_id
- **Benefit**: Avoids expensive remote API calls (Gmail 10+ seconds) when contact is already known

**Layer 2: Semantic Memory (`zylch_memory/`)**
- **Purpose**: Vector-based semantic storage with reconsolidation
- **Technology**: SQLite + HNSW index + sentence-transformers
- **Key insight**: Similar memories are the SAME memory (updated, not duplicated)

### Memory Lookup Flow

When user asks "info su Luigi":

```
1. search_local_memory("Luigi")
   ↓
2. IdentifierMapCache.lookup("Luigi")  [O(1), <1ms]
   ↓
   If found AND fresh (TTL 7 days) → RETURN CACHED DATA
   If found BUT stale → Return cached + suggest refresh
   If not found → Proceed to remote searches
   ↓
3. Remote searches (ONLY if not in cache):
   - get_contact() from StarChat
   - search_emails() from local archive
   - search_gmail() from Gmail API (10+ seconds!)
   - search_calendar_events()
```

### Configuration

```python
# zylch_memory/config.py
similarity_threshold: float = 0.85  # Conservative: only merge truly similar memories
confidence_boost_on_update: float = 0.1  # Reinforce memory on reconsolidation
```

### Implementation Details

**Files modified for reconsolidation:**
- `zylch_memory/zylch_memory/config.py` - Added threshold configs
- `zylch_memory/zylch_memory/storage.py` - Added `update_memory()`, `get_embedding_by_id()`
- `zylch_memory/zylch_memory/core.py` - Added `_find_similar_memories()`, modified `store_memory()`

**Files for person-centric lookup:**
- `zylch/cache/identifier_map.py` - IdentifierMapCache class
- `zylch/tools/factory.py` - `_SearchLocalMemoryTool`, modified `_SaveContactTool`
- `zylch/agent/prompts.py` - "LOCAL MEMORY FIRST" instructions

### Example: Reconsolidation in Action

```python
# First store
id1 = mem.store_memory(
    namespace="contacts",
    category="person",
    context="Contact info for Luigi Scrosati",
    pattern="phone: 348-1234567"
)
# → Creates memory ID 1, confidence 0.5

# Second store (similar content)
id2 = mem.store_memory(
    namespace="contacts",
    category="person",
    context="Contact info for Luigi Scrosati",
    pattern="telephone: 339-9876543 (updated)"
)
# → Similarity 0.97 > 0.85 threshold
# → RECONSOLIDATES memory ID 1
# → Returns ID 1, confidence now 0.6, pattern updated
# → Only ONE memory exists!
```

### When Reconsolidation Does NOT Happen

If texts are semantically different (similarity < 0.85), new memory is created:

```python
# "Tizio phone 348" vs "Tizio tel 339"
# Similarity: 0.72 (different numbers = different semantics)
# → Creates NEW memory (correct behavior!)
```

### The force_new Parameter

For cases where you WANT to create a distinct memory even if similar exists:

```python
mem.store_memory(..., force_new=True)  # Bypasses similarity check
```

## Known Limitations

1. **HNSW index updates**: HNSW doesn't support in-place vector updates. After reconsolidation, the old vector position remains until index rebuild. This is acceptable for now.
2. **Contact tools**: Not available in API (CLI-only, require StarChat)
3. **Stateless API**: Client manages conversation history
4. **Single account**: Gmail OAuth for one account per deployment
