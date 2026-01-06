# MrCall Configurator Agent

Manages MrCall assistant configuration through dynamic sub-prompts.

## Overview

The MrCall Configurator uses a **sub-prompt architecture** to configure individual features of an AI phone assistant. Instead of one monolithic prompt, each feature (welcome_message, booking, etc.) has its own sub-prompt that can be independently trained and modified.

## Key Components

| Component | File | Purpose |
|-----------|------|---------|
| Trainer | `zylch/agents/mrcall_configurator_trainer.py` | Generates sub-prompts from current MrCall config |
| LLM Helper | `zylch/tools/mrcall/llm_helper.py` | Function-calling based prompt modification |
| Command Handler | `zylch/services/command_handlers.py` | `/mrcall train`, `/mrcall show`, `/mrcall config` |

## Architecture

### Feature Definition

Each feature is defined in `MrCallConfiguratorTrainer.FEATURES`:

```python
FEATURES = {
    "welcome_message": {
        "variables": ["OSCAR_INBOUND_WELCOME_MESSAGE_PROMPT"],
        "description": "How the assistant answers the phone",
        "display_name": "Come risponde al telefono l'assistente",
        "meta_prompt": WELCOME_MESSAGE_META_PROMPT,
    },
}
```

### Sub-Prompt Storage

Sub-prompts are stored in `agent_prompts` table:
- `agent_type`: `mrcall_{business_id}_{feature_name}`
- Example: `mrcall_abc123_welcome_message`

### Configuration Flow

1. **Lazy Generation**: On first `/mrcall config`, sub-prompt is generated if missing
2. **LLM Modification**: User instructions are applied via function calling
3. **StarChat Update**: Modified values are pushed to MrCall API
4. **Auto-Retrain**: Sub-prompt is regenerated to reflect new state

## CLI Commands

| Command | Duration | Description |
|---------|----------|-------------|
| `/mrcall train [feature]` | 3-5s | Generate/refresh sub-prompt |
| `/mrcall show [feature]` | <500ms | Display current sub-prompt |
| `/mrcall config <feature> "instructions"` | 5-10s | Modify configuration |

## Function Calling

The `/mrcall config` command uses LiteLLM function calling to ensure structured output:

```python
# Dynamic tool schema built from feature's variables
tool = build_update_variables_tool(variable_names)

# Forced tool use - LLM must return structured JSON
response = await client.create_message(
    tools=[tool],
    tool_choice={"type": "tool", "name": "update_variables"},
)
```

## Adding New Features

See skill: `zylch-mrcall-feature-configuration`

1. Ask user for: feature key, display_name, variables
2. Create meta-prompt in trainer
3. Add to FEATURES dict
4. Add to FEATURE_TO_VARIABLES in command_handlers
5. Add to VARIABLE_TO_FEATURE in config_tools
6. Update help text

## Related

- [MrCall Integration](../features/mrcall-integration.md) - OAuth, API, contacts
