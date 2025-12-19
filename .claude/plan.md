# Plan: `/agent train email` Command

## Overview

Create a command that **learns from the user's email history** to generate a personalized agent for entity extraction. Instead of hardcoded rules, the system analyzes:
- Who the user actually replies to
- What topics they engage with
- What they ignore (cold outreach patterns unique to them)
- Their role, business context, and priorities

The generated agent is stored in the DB and used by `memory_worker.py` when processing emails.

---

## Implementation (Completed)

### 1. Database Table for Agents

**File:** `zylch/storage/migrations/007_rename_user_prompts_to_agent_prompts.sql`

```sql
-- Table: agent_prompts
-- Columns: id, owner_id, agent_type, agent_prompt, metadata, created_at, updated_at
-- Unique constraint on (owner_id, agent_type)
```

### 2. Supabase Storage Methods

**File:** `zylch/storage/supabase_client.py`

Methods:
- `get_agent_prompt(owner_id, agent_type) -> Optional[str]`
- `store_agent_prompt(owner_id, agent_type, prompt, metadata) -> Dict`
- `delete_agent_prompt(owner_id, agent_type) -> bool`
- `get_agent_prompt_metadata(owner_id, agent_type) -> Optional[Dict]`

### 3. Email Agent Builder

**File:** `zylch/services/email_agent_builder.py`

```python
class EmailAgentBuilder:
    """Builds personalized email agent by analyzing user's email patterns."""

    async def build_memory_email_prompt(self) -> Tuple[str, Dict]:
        """Analyze user's emails and generate personalized extraction agent."""
```

Uses `EMAIL_AGENT_META_PROMPT` to generate agent that extracts entities in `#Identifiers` / `#About` format.

### 4. Command Handler

**File:** `zylch/services/command_handlers.py`

Commands:
- `/agent train email` - Analyze emails and create personalized extraction agent
- `/agent show email` - Display current agent
- `/agent reset email` - Delete custom agent

### 5. Memory Worker Integration

**File:** `zylch/workers/memory_worker.py`

- Loads agent from `agent_prompts` table via `storage.get_agent_prompt(owner_id, 'email')`
- Falls back to no extraction if no agent configured (gate)
- Outputs `SKIP` for irrelevant emails

---

## Testing Plan

1. **No emails synced:** `/agent train email` → Error message
2. **Few emails:** `/agent train email` → Error, suggest more sync
3. **Sufficient emails:** Generate agent, store in DB, confirm success
4. **Show agent:** `/agent show email` → Display stored agent
5. **Memory process without agent:** Show warning/gate
6. **Memory process with agent:** Use personalized agent for extraction
7. **Reset:** `/agent reset email` → Delete, confirm
