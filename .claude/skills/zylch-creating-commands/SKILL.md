---
name: creating-zylch-commands
description: Guide for creating new Zylch slash commands (/sync, /agent, etc.) with proper async patterns. Use when creating a new Zylch command, adding a /command handler, or implementing command handlers in zylch/services/command_handlers.py.
---

# Creating Zylch Commands

## 🚨 CRITICAL: Handler Signature

**ALL command handlers MUST use this exact signature:**

```python
async def handle_commandname(args: List[str], config, owner_id: str) -> str:
```

**Parameters (in order):**
1. `args: List[str]` - Arguments after command name
2. `config` - ToolConfig (rarely used, but required)
3. `owner_id: str` - User identity (EMAIL_ADDRESS)

**Returns:** Markdown string shown to user

❌ **WRONG signatures that will cause runtime errors:**
```python
async def handle_cmd(args):                    # Missing config, owner_id
async def handle_cmd(args: List[str]):         # Missing config, owner_id
async def handle_cmd(args: List[str] = None):  # Missing config, owner_id
```

---

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
- `zylch/storage/storage.py` - `create_background_job()`, `Storage.get_instance()`
- `zylch/api/token_storage.py` - `get_active_llm_provider(owner_id)`, `get_mrcall_credentials(owner_id)`
- `zylch/tools/starchat.py` - StarChat/MrCall channel client

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

## CRITICAL: Command Dispatch Registration

⚠️ **You MUST also update `chat_service.py`!** When a command is added to `COMMAND_HANDLERS`, it must ALSO be added to the dispatch logic in `chat_service.py` (lines 268-295). Otherwise it falls through to the default case which calls `handler()` with NO arguments, causing:

```
TypeError: handle_xxx() missing N required positional arguments
```

### Dispatch Branches by Signature

| Handler Signature | Add to Branch |
|-------------------|---------------|
| `(args, owner_id)` | `elif cmd in ['/stats', '/jobs', '/reset', '/tutorial']:` |
| `(args, config, owner_id)` | `elif cmd in ['/memory', '/email', '/train', '/agent']:` |
| `(args, owner_id, user_email)` | `elif cmd in ['/mrcall', '/connect']:` |
| `(args)` or `()` | `elif cmd in ['/model', '/help', '/clear', '/echo']:` |

### Example: Adding `/mycommand` with signature `(args, owner_id)`

```python
# In chat_service.py line 283-285:
elif cmd in ['/stats', '/jobs', '/reset', '/tutorial', '/mycommand']:  # ADD HERE
    # These need args and owner_id
    response_text = await handler(args, owner_id)
```

### Checklist for New Commands

1. [ ] Write handler function in `command_handlers.py`
2. [ ] Add to `COMMAND_HANDLERS` dict
3. [ ] Add to `COMMAND_PATTERNS` dict (for semantic matching)
4. [ ] **Add to dispatch branch in `chat_service.py`** ← Don't forget!
5. [ ] Update inline `help_text`
6. [ ] Update `COMMAND_REGISTRY` dict
7. [ ] Update `docs/guides/cli-commands.md`

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
