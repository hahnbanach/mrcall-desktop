# Command Wiring for Agents

This document explains how to wire `/agent` commands for new agents.

For general command creation patterns, see the `zylch-creating-commands` skill.

## Command Structure

All agents use this pattern:
```
/agent <domain> <action> [channel|instructions]
```

Where:
- `domain`: memory, task, email, or your new domain
- `action`: train, run, show, reset
- `channel`: email, calendar, all (for memory/task)
- `instructions`: quoted string (for email run)

## Adding a New Domain

### 1. Update valid_domains

In `handle_agent()`:
```python
valid_domains = ['memory', 'task', 'email', 'yourdomain']
```

### 2. Add Domain Handler Block

```python
# =====================
# YOURDOMAIN DOMAIN
# =====================
elif domain == 'yourdomain':
    if action == 'train':
        return await _handle_yourdomain_train(storage, owner_id, api_key, llm_provider, user_email)
    elif action == 'run':
        # Extract instructions from args
        instructions = ' '.join(args[2:]) if len(args) > 2 else ''
        return await _handle_yourdomain_run(storage, owner_id, api_key, llm_provider, instructions)
    elif action == 'show':
        return await _handle_yourdomain_show(storage, owner_id)
    elif action == 'reset':
        return await _handle_yourdomain_reset(storage, owner_id)
```

### 3. Add Helper Functions

```python
async def _handle_yourdomain_train(storage, owner_id, api_key, llm_provider, user_email):
    """Train your domain agent."""
    from zylch.agents.your_agent_trainer import YourAgentTrainer

    # Validation
    if not api_key or not llm_provider:
        return """❌ **LLM API key required**

Connect your LLM provider:
\`/connect anthropic\` or \`/connect openai\` or \`/connect mistral\`"""

    try:
        trainer = YourAgentTrainer(storage, owner_id, api_key, user_email, llm_provider)
        prompt, metadata = await trainer.build_prompt()
        storage.store_agent_prompt(owner_id, 'yourdomain', prompt, metadata)

        return f"""✅ **Your Agent Trained**

Analyzed {metadata.get('data_analyzed', 0)} items.

Use \`/agent yourdomain run "instructions"\` to execute."""

    except ValueError as e:
        return f"❌ **Training failed:** {str(e)}"
    except Exception as e:
        logger.error(f"Training error: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}"


async def _handle_yourdomain_run(storage, owner_id, api_key, llm_provider, instructions):
    """Execute your domain agent."""
    from zylch.agents.your_agent import YourAgent

    if not instructions.strip():
        return """❌ **Missing instructions**

Usage: \`/agent yourdomain run "your instructions"\`"""

    if not api_key or not llm_provider:
        return "❌ **LLM API key required**"

    try:
        agent = YourAgent(storage, owner_id, api_key, llm_provider)
        result = await agent.run(instructions)

        # Format response based on tool used
        tool_used = result.get('tool_used')
        tool_result = result.get('result', {})

        if tool_used == 'your_action':
            # Handle your action's output
            return f"✅ **Action completed**\n\n{tool_result}"
        elif tool_used == 'respond_text':
            return f"💬 **Response**\n\n{tool_result.get('response', '')}"
        else:
            return f"⚠️ Unexpected result: {result}"

    except Exception as e:
        logger.error(f"Run error: {e}", exc_info=True)
        return f"❌ **Error:** {str(e)}"


async def _handle_yourdomain_show(storage, owner_id):
    """Show your domain agent prompt."""
    agent_prompt = storage.get_agent_prompt(owner_id, 'yourdomain')
    if not agent_prompt:
        return """❌ **No agent found**

Train first: \`/agent yourdomain train\`"""

    meta = storage.get_agent_prompt_metadata(owner_id, 'yourdomain')
    # ... format and return prompt display


async def _handle_yourdomain_reset(storage, owner_id):
    """Delete your domain agent prompt."""
    deleted = storage.delete_agent_prompt(owner_id, 'yourdomain')
    if deleted:
        return """✅ **Agent deleted**

Retrain with: \`/agent yourdomain train\`"""
    return "❌ No agent found"
```

### 4. Update Help Text

In `handle_agent()`, update the help_text variable:
```python
help_text = """**🤖 Manage AI Agents**

...

**Your Domain Agent** (description):
• \`/agent yourdomain train\` - Description
• \`/agent yourdomain run "instructions"\` - Execute
• \`/agent yourdomain show\` - Show prompt
• \`/agent yourdomain reset\` - Delete

..."""
```

## agent_prompts Table

Trained prompts are stored in the `agent_prompts` table:

| Column | Type | Description |
|--------|------|-------------|
| owner_id | text | Firebase UID |
| agent_type | text | e.g., 'emailer', 'memory_email', 'task_calendar' |
| prompt | text | The generated prompt |
| metadata | jsonb | Training metadata |
| created_at | timestamp | When trained |

Storage methods:
- `storage.store_agent_prompt(owner_id, agent_type, prompt, metadata)`
- `storage.get_agent_prompt(owner_id, agent_type)`
- `storage.get_agent_prompt_metadata(owner_id, agent_type)`
- `storage.delete_agent_prompt(owner_id, agent_type)`
