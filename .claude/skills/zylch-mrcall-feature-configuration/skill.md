---
name: zylch-mrcall-feature-configuration
description: Guide for adding new MrCall feature configurations. Use when adding a new configurable feature like booking, conversation_flow, or any other MrCall variable that users should be able to modify via /mrcall config.
---

# Adding MrCall Feature Configurations

## Architecture Overview

### Direct Agent Architecture (No Orchestrator)

```
User message (via dashboard or CLI)
    │
    │ chat_service calls MrCallAgent.run() directly
    ↓
MrCallAgent (agentic loop)
    │
    │ while(tool_use) loop — terminates when LLM stops calling tools
    │ 10 configure tools + respond_text + web_search
    │ Post-tool-use <config-progress> injection between turns
    │ Context compression for long sessions
    ↓
StarChat API (updates variables)
```

### Runtime Prompts (No Training Step)

```
/mrcall open <business_id>      → Enter config mode
User: "configure X"             → Agent builds runtime prompt with LIVE values
                                   from StarChat, executes tools, feeds results back
/mrcall exit                    → Exit config mode
```

**No training step.** Templates are static, values are fetched live on every run.

### Single Source of Truth

**CRITICAL**: All feature/variable mappings are defined ONCE in `MrCallConfiguratorTrainer.FEATURES`. Other files IMPORT and DERIVE from this source.

```
MrCallConfiguratorTrainer.FEATURES  (SINGLE SOURCE OF TRUTH)
         │
         ├──> command_handlers.py: FEATURE_TO_VARIABLES (derived via import)
         ├──> config_tools.py: VARIABLE_TO_FEATURE (derived via import)
         ├──> MrCallAgentTrainer: Combines feature sub-prompts
         └──> MrCallAgent: Multi-tool runner (auto-detects feature)
```

## Tools Available

The unified agent has 4 tools:

| Tool | When to Use |
|------|-------------|
| `configure_welcome_message` | User wants to CHANGE, UPDATE, MODIFY greeting |
| `configure_booking` | User wants to CHANGE, UPDATE, MODIFY booking |
| `get_current_config` | User asks to SEE, VIEW, DISPLAY raw settings |
| `respond_text` | User asks YES/NO or interpretive questions |

### Tool Selection Rules

**Important:** The tool choice depends on user INTENT, not just keywords:

- "change the greeting" → `configure_welcome_message`
- "what are my current settings?" → `get_current_config` (shows raw values)
- "is booking enabled?" → `respond_text` (interprets and answers)
- "does the assistant answer formally?" → `respond_text` (interprets)
- "how does it greet callers?" → `respond_text` (explains behavior)

**Rule:** Questions like "is X enabled?" or "does it do Y?" should use `respond_text` (interprets settings), NOT `get_current_config` (shows raw values).

## OAuth Requirements

MrCall OAuth must include these scopes for full functionality:

```
business:read business:write contacts:read contacts:write sessions:read sessions:write templates:read
```

Without `business:write`, variable updates will fail with 400/403 errors.

## Checklist

When adding a new feature (e.g., "booking"):

1. [ ] **Ask the user for:**
   - Feature key (e.g., `booking`)
   - Display name in user's language (e.g., "Gestione prenotazioni appuntamenti")
   - Which MrCall variable(s) it controls
2. [ ] Define meta-prompt constant in `mrcall_configurator_trainer.py`
3. [ ] Add to `FEATURES` dict in `MrCallConfiguratorTrainer` class
4. [ ] Add tool to `MRCALL_AGENT_TOOLS` in `mrcall_agent.py`
5. [ ] Add tool handler in `MrCallAgent._handle_tool_response()`
6. [ ] Update help text in `command_handlers.py` (features list description)
7. [ ] **VERIFY**: Run Python import test to ensure no circular imports

## Files to Modify

| File | What to Add |
|------|-------------|
| `zylch/agents/mrcall_configurator_trainer.py` | Meta-prompt + FEATURES entry **(ONLY place to define variables)** |
| `zylch/agents/mrcall_agent.py` | Tool definition + handler |
| `zylch/services/command_handlers.py` | Help text update only (mappings are auto-derived) |

**DO NOT manually edit** `FEATURE_TO_VARIABLES` in command_handlers.py or `VARIABLE_TO_FEATURE` in config_tools.py - these are derived automatically via import.

## Storage Pattern

Sub-prompts stored in `agent_prompts` table:

| Key Pattern | Content |
|-------------|---------|
| `mrcall_{business_id}_{feature}` | Feature sub-prompt (e.g., `mrcall_abc123_booking`) |
| `mrcall_{business_id}` | Unified agent prompt combining all features |

## Finding MrCall Variables

To discover available variables:
1. Run `/mrcall variables` to list all variables
2. Run `/mrcall variables --name BOOKING` to filter
3. Look at StarChat business config for variable names

See [REFERENCE.md](REFERENCE.md) for templates and step-by-step guide.
