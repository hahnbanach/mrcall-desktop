---
name: zylch-mrcall-feature-configuration
description: Guide for adding new MrCall feature configurations. Use when adding a new configurable feature like booking, conversation_flow, or any other MrCall variable that users should be able to modify via /mrcall config.
---

# Adding MrCall Feature Configurations

## Architecture Overview

### Single Command Training

```
/agent mrcall train              → Trains ALL features + builds unified agent
/agent mrcall train <feature>    → Trains specific feature + rebuilds agent
/agent mrcall run "..."          → Agent chooses tool based on user intent
```

**One command does everything.** No separate training steps.

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

### Tools Available

- `configure_welcome_message` - Modify greeting settings
- `configure_booking` - Modify appointment booking settings
- `get_current_config` - Show current configuration
- `respond_text` - Answer questions about settings

## Checklist

When adding a new feature (e.g., "booking"):

1. [ ] **Ask the user for:**
   - Feature key (e.g., `booking`)
   - Display name in user's language (e.g., "Gestione prenotazioni appuntamenti")
   - Which MrCall variable(s) it controls
2. [ ] Define meta-prompt constant in `mrcall_configurator_trainer.py`
3. [ ] Add to `FEATURES` dict in `MrCallConfiguratorTrainer` class
4. [ ] Update help text in `command_handlers.py` (features list description)
5. [ ] **VERIFY**: Run Python import test to ensure no circular imports

## Files to Modify

| File | What to Add |
|------|-------------|
| `zylch/agents/mrcall_configurator_trainer.py` | Meta-prompt + FEATURES entry **(ONLY place to define variables)** |
| `zylch/services/command_handlers.py` | Help text update only (mappings are auto-derived) |

**DO NOT manually edit** `FEATURE_TO_VARIABLES` in command_handlers.py or `VARIABLE_TO_FEATURE` in config_tools.py - these are derived automatically via import.

## Storage Pattern

Sub-prompts stored in `agent_prompts` table:
- `agent_type`: `mrcall_{business_id}_{feature_name}`
- Example: `mrcall_abc123_booking`

## Finding MrCall Variables

To discover available variables:
1. Run `/mrcall variables` to list all variables
2. Run `/mrcall variables --name BOOKING` to filter
3. Look at StarChat business config for variable names

See [REFERENCE.md](REFERENCE.md) for templates and step-by-step guide.
