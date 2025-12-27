# Relationship Intelligence System

## Philosophy: Task-First, Not Classification-First

***********************************************************
  QUELLO CHE DOBBIAMO CAPIRE È SE DOBBIAMO CREARE UN TASK
***********************************************************

Zylch AI's goal is NOT to classify emails into categories.
Zylch AI's goal IS to identify what Mario needs to do.

### The Only Question
When analyzing any email thread, ask ONE question:
**"C'È BISOGNO DI CREARE UN TASK PER MARIO?"**

- Does the contact expect something from Mario NOW?
- Does Mario expect something from himself?
- **Was the contact expected to respond but didn't?** → Mario needs to follow up

If any is true → TASK
If all are false → NO TASK (thread closed)

### AI-Generated Email Detection

**CRITICAL RULE**: Email AI-generated da business developer = NO TASK

**Segnali di email AI-generated:**
1. Struttura troppo perfetta con bullet points formattati
2. Linguaggio marketing eccessivamente ottimizzato (buzzwords)
3. Pattern ripetitivi e template-like
4. Zero personalizzazione reale oltre al nome
5. Formattazione elaborata (emoji, spacing perfetto, sezioni)

**Business Logic:**
- Business Developer che "offre opportunità" = vuole VENDERE (stand, sponsorship, servizi)
- Cold outreach AI-generated = spam qualificato
- Low-effort outreach = priorità BASSA / NO TASK

**Esempio:**
```
Da: Irene Lorenzo <irene@sesamers.com>
Subject: Café 124 at Vitafoods Europe 2026

Hi Mario,
I hope you're doing well.

Reaching out from Sesamers where we are curating...
• Clean, functional beverages backed by clear science
• Active ingredients with proven claims
• Lifestyle formats that scale quickly into retail & D2C
```

→ **NO TASK** (Email 100% AI-generated da business developer che vuole vendere stand)

### Performance Philosophy
- Precision > Cost (always use Sonnet, not Haiku)
- Full context > Partial analysis
- Real-time > Batch processing

## Overview

Zylch AI uses an **Avatar System** that aggregates intelligence per-contact. Each avatar contains:
- Communication patterns across all channels (email, calendar, etc.)
- Pending tasks and action items
- Relationship health indicators

## Key Concept

**Instead of just managing individual channels separately, Zylch AI analyzes patterns across all communication to answer:**
- Did you follow up after that meeting?
- Should you schedule a call for that urgent email?
- Which important contacts have gone silent?

## Architecture

```
Data Flow:
├─ sync_emails() → Supabase `emails` table
├─ sync_calendar() → Supabase `calendar_events` table
└─ Avatar Worker (background) → Supabase `avatars` table
    ├─ Per-contact aggregation
    ├─ Task detection via LLM
    └─ Priority scoring
```

## Components

### 1. Avatar System (`zylch/services/avatar_aggregator.py`)
- Aggregates data per-contact (email address)
- Computes tasks, status, priority
- Stores in Supabase `avatars` table with `pg_vector` embeddings

### 2. Task Detection
Each avatar contains:
- All threads with this contact
- All calendar events involving this contact
- AI-computed tasks (what Mario needs to do)
- Read tracking data (if enabled)

## Task Examples
A TASK is needed when:
1. **Mario must answer**: Contact asked a question
2. **Mario must deliver**: He promised to send something
3. **Mario must fix**: He said he would solve a problem
4. **Mario must follow up**: Contact was expected to respond but didn't
5. **Mario must remind**: Contact needs to provide information they forgot

NOT a task:
- Contact thanked Mario and conversation naturally ended
- All commitments fulfilled, no pending actions
- Ball is in contact's court AND they know it

## CLI Commands

### `/sync` - Sync data from providers
Runs the complete sync workflow:
```bash
$ /sync

📧 Syncing emails...
   ✅ Email sync complete: 5 new, 2 updated

📅 Syncing calendar...
   ✅ Calendar sync complete: 3 events

⏳ Avatar computation queued
```

### `/briefing` or `/tasks` - View your tasks
Shows actionable tasks computed from avatars:
```bash
$ /briefing

📋 YOUR TASKS
============================================================

🔴 HIGH PRIORITY:
1. John Smith - Reply to contract question
   📧 Last email: 2 days ago
   💡 He asked about Q4 pricing

⚡ MEDIUM PRIORITY:
1. Maria Rossi - Schedule follow-up call
   📅 Meeting was 5 days ago
   💡 Promised to send proposal

💤 LOW PRIORITY:
1. Tom Wilson - Check in
   ⏰ 45 days since last contact
```

## Data Storage

All data is stored in Supabase with `owner_id` scoping:

| Table | Purpose |
|-------|---------|
| `emails` | Email metadata and content |
| `calendar_events` | Calendar events |
| `avatars` | Per-contact intelligence blobs |
| `avatar_compute_queue` | Background processing queue |

## Testing

### Run tests:
```bash
pytest tests/test_avatar_aggregator.py
```

## References

- **Email sync**: `zylch/services/sync_service.py`
- **Avatar aggregation**: `zylch/services/avatar_aggregator.py`
- **Task formatting**: `zylch/services/task_formatter.py`
- **Background worker**: `zylch/workers/avatar_compute_worker.py`
