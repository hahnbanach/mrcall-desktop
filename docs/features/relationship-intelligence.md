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

Zylch AI now includes a **Relationship Intelligence** system that correlates communication across multiple channels (email, calendar, etc.) to identify relationship gaps and opportunities.

## Key Concept

**Instead of just managing individual channels separately, Zylch AI analyzes patterns across all communication to answer:**
- Did you follow up after that meeting?
- Should you schedule a call for that urgent email?
- Which important contacts have gone silent?

## Architecture

```
Morning Sync (5am via cron):
├─ sync_emails() → cache/emails/threads.json
├─ sync_calendar() → cache/calendar/events.json
└─ analyze_gaps() → cache/relationship_gaps.json
    ├─ Meetings without follow-up email 📅→❌📧
    ├─ Urgent emails without meeting 📧→❌📅
    └─ Silent contacts (>30 days) 💤
```

## Components

### 1. CalendarSyncManager (`zylch/tools/calendar_sync.py`)
- Syncs events from Google Calendar (-30/+30 day window)
- Caches in `cache/calendar/events.json`
- Tracks attendees, external contacts, past/future events
- Methods: `get_events_by_contact()`, `get_recent_meetings()`, `search_events()`

### 2. RelationshipAnalyzer (`zylch/tools/relationship_analyzer.py`)
- Correlates `threads.json` + `events.json`
- Uses **AI-powered semantic filtering** with Claude Sonnet to identify genuinely important emails
- Integrates with **Memory System** for personalized filtering rules
- Identifies 3 types of relationship gaps:

#### Gap Type 1: Meeting without follow-up email
**Problem**: You had a meeting but didn't send a follow-up email within 48 hours.

**Example**:
```
Meeting with John Smith (3 days ago)
📅 Client meeting about Q4 strategy
✉️  No follow-up email sent yet
💡 Suggested: Draft follow-up email
```

#### Gap Type 2: Urgent email without meeting
**Problem**: Email is marked urgent/important but no meeting is scheduled.

**Intelligence Features**:
- 🤖 **AI Semantic Filtering**: Claude Sonnet analyzes email content to distinguish genuine requests from newsletters/marketing
- 🧠 **Memory-Based Personalization**: Learns user preferences (e.g., "always ignore reminder@superhuman.com")
- 🚫 **Bot Detection**: Automatically filters out automated emails (noreply@, notifications@, etc.)
- ✅ **Meeting Acceptance Filter**: Only flags meetings you actually accepted/organized

**Example**:
```
John Smith's email (2 days ago)
📧 URGENT: Contract review needed
🔥 Priority: 9/10
📅 No meeting scheduled
💡 Suggested: Propose a meeting
```

#### Gap Type 3: Silent contacts
**Problem**: Contact with past interactions but no communication in 30+ days.

**Example**:
```
Maria Rossi
📊 5 past interactions (3 emails, 2 meetings)
⏰ 45 days since last contact
💡 Suggested: Re-engage with check-in email
```

## Email Task Detection

### Person-Level Aggregation
Tasks are aggregated by PERSON, not by individual thread:
- All threads from a person are analyzed together
- Sonnet sees the complete relationship context
- Result: ONE task per person maximum

### Thread Analysis
Each thread contains:
- All messages sorted by ACTUAL datetime (using parsedate_to_datetime)
- Complete conversation history from thread start
- The "last message" is the chronologically latest message

CRITICAL: Dates MUST be sorted by datetime object, not alphabetically.
Example bug: "Thu, 20 Nov" sorts BEFORE "Wed, 19 Nov" alphabetically (T < W).

### Task Examples
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

### 3. Morning Sync Script (`morning_sync.py`)
- Automated workflow for cron
- Runs all 3 steps sequentially
- Saves results to `cache/relationship_gaps.json`
- Logging to `logs/morning_sync.log`

## CLI Commands

### `/sync` - Manual morning sync
Runs the complete sync workflow:
```bash
$ /sync

🌅 Starting morning sync workflow...

📧 STEP 1/3: Syncing email threads...
   ✅ Email sync complete: 5 new, 2 updated

📅 STEP 2/3: Syncing calendar events...
   ✅ Calendar sync complete: 3 new, 1 updated

🔍 STEP 3/3: Analyzing relationship gaps...
   ✅ Gap analysis complete: 3 relationship gaps found
      - Meetings without follow-up: 1
      - Urgent emails without meeting: 1
      - Silent contacts: 1

✅ Morning sync complete! Use /gaps to see your briefing.
```

### `/gaps` or `/briefing` - View relationship briefing
Shows actionable relationship gaps:
```bash
$ /gaps

📋 RELATIONSHIP BRIEFING
   Analyzed: 2025-11-20T18:30:00
============================================================

🚨 MEETINGS WITHOUT FOLLOW-UP:

1. Meeting with John Smith (3 days ago)
   📅 Client meeting about Q4 strategy
   ✉️  No follow-up email sent yet
   💡 Suggested: Draft follow-up email

⚡ URGENT EMAILS WITHOUT MEETING:

1. John Smith's email (2 days ago)
   📧 URGENT: Contract review needed
   🔥 Priority: 9/10
   📅 No meeting scheduled
   💡 Suggested: Propose a meeting

💤 SILENT CONTACTS:

1. Maria Rossi
   📊 5 past interactions (3 emails, 2 meetings)
   ⏰ 45 days since last contact
   💡 Suggested: Re-engage with check-in email

📊 SUMMARY: 3 total relationship gaps
============================================================
```

## Setup Automated Sync (Cron)

### Option 1: Using morning_sync.py
```bash
# Add to crontab:
crontab -e

# Run every day at 5am:
0 5 * * * cd /Users/mal/starchat/zylch && /usr/bin/python3 morning_sync.py >> logs/morning_sync.log 2>&1
```

### Option 2: Using CLI directly
```bash
# Run every day at 5am:
0 5 * * * cd /Users/mal/starchat/zylch && echo "/sync\n/quit" | python -m zylch.cli.main >> logs/morning_sync.log 2>&1
```

## Typical Workflow

### Morning (5am - Automated)
```bash
# Cron runs morning_sync.py:
1. Sync emails → threads.json
2. Sync calendar → events.json
3. Analyze gaps → relationship_gaps.json
```

### Morning (8am - User)
```bash
# User starts Zylch AI CLI:
$ python -m zylch.cli.main

# Check morning briefing:
$ /gaps

📋 RELATIONSHIP BRIEFING
   3 relationship gaps found...
   [Shows gaps as above]

# User can then:
# - Ask Zylch AI to draft follow-up emails
# - Schedule meetings for urgent contacts
# - Re-engage silent contacts
```

### During Day - Natural Interaction
User can ask Zylch AI naturally:
```
User: "What should I work on today?"
Zylch AI: Based on your briefing:
  1. Yesterday's meeting with John Smith needs a follow-up
  2. Mr. Rossi's email seems urgent - shall I propose a meeting?
  3. Maria Rossi has been silent for 45 days - consider checking in

User: "Draft the follow-up for John"
Zylch AI: [Drafts email based on meeting context]
```

## Personalized Filtering with Memory System

### Overview
The Relationship Analyzer integrates with Zylch AI's Memory System to learn your personal preferences for email filtering. This allows you to teach the system which emails to ignore or prioritize.

### How It Works

1. **Memory Storage**: User preferences are stored in `cache/memory_mario.json` under the 'email' channel
2. **AI Integration**: Memory rules are injected into Claude Sonnet's prompt with highest priority
3. **Automatic Application**: Rules are automatically applied during gap analysis

### Teaching the System

You can add filtering rules using the memory system:

```python
from zylch.memory.reasoning_bank import ReasoningBankMemory

memory = ReasoningBankMemory(user_id="mario")

# Add a rule to ignore specific senders
memory.add_correction(
    what_went_wrong="Email da reminder@superhuman.com viene considerata importante",
    correct_behavior="Ignorare sempre le email da reminder@superhuman.com, sono reminder automatici",
    channel='email'
)

# Add a rule to prioritize specific senders
memory.add_correction(
    what_went_wrong="Email da CEO non sempre flaggate come urgenti",
    correct_behavior="Email dal CEO sono sempre da considerare prioritarie",
    channel='email'
)
```

### Example Rules

**Ignore automated services**:
```python
memory.add_correction(
    what_went_wrong="Newsletter di Marie at Tally considerata importante",
    correct_behavior="Newsletter e marketing emails vanno sempre ignorate",
    channel='email'
)
```

**Prioritize specific domains**:
```python
memory.add_correction(
    what_went_wrong="Email da clienti enterprise non prioritizzate",
    correct_behavior="Email da domini @enterprise-client.com sempre prioritarie",
    channel='email'
)
```

### Confidence Scoring

- Memory rules start with confidence 0.5
- Only rules with confidence ≥ 0.5 are applied
- Confidence increases/decreases based on user feedback over time

## Cache Files

- `cache/emails/threads.json` - Email conversations with AI analysis
- `cache/calendar/events.json` - Calendar events with attendee metadata
- `cache/relationship_gaps.json` - Analyzed relationship gaps
- `cache/memory_mario.json` - User-specific memory rules and preferences
- `logs/morning_sync.log` - Sync execution logs

## Future Enhancements

### Planned:
- [ ] WhatsApp integration (silent contacts on WhatsApp)
- [ ] Task tracking (promised to send doc, but didn't)
- [ ] Relationship health score per contact
- [ ] Automated draft generation for gaps
- [ ] Weekly relationship summary email

### Possible:
- [ ] Slack/Teams integration
- [ ] CRM integration (sync gaps to Pipedrive tasks)
- [ ] AI-powered relationship insights
- [ ] Predictive gap detection (likely to forget follow-up)

## Technical Details

### CalendarSyncManager
```python
from zylch.tools.calendar_sync import CalendarSyncManager

calendar_sync = CalendarSyncManager(
    calendar_client=calendar,
    cache_dir="cache/calendar",
    days_back=30,      # Past events window
    days_forward=30    # Future events window
)

# Sync events
results = calendar_sync.sync_events()

# Query events
events = calendar_sync.get_events_by_contact("john@client.com")
recent = calendar_sync.get_recent_meetings(days_back=7, only_external=True)
```

### RelationshipAnalyzer
```python
from zylch.tools.relationship_analyzer import RelationshipAnalyzer
from zylch.memory.reasoning_bank import ReasoningBankMemory

# Initialize memory for personalized filtering
memory = ReasoningBankMemory(user_id="mario")

# Initialize analyzer with AI and memory support
analyzer = RelationshipAnalyzer(
    email_cache_path="cache/emails/threads.json",
    calendar_cache_path="cache/calendar/events.json",
    anthropic_api_key="your-api-key",  # Enable semantic filtering
    memory_bank=memory  # Enable personalized rules
)

# Find specific gaps
meetings_no_followup = analyzer.find_meeting_without_followup(days_back=7)
urgent_no_meeting = analyzer.find_urgent_email_without_meeting(days_back=7)
silent_contacts = analyzer.find_silent_contacts(days_threshold=30)

# Or analyze all at once
all_gaps = analyzer.analyze_all_gaps(days_back=7)
```

## Testing

### Run test with mock data:
```bash
python test_relationship_intelligence.py
```

This creates mock emails and calendar events, then tests all gap detection types.

## References

- **Email sync**: `zylch/tools/email_sync.py`
- **Calendar sync**: `zylch/tools/calendar_sync.py`
- **Relationship analyzer**: `zylch/tools/relationship_analyzer.py`
- **Morning sync script**: `morning_sync.py`
- **Test script**: `test_relationship_intelligence.py`
- **CLI integration**: `zylch/cli/main.py` (lines 1943-2078)
