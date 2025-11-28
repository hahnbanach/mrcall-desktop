# Zylch AI Memory System

**Complete guide to Zylch AI's channel-based behavioral memory system**

> **⚠️ MIGRATION NOTE**: This documentation describes the legacy ReasoningBank system.
> The system has been migrated to **ZylchMemory** with semantic search and O(log n) HNSW indexing.
> See `zylch_memory/README.md` and `zylch_memory/ZYLCH_MEMORY_ARCHITECTURE.md` for current implementation.
> The CLI commands documented here still work but now use ZylchMemory backend.

---

## Table of Contents

1. [Overview](#overview)
2. [Design Philosophy](#design-philosophy)
3. [Architecture](#architecture)
4. [Usage Guide](#usage-guide)
5. [Integration Examples](#integration-examples)
6. [Technical Implementation](#technical-implementation)
7. [Best Practices](#best-practices)

---

## Overview

Zylch AI implements a **ReasoningBank-inspired memory system** that learns from user corrections and applies them automatically in future interactions. The system is organized by **communication channels** (email, calendar, WhatsApp, phone calls, tasks) with separate memory for each channel.

### Key Features

- 🧠 **Behavioral Learning**: Remembers corrections like "use 'lei' not 'tu'" or "always include timezone"
- 📡 **Channel Isolation**: Email rules don't affect phone calls, calendar rules don't affect WhatsApp
- 👤 **Personal Memory**: Each user has their own preferences
- 🌍 **Global Memory**: Admins can set system-wide improvements
- 📈 **Confidence Scoring**: Rules improve over time based on success/failure
- 🔄 **Automatic Application**: Memories are automatically injected into AI prompts

---

## Design Philosophy

### The Problem

Traditional AI assistants forget corrections. If you say "don't do that," they'll do it again next time. This creates frustration and wastes time repeating feedback.

**Human Analogy:** Humans have excellent behavioral memory. If someone corrects us once, we remember. Zylch AI should work the same way.

### The Solution: Channel-Based Memory

Zylch AI operates across 5 communication channels:

| Channel | Purpose | Example Rules |
|---------|---------|---------------|
| `email` | Email drafting and responses | "Use 'lei' for formal contacts", "Keep emails under 3 paragraphs" |
| `calendar` | Calendar event management | "Always specify timezone for international meetings" |
| `whatsapp` | WhatsApp messaging | "Use casual tone", "Keep messages brief" |
| `mrcall` | Phone assistant behavior | "Speak slowly and clearly" |
| `task` | Task management | "Set reminders 1 day before deadlines" |

### Why Channel-Based?

**✅ Advantages:**
- **Clear boundaries**: Email rules ≠ Phone rules ≠ WhatsApp rules
- **No conflicts**: Can be formal on email, casual on WhatsApp
- **Scalable**: Works with 10 contacts or 10,000
- **Simple**: No per-contact complexity
- **Extensible**: Easy to add Slack, Teams, SMS later

**❌ Rejected Alternative - Contact-specific rules:**
- Too granular (management nightmare)
- Doesn't scale ("be formal with Luisa" → what about 1000 contacts?)
- Hard to generalize

### Two-Tier Architecture

1. **👤 Personal Memory** (`cache/memory_{user_id}.json`)
   - User's own learned behaviors per channel
   - Example: "I prefer casual tone in WhatsApp messages"

2. **🌍 Global Memory** (`cache/memory_global.json`)
   - System-wide improvements for all users (admin only)
   - Example: "Always check past communication history before drafting"

---

## Architecture

### Memory Storage (JSON)

**Why JSON instead of SQLite?**
- ✅ Consistent with Zylch AI architecture (threads.json, tasks.json)
- ✅ Human-readable and debuggable
- ✅ Easy backup and version control
- ✅ No SQL dependency

### Memory Schema

```json
{
  "user_id": "mario",
  "created_at": "2025-11-20T18:00:00",
  "last_updated": "2025-11-20T18:30:00",
  "corrections": [
    {
      "id": 1,
      "channel": "email",
      "what_went_wrong": "Used 'tu' instead of 'lei'",
      "correct_behavior": "Always use 'lei' for formal email communication",
      "attempted_text": null,
      "correct_text": null,
      "confidence": 0.575,
      "times_applied": 1,
      "times_successful": 1,
      "created_at": "2025-11-20T18:00:00",
      "last_applied": "2025-11-20T18:10:00",
      "last_updated": "2025-11-20T18:10:00"
    }
  ],
  "applications": [
    {
      "correction_id": 1,
      "task_type": "email_draft",
      "was_successful": true,
      "user_feedback": null,
      "applied_at": "2025-11-20T18:10:00",
      "scope": "personal"
    }
  ]
}
```

### Field Descriptions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | int | ✅ | Unique correction ID |
| `channel` | string | ✅ | One of: email, calendar, whatsapp, mrcall, task |
| `what_went_wrong` | string | ✅ | Description of the problem |
| `correct_behavior` | string | ✅ | What should be done instead |
| `attempted_text` | string | ❌ | Optional: What the AI tried |
| `correct_text` | string | ❌ | Optional: Corrected version |
| `confidence` | float | ✅ | 0.0-1.0, starts at 0.5 |
| `times_applied` | int | ✅ | How many times used |
| `times_successful` | int | ✅ | How many times worked |

### Confidence Scoring (Bayesian Update)

All corrections start at **50% confidence** (neutral).

**Update formula:**
- **Success**: `confidence += 0.15 * (1 - confidence)`
- **Failure**: `confidence -= 0.10 * confidence`

**Example progression:**
```
Initial:         0.50 (50%)
After 1 success: 0.575 (57.5%)
After 2 success: 0.639 (63.9%)
After 3 success: 0.693 (69.3%)
...converges toward 1.0

After 1 failure: 0.45 (45%)
After 2 failure: 0.405 (40.5%)
...converges toward 0.0
```

**Filtering:**
- Only inject memories with confidence > 30% (configurable)
- Sort by confidence descending (most reliable first)

---

## Usage Guide

### CLI Commands

All memory operations use Unix-style subcommands:

#### List Memories

```bash
# List personal memories (default)
/memory --list

# List global memories (admin)
/memory --list --global

# List all memories (personal + global)
/memory --list --all
```

#### Add Memory

```bash
# Add personal memory (channel-specific)
/memory --add "what went wrong" "correct behavior" channel

# Examples:
/memory --add "Used tu instead of lei" "Always use lei for formal email communication" email
/memory --add "Missing timezone" "Always specify timezone (e.g., CET, PST) in event description" calendar
/memory --add "Too formal tone" "Use casual, friendly language on WhatsApp" whatsapp
/memory --add "Script too brief" "Provide full context when explaining reason for phone call" mrcall

# Add global memory (admin only)
/memory --add --global "Didn't check past style" "Always check past communication history before drafting" email
```

#### Remove Memory

```bash
# Remove personal memory
/memory --remove <id>

# Remove global memory (admin)
/memory --remove <id> --global

# Example:
/memory --remove 5
```

#### Statistics

```bash
# Show personal memory stats
/memory --stats

# Show global memory stats (admin)
/memory --stats --global

# Show all memory stats (includes breakdown by channel)
/memory --stats --all
```

### Programmatic Usage

```python
from zylch.memory.reasoning_bank import ReasoningBankMemory

# Initialize memory for a user
memory = ReasoningBankMemory(user_id="mario")

# Add a correction
correction_id = memory.add_correction(
    what_went_wrong="Used tu instead of lei",
    correct_behavior="Always use lei for formal business communication",
    channel='email'
)

# Retrieve relevant memories for a channel
memories = memory.get_relevant_memories(
    channel='email',
    min_confidence=0.5,
    limit=5
)

# Build memory prompt for AI
memory_prompt = memory.build_memory_prompt(
    channel='email',
    task_description="drafting formal business email"
)

# Record application outcome
memory.record_application(
    correction_id=correction_id,
    was_successful=True,
    task_type="email_draft"
)
```

---

## Integration Examples

### Email Channel - Drafting

**Workflow:**

1. User asks Zylch AI to draft email → Zylch AI uses 'tu'
2. User corrects: "No, use 'lei' - this is formal business"
3. User adds memory:
   ```bash
   /memory --add "Used tu instead of lei" "Always use lei for formal business communication" email
   ```
4. Next time: Zylch AI automatically uses 'lei' because memory is injected into prompt

### Email Channel - Gap Analysis (NEW ✨)

**Workflow:**

1. User runs `/gaps` → System shows reminder@superhuman.com email as urgent
2. User annoyed: "This is just an automated reminder!"
3. User teaches the system:
   ```python
   memory.add_correction(
       what_went_wrong="Email da reminder@superhuman.com considerata importante",
       correct_behavior="Ignorare sempre reminder@superhuman.com, sono reminder automatici",
       channel='email'
   )
   ```
4. Next `/gaps` run: reminder@superhuman.com automatically filtered out
5. System learns over time as user adds more rules

**See:** [Relationship Intelligence docs](./relationship-intelligence.md) for details

### Calendar Channel

**Workflow:**

1. User creates meeting with international attendees → Zylch AI creates event without timezone
2. User corrects: "Add timezone - this is international!"
3. User adds memory:
   ```bash
   /memory --add "Missing timezone" "Always specify timezone (e.g., CET, PST) in event description" calendar
   ```
4. Next calendar event: Zylch AI automatically includes timezone

### Channel Isolation Example

```bash
# Add email rule
/memory --add "Too formal" "Use friendly, conversational tone" email

# Add whatsapp rule (opposite!)
/memory --add "Too casual" "Be more professional on WhatsApp" whatsapp

# Result: No conflict! Each channel has independent rules.
```

---

## Technical Implementation

### Core Class: `ReasoningBankMemory`

```python
class ReasoningBankMemory:
    """Channel-based behavioral memory system."""

    def __init__(self, user_id: str, cache_dir: str = "cache"):
        """Initialize memory for a user."""

    def add_correction(
        self,
        what_went_wrong: str,
        correct_behavior: str,
        channel: str,  # REQUIRED
        attempted_text: Optional[str] = None,
        correct_text: Optional[str] = None,
        is_global: bool = False
    ) -> int:
        """Add a new correction to memory."""

    def get_relevant_memories(
        self,
        channel: str,  # REQUIRED
        min_confidence: float = 0.3,
        limit: int = 5,
        include_global: bool = True
    ) -> List[Dict]:
        """Retrieve relevant memories for a channel."""

    def build_memory_prompt(
        self,
        channel: str,  # REQUIRED
        task_description: Optional[str] = None,
        min_confidence: float = 0.3
    ) -> str:
        """Build prompt section with relevant memories."""

    def record_application(
        self,
        correction_id: int,
        was_successful: bool,
        task_type: str = "email_draft",
        feedback: Optional[str] = None,
        is_global: bool = False
    ):
        """Record that a memory was applied and update confidence."""
```

### Integration with Relationship Intelligence

The memory system is integrated with relationship gap analysis for personalized email filtering:

```python
# In relationship_analyzer.py:
def _sonnet_requires_response(self, thread, contact_email, contact_name):
    # 1. Load user's email channel memories
    memories = self.memory_bank.get_relevant_memories(
        channel='email',
        min_confidence=0.5
    )

    # 2. Build memory rules section
    memory_rules = "\n\nREGOLE PERSONALI DELL'UTENTE (PRIORITÀ ASSOLUTA):\n"
    for mem in memories:
        memory_rules += f"- {mem['what_went_wrong']} → {mem['correct_behavior']}\n"

    # 3. Inject into Sonnet prompt
    prompt = f"""Analizza questa email...
{memory_rules}
IMPORTANTE: Le regole personali hanno PRIORITÀ ASSOLUTA."""

    # 4. Get Sonnet's decision
    response = anthropic_client.messages.create(...)
```

**Benefits:**
- ✅ No more false positives: Newsletter/marketing emails automatically filtered
- ✅ Personalized rules: Each user has their own preferences
- ✅ Continuous learning: Rules improve over time
- ✅ Explainable AI: You can see exactly what rules were applied

### Automatic Injection

When Zylch AI performs a task, relevant memories are automatically injected:

1. **Global rules** for the current channel (if confidence > 30%)
2. **Personal rules** for the current channel
3. **Only relevant channel rules** (email rules not injected for calendar tasks)

Example - Scheduling a calendar event:
```python
context = {"channel": "calendar"}
memory_prompt = memory.build_memory_prompt(
    channel="calendar",
    task_description="scheduling and managing calendar events"
)
# Result: Only calendar rules injected, not email/whatsapp rules
```

---

## Best Practices

### Writing Good Corrections

**✅ Good:**
```
what_went_wrong: "Used 'tu' instead of 'lei'"
correct_behavior: "Always use 'lei' for formal email communication"
```
- Clear and specific
- Generalizable to future situations
- Actionable

**❌ Bad:**
```
what_went_wrong: "Wrong"
correct_behavior: "Fix it"
```
- Too vague
- Not actionable
- Can't be applied automatically

### Channel Selection

Always choose the most specific channel:

- Email drafting/responses → `email`
- Calendar events → `calendar`
- WhatsApp messages → `whatsapp`
- Phone assistant behavior → `mrcall`
- Task management → `task`

### Global vs Personal Memory

**Use Personal Memory when:**
- Preference is user-specific ("I like casual tone")
- Rule applies to your workflow ("Set reminders 1 day before")

**Use Global Memory when (admin only):**
- Improvement benefits all users ("Always check past communication")
- Fixes a systematic problem ("Include video link for remote meetings")

### Confidence Threshold

- **0.3-0.5**: Experimental rules, being tested
- **0.5-0.7**: Proven rules, reliable
- **0.7+**: Highly reliable, used many times successfully

Adjust `min_confidence` parameter based on how conservative you want filtering to be.

---

## Files and References

### Implementation
- **Core class**: `zylch/memory/reasoning_bank.py`
- **CLI integration**: `zylch/cli/main.py`
- **Agent integration**: `zylch/agent/core.py`

### Documentation
- **This guide**: Complete memory system documentation
- **Relationship Intelligence**: [./relationship-intelligence.md](./relationship-intelligence.md)
- **Quick Start**: [./quick-start.md](./quick-start.md)

### Tests
- **Channel isolation**: `test_channel_memory.py`
- **Calendar integration**: `test_calendar_memory.py`
- **Relationship analyzer**: `test_relationship_intelligence.py`

---

## Design Decisions

### Decision 1: Channel-Based (not contact-based)
**Date:** 2025-11-20
**Rationale:** User feedback: "io non metterei il contatto... altrimenti impazziamo"
**Result:** Removed `contact_email` field entirely

### Decision 2: Remove correction_type
**Date:** 2025-11-20
**Rationale:** Too granular, adds complexity without value
**Result:** `what_went_wrong` and `correct_behavior` describe everything needed

### Decision 3: Keep personal/global distinction
**Date:** 2025-11-20
**Rationale:** User: "Non perde senso!!! Io come admin faccio miglioramenti che valgono per tutti"
**Result:** Two-tier architecture maintained

### Decision 4: Mandatory channel field
**Date:** 2025-11-20
**Rationale:** Channel is ALWAYS known and clear
**Result:** `channel` is required, validates against CHANNEL_TYPES

### Decision 5: JSON storage (not SQLite)
**Date:** 2025-11-19
**Rationale:** Consistent with Zylch AI architecture, human-readable
**Result:** `cache/memory_{user_id}.json` format

---

## Inspiration

Based on Google's **ReasoningBank** paper:
- **Strategy-level memory** (not raw traces)
- **Success + Failure learning**
- **Retrieval-augmented generation**
- **Self-evolution** with confidence scores
- **Contrastive learning** ("Do this, not that")

**Reference:** [Google Research - Learning from Failures](https://arxiv.org/abs/2305.xxxxx)
