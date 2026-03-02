---
description: |
  Two-tier architecture for configuring MrCall AI phone assistants. Layer 1 (ConfiguratorTrainer):
  for each feature, fetches current variable values from StarChat, applies meta-prompt template,
  generates feature sub-prompt via LLM. Layer 2 (AgentTrainer): combines all sub-prompts into a
  unified agent with tool selection. Trained via /agent mrcall train.
---

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
| `mrcall_{business_id}_snapshot` | Training snapshot (variable values at last training) |

Example:
- `mrcall_abc123` → Unified agent
- `mrcall_abc123_welcome_message` → Welcome message sub-prompt
- `mrcall_abc123_booking` → Booking sub-prompt
- `mrcall_abc123_snapshot` → Last-trained variable values (JSON)

## Training Optimization (Selective Retraining)

### Problem
Full training regenerates ALL 8 feature prompts via LLM calls (each 3-5s), even when only 1 variable changed. This wastes time and API credits.

### Solution: Snapshot-based selective retraining

After each training, variable values are saved as a **snapshot** in `agent_prompts` table (key: `mrcall_{business_id}_snapshot`). On the next training:

1. **Load snapshot** of last-trained values
2. **Fetch live values** from StarChat
3. **Diff**: identify which variables changed
4. **Map** changed variables → affected features (via `VARIABLE_TO_FEATURE` inverse mapping from `FEATURES` dict)
5. **Retrain only stale features** (skip current ones)
6. **Save updated snapshot** (only for successfully trained features)

### CLI Usage

```bash
/agent mrcall train          # Selective (only changed features)
/agent mrcall train --force  # Force full retrain (all features)
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/mrcall/training/status` | GET | Returns status: `untrained`, `current`, `stale`, `in_progress` + changed variables list |
| `/api/mrcall/training/start` | POST | Starts training as background job, returns `job_id` for polling |
| `/api/jobs/{job_id}` | GET | Poll background job status |

### Training Status Values

| Status | Meaning | Dashboard Button Color |
|--------|---------|----------------------|
| `untrained` | No snapshot exists (first time) | Gray |
| `current` | All variables match snapshot | Green |
| `stale` | Some variables changed since last training | Red |
| `in_progress` | Training job running | Yellow (animated) |

### Dashboard Integration

**BusinessConfiguration.vue** (`~/hb/mrcall-dashboard`): Color-coded training button in footer between "Configure with AI" and "Save". Shows changed variable count when stale. Starts background training job and polls for completion.

**ConfigureAI.vue** (`~/hb/mrcall-dashboard`): Training status badge in sidebar showing current status before user enters chat.

### Key Files

| File | What |
|------|------|
| `zylch/storage/supabase_client.py` | `get_training_snapshot()`, `store_training_snapshot()` |
| `zylch/agents/trainers/mrcall_configurator.py` | `diff_snapshot()`, `build_snapshot_from_business()` classmethods |
| `zylch/services/command_handlers.py` | Updated `_handle_mrcall_agent_train()` with selective logic + `--force` |
| `zylch/api/routes/mrcall.py` | Training status + start endpoints |
| `zylch/tools/mrcall/config_tools.py` | Inline snapshot update after `ConfigureAssistantTool.execute()` |

### Edge Cases

- **First training** (no snapshot): trains all features, saves initial snapshot
- **Partial failure**: snapshot only updated for successfully trained features
- **`--force` flag**: bypasses diff, retrains everything
- **Inline retraining** (via `ConfigureAssistantTool`): updates snapshot for the affected feature's variables
- **Stuck jobs**: self-healing — jobs older than 10 minutes auto-marked as failed

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
