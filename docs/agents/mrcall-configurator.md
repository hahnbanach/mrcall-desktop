# MrCall Configurator Agent

Manages MrCall assistant configuration through a two-tier sub-prompt architecture.

## Overview

The MrCall Configurator uses a **two-tier architecture** to configure AI phone assistants:

1. **Layer 1 (ConfiguratorTrainer)**: Generates feature-specific sub-prompts from current MrCall config
2. **Layer 2 (AgentTrainer)**: Combines sub-prompts into a unified agent with tool selection

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    /agent mrcall train                       │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│           MrCallConfiguratorTrainer (Layer 1)                │
│                                                              │
│  For each feature in FEATURES dict:                          │
│    1. Fetch current variable values from StarChat            │
│    2. Apply meta-prompt template                             │
│    3. Generate feature sub-prompt via LLM                    │
│    4. Store as: mrcall_{business_id}_{feature}               │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│             MrCallAgentTrainer (Layer 2)                     │
│                                                              │
│  1. Load all feature sub-prompts                             │
│  2. Combine with UNIFIED_META_PROMPT (tool selection)        │
│  3. Store unified agent as: mrcall_{business_id}             │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    /agent mrcall run                         │
│                                                              │
│  MrCallAgent loads unified prompt and runs with 4 tools:     │
│  - configure_welcome_message                                 │
│  - configure_booking                                         │
│  - get_current_config                                        │
│  - respond_text                                              │
└─────────────────────────────────────────────────────────────┘
```

## Key Components

| Component | File | Purpose |
|-----------|------|---------|
| ConfiguratorTrainer | `zylch/agents/trainers/mrcall_configurator.py` | Layer 1: Generates feature sub-prompts |
| AgentTrainer | `zylch/agents/trainers/mrcall.py` | Layer 2: Combines into unified agent |
| Agent | `zylch/agents/mrcall_agent.py` | Runs unified agent with tools |
| Command Handler | `zylch/services/command_handlers.py` | CLI command routing |

## Feature Definition

Each feature is defined ONCE in `MrCallConfiguratorTrainer.FEATURES`:

```python
FEATURES = {
    "welcome_message": {
        "variables": ["OSCAR_INBOUND_WELCOME_MESSAGE_PROMPT"],
        "description": "How the assistant answers the phone",
        "display_name": "Come risponde al telefono l'assistente",
        "meta_prompt": WELCOME_MESSAGE_META_PROMPT,
        "dynamic_context": True,
    },
    "booking": {
        "variables": [
            "START_BOOKING_PROCESS",
            "BOOKING_HOURS",
            "BOOKING_EVENTS_MINUTES",
            # ... 17 variables total
        ],
        "description": "Appointment booking behavior",
        "display_name": "How your MrCall assistant manages booking requests",
        "meta_prompt": BOOKING_META_PROMPT,
        "dynamic_context": True,
    },
}
```

This is the **single source of truth** - other files derive mappings via import.

**Unified Training Path**: ALL features use `dynamic_context: True`. During training, two context builders run:

1. **`_build_variables_context()`** fetches variable metadata from StarChat API using `get_variable_schema(nested=True, language_descriptions={lang})`. The response is a collections array `[{variables: [...]}]` where variables arrays can contain nested lists (matching the MrCall dashboard's `.flat()` pattern). Per-variable metadata includes localized flat keys: `humanName` (rich user-facing description from `human_name_multilang`), `description` (short behavioral note from `description_multilang`), `defaultValue`, `type`, and the current value. Language fallback: description uses `en-US` → `en` → `*`; default value uses business `languageCountry` (e.g. `it-IT`) → short code (e.g. `it`) → `*`. Injected via `{variables_context}` placeholder.

2. **`_build_conversation_variables_context()`** parses `ASSISTANT_TOOL_VARIABLE_EXTRACTION` from the business config to discover which caller-extracted variables are available (e.g., FIRST_NAME, EMAIL_ADDRESS, BOOKING_DATE). Combines these with static `public:*` variables (date/time, business status) and exportable aliases (CALLER_NUMBER, RECURRENT_CONTACT, OUTBOUND_CALL). Injected via `{conversation_variables_context}` placeholder.

Both context builders accept an optional pre-fetched `business` dict — `train_feature()` fetches it once and passes it to both. New meta-prompts should include both `{variables_context}` and `{conversation_variables_context}` placeholders. There is no separate path for single-variable vs multi-variable features.

## Tool Selection

The unified agent has 4 tools with distinct purposes:

| Tool | When to Use | Example |
|------|-------------|---------|
| `configure_welcome_message` | User wants to CHANGE greeting | "make the greeting more formal" |
| `configure_booking` | User wants to CHANGE booking | "enable 30-min appointments" |
| `get_current_config` | User asks to SEE raw settings | "show my current settings" |
| `respond_text` | User asks YES/NO or interpretive questions | "is booking enabled?" |

### Important: Interpretive vs. Display Questions

**Questions like "is booking enabled?" or "does it answer formally?" should use `respond_text`** (interprets and answers), NOT `get_current_config` (shows raw variable values).

Examples:
- "what are my settings?" → `get_current_config` (shows raw values)
- "is booking enabled?" → `respond_text` (answers "Yes, booking is enabled...")
- "does the assistant answer formally?" → `respond_text` (interprets prompt)
- "how does it greet callers?" → `respond_text` (explains behavior)

## CLI Commands

### Connection & Setup

| Command | Description |
|---------|-------------|
| `/connect mrcall` | OAuth authentication with StarChat |
| `/mrcall list` | List all your MrCall assistants |
| `/mrcall link <business_id>` | Link to assistant by ID |
| `/mrcall unlink` | Disconnect from current assistant |

### Agent Commands

| Command | Duration | Description |
|---------|----------|-------------|
| `/agent mrcall train` | 3-10s | Train all features + build unified agent |
| `/agent mrcall train <feature>` | 3-5s | Train specific feature + rebuild agent |
| `/agent mrcall run "..."` | 5-10s | Run agent (auto-selects tool) |
| `/agent mrcall show` | <500ms | Display unified agent prompt |
| `/agent mrcall reset` | <500ms | Delete agent (must retrain) |

### Direct Commands (Simple)

| Command | Description |
|---------|-------------|
| `/mrcall variables` | List all variables with values |
| `/mrcall variables --name BOOKING` | Filter variables by name |
| `/mrcall variables set VAR VALUE` | Set variable directly |
| `/mrcall show <feature>` | Show feature sub-prompt |
| `/mrcall config <feature> "..."` | Modify via LLM (legacy) |

### Examples

```bash
# Setup
/connect mrcall
/mrcall list
/mrcall link <business_id>    # Copy ID from list
/connect anthropic

# Train and use agent
/agent mrcall train
/agent mrcall run "enable booking with 30-min appointments"
/agent mrcall run "make the greeting more casual"
/agent mrcall run "is booking enabled?"
/agent mrcall run "how does the assistant answer the phone?"

# Check configuration
/mrcall variables --name BOOKING
/agent mrcall show
```

## OAuth Requirements

MrCall OAuth requires these scopes:

```
business:read business:write contacts:read contacts:write sessions:read sessions:write templates:read
```

Without `business:write`, variable updates will fail. Users must re-run `/connect mrcall` if scopes were added.

## Storage Pattern

| Key Pattern | Content |
|-------------|---------|
| `mrcall_{business_id}` | Unified agent prompt |
| `mrcall_{business_id}_{feature}` | Feature sub-prompt |

Example:
- `mrcall_abc123` → Unified agent
- `mrcall_abc123_welcome_message` → Welcome message sub-prompt
- `mrcall_abc123_booking` → Booking sub-prompt

## Adding New Features

See skill: `zylch-mrcall-feature-configuration`

Summary:
1. Add meta-prompt constant in `mrcall_configurator.py` (uses `{variables_context}` placeholder)
2. Add to `FEATURES` dict with `"dynamic_context": True` (single source of truth)
3. Add tool in `mrcall_agent.py` (`MRCALL_AGENT_TOOLS` + handler)
4. Update help text in `command_handlers.py`

## Related

- [MrCall Integration](../features/mrcall-integration.md) - OAuth, API, contacts
- [Skill: zylch-mrcall-feature-configuration](../../.claude/skills/zylch-mrcall-feature-configuration/SKILL.md)
