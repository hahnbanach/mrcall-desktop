---
name: zylch-mrcall-feature-configuration
description: Guide for adding new MrCall feature configurations. Use when adding a new configurable feature like booking, conversation_flow, or any other MrCall variable that users should be able to modify via /mrcall config.
---

# Adding MrCall Feature Configurations

## Checklist

When adding a new feature (e.g., "booking"):

1. [ ] Define meta-prompt in `mrcall_configurator_trainer.py`
2. [ ] Add to `FEATURES` dict in `mrcall_configurator_trainer.py`
3. [ ] Add to `FEATURE_TO_VARIABLE` in `command_handlers.py`
4. [ ] Add to `VARIABLE_TO_FEATURE` in `config_tools.py`
5. [ ] Update help text in `command_handlers.py` (inline + registry)

## Files to Modify

| File | What to Add |
|------|-------------|
| `zylch/agents/mrcall_configurator_trainer.py` | Meta-prompt + FEATURES entry |
| `zylch/services/command_handlers.py` | FEATURE_TO_VARIABLE mapping + help text |
| `zylch/tools/mrcall/config_tools.py` | VARIABLE_TO_FEATURE mapping |

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
