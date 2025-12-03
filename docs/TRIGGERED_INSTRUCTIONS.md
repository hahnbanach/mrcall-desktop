# Triggered Instructions

## Overview

Triggered Instructions are event-driven automation rules that execute when specific events occur. They are different from Behavioral Memory (`/memory`), which contains always-on behavioral rules.

**Key Difference:**
- **Triggered Instructions** (`/trigger`): "Do X **when** Y happens" (event-driven)
- **Behavioral Memory** (`/memory`): "**Always** do X" (always-on)

## Trigger Types

### 1. session_start
Executes when a new CLI or API session starts.

**Examples:**
- "Greet me at the start of every session with Good morning, today is [date]"
- "Show my top 3 priorities for today"
- "Check for urgent emails and summarize"

### 2. email_received
Executes when a new email arrives.

**Examples:**
- "When a new email arrives from unknown sender, create a contact"
- "Alert me for VIP emails"
- "Auto-categorize newsletters"

### 3. sms_received
Executes when a new SMS arrives.

**Examples:**
- "Log all SMS in calendar"
- "Alert for messages from family"

### 4. call_received
Executes when a new phone call is received.

**Examples:**
- "Send follow-up email after sales calls"
- "Log call duration in CRM"

## CLI Commands

### Basic Commands

```bash
# Show help
/trigger --help

# List all triggered instructions
/trigger --list

# Show available trigger types
/trigger --types

# Add new triggered instruction (interactive)
/trigger --add

# Remove a triggered instruction
/trigger --remove trigger_abc123
```

### Validation Mode (--check flag)

Validate commands without executing them:

```bash
# Validate new instruction without saving
/trigger --add --check

# Validate removal without removing
/trigger --remove trigger_abc123 --check
```

**Example Interactive Session:**
```
$ /trigger --add --check

=== 🔍 Validate Triggered Instruction (Check Mode) ===

Available trigger types:
  1. session_start    - When a new session starts
  2. email_received   - When a new email arrives
  3. sms_received     - When a new SMS arrives
  4. call_received    - When a new call is received

Select trigger type (1-4): 1
Enter instruction: Greet me at the start of every session
Enter name (optional): Morning greeting

✅ Validation Result:
  This instruction is valid for session_start trigger.
  It will execute when a new CLI or API session starts.

  Preview:
    trigger: session_start
    instruction: Greet me at the start of every session
    will_execute_on: When a new CLI or API session starts
    example_scenario: You open Zylch CLI → instruction executes
```

## Storage & Data Structure

### Storage Location
- **System**: ZylchMemory with semantic search
- **Namespace**: `{owner_id}:{zylch_assistant_id}:triggers`
- **Category**: `trigger`
- **Format**: JSON stored in pattern field

### Data Structure

```json
{
  "id": "trigger_abc123",
  "instruction": "Greet me when session starts",
  "trigger": "session_start",
  "name": "Morning greeting",
  "created_at": "2024-01-15T10:30:00",
  "active": true,
  "namespace": "user123:zylch_main:triggers",
  "will_execute_on": "When a new CLI or API session starts",
  "example_scenario": "You open Zylch CLI → instruction executes"
}
```

### Fields

- **id**: Unique identifier (format: `trigger_xxxxxxxx`)
- **instruction**: What Zylch should do when trigger fires
- **trigger**: Event type (session_start, email_received, etc.)
- **name**: Short descriptive name (optional, defaults to first 50 chars of instruction)
- **created_at**: ISO timestamp of creation
- **active**: Boolean (true = active, false = deactivated)
- **namespace**: User/assistant namespace for isolation
- **will_execute_on**: Human-readable event description
- **example_scenario**: Example of when it executes

## Execution Flow

### Session Start Triggers

1. **Loading at CLI Initialization** (`cli/main.py:213-224`)
   ```python
   all_triggers_data = await load_triggered_instructions(
       zylch_memory=self.memory,
       owner_id=self.owner_id,
       zylch_assistant_id=self.zylch_assistant_id,
       trigger_filter=None  # Get all triggers
   )
   triggered_instructions = [t["instruction"] for t in all_triggers_data]
   ```

2. **Prompt Injection**
   - Instructions injected into system prompt
   - Claude executes them automatically on first interaction

3. **Example Flow**
   ```
   User opens CLI → Triggers loaded → Instructions in prompt →
   User sends first message → Claude executes session_start triggers →
   Claude greets with date/time/priorities
   ```

### Email/SMS/Call Triggers (Future Implementation)

**Planned Flow:**
1. Event occurs (email/SMS/call received via API webhook)
2. System loads triggers with filter: `trigger_filter="email_received"`
3. For each matching trigger:
   - Extract instruction
   - Build context (sender, subject, body, etc.)
   - Execute via agent with context
4. Agent performs action (create contact, send reply, log event)

## Lifecycle Management

### Create
```bash
/trigger --add
> Select trigger type: session_start
> Instruction: Greet me when session starts
> Name: Morning greeting
```

**What happens:**
1. Tool validates required parameters (instruction + trigger)
2. Generates unique trigger_id: `trigger_abc123`
3. Stores in ZylchMemory with `active=True`
4. Loads on next session (session_start) or event (others)

### List
```bash
/trigger --list
```

**Output:**
```
=== 🎯 Triggered Instructions (2) ===

ID: trigger_abc123
   Name: Morning greeting
   Trigger: session_start
   Instruction: Greet me at the start of every session...

ID: trigger_def456
   Name: Auto-create contacts
   Trigger: email_received
   Instruction: When email from unknown sender, create contact...
```

### Deactivate
```bash
/trigger --remove trigger_abc123
```

**What happens:**
1. Tool finds trigger by ID
2. Sets `active=False` (not deleted!)
3. Adds `deactivated_at` timestamp
4. Trigger no longer loads or executes
5. Still retrievable for audit

**Why deactivate vs delete?**
- Audit trail preservation
- Undo capability (can reactivate manually)
- Historical analysis

## Implementation Files

### Tools (`zylch/tools/instruction_tools.py`)

**AddTriggeredInstructionTool** (lines 24-173)
- `execute(validation_only, instruction, trigger, name)`
- Validates required parameters
- Returns preview in validation_only mode
- Saves to ZylchMemory in execution mode
- Helpers: `_get_trigger_description()`, `_get_example_scenario()`

**ListTriggeredInstructionsTool** (lines 175-241)
- `execute()` - no parameters
- Retrieves all active triggers from memory
- Filters out deactivated triggers (`active=False`)

**RemoveTriggeredInstructionTool** (lines 244-367)
- `execute(validation_only, trigger_id)`
- Finds trigger by ID in memory
- Returns preview in validation_only mode
- Deactivates in execution mode

**load_triggered_instructions()** (lines 370-424)
- Helper function for loading triggers
- Optional `trigger_filter` parameter
- Used by CLI and chat service

### CLI Integration (`zylch/cli/main.py`)

**Handler** (lines 540-627)
- `_handle_trigger_command()`: Parse flags and route
- Flag parsing with shlex
- Routing to appropriate sub-handler

**Sub-handlers**
- `_trigger_add_interactive()` (lines 724-772): Interactive add
- `_trigger_list()` (lines 703-723): Display list
- `_trigger_remove()` (lines 774-783): Remove by ID
- `_trigger_check_add()` (lines 785-853): Validation mode for add
- `_trigger_check_remove()` (lines 855-886): Validation mode for remove
- `_print_trigger_help()` (lines 679-701): Help text

**Initialization** (lines 213-224)
- Load triggers at startup
- Extract instructions for prompt injection

### Tutorial (`zylch/tutorial/steps/triggers_demo.py`)

Educational step explaining:
- What are triggered instructions
- Available trigger types
- Examples for each type
- Difference from behavioral memory
- Managing commands

## Semantic Validation

### Detecting Misuse

The validation system (with `--check` flag) detects semantic issues:

**❌ WRONG: Always-on behavior in /trigger**
```bash
/trigger --add
> Instruction: "always use formal tone"

❌ Semantic issue: No event trigger detected
💡 Suggestion: Use /memory --add "always use formal tone" instead
```

**❌ WRONG: Event-driven behavior in /memory**
```bash
/memory --add "when email arrives, alert me"

❌ Semantic issue: Event trigger detected
💡 Suggestion: Use /trigger --add instead
```

**✅ CORRECT: Event-driven in /trigger**
```bash
/trigger --add
> Trigger: session_start
> Instruction: "greet me when session starts"

✅ Valid: Has event trigger (session_start)
```

### Keyword Detection

**Trigger Keywords** (event-driven):
- when, if, after, before, on, whenever
- arrives, starts, ends, happens, occurs

**Memory Keywords** (always-on):
- always, never, all, every (without event context)
- prefer, avoid, use, don't use

## API Usage (Future)

### REST Endpoints (Planned)

```bash
# Create triggered instruction
POST /api/v1/triggers
{
  "instruction": "Greet me when session starts",
  "trigger": "session_start",
  "name": "Morning greeting"
}

# List triggered instructions
GET /api/v1/triggers

# Get specific trigger
GET /api/v1/triggers/trigger_abc123

# Update trigger
PATCH /api/v1/triggers/trigger_abc123
{
  "active": false
}

# Delete (deactivate) trigger
DELETE /api/v1/triggers/trigger_abc123

# Validate before creating
POST /api/v1/triggers/validate
{
  "instruction": "always use formal tone",
  "trigger": "session_start"
}
# Returns: { "valid": false, "issues": [...], "suggestion": "..." }
```

### Programmatic Usage

```python
from zylch.tools.instruction_tools import AddTriggeredInstructionTool, load_triggered_instructions

# Add trigger
tool = AddTriggeredInstructionTool(
    zylch_memory=memory,
    owner_id="user123",
    zylch_assistant_id="zylch_main"
)

result = await tool.execute(
    instruction="Greet me when session starts",
    trigger="session_start",
    name="Morning greeting"
)

# Load triggers
triggers = await load_triggered_instructions(
    zylch_memory=memory,
    owner_id="user123",
    zylch_assistant_id="zylch_main",
    trigger_filter="session_start"  # Optional filter
)
```

## Best Practices

### When to Use Triggered Instructions

**✅ Use /trigger for:**
- Event-driven automation: "Do X when Y happens"
- One-time actions on events: "Create contact when email arrives"
- Time-based greetings: "Greet me at session start"
- Automated workflows: "Send follow-up after calls"

**❌ Don't use /trigger for:**
- Always-on behavior: "Always use formal tone" → Use /memory
- Continuous preferences: "Prefer short emails" → Use /memory
- Global settings: "Never mention competitors" → Use /memory

### Writing Good Instructions

**Clear and Specific:**
```
✅ "Greet me at the start of every session with today's date"
❌ "Say hi sometimes"
```

**Include Context:**
```
✅ "When email arrives from unknown sender, create a contact with their email and name"
❌ "Make contacts"
```

**Action-Oriented:**
```
✅ "Check for urgent emails and summarize them"
❌ "Emails are important"
```

### Naming Triggers

```
✅ "Morning greeting"
✅ "Auto-create contacts"
✅ "VIP email alerts"
❌ "trigger1"
❌ "test"
```

## Troubleshooting

### Trigger Not Executing

**For session_start:**
1. Check trigger is active: `/trigger --list`
2. Restart CLI to reload triggers
3. Check logs for loading confirmation

**For email_received (future):**
1. Verify webhook is configured
2. Check email integration is active
3. Review logs for event reception

### Wrong Command Type

If you get semantic validation errors:
- "Always" behavior → Use `/memory` instead
- No event context → Use `/memory` instead
- Event-driven → Correct, use `/trigger`

### Finding Trigger IDs

```bash
# List shows all IDs
/trigger --list

# IDs format: trigger_xxxxxxxx
# Copy ID from list output for --remove command
```

## Migration Notes

### Renaming from "Standing Instructions"

This system was originally called "Standing Instructions" but was renamed to "Triggered Instructions" for clarity.

**If you see old references:**
- "Standing instructions" = Triggered instructions
- Same functionality, just renamed
- Old comments may still use old name

### ChatService Integration Bug (Fixed)

**Issue:** When integrating triggered instructions into chat service, there was a tuple unpacking bug.

**Error:** `AttributeError: 'list' object has no attribute 'name'`

**Cause:**
```python
# Wrong
tools = await ToolFactory.create_all_tools(...)
```

**Fix:**
```python
# Correct
tools, session_state, persona_analyzer = await ToolFactory.create_all_tools(...)
```

This has been fixed in the codebase.
