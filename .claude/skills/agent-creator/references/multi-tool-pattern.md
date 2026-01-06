# Multi-Tool Agent Pattern

Based on industry best practices from [DeepLearning.AI](https://www.deeplearning.ai/the-batch/agentic-design-patterns-part-3-tool-use/).

## Why Multi-Tool?

**This is what makes an agent different from a prompt:**
- A prompt always does the same thing
- An agent has tools and decides how to use them

## Tool Schema

Tools are defined as JSON schemas in Anthropic format:

```python
AGENT_TOOLS = [
    {
        "name": "tool_name",
        "description": "What this tool does. Be specific about WHEN to use it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "param1": {
                    "type": "string",
                    "description": "Description of param1"
                },
                "param2": {
                    "type": "integer",
                    "description": "Description of param2"
                }
            },
            "required": ["param1"]
        }
    }
]
```

## Tool Selection in Trained Prompt

The meta-prompt should instruct the trainer to include tool selection guidance:

```python
META_PROMPT = """...
Generate a prompt that includes:

**TOOL SELECTION GUIDANCE**
Instruct the agent when to use each tool:
- Use `write_email` when: user wants to compose, write, reply, send an email
- Use `search_memory` when: need more context before answering
- Use `respond_text` when: user asks a question or wants analysis
...
"""
```

## Handling Tool Responses

The `_handle_tool_response()` method in BaseAgent extracts tool calls:

```python
def _handle_tool_response(self, response) -> Dict[str, Any]:
    result = {
        'tool_used': None,
        'tool_input': {},
        'result': None
    }

    if response.stop_reason == "tool_use":
        for block in response.content:
            if hasattr(block, 'input'):  # ToolUseBlock
                result['tool_used'] = block.name
                result['tool_input'] = block.input
                break

    return result
```

## Processing Different Tools

In your agent, process each tool's output:

```python
async def run(self, instructions: str, **kwargs) -> Dict[str, Any]:
    # ... call LLM with tools ...

    result = self._handle_tool_response(response)

    # Process based on tool used
    if result['tool_used'] == 'write_email':
        result['result'] = self._process_write_email(result['tool_input'])
    elif result['tool_used'] == 'search_memory':
        result['result'] = self._process_search_memory(result['tool_input'])
    elif result['tool_used'] == 'respond_text':
        result['result'] = {'response': result['tool_input'].get('response', '')}

    return result
```

## Best Practices

1. **Let the LLM choose** - Pass all tools and let the model decide
2. **Clear descriptions** - Tool descriptions should clearly state WHEN to use
3. **Include respond_text** - Always have a fallback for questions/analysis
4. **Process tool output** - Don't just return raw tool input, process it

## Example: Email Agent Tools

```python
EMAIL_AGENT_TOOLS = [
    {
        "name": "write_email",
        "description": "Compose and save an email as draft. Use when user wants to write/compose/reply/send.",
        "input_schema": {...}
    },
    {
        "name": "search_memory",
        "description": "Search blobs for context. Use when you need more information.",
        "input_schema": {...}
    },
    {
        "name": "get_email",
        "description": "Fetch original email by ID. Use when blob references need more detail.",
        "input_schema": {...}
    },
    {
        "name": "respond_text",
        "description": "Return analysis/suggestions. Use for questions, NOT for composing.",
        "input_schema": {...}
    }
]
```

See `zylch/agents/emailer_agent.py` for the full implementation.
