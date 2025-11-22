# Task Management System - Person-Centric Email Intelligence

## What is a Task?

A task exists when Mario needs to take action. Period.

NOT about whether it's:
- An answer vs a reminder
- Urgent vs non-urgent
- Email vs meeting follow-up

ONLY about: **Does Mario need to do something?**

### Task Detection Logic
```python
# The core logic is simple:
requires_action = (expected_action is not None)

# NOT:
requires_action = (expected_action == 'answer')  # ❌ Too narrow!

# Because:
# - "answer a question" → TASK
# - "send promised document" → TASK
# - "fix something" → TASK
# - "follow up on meeting" → TASK
# - "remind customer who didn't respond" → TASK
# - ALL of these need expected_action != None
```

### Task Categories (for context only)
While we don't classify for filtering, these are common task patterns:
1. **Answer**: Contact asked, Mario must respond
2. **Deliver**: Mario promised something (document, fix, information)
3. **Follow-up**: Contact expected to respond but didn't → Mario reminds
4. **Fix**: Technical issue Mario said he'd resolve
5. **Schedule**: Need to arrange meeting/call

ALL of these are TASKs. None should be filtered out.

### Task Aggregation
Tasks are grouped by PERSON:
- One person = maximum one task
- Sonnet analyzes ALL threads with that person
- Provides single consolidated action needed

---

## The Problem

Traditional email clients (Gmail, Outlook, Superhuman) organize emails by **threads**. This creates problems for B2B sales professionals:

### Example: Luisa Boni's 5 Threads
```
Thread 1: "Re: Urgente" (Feb 2024)
Thread 2: "Passaggio al nuovo assistente MrCall" (Nov 5)
Thread 3: "settaggio wa" (Nov 19)
Thread 4: "settaggio orari segreteria" (Nov 19)
Thread 5: "Richiesta per passaggio" (Nov 13-19)
```

**Problem**: You have to mentally aggregate:
- What's the overall situation with Luisa?
- Is she happy or at risk?
- What action do I need to take?
- How urgent is it?

---

## MrPark's Solution: Person-Centric Tasks

**One person = One task (maximum)**

MrPark aggregates ALL threads from the same contact into a unified task view.

### Example Output
```
📋 Task: Luisa Boni

Email: studioped.boni@gmail.com
Status: open
Priority: 10/10 (URGENT)
Threads: 5

View:
Il contatto ha avuto problemi con l'assistente precedente ("Re: Urgente")
ed è stata migrata a un nuovo assistente ("Passaggio al nuovo assistente
MrCall"). Ha problemi di configurazione (WhatsApp, orari, messaggi) ed è
molto ansiosa per la migrazione - ha detto di non dormire la notte.
Rischiamo di perdere questa cliente.

Action:
Contattare SUBITO - rischio di perdere la cliente. Chiamare o scrivere
oggi per rassicurarla e risolvere i problemi di configurazione.
```

**Benefits:**
- ✅ See the **full picture** instantly
- ✅ Understand **emotional context** (anxious, frustrated, happy)
- ✅ Know **priority** (1-10 score)
- ✅ Get **actionable next step**

---

## Architecture

### Two-Tier System

```
┌─────────────────────────────────────────────────────────────┐
│ Gmail API                                                   │
│ (Fetches emails via OAuth)                                 │
└──────────────────────┬──────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────┐
│ TIER 1: Thread Cache (threads.json)                        │
│                                                             │
│ - Haiku analysis (~$0.92/1K emails)                        │
│ - Fast sync (Gmail API → JSON)                             │
│ - Thread-by-thread view                                    │
│ - Preserves all details                                    │
│ - Enables search (subject, participants, body)             │
│                                                             │
│ Example:                                                    │
│ {                                                           │
│   "thread_123": {                                           │
│     "subject": "settaggio wa",                              │
│     "participants": ["studioped.boni@gmail.com"],           │
│     "summary": "Chiede come resettare messaggio WA",        │
│     "open": true,                                           │
│     "expected_action": "answer"                             │
│   }                                                         │
│ }                                                           │
└──────────────────────┬──────────────────────────────────────┘
                       ↓
         TaskManager.build_tasks_from_threads()
         (Groups by contact, analyzes with Sonnet)
                       ↓
┌─────────────────────────────────────────────────────────────┐
│ TIER 2: Task Cache (tasks.json)                            │
│                                                             │
│ - Sonnet analysis (~$1.40/200 contacts)                    │
│ - Person-centric aggregation                               │
│ - One task per contact                                     │
│ - Intelligent view with context                            │
│ - Priority scoring (1-10)                                  │
│                                                             │
│ Example:                                                    │
│ {                                                           │
│   "contact_luisa_boni": {                                   │
│     "contact_name": "Luisa Boni",                           │
│     "contact_email": "studioped.boni@gmail.com",            │
│     "status": "open",                                       │
│     "score": 10,                                            │
│     "view": "Cliente ansiosa...",                           │
│     "action": "Contattare SUBITO",                          │
│     "threads": ["thread_123", "thread_456", ...]            │
│   }                                                         │
│ }                                                           │
└─────────────────────────────────────────────────────────────┘
```

### Why Two Tiers?

**Thread Cache (Tier 1):**
- Fast to sync (Haiku is cheap and fast)
- Preserves all email details
- Enables granular search
- Source of truth for raw email data

**Task Cache (Tier 2):**
- Expensive to build (Sonnet analysis)
- But only built once or on-demand
- Provides **actionable intelligence**
- Saves time: you see what matters

---

## Contact Identification

### The Challenge
MrPark needs to identify **who is the contact** (vs. you) in each thread.

**Example thread participants:**
```
From: Luisa Boni <studioped.boni@gmail.com>
To: Mario Alemi <mario.alemi@mrcall.ai>
Cc: Support <support@mrcall.ai>
```

**Question:** Who is the "contact" here?
- Not mario.alemi@mrcall.ai (that's you!)
- Not support@mrcall.ai (that's you too!)
- **Answer:** studioped.boni@gmail.com

### Solution: MY_EMAILS Configuration

In `.env`:
```bash
MY_EMAILS=mario.alemi@gmail.com,mario.alemi@mrcall.ai,support@mrcall.ai,*@pipedrivemail.com
```

**Features:**
- Comma-separated list
- Supports wildcards: `*@pipedrivemail.com` matches all Pipedrive automated emails
- Used to filter out "you" and find "them"

**Algorithm:**
```python
def _extract_contact_email(thread):
    participants = thread.get('participants')  # [email1, email2, ...]

    for participant in participants:
        if not _is_my_email(participant):
            return participant  # This is the contact!

    return None
```

---

## Task Analysis with Sonnet

### Input Context
When analyzing a contact, TaskManager provides Sonnet with:

```json
{
  "contact_email": "studioped.boni@gmail.com",
  "contact_name": "Luisa Boni",
  "threads_count": 5,
  "threads": [
    {
      "subject": "Re: Urgente",
      "date": "2024-02-06",
      "summary": "Problema critico con assistente",
      "body_preview": "Grazie! Mi potete informare quando risolto?...",
      "open": true,
      "expected_action": "answer"
    },
    {
      "subject": "Passaggio al nuovo assistente",
      "date": "2025-11-05",
      "summary": "Migrazione a nuovo assistente confermata",
      "body_preview": "Buongiorno. Va bene grazie...",
      "open": false,
      "expected_action": null
    },
    // ... 3 more threads
  ]
}
```

### Sonnet Prompt
```
Analyze these 5 email threads for Luisa Boni and create a TASK summary.

IMPORTANT: This is B2B context. One person = one task maximum.
Aggregate ALL threads into a single unified view.

Respond with JSON:
{
  "contact_name": "First Last",
  "view": "Narrative summary of entire relationship and current situation.
           Include: what happened chronologically, current problems,
           emotional state (anxious, frustrated, happy), context.",
  "status": "open|closed|waiting",
  "score": 1-10,
  "action": "Specific next step"
}

Rules:
- status: "open" = needs our action, "waiting" = waiting for them, "closed" = done
- score: 1 (low) to 10 (URGENT - risk losing customer)
- view: Italian, natural narrative, 2-4 sentences
- action: Specific next step in Italian
```

### Output
```json
{
  "contact_name": "Luisa Boni",
  "contact_emails": ["studioped.boni@gmail.com", "lunibo@gmail.com"],
  "view": "Il contatto ha avuto problemi con l'assistente precedente...",
  "status": "open",
  "score": 10,
  "action": "Contattare SUBITO - rischio di perdere la cliente..."
}
```

---

## Usage Patterns

### Initial Setup (First Time)

```bash
# 1. Sync emails (30 days, Haiku analysis)
You: sync emails
# Takes: ~5-10 minutes for 1000 emails
# Cost: ~$0.92

# 2. Build tasks (Sonnet aggregation)
You: build tasks
# Takes: ~2-3 minutes for 200 contacts
# Cost: ~$1.40

# Total: ~$2.50, 10-15 minutes
```

### Daily Workflow

```bash
# Morning: Check urgent tasks
You: show urgent tasks
# Returns: All tasks with score >= 8

# Work on specific contact
You: status di Luisa Boni
# Returns: Full aggregated view + action

# Update after contact
You: rebuild tasks  # Optional, only if many new emails
```

### Incremental Updates

```bash
# New emails arrived? Sync threads
You: sync emails
# Fast: only fetches new emails since last sync

# Update specific contact's task
You: get contact task studioped.boni@gmail.com
# On-demand: re-analyzes only that contact
# Cost: <$0.01
```

---

## API / Tool Reference

### build_tasks
**Description:** Build tasks.json from threads.json (batch operation)

**Parameters:**
- `force_rebuild` (bool, default: false) - Rebuild even if cache exists

**Usage:**
```
You: build tasks
You: build tasks force_rebuild=true
```

**Cost:** ~$7 per 1K contacts (Sonnet)

---

### get_contact_task
**Description:** Get/rebuild task for specific contact (on-demand)

**Parameters:**
- `contact_email` (string, required) - Contact email address

**Usage:**
```
You: status di Luisa Boni
You: get contact task studioped.boni@gmail.com
```

**Cost:** ~$0.007 per contact (< 1 cent)

---

### search_tasks
**Description:** Search tasks with filters

**Parameters:**
- `status` (string, optional) - Filter by: "open", "closed", "waiting"
- `min_score` (int, optional) - Minimum priority score (1-10)
- `query` (string, optional) - Search in name/email/view

**Usage:**
```
You: show urgent tasks          # min_score=8
You: show open tasks            # status=open
You: search tasks luisa         # query="luisa"
You: tasks score 7 status open  # combined
```

---

### task_stats
**Description:** Get task statistics

**Usage:**
```
You: task stats
You: overview tasks
You: situazione generale
```

**Returns:**
- Total tasks
- Open tasks
- Urgent tasks (score >= 8)
- Average priority score
- Last build timestamp

---

## Performance & Costs

### Initial Sync (First Time)
| Operation | Volume | Model | Time | Cost |
|-----------|--------|-------|------|------|
| Sync emails | 1000 emails | Haiku | 5-10 min | $0.92 |
| Build tasks | 200 contacts | Sonnet | 2-3 min | $1.40 |
| **Total** | | | **~12 min** | **$2.32** |

### Daily Usage
| Operation | Frequency | Model | Cost/day |
|-----------|-----------|-------|----------|
| Sync new emails | 1x/day (50 new) | Haiku | $0.05 |
| Update 5 contacts | As needed | Sonnet | $0.04 |
| **Total** | | | **~$0.10** |

### Monthly Cost Estimate
- Initial: $2.32 (one-time)
- Daily: $0.10 × 30 = $3.00
- **Total: ~$5.50/month** for 1000 emails, 200 contacts

---

## Future Enhancements

### Reasoning History (Planned)
Track decisions and actions over time:

```json
{
  "task_id": "contact_luisa",
  "reasoning_history": [
    {
      "date": "2025-11-19T10:00:00Z",
      "reasoning": "Cliente ansiosa, rischio perdita. Decision: chiamare.",
      "action_taken": "Chiamata rassicurante effettuata",
      "user": "mario"
    },
    {
      "date": "2025-11-19T15:30:00Z",
      "reasoning": "Ancora confusa su WA. Decision: inviare guida.",
      "action_taken": "Email con screenshot inviata",
      "user": "mario"
    }
  ]
}
```

**Benefits:**
- Continuity: Don't repeat same actions
- Context: Sonnet knows what was already tried
- Learning: Patterns emerge over time
- Audit trail: Full history of decisions

---

## Best Practices

### 1. Sync Strategy
- **Initial:** 30 days (fixed)
- **Daily:** Incremental (only new emails)
- **After absence:** `sync emails force_full=true`

### 2. Task Rebuild Frequency
- **Daily:** Not needed (expensive!)
- **Weekly:** `build tasks force_rebuild=true`
- **On-demand:** `get contact task [email]` for specific contacts

### 3. Contact Identification
- Add ALL your email addresses to `MY_EMAILS`
- Use wildcards for automated services: `*@pipedrivemail.com`, `*@noreply.github.com`
- Test: search for a known contact and verify they appear correctly

### 4. Search vs Tasks
- **Use search_emails when:** Looking for specific thread/subject
- **Use tasks when:** Want to understand overall situation with a person

---

## Troubleshooting

### "No tasks found for [email]"
**Cause:** Email might not be in threads cache

**Solution:**
1. Check: `search emails [email]`
2. If found: `get contact task [email]` (rebuilds on-demand)
3. If not found: `sync emails` first

### "Task shows wrong contact"
**Cause:** Your email not in `MY_EMAILS`

**Solution:**
1. Add your email to `MY_EMAILS` in `.env`
2. Restart MrPark
3. `build tasks force_rebuild=true`

### "Task is outdated"
**Cause:** New emails arrived but task not rebuilt

**Solution:**
1. `sync emails` (updates threads)
2. `get contact task [email]` (updates that task)
3. Or: `build tasks force_rebuild=true` (updates all)

---

## Technical Details

### Thread Grouping Algorithm
```python
def _group_threads_by_contact(threads):
    contact_threads = {}

    for thread in threads:
        # Find the contact (not me)
        contact_email = _extract_contact_email(thread)

        if contact_email:
            if contact_email not in contact_threads:
                contact_threads[contact_email] = []

            contact_threads[contact_email].append(thread)

    return contact_threads
```

### Cc Handling
Threads can have contacts in Cc field:
```
From: You
To: Person A
Cc: Person B, Person C
```

**Question:** Who is the "contact"?

**Answer:** First non-you email in participants list.

In this example: Person A (from To field)

Person B and C are also tracked in `participants` for search, but task is created for Person A.

### StarChat Integration
When analyzing, TaskManager tries to enrich from StarChat:
```python
contact = starchat.get_contact_by_email(contact_email)

# If found, includes:
# - contact.name
# - contact.phone
# - contact.id
# - Any other StarChat variables
```

This enriches the task with phone numbers, CRM data, etc.

---

## Comparison: Threads vs Tasks

### Thread View (Traditional)
```
Inbox:
1. "settaggio wa" - Luisa Boni
2. "Re: Urgente" - Luisa Boni
3. "Passaggio al nuovo assistente" - Luisa Boni
4. "Order confirmation" - Amazon
5. "settaggio orari" - Luisa Boni
```

**You must mentally:**
- Realize #1, #2, #3, #5 are same person
- Remember context from each thread
- Decide priority
- Figure out next action

### Task View (MrPark)
```
Tasks:
1. Luisa Boni (10/10 URGENT) - 5 threads
   Status: open
   Action: Contattare SUBITO - rischio perdita cliente

2. Amazon (1/10) - 1 thread
   Status: closed
   Action: None
```

**MrPark does:**
- ✅ Aggregates 5 threads → 1 task
- ✅ Analyzes context from all threads
- ✅ Assigns priority (10/10)
- ✅ Suggests action

**You just:**
- See what matters
- Take action

---

## Summary

**MrPark's Task Management System transforms email from "inbox chaos" to "actionable intelligence".**

- **Problem:** Email clients show threads, you think in people
- **Solution:** MrPark aggregates threads by person
- **Result:** One person = one task = one clear action

**Cost:** ~$5/month for typical usage
**Time saved:** Hours per week in mental aggregation

**Philosophy:** Email is about relationships, not threads.
