---
name: agent-creator
description: Create new trainable agents for Zylch. Use when adding a new agent type that learns from user data and can perform multiple actions. Covers trainer classes, multi-tool patterns, command wiring, and the base class for shared logic.
---

# Agent Creator Skill

Create trainable agents that learn from user data and can perform multiple actions.

## MANDATORY: Inherit from Base Classes

All agents MUST inherit from:
- `BaseAgent` for runners (`zylch/agents/base_agent.py`)
- `BaseAgentTrainer` for trainers (`zylch/agents/base_trainer.py`)

**DO NOT** create standalone classes that duplicate base class functionality.

## What Makes an Agent (vs a Prompt)

An **agent** has:
1. A **trained prompt** that learns from user data (writing style, patterns)
2. **Multiple tools** it can choose from based on the request
3. The ability to **autonomously seek more information** when context is insufficient

A **prompt** is just static instructions.

## Agent Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Agent                            │
├─────────────────────────────────────────────────────┤
│  Trainer (learns from user data)                    │
│    → Analyzes emails/calendar/blobs                 │
│    → Generates personalized prompt                  │
│    → Stores in agent_prompts table                  │
├─────────────────────────────────────────────────────┤
│  Runner (executes with instructions)                │
│    → Loads trained prompt                           │
│    → Gathers context (hybrid search, task sources)  │
│    → Has multiple tools to choose from              │
│    → LLM decides which tool(s) to use               │
└─────────────────────────────────────────────────────┘
```

## Command Pattern

All agents follow the standardized command pattern:

```
/agent <domain> train [channel]      # Create personalized prompt
/agent <domain> run "instructions"   # Execute agent
/agent <domain> show [channel]       # View current prompt
/agent <domain> reset [channel]      # Delete prompt
```

**Current agents:**

| Domain | Commands | Channel |
|--------|----------|---------|
| `memory` | train, run, show, reset | email, calendar, all |
| `task` | train, run, show, reset | email, calendar, all |
| `email` | train, run, show, reset | (none) |

For command wiring details, see the `zylch-creating-commands` skill.

## Creating a New Agent

### Step 1: Create the Trainer

Inherit from `BaseAgentTrainer` (`zylch/agents/base_trainer.py`):

```python
# zylch/agents/my_agent_trainer.py
from zylch.agents.base_trainer import BaseAgentTrainer

class MyAgentTrainer(BaseAgentTrainer):
    """Builds personalized agent by analyzing user's data."""

    # Your meta-prompt that instructs LLM to generate a personalized prompt
    META_PROMPT = """Analyze user's data and generate a personalized prompt.

    === USER PROFILE ===
    {user_profile}

    === SAMPLES ===
    {samples}

    Generate a prompt that instructs an agent to...

    The agent will have these tools available:
    - tool_a: description
    - tool_b: description

    Include instructions for WHEN to use each tool.
    """

    async def build_prompt(self) -> Tuple[str, Dict[str, Any]]:
        """Build the agent prompt. Required by BaseAgentTrainer."""

        # Get data using inherited methods
        data = self._get_emails(limit=50, filter_sent=True)

        if not data:
            raise ValueError("No data found. Please sync first.")

        # Analyze patterns using inherited method
        profile = self._analyze_user_profile(data)

        # Format samples using inherited method
        samples = self._format_email_samples(data, max_samples=15)

        # Generate prompt using inherited method
        meta_prompt = self.META_PROMPT.format(
            user_profile=profile,
            samples=samples
        )
        prompt_content = self._generate_prompt(meta_prompt, max_tokens=4000)

        # Build metadata using inherited method
        metadata = self._build_metadata(data_analyzed=len(data))

        return prompt_content, metadata
```

### Step 2: Create the Agent (Runner)

Inherit from `BaseAgent` (`zylch/agents/base_agent.py`):

```python
# zylch/agents/my_agent.py
from zylch.agents.base_agent import BaseAgent

# Define tools the agent can use
MY_AGENT_TOOLS = [
    {
        "name": "do_action",
        "description": "Perform the main action",
        "input_schema": {
            "type": "object",
            "properties": {
                "param": {"type": "string", "description": "..."}
            },
            "required": ["param"]
        }
    },
    {
        "name": "respond_text",
        "description": "Return analysis/suggestions (not an action)",
        "input_schema": {
            "type": "object",
            "properties": {
                "response": {"type": "string"}
            },
            "required": ["response"]
        }
    }
]

class MyAgent(BaseAgent):
    """Multi-tool agent for my domain."""

    PROMPT_KEY = 'my_agent'  # Key in agent_prompts table
    TOOLS = MY_AGENT_TOOLS

    async def run(self, instructions: str, **kwargs) -> Dict[str, Any]:
        """Execute the agent with given instructions."""

        # Gather context (can override _gather_context for custom logic)
        context = await self._gather_context(instructions, **kwargs)

        # Load trained prompt
        trained_prompt = self._get_trained_prompt()

        # Build full prompt
        if trained_prompt:
            prompt = f"{trained_prompt}\n\nCONTEXT:\n{context}\n\nINSTRUCTIONS: {instructions}"
        else:
            prompt = f"You are an assistant.\n\nCONTEXT:\n{context}\n\nINSTRUCTIONS: {instructions}"

        # Call LLM with tools - let it choose
        response = await self.llm.create_message(
            messages=[{"role": "user", "content": prompt}],
            tools=self.TOOLS,
            max_tokens=2000
        )

        # Handle response
        return self._handle_tool_response(response)
```

### Step 3: Wire the Commands

In `zylch/services/command_handlers.py`:

1. Add domain to `valid_domains`:
```python
valid_domains = ['memory', 'task', 'email', 'myagent']
```

2. Add domain handler block in `handle_agent()`:
```python
# =====================
# MYAGENT DOMAIN
# =====================
elif domain == 'myagent':
    if action == 'train':
        return await _handle_myagent_train(storage, owner_id, api_key, llm_provider, user_email)
    elif action == 'run':
        instructions = ' '.join(args[2:]) if len(args) > 2 else ''
        return await _handle_myagent_run(storage, owner_id, api_key, llm_provider, instructions)
    elif action == 'show':
        return await _handle_myagent_show(storage, owner_id)
    elif action == 'reset':
        return await _handle_myagent_reset(storage, owner_id)
```

3. Add helper functions:
```python
async def _handle_myagent_train(storage, owner_id, api_key, llm_provider, user_email):
    from zylch.agents.my_agent_trainer import MyAgentTrainer

    trainer = MyAgentTrainer(storage, owner_id, api_key, user_email, llm_provider)
    prompt, metadata = await trainer.build_prompt()
    storage.store_agent_prompt(owner_id, 'my_agent', prompt, metadata)

    return f"✅ **Agent trained** ({metadata.get('data_analyzed', 0)} items analyzed)"

async def _handle_myagent_run(storage, owner_id, api_key, llm_provider, instructions):
    from zylch.agents.my_agent import MyAgent

    if not instructions.strip():
        return "❌ **Missing instructions**\n\nUsage: `/agent myagent run \"instructions\"`"

    agent = MyAgent(storage, owner_id, api_key, llm_provider)
    result = await agent.run(instructions)

    # Format response based on tool used
    tool_used = result.get('tool_used')
    if tool_used == 'do_action':
        return f"✅ Action completed: {result['result']}"
    elif tool_used == 'respond_text':
        return f"💬 {result['result']['response']}"

    return f"Result: {result}"
```

4. Update help text in `handle_agent()`.

For complete command patterns, see the `zylch-creating-commands` skill.

## Base Classes Reference

### BaseAgentTrainer Methods

```python
class BaseAgentTrainer:
    def __init__(self, storage, owner_id, api_key, user_email, provider):
        # Common initialization (ONE place)

    def _get_emails(self, limit, filter_sent=False) -> List[Dict]:
        # Fetch and filter emails

    def _get_blobs(self, entity_type=None, limit=50) -> List[Dict]:
        # Fetch memory blobs

    def _generate_prompt(self, meta_prompt, max_tokens=4000) -> str:
        # Call LLM to generate personalized prompt

    def _format_email_samples(self, emails, max_samples=15, body_limit=500) -> str:
        # Format emails for meta-prompt

    def _analyze_user_profile(self, sent_emails) -> str:
        # Extract writing patterns

    def _build_metadata(self, **extra) -> Dict[str, Any]:
        # Build metadata dict

    async def build_prompt(self) -> Tuple[str, Dict[str, Any]]:
        # MUST override in subclass
```

### BaseAgent Methods

```python
class BaseAgent:
    PROMPT_KEY = ''  # Key in agent_prompts table
    TOOLS = []       # Tool schemas for LLM

    def __init__(self, storage, owner_id, api_key, provider):
        # Common initialization

    def _get_trained_prompt(self) -> Optional[str]:
        # Load from agent_prompts table

    def has_trained_prompt(self) -> bool:
        # Check if trained

    async def _gather_context(self, instructions, **kwargs) -> str:
        # Default: hybrid search. Override for custom logic.

    def _handle_tool_response(self, response) -> Dict[str, Any]:
        # Extract tool call results

    async def run(self, instructions, **kwargs) -> Dict[str, Any]:
        # Main entry point. Override for custom behavior.
```

## Multi-Tool Best Practices

Based on [DeepLearning.AI Agentic Design Patterns](https://www.deeplearning.ai/the-batch/agentic-design-patterns-part-3-tool-use/):

1. **Let the LLM choose** - Don't hard-code which tool to use
2. **Include tool selection guidance in the trained prompt** - "Use write_email when..., use respond_text when..."
3. **Set iteration limits** - Guard against infinite loops (built into BaseAgent)
4. **Handle errors gracefully** - Retry mechanisms, fallbacks

## Training Does Everything

**CRITICAL**: When a user runs `/agent <domain> train`, the trainer should do ALL the work:
1. Gather all necessary data (fetch from APIs, analyze patterns)
2. Generate the trained prompt
3. Store the prompt

The user should NOT need to run multiple preparatory commands.

**WRONG pattern:**
```
/prepare-data          ← Step 1: prepare data
/agent myagent train   ← Step 2: train agent
```

**CORRECT pattern:**
```
/agent myagent train   ← Does everything in one step
```

**Example - MrCall Agent:**
- `/agent mrcall train` trains all features AND builds the unified agent
- No separate `/mrcall train` command needed
- The trainer internally calls feature trainers, then combines results

## Files to Create

| File | Purpose |
|------|---------|
| `zylch/agents/my_agent_trainer.py` | Your trainer (extends BaseAgentTrainer) |
| `zylch/agents/my_agent.py` | Your agent (extends BaseAgent) |
| Update `command_handlers.py` | Wire commands |
| Update help text | Document new agent |

## Example: Email Agent

See `zylch/agents/emailer_agent.py` and `zylch/agents/emailer_agent_trainer.py` for a complete example of:
- Multi-tool agent with 4 tools (write_email, search_memory, get_email, respond_text)
- Trainer that learns writing style from sent emails
- Command handler integration

The meta-prompt includes tool selection guidance so the trained agent knows when to compose emails vs. answer questions.

## What NOT to Do

### WRONG: Standalone class that duplicates BaseAgent

```python
# ❌ WRONG - Missing inheritance, duplicates base class code
class MyAgent:
    def __init__(self, storage, owner_id, api_key, provider):
        self.storage = storage  # Duplicates BaseAgent
        self.owner_id = owner_id  # Duplicates BaseAgent
        self.llm = LLMClient(api_key=api_key, provider=provider)  # Duplicates BaseAgent
        self.search_engine = HybridSearchEngine(...)  # Duplicates BaseAgent

    def _get_trained_prompt(self):
        # Duplicates BaseAgent._get_trained_prompt()
        return self.storage.get_agent_prompt(self.owner_id, 'my_agent')
```

### CORRECT: Inherit from BaseAgent

```python
# ✅ CORRECT - Uses inheritance, no duplication
from zylch.agents.base_agent import BaseAgent

class MyAgent(BaseAgent):
    PROMPT_KEY = 'my_agent'
    TOOLS = MY_AGENT_TOOLS

    def __init__(self, storage, owner_id, api_key, provider):
        super().__init__(storage, owner_id, api_key, provider)
        # Only add what's unique to this agent
        self.custom_client = CustomClient()
```

### WRONG: Standalone trainer that duplicates BaseAgentTrainer

```python
# ❌ WRONG - Missing inheritance, duplicates base class code
class MyAgentTrainer:
    def __init__(self, storage, owner_id, api_key, user_email, provider):
        self.storage = storage  # Duplicates BaseAgentTrainer
        self.owner_id = owner_id  # Duplicates BaseAgentTrainer
        self.client = LLMClient(...)  # Duplicates BaseAgentTrainer
        self.user_email = user_email  # Duplicates BaseAgentTrainer
```

### CORRECT: Inherit from BaseAgentTrainer

```python
# ✅ CORRECT - Uses inheritance, no duplication
from zylch.agents.base_trainer import BaseAgentTrainer

class MyAgentTrainer(BaseAgentTrainer):
    def __init__(self, storage, owner_id, api_key, user_email, provider):
        super().__init__(storage, owner_id, api_key, user_email, provider)
        # Only add what's unique to this trainer

    async def build_prompt(self) -> Tuple[str, Dict[str, Any]]:
        # Use inherited methods: _get_emails, _generate_prompt, etc.
        ...
```

## Summary: DRY Principle

| What | WRONG | CORRECT |
|------|-------|---------|
| Agent runner | `class MyAgent:` | `class MyAgent(BaseAgent):` |
| Agent trainer | `class MyTrainer:` | `class MyTrainer(BaseAgentTrainer):` |
| Init | Duplicate all fields | `super().__init__(...)` + only unique fields |
| Methods | Rewrite `_get_trained_prompt`, etc. | Use inherited methods |

## Thread-Based Email Fetching (Memory Agent Pattern)

When training agents from email data, use thread-based fetching to avoid context window overflow:

### Pattern

```python
class MyAgentTrainer(BaseAgentTrainer):
    def __init__(self, ...):
        super().__init__(...)
        self.search_limit = 20  # Limit threads to control prompt size

    def _get_recent_threads(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent threads, returning only the last email per thread.

        The last email contains quoted conversation history, so we only
        need that one to get full context.
        """
        # Fetch 3x limit to ensure enough threads
        emails = self.storage.get_emails(self.owner_id, limit=limit * 3)

        # Group by thread_id
        threads: Dict[str, List[Dict]] = {}
        for email in emails:
            tid = email.get('thread_id', email.get('id', ''))
            if tid:
                threads.setdefault(tid, []).append(email)

        # Sort threads by most recent
        thread_list = []
        for tid, thread_emails in threads.items():
            thread_emails.sort(key=lambda e: e.get('date_timestamp', 0))
            most_recent = max(e.get('date_timestamp', 0) for e in thread_emails)
            thread_list.append({
                'thread_id': tid,
                'emails': thread_emails,
                'most_recent': most_recent
            })

        thread_list.sort(key=lambda t: t['most_recent'], reverse=True)
        return thread_list[:limit]

    def _format_email_samples(self, threads: List[Dict]) -> str:
        """Format threads - only last email per thread."""
        samples = []
        for i, thread in enumerate(threads, 1):
            emails = thread.get('emails', [])
            if not emails:
                continue

            subject = emails[0].get('subject', '(no subject)')
            last_email = emails[-1]  # Last email has full thread context

            samples.append(f"""
--- Thread {i}: {subject} ({len(emails)} emails) ---
From: {last_email.get('from_email', 'unknown')}
Date: {last_email.get('date', 'unknown')}
Body: {last_email.get('body_plain', '')}
""")
        return '\n'.join(samples)
```

### Why Thread-Based?

1. **Avoids context overflow**: 100 emails = 200k+ tokens. 20 threads = manageable.
2. **Last email has history**: The last email in a thread contains quoted replies.
3. **Better signal**: One conversation = one training sample, not 10 duplicate samples.

### Prompt Size Logging

Always log prompt size before LLM call for debugging:

```python
logger.debug(f"Prompt size: {len(meta_prompt)} chars (~{len(meta_prompt)//4} tokens)")
```

### Metadata

Use `threads_analyzed` (not `emails_analyzed`) in metadata:

```python
metadata = {
    'generated_at': datetime.now(timezone.utc).isoformat(),
    'threads_analyzed': len(threads)  # Not emails_analyzed
}
```
