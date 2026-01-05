---
name: creating-zylch-commands
description: Guide for creating new Zylch slash commands (/sync, /agent, etc.) with proper async patterns. Use when creating a new Zylch command, adding a /command handler, or implementing command handlers in zylch/services/command_handlers.py.
---

# Creating Zylch Commands

## Decision Tree

```
New command needed
    │
    ▼
Duration > 5 seconds? ──Yes──► Background Job
    │                          (fire-and-forget, notification)
    No
    │
    ▼
Duration > 500ms? ──Yes──► run_in_executor
    │                      (non-blocking, wait for result)
    No
    │
    ▼
Inline (sync OK)
```

## Pattern Selection

| Duration | Pattern | Example Commands |
|----------|---------|------------------|
| <500ms | Inline | `/stats`, `/help`, `/memory search` |
| 500ms-5s | `run_in_executor` | `/mrcall train`, single LLM call |
| 5-10s | `run_in_executor` | `/mrcall config` (LLM + API + LLM) |
| >10s | Background Job | `/sync`, `/agent process` |

## Key Files

- `zylch/services/command_handlers.py` - All command handlers
- `zylch/services/job_executor.py` - Background job execution
- `zylch/storage/supabase_client.py` - `create_background_job()`, `SupabaseStorage.get_instance()`
- `zylch/api/token_storage.py` - `get_active_llm_provider(owner_id)`, `get_mrcall_credentials(owner_id)`
- `zylch/tools/mrcall/llm_helper.py` - `modify_prompt_with_llm()` for LLM-based modifications
- `zylch/tools/starchat.py` - `create_starchat_client()` for MrCall API

## CRITICAL: Help Text Updates

When creating/modifying a command, update help in **TWO places**:

1. **Inline `help_text`** at top of handler function
2. **`COMMAND_REGISTRY`** dict at bottom of command_handlers.py (~line 2100+)

See [REFERENCE.md](REFERENCE.md) for templates.

## Critical: Async Chain Rule

If using async SDK, the ENTIRE chain must be async. Mixing sync calls in async functions blocks the event loop:

```python
# ❌ WRONG - blocks event loop
async def handler():
    result = await async_llm_call()
    data = sync_db_query(result)  # BLOCKS OTHER USERS!

# ✅ CORRECT - fully async OR use run_in_executor
async def handler():
    result = await async_llm_call()
    data = await async_db_query(result)
```

## Registration

Add handler to `COMMAND_HANDLERS` dict in `command_handlers.py`:

```python
COMMAND_HANDLERS = {
    # ... existing ...
    '/mycommand': handle_mycommand,
}
```

## Background Jobs

For commands >10 seconds, use the job system:

1. Create job with `storage.create_background_job(owner_id, job_type, channel)`
2. Return immediately with job ID
3. Execute in `JobExecutor` (runs in thread pool)
4. Notify user via `storage.create_notification(owner_id, message, "info")`

User sees:
```
🚀 **Command started in background**
Job ID: `abc123`
You'll be notified when complete.
```

## Auth Error Handling

Always detect auth errors and suggest reconnection:

```python
except Exception as e:
    error_str = str(e)
    if any(code in error_str for code in ["405", "401", "403", "Unauthorized", "Forbidden"]):
        return "❌ **Connection expired**\n\nRun `/connect mrcall` to reconnect."
    return f"❌ **Error:** {error_str}"
```

## Templates

See [REFERENCE.md](REFERENCE.md) for complete code templates:
- Inline command template (<500ms)
- run_in_executor template (500ms-5s)
- run_in_executor with async calls (new event loop pattern)
- Background job template (>10s)
- Adding new job types to JobExecutor
- Adding subcommands to existing commands
- Multi-line input handling
- LLM helper patterns
- External API patterns (StarChat/MrCall)
