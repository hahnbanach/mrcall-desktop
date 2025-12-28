# Zylch Von Neumann Memory Architecture

> **⚠️ HISTORICAL DESIGN DOC**
>
> This document describes a planned architecture. **The Avatar system was never implemented** - the CRM Agent write pipeline was never built.
>
> **Current Reality:** Tasks come from `task_items` table via `/tasks` command. See `.claude/ARCHITECTURE.md` for up-to-date architecture.

## Overview

Zylch's data architecture is inspired by the **Von Neumann machine model**, separating long-term storage (Memory) from working state (CRM/Avatar).

```
┌─────────────────────────────────────────────────────────┐
│                         I/O                              │
│        (Email, Calendar, WhatsApp, Phone Calls)         │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │   MEMORY    │  ← Writes to Memory
                    │    AGENT    │
                    └──────┬──────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│                      MEMORY                               │
│            (mass storage - the past)                      │
│                                                           │
│  Stable knowledge that accumulates over time:            │
│  • "Tiziano works at Tesia Snc"                          │
│  • "We communicate in Italian"                           │
│  • "Interested in MrCall partnership"                    │
│  • "On 12/3 he wrote about X" (past event = OK)          │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │     CRM     │  ← Reads Memory
                    │    AGENT    │    + timestamps from I/O
                    └──────┬──────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│              WORKING MEMORY / CRM                         │
│              (registers - the present)                    │
│                                                           │
│  Computed state, volatile, recalculated on each sync:    │
│  • status: open/waiting/closed                           │
│  • priority: 1-10                                        │
│  • action: "Reply about partnership"                     │
└──────────────────────────────────────────────────────────┘
```

## Core Principles

### 1. Memory = Mass Storage (The Past)

**What it stores**: Accumulated knowledge about people, relationships, preferences, past events.

**Characteristics**:
- **Persistent**: Never lost (only updated via reconsolidation)
- **Stable**: Facts don't change frequently
- **Semantic**: Searchable by meaning, not just keywords
- **Person-centric**: Organized around contacts, not events

**Examples of valid Memory content**:
```
✓ "Tiziano D'Agostino works at Tesia Snc"
✓ "We use Italian in our communications"
✓ "He prefers formal but cordial tone"
✓ "On 12/3/2025 he sent an email about partnership proposal"
✓ "Mario (owner) typically writes emails in Italian"
```

**NOT valid for Memory** (temporal state):
```
✗ "I need to reply to Tiziano" (changes when you reply)
✗ "6 days since last contact" (changes every day)
✗ "His email requires response" (inferred, not fact)
```

### 2. Working Memory/CRM = Registers (The Present)

**What it stores**: Current actionable state, computed from Memory + timestamps.

**Characteristics**:
- **Volatile**: Recalculated on every sync
- **Computed**: Derived from Memory + I/O timestamps
- **Structured**: Exact fields (status, priority, action)
- **Actionable**: Answers "what should I do now?"

**Examples of Working Memory content**:
```
contact_id: "abc123"
status: "open"           ← computed from "last email was from contact"
priority: 7              ← computed from "important topic + 6 days old"
action: "Reply about partnership proposal"
last_email_date: "2025-12-03"
last_email_direction: "inbound"
```

### 3. Agents = CPU (Processing)

Two specialized agents transform data between layers:

#### Memory Agent
- **Input**: Raw data from I/O (emails, calendar, WhatsApp)
- **Output**: Extracted knowledge written to Memory
- **Responsibilities**:
  - Extract facts from communications
  - Identify contact information (phones, LinkedIn)
  - Detect language preferences
  - Note communication style
  - Record events as past facts

#### CRM Agent
- **Input**: Memory content + timestamps from email_archive
- **Output**: Computed state written to Working Memory/CRM
- **Responsibilities**:
  - Determine status (open/waiting/closed)
  - Calculate priority (1-10)
  - Generate suggested action
  - Identify urgent items

## Data Flow

### On New Email Arrival

```
1. Email arrives in email_archive (I/O)
         │
         ▼
2. Memory Agent triggered
         │
         ├─ Extracts: "Tiziano mentioned partnership timeline"
         ├─ Extracts: "Phone number in signature: +39..."
         ├─ Detects: "Email in Italian"
         │
         ▼
3. Memory updated (new facts stored, existing reconsolidated)
         │
         ▼
4. CRM Agent triggered
         │
         ├─ Reads: Memory facts about Tiziano
         ├─ Reads: email_archive timestamp (last email from him, 12/3)
         ├─ Computes: status = "open" (his email, I didn't reply)
         ├─ Computes: priority = 7 (important topic + 6 days)
         │
         ▼
5. Working Memory/CRM updated
```

### On User Query "Who should I contact?"

```
1. Query goes to CRM (Working Memory)
         │
         ├─ SELECT * FROM avatars
         │  WHERE status = 'open'
         │  ORDER BY priority DESC
         │
         ▼
2. Returns: Tiziano (priority 7), Marco (priority 5), ...
```

### On User Query "What do I know about Tiziano?"

```
1. Query goes to Memory (semantic search)
         │
         ├─ Vector search: "Tiziano"
         │
         ▼
2. Returns: All accumulated knowledge
   - Works at Tesia Snc
   - Italian language
   - Partnership interest
   - Past email events
```

## Database Tables

### Memory Layer (Supabase `memories` table)

```sql
CREATE TABLE memories (
    id UUID PRIMARY KEY,
    owner_id TEXT NOT NULL,           -- Firebase UID
    namespace TEXT NOT NULL,          -- "contact:email" or "user:owner_id"
    category TEXT NOT NULL,           -- "contacts", "preferences", "events"
    context TEXT,                     -- Descriptive context
    pattern TEXT,                     -- The actual knowledge
    examples JSONB,                   -- Supporting examples
    confidence REAL DEFAULT 0.5,
    embedding vector(384),            -- For semantic search
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);
```

### Working Memory Layer (Supabase `avatars` table)

```sql
CREATE TABLE avatars (
    id UUID PRIMARY KEY,
    owner_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    display_name TEXT,

    -- Computed state (volatile)
    relationship_status TEXT,         -- 'open', 'waiting', 'closed'
    relationship_score INTEGER,       -- 1-10 priority
    suggested_action TEXT,

    -- Aggregated stats (from email_archive)
    last_interaction TIMESTAMPTZ,
    last_email_direction TEXT,        -- 'inbound', 'outbound'

    -- Computed on each sync
    last_computed TIMESTAMPTZ,
    compute_trigger TEXT,

    UNIQUE(owner_id, contact_id)
);
```

## Key Differences from Current Implementation

### Current (Problematic)

```
Email ──→ Avatar Worker ──→ AVATAR
                │
                └─ Extracts phone, LinkedIn, status, priority
                   directly from emails (bypasses Memory)

Email ──→ ??? ──→ MEMORY (unclear when/how populated)
```

**Problems**:
1. Avatar Worker reads emails directly, not from Memory
2. Memory and Avatar are parallel systems, not layered
3. No single source of truth

### Proposed (Von Neumann)

```
Email ──→ Memory Agent ──→ MEMORY ──→ CRM Agent ──→ AVATAR
```

**Benefits**:
1. All knowledge goes through Memory first
2. Avatar/CRM is a computed view, not primary storage
3. Memory is single source of truth
4. If Avatar is lost, recalculate from Memory

## Owner Profile

A special case: **the owner's own preferences** should also be in Memory.

```
namespace: "user:{owner_id}"
category: "preferences"
pattern: "Mario writes emails primarily in Italian"
```

This allows Zylch to know:
- Owner's language preference
- Owner's communication style
- Owner's timezone
- Owner's signature preferences

## Questions for Implementation

1. **Memory Agent trigger**: On every email, or batch during `/sync`?
2. **CRM Agent trigger**: After Memory Agent, or separate schedule?
3. **Owner profile**: Auto-detect from email patterns, or explicit setup?
4. **Conflict resolution**: When Memory says "formal" but recent email is casual?

## Related Files

- `zylch/services/avatar_aggregator.py` - Current avatar aggregation (to be refactored)
- `zylch/workers/avatar_compute_worker.py` - Current avatar computation (to be refactored)
- `zylch_memory/zylch_memory/core.py` - Memory system core
- `zylch/storage/supabase_client.py` - Database access layer

## References

- Von Neumann Architecture: https://en.wikipedia.org/wiki/Von_Neumann_architecture
- Human Memory Systems: Working Memory vs Long-Term Memory
- Current Architecture: `.claude/ARCHITECTURE.md`
