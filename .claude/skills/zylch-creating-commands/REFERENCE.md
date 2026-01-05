# Zylch Command Templates Reference

## Template 1: Inline (<500ms)

Use for fast operations: DB lookups, status checks, help text.

```python
async def handle_mycommand(args: List[str], config, owner_id: str) -> str:
    """Handle /mycommand - fast operation."""
    from zylch.storage.supabase_client import SupabaseStorage

    # Parse args
    if '--help' in args:
        return """**Usage:** `/mycommand [options]`"""

    storage = SupabaseStorage.get_instance()
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
        from zylch.storage.supabase_client import SupabaseStorage
        storage = SupabaseStorage.get_instance()
        return expensive_operation(storage)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, _blocking_work)

    return f"✅ Result: {result}"
```

## Template 3: Background Job (>5s)

Use for long operations: LLM batch processing, sync, imports.

```python
async def handle_mycommand(args: List[str], config, owner_id: str) -> str:
    """Handle /mycommand - long operation with background job."""
    from zylch.storage.supabase_client import SupabaseStorage
    from zylch.services.job_executor import JobExecutor
    from zylch.api.token_storage import get_active_llm_provider
    import asyncio

    # Parse args
    if '--help' in args:
        return """**Usage:** `/mycommand [options]`"""

    storage = SupabaseStorage.get_instance()

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

## Handler Signature

All command handlers must follow this signature:

```python
async def handle_commandname(
    args: List[str],     # Arguments after command name
    config,              # ToolConfig (rarely needed)
    owner_id: str        # Firebase UID
) -> str:                # Markdown response to user
```

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
