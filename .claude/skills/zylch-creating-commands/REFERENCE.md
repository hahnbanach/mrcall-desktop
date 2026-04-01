# Zylch Command Templates Reference

## Template 1: Inline (<500ms)

Use for fast operations: DB lookups, status checks, help text.

```python
async def handle_mycommand(args: List[str], config, owner_id: str) -> str:
    """Handle /mycommand - fast operation."""
    from zylch.storage import Storage

    # Parse args
    if '--help' in args:
        return """**Usage:** `/mycommand [options]`"""

    storage = Storage.get_instance()
    result = storage.get_something(owner_id)

    return f"✅ Result: {result}"
```

## Template 2: run_in_executor (500ms-5s)

Use for medium operations where user waits for result.

```python
async def handle_mycommand(args: List[str], config, owner_id: str) -> str:
    """Handle /mycommand - medium operation."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    executor = ThreadPoolExecutor(max_workers=4)

    def _blocking_work():
        # All sync/blocking code goes here
        # This runs in a separate thread, not blocking the event loop
        from zylch.storage import Storage
        storage = Storage.get_instance()
        return expensive_operation(storage)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, _blocking_work)

    return f"✅ Result: {result}"
```

⚠️ **CRITICAL: Executor Function Import Rule**

When using `run_in_executor`, ALL external dependencies must be imported **INSIDE** the executor function, not in the outer scope. This is because:

1. The function runs in a separate thread
2. Closure captures variables (like `owner_id`) but NOT module-level class names
3. Class references from outer scope cause `NameError`

**Always do this:**
```python
def _blocking_work():
    from zylch.storage import Storage  # ✅ Inside
    from zylch.api.token_storage import get_mrcall_credentials  # ✅ Inside
    storage = Storage.get_instance()
```

**Never do this:**
```python
async def handle_xxx(...):
    from zylch.storage import Storage  # ❌ Outside

    def _blocking_work():
        storage = Storage.get_instance()  # NameError!
```

## Template 3: Background Job (>5s)

Use for long operations: LLM batch processing, sync, imports.

```python
async def handle_mycommand(args: List[str], config, owner_id: str) -> str:
    """Handle /mycommand - long operation with background job."""
    from zylch.storage import Storage
    from zylch.services.job_executor import JobExecutor
    from zylch.api.token_storage import get_active_llm_provider
    import asyncio

    # Parse args
    if '--help' in args:
        return """**Usage:** `/mycommand [options]`"""

    storage = Storage.get_instance()

    # Get LLM credentials if command needs LLM
    llm_provider, api_key = get_active_llm_provider(owner_id)
    if not api_key:
        return "❌ Configure LLM provider first with `/connect anthropic`"

    # Create job (returns existing if duplicate pending/running)
    job = storage.create_background_job(
        owner_id=owner_id,
        job_type="mycommand",  # Must match JobExecutor dispatch
        channel=None           # Or "email", "calendar", "all"
    )

    if job["status"] == "running":
        return f"""⏳ **Already running**

Job ID: `{job['id']}`
Progress: {job.get('progress_pct', 0)}%"""

    if job["status"] == "pending":
        # Schedule execution in background
        executor = JobExecutor(storage)
        asyncio.create_task(executor.execute_job(
            job["id"],
            owner_id,
            api_key,
            llm_provider
        ))

        return f"""🚀 **Started in background**

Job ID: `{job['id']}`

You'll be notified when complete."""

    return f"Job status: {job['status']}"
```

## Adding New Job Type to JobExecutor

When creating a background job command, add the handler in `job_executor.py`:

### Step 1: Add dispatch in execute_job()

```python
async def execute_job(self, job_id, owner_id, api_key, llm_provider, user_email=""):
    # ... existing code ...

    # Add new job type to dispatch
    elif job_type == "mycommand":
        await self._execute_mycommand(job_id, owner_id, api_key, llm_provider)
```

### Step 2: Implement the handler

```python
async def _execute_mycommand(
    self,
    job_id: str,
    owner_id: str,
    api_key: str,
    llm_provider: str
) -> None:
    """Execute mycommand in thread pool."""
    storage = self.storage

    def _sync_process() -> Dict[str, Any]:
        """Sync code that runs in thread pool."""
        # All blocking code here - OK because runs in thread

        # Update progress periodically
        storage.update_background_job_progress(
            job_id, 50, 5, 10, "Processing item 5/10..."
        )

        # Do the work...
        result = do_expensive_work()

        return {"processed": 10, "result": result}

    # Execute in thread pool
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, _sync_process)

    # Complete job and notify
    self.storage.complete_background_job(job_id, result)
    self.storage.create_notification(
        owner_id,
        f"Command complete: {result['processed']} items processed",
        "info"
    )
```

## Handler Signatures

Command handlers use different signatures based on their needs:

### Standard Signature (most commands)
```python
async def handle_commandname(
    args: List[str],     # Arguments after command name
    owner_id: str        # Firebase UID
) -> str:                # Markdown response to user
```

### With Config (LLM/BYOK operations)
```python
async def handle_commandname(
    args: List[str],     # Arguments after command name
    config,              # ToolConfig with LLM credentials
    owner_id: str        # Firebase UID
) -> str:                # Markdown response to user
```

### With User Email (sharing/integration operations)
```python
async def handle_commandname(
    args: List[str],     # Arguments after command name
    owner_id: str,       # Firebase UID
    user_email: str      # User's email address
) -> str:                # Markdown response to user
```

**Choose signature based on what your command needs:**
- Most commands → `(args, owner_id)`
- LLM calls needed → `(args, config, owner_id)`
- User email needed → `(args, owner_id, user_email)`

## Common Patterns

### Subcommands

```python
async def handle_mycommand(args: List[str], config, owner_id: str) -> str:
    positional = [a for a in args if not a.startswith('--')]
    subcommand = positional[0].lower() if positional else None

    if subcommand == 'status':
        return await _handle_status(owner_id)
    elif subcommand == 'reset':
        return await _handle_reset(owner_id)
    else:
        # Default action
        return await _handle_default(args, owner_id)
```

### Option Parsing

```python
# Parse --days option
days_back = 30
for i, arg in enumerate(args):
    if arg == '--days' and i + 1 < len(args):
        try:
            days_back = int(args[i + 1])
        except ValueError:
            return f"❌ Invalid number: {args[i + 1]}"
        break
```

### Error Handling

```python
try:
    result = await do_operation()
    return f"✅ Success: {result}"
except Exception as e:
    logger.error(f"Command failed: {e}")
    return f"❌ **Error:** {str(e)}"
```

---

## Help Text Updates (CRITICAL)

When creating/modifying a command, update help in **TWO places**:

### 1. Inline help_text in handler

```python
async def handle_mycommand(args: List[str], config, owner_id: str) -> str:
    """Handle /mycommand."""

    help_text = """**📋 My Command**

**Commands:**
• `/mycommand action` - Do something
• `/mycommand status` - Check status

**Examples:**
• `/mycommand action "some input"`"""

    if '--help' in args:
        return help_text

    # ... rest of handler
```

### 2. COMMAND_REGISTRY dict (bottom of command_handlers.py, ~line 2100+)

```python
COMMAND_REGISTRY = {
    # ... existing commands ...
    '/mycommand': {
        'summary': 'Short description for /help listing',
        'usage': '/mycommand [action|status]',
        'description': '''Detailed description shown by `/mycommand --help`.

**Subcommands:**
- `action` - Do something
- `status` - Check status

**Examples:**
- `/mycommand action "input"` - Example usage''',
    },
}
```

---

## Adding Subcommands to Existing Commands

When adding a subcommand (like `config` to `/mrcall`):

```python
async def handle_existingcommand(args: List[str], owner_id: str, ...) -> str:
    # Parse positional args (exclude --options)
    positional = [a for a in args if not a.startswith('--')]
    subcommand = positional[0].lower() if positional else None

    # ... existing subcommands ...

    # NEW: Add your subcommand
    if subcommand == 'newaction':
        # Get remaining args after subcommand
        feature = positional[1] if len(positional) > 1 else None
        content = ' '.join(positional[2:])  # Multi-line content from quotes

        # Validate
        if not feature:
            return "❌ Missing feature\n\nUsage: `/command newaction <feature>`"

        # ... implementation ...

        return f"✅ Done: {feature}"
```

**Don't forget to update:**
1. The `help_text` variable at the top of the handler
2. The `COMMAND_REGISTRY` entry at the bottom of command_handlers.py

---

## Complete Registration Checklist

⚠️ **CRITICAL**: Missing any step will cause runtime errors!

When adding a new command, complete ALL steps:

### Step 1: Write the handler function
```python
async def handle_mycommand(args: List[str], owner_id: str) -> str:
    """Handle /mycommand."""
    # ... implementation
```

### Step 2: Add to COMMAND_HANDLERS dict
```python
# In command_handlers.py:
COMMAND_HANDLERS = {
    # ... existing ...
    '/mycommand': handle_mycommand,
}
```

### Step 3: Add to COMMAND_PATTERNS dict (for semantic matching)
```python
# In command_handlers.py:
COMMAND_PATTERNS = {
    # ... existing ...
    '/mycommand': ["mycommand", "do my thing", "trigger phrases"],
}
```

### Step 4: Add to chat_service.py dispatch (CRITICAL!)

The command dispatch in `chat_service.py` (lines 268-295) has explicit branches for different handler signatures. **New commands MUST be added to the correct branch or they will fail at runtime!**

```python
# In chat_service.py, find the branch matching your signature:

# For (args, owner_id) signature:
elif cmd in ['/stats', '/jobs', '/reset', '/tutorial', '/mycommand']:  # ADD HERE
    response_text = await handler(args, owner_id)

# For (args, config, owner_id) signature:
elif cmd in ['/memory', '/email', '/train', '/agent', '/mycommand']:  # ADD HERE
    config = ToolConfig.from_settings_with_owner(owner_id)
    response_text = await handler(args, config, owner_id)

# For (args, owner_id, user_email) signature:
elif cmd in ['/mrcall', '/share', '/revoke', '/connect', '/mycommand']:  # ADD HERE
    response_text = await handler(args, owner_id, user_email)
```

⚠️ **If you forget this step**, the command falls through to the default case which calls `handler()` with NO arguments, causing:
```
TypeError: handle_xxx() missing N required positional arguments
```

### Step 5: Update help text
1. Inline `help_text` variable in handler
2. `COMMAND_REGISTRY` dict

### Step 6: Update documentation
- `docs/guides/cli-commands.md`

---

## Multi-Line Input Handling

`shlex.split()` in `chat_service.py` (line ~228) preserves quoted content:

```python
# User input: /memory store "line 1
# line 2
# line 3"
#
# args = ['store', 'line 1\nline 2\nline 3']

# Join args after subcommand for multi-line content:
content = ' '.join(positional[2:])
```

Triple quotes (`"""..."""`) and regular quotes (`"..."`) both work.

---

## Template: run_in_executor with Async Calls

When blocking work includes async calls, create a new event loop in the thread:

```python
async def handle_mycommand(args: List[str], config, owner_id: str) -> str:
    """Handle /mycommand - uses async APIs in executor."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from zylch.tools.starchat import create_starchat_client

    def _blocking_work():
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Async calls inside sync function
            client = loop.run_until_complete(create_starchat_client(owner_id))
            result = loop.run_until_complete(client.get_something())
            loop.run_until_complete(client.close())
            return result, None
        except Exception as e:
            return None, str(e)
        finally:
            loop.close()

    executor = ThreadPoolExecutor(max_workers=1)
    loop = asyncio.get_event_loop()

    try:
        result, error = await loop.run_in_executor(executor, _blocking_work)

        if error:
            # Check for auth errors
            if any(code in error for code in ["405", "401", "403"]):
                return "❌ **Connection expired**\n\nRun `/connect mrcall` to reconnect."
            return f"❌ **Error:** {error}"

        return f"✅ Result: {result}"
    except Exception as e:
        return f"❌ **Error:** {str(e)}"
```

---

## LLM Helper Patterns

For commands that need LLM:

```python
from zylch.api.token_storage import get_active_llm_provider
from zylch.tools.mrcall.llm_helper import modify_prompt_with_llm

# Get user's LLM credentials (BYOK - Bring Your Own Key)
llm_provider, api_key = get_active_llm_provider(owner_id)
if not api_key:
    return "❌ **No LLM configured**\n\nRun `/connect anthropic` first."

# Call LLM to modify a prompt (preserves %%...%% variables)
new_value, validation = await modify_prompt_with_llm(
    current_prompt=current_value,
    user_request=instructions,
    api_key=api_key,
    provider=llm_provider,
)

# Check for validation errors
if validation.get("error"):
    return f"❌ **LLM error:** {validation['error']}"
```

---

## External API Patterns (StarChat/MrCall)

```python
from zylch.api.token_storage import get_mrcall_credentials
from zylch.tools.starchat import create_starchat_client

# Get OAuth credentials
creds = get_mrcall_credentials(owner_id)
if not creds or not creds.get('access_token'):
    return "❌ **MrCall not connected**\n\nRun `/connect mrcall` first."

business_id = creds.get('business_id')
if not business_id:
    return "❌ **No assistant linked**\n\nRun `/mrcall list` then `/mrcall link N`."

# Create client (async)
starchat = await create_starchat_client(owner_id)

try:
    # Use client
    business = await starchat.get_business_config(business_id)
    await starchat.update_business_variable(business_id, var_name, new_value)
finally:
    # Always close
    await starchat.close()
```

---

## Auth Error Handling Pattern

Always check for auth errors and suggest reconnection:

```python
try:
    result = await starchat.do_something()
except Exception as e:
    error_str = str(e)
    # Detect various auth error codes
    if any(code in error_str for code in ["405", "401", "403", "Unauthorized", "Forbidden"]):
        return "❌ **Connection expired**\n\nRun `/connect mrcall` to reconnect."
    return f"❌ **Error:** {error_str}"
```
