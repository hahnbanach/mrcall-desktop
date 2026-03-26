---
description: |
  MrCall configurator architecture: live variable loading at runtime (no stale trained prompts),
  conversation memory across run calls, config memory persisted as entity blobs.
  Layer 2 (AgentTrainer) still assembles unified agent prompt. Trained via /agent mrcall train.
---

# MrCall Configurator Agent

Manages MrCall assistant configuration with live variable loading and conversation memory.

## Overview

The MrCall Configurator uses **live runtime context** (not pre-trained prompts) for feature knowledge:

1. **Fixed templates** (`mrcall_templates.py`): Structure/format per feature — stable, no LLM generation needed
2. **Live values** (`mrcall_context.py`): Current StarChat variables fetched before every LLM call
3. **Conversation memory** (`mrcall_agent.py`): Message history preserved across `run()` calls in a session
4. **Config memory** (`mrcall_memory.py`): Configuration decisions persisted as entity blobs across sessions
5. **Layer 2 (AgentTrainer)**: Combines templates into a unified agent with tool selection instructions

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    /agent mrcall run "..."                    │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              MrCallContext (mrcall_context.py)                │
│                                                              │
│  1. Fetch LIVE variable values from StarChat API             │
│  2. Apply fixed templates from mrcall_templates.py           │
│  3. Load config memory blobs (prior decisions)               │
│  4. Assemble runtime prompt with fresh data                  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              MrCallAgent (mrcall_agent.py)                    │
│                                                              │
│  1. Inject conversation_history (prior run() exchanges)      │
│  2. LLM selects tool from 11 available tools                 │
│  3. Tool executes (validate, summarize, apply or dry_run)    │
│  4. Append exchange to conversation_history                  │
│  5. Store config decision in memory (mrcall_memory.py)       │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    /agent mrcall train                        │
│                                                              │
│  Layer 2 only: assembles unified agent prompt from           │
│  fixed templates + tool selection instructions.              │
│  No longer generates per-feature sub-prompts via LLM.        │
└─────────────────────────────────────────────────────────────┘
```

## Key Components

| Component | File | Purpose |
|-----------|------|---------|
| Context Builder | `zylch/agents/mrcall_context.py` | Live StarChat variable fetching + prompt assembly |
| Feature Templates | `zylch/agents/mrcall_templates.py` | Fixed structure/format templates per feature |
| Config Memory | `zylch/agents/mrcall_memory.py` | Persist configuration decisions as entity blobs |
| Agent | `zylch/agents/mrcall_agent.py` | Runs agent with tools + conversation history |
| AgentTrainer | `zylch/agents/trainers/mrcall.py` | Layer 2: Combines templates into unified agent |
| ConfiguratorTrainer | `zylch/agents/trainers/mrcall_configurator.py` | Simplified: template management, FEATURES dict |
| Command Handler | `zylch/services/command_handlers.py` | CLI command routing, session-level agent reuse |

## Feature Definition

Each feature is defined ONCE in `MrCallConfiguratorTrainer.FEATURES`:

```python
FEATURES = {
    "welcome_inbound": {
        "variables": ["ENABLE_INBOUND_WELCOME_MESSAGE_PROMPT", "INBOUND_WELCOME_MESSAGE_PROMPT", ...],
        "description": "How the assistant answers incoming calls",
        "meta_prompt": WELCOME_MESSAGE_META_PROMPT,
        "dynamic_context": True,
    },
    "booking": {
        "variables": ["START_BOOKING_PROCESS", "BOOKING_HOURS", "BOOKING_EVENTS_MINUTES", ...],
        "description": "Appointment booking behavior",
        "meta_prompt": BOOKING_META_PROMPT,
        "dynamic_context": True,
    },
    # + welcome_outbound, caller_followup, conversation, knowledge_base,
    #   notifications_business, runtime_data, call_transfer
}
```

This is the **single source of truth** - other files derive mappings via import.

**Unified Training Path**: ALL features use `dynamic_context: True`. During training, two context builders run:

1. **`_build_variables_context()`** fetches variable metadata from StarChat API using `get_variable_schema(nested=True, language_descriptions={lang})`. The response is a collections array `[{variables: [...]}]` where variables arrays can contain nested lists (matching the MrCall dashboard's `.flat()` pattern). Per-variable metadata includes localized flat keys: `humanName` (rich user-facing description from `human_name_multilang`), `description` (short behavioral note from `description_multilang`), `defaultValue`, `type`, and the current value. Language fallback: description uses `en-US` → `en` → `*`; default value uses business `languageCountry` (e.g. `it-IT`) → short code (e.g. `it`) → `*`. Injected via `{variables_context}` placeholder.

2. **`_build_conversation_variables_context()`** parses `ASSISTANT_TOOL_VARIABLE_EXTRACTION` from the business config to discover which caller-extracted variables are available (e.g., FIRST_NAME, EMAIL_ADDRESS, BOOKING_DATE). Combines these with static `public:*` variables (date/time, business status) and exportable aliases (CALLER_NUMBER, RECURRENT_CONTACT, OUTBOUND_CALL). Injected via `{conversation_variables_context}` placeholder.

Both context builders accept an optional pre-fetched `business` dict — `train_feature()` fetches it once and passes it to both. New meta-prompts should include both `{variables_context}` and `{conversation_variables_context}` placeholders. There is no separate path for single-variable vs multi-variable features.

## Tool Selection

The unified agent has 11 tools — 9 configure tools (one per feature), plus 2 utility tools:

| Tool | When to Use | Example |
|------|-------------|---------|
| `configure_welcome_inbound` | Change inbound greeting | "make the greeting more formal" |
| `configure_welcome_outbound` | Change outbound greeting | "change the outgoing call intro" |
| `configure_booking` | Change booking settings | "enable 30-min appointments" |
| `configure_caller_followup` | Change post-call messages | "send WhatsApp after calls" |
| `configure_conversation` | Change conversation flow | "ask for caller's email" |
| `configure_knowledge_base` | Change Q&A knowledge | "add info about parking" |
| `configure_notifications_business` | Change notifications | "send email after missed calls" |
| `configure_runtime_data` | Change API integrations | "connect CRM lookup" |
| `configure_call_transfer` | Change call forwarding | "forward sales calls to +39..." |
| `get_current_config` | Show raw settings | "show my current settings" |
| `respond_text` | Answer interpretive questions | "is booking enabled?" |

## Dry Run & Save Button (Dashboard)

When invoked from the MrCall dashboard, `configure_*` tools run in **dry_run mode**:

1. LLM determines the changes (validates variables, generates summary)
2. Changes are NOT applied to StarChat — returned as `pending_changes` in API metadata
3. Dashboard accumulates pending changes in frontend memory
4. **Save button** appears in the sidebar with a count badge
5. User clicks Save → `POST /api/mrcall/apply-changes` → StarChat updated in batch
6. **Discard** clears pending changes without applying

This gives users a chance to review before changes go live. CLI (`/agent mrcall run`) still applies immediately (no dry_run).

### Key endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/mrcall/apply-changes` | POST | Apply pending changes to StarChat (body: `{business_id, changes: [{variable_name, new_value}]}`) |

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

### Agent Prompts (agent_prompts table)

| Key Pattern | Content |
|-------------|---------|
| `mrcall_{business_id}` | Unified agent prompt (Layer 2 output) |
| `mrcall_{business_id}_{feature}` | Feature sub-prompt (legacy, may be unused now) |
| `mrcall_{business_id}_snapshot` | Training snapshot (variable values at last training) |

### Config Memory (blobs table)

| Namespace | Content |
|-----------|---------|
| `{owner_id}:mrcall:{business_id}` | Configuration decisions — summaries of what was configured and why |

Config memory blobs are created after each successful `configure_*` call. They persist across sessions and are loaded as context for subsequent conversations, giving the agent knowledge of prior configuration decisions without re-reading all variables.

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
