# MrCall Feature Configuration Reference

## Architecture Overview

**Single Source of Truth**: `MrCallConfiguratorTrainer.FEATURES`

All feature/variable mappings live in ONE place. Other files derive automatically:

```python
# In command_handlers.py (DERIVED - do NOT edit manually):
from zylch.agents.trainers import MrCallConfiguratorTrainer
FEATURE_TO_VARIABLES = {
    name: feature["variables"]
    for name, feature in MrCallConfiguratorTrainer.FEATURES.items()
}

# In config_tools.py (DERIVED - do NOT edit manually):
VARIABLE_TO_FEATURE = {
    var: feature_name
    for feature_name, feature in MrCallConfiguratorTrainer.FEATURES.items()
    for var in feature["variables"]
}
```

---

## Step 1: Create Meta-Prompt

Add constant to `zylch/agents/trainers/mrcall_configurator.py`:

```python
BOOKING_META_PROMPT = """You are analyzing the booking configuration for a MrCall AI phone assistant.

Your task: Given the current values of booking variables, generate a
self-contained sub-prompt that another LLM can use to both UNDERSTAND and MODIFY the configuration.

## UNDERSTANDING THE VARIABLES

This feature uses MULTIPLE coordinated variables:
- START_BOOKING_PROCESS (bool): Master switch to enable/disable booking
- BOOKING_TRIGGER (str): When to offer booking (e.g., "first turn", "when requested")
- BOOKING_HOURS (JSON str): Available hours per day
- ... etc

## YOUR OUTPUT FORMAT

Generate a sub-prompt with these exact sections:

### SECTION 1: AVAILABLE VARIABLES
Create a markdown table with columns: Variable | Type | Description | Default | Current Value

### SECTION 2: CURRENT BEHAVIOR
Describe what the assistant DOES in plain language.

### SECTION 3: WHAT CAN BE CHANGED
List modifications users can request with examples.

### SECTION 4: WHAT CANNOT BE CHANGED (via this feature)
List system constraints.

### SECTION 5: CURRENT CONFIGURATION
Include key variable values.

---

## VARIABLES CONTEXT:

{variables_context}

---

OUTPUT ONLY THE SUB-PROMPT TEXT. No explanations."""
```

---

## Step 2: Add to FEATURES Dict (ONLY PLACE TO DEFINE MAPPINGS)

In `MrCallConfiguratorTrainer` class:

```python
FEATURES = {
    "welcome_message": {
        "variables": ["OSCAR_INBOUND_WELCOME_MESSAGE_PROMPT"],
        "description": "How the assistant answers the phone",  # for devs
        "display_name": "Come risponde al telefono l'assistente",  # for users
        "meta_prompt": WELCOME_MESSAGE_META_PROMPT,
    },
    # NEW FEATURE:
    "booking": {
        "variables": [
            "START_BOOKING_PROCESS",
            "BOOKING_TRIGGER",
            "NO_BOOKING_INSTRUCTIONS",
            "ENABLE_GET_CALENDAR_EVENTS",
            "ENABLE_CLEAR_CALENDAR_EVENTS",
            "BOOKING_HOURS",
            "BOOKING_EVENTS_MINUTES",
            "BOOKING_DAYS_TO_GENERATE",
            "BOOKING_SHORTEST_NOTICE",
            "BOOKING_ONLY_WORKING_HOURS",
            "BOOKING_MULTIPLE_ALLOWED",
            # BOOKING_CALENDAR_ID is auto-set via OAuth, not user-configurable
            "BOOKING_TITLE",
            "BOOKING_DESCRIPTION",
            "BOOKING_PRE_INSTRUCTION",
            "BOOKING_LAST_INSTRUCTION",
            "COMMUNICATE_BOOKING_MESSAGE",
        ],
        "description": "Appointment booking behavior",
        "display_name": "How your MrCall assistant manages booking requests",
        "meta_prompt": BOOKING_META_PROMPT,
        "dynamic_context": True,  # Uses _build_variables_context for metadata
    },
}
```

**Important:** Always ask the user for the `display_name` in their language.

---

## Step 3: Update Help Text

In `command_handlers.py`, update the help text description of features:

```python
**Features:** welcome_message (greeting), booking (appointment scheduling)
```

**DO NOT** manually edit `FEATURE_TO_VARIABLES` - it's auto-derived from trainer.

---

## Meta-Prompt Requirements

For single-variable features:
1. Must use `{current_value}` placeholder

For multi-variable features:
1. Must use `{variables_context}` placeholder
2. Set `"dynamic_context": True` in FEATURES entry
3. Consider implementing `_build_variables_context()` in trainer for metadata fetching

---

## Testing New Feature

```bash
# 1. Train all features + build unified agent (ONE COMMAND)
/agent mrcall train
# → "✅ Agent trained (features: welcome_message, booking)"

# 2. Or train just the new feature
/agent mrcall train booking
# → "✅ Feature 'booking' trained, agent updated"

# 3. Run the agent (auto-detects feature from intent)
/agent mrcall run "enable booking with 30-min appointments"
/agent mrcall run "change the welcome message to say Good morning"
/agent mrcall run "what are my current settings?"

# 4. Show unified agent prompt
/agent mrcall show

# 5. Show feature-specific sub-prompt
/mrcall show booking
```

The agent automatically detects which feature to configure based on user intent.

---

## Why Single Source of Truth?

**BAD (old pattern):**
```
trainer.py      → defines variables: [A, B, C]
command_handlers.py → manually duplicates: [A, B, C]  # can get out of sync!
config_tools.py    → manually duplicates: {A→f, B→f, C→f}  # can get out of sync!
```

**GOOD (current pattern):**
```
trainer.py      → defines variables: [A, B, C]  (SINGLE SOURCE)
command_handlers.py → imports and derives automatically
config_tools.py    → imports and derives automatically
```

Benefits:
- Add feature in ONE place, works everywhere
- Remove feature in ONE place, removed everywhere
- No risk of mappings getting out of sync
- Easier to maintain and verify

---

## Unified Agent Files

When you add a new feature, the unified agent automatically picks it up:

| File | Purpose |
|------|---------|
| `zylch/agents/trainers/mrcall_configurator.py` | Feature sub-prompt training (FEATURES dict is the source of truth) |
| `zylch/agents/trainers/mrcall.py` | Unified agent trainer - combines all feature sub-prompts |
| `zylch/agents/mrcall_agent.py` | Unified agent runner with multi-tool support |

### Storage Keys

| Key Pattern | Content |
|-------------|---------|
| `mrcall_{business_id}_{feature}` | Feature sub-prompt (e.g., `mrcall_abc123_booking`) |
| `mrcall_{business_id}` | Unified agent prompt combining all features |

### Adding a Tool to Unified Agent

When adding a new feature, add a corresponding tool in `mrcall_agent.py`:

```python
MRCALL_AGENT_TOOLS = [
    # ... existing tools ...
    {
        "name": "configure_new_feature",
        "description": "Modify new_feature settings. Description of behavior.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": {
                    "type": "object",
                    "description": "Map of variable_name -> new_value. ALL VALUES ARE STRINGS.",
                    "additionalProperties": {"type": "string"}
                }
            },
            "required": ["changes"]
        }
    },
]
```

Then add the handler in `MrCallAgent._handle_tool_response()`:

```python
elif block.name == 'configure_new_feature':
    result['result'] = await self._process_configure(
        block.input, 'new_feature'
    )
```
