# Round 3: Incremental Task Prompt Generation

## Problem

The task agent requires a manual `/agent task train email` step
before task detection works at all. Without it, the post-sync
chain in `_chain_processing_after_sync()` skips task processing
and shows a notification asking the user to train. This is a UX
blocker: new users sync emails and get nothing.

## Design: Reconsolidation-Based Prompt Generation

Replace the manual training gate with automatic prompt
generation/update that runs as part of the post-sync chain.
The prompt is generated on first sync and incrementally updated
on subsequent syncs using a reconsolidation pattern (update
existing context, don't recreate from zero).

### Flow After This Change

```
sync completes
  -> _chain_processing_after_sync()
    -> memory processing (if trained, unchanged)
    -> _refresh_task_prompt()        # NEW STEP
      -> load existing prompt from agent_prompts (may be None)
      -> get user_email from oauth_tokens (not settings)
      -> get NEW emails only (since last prompt generation)
      -> if first time: full generation (~30s, ~20 threads)
      -> if update: incremental check (~5s, new emails only)
      -> if LLM says "no changes": skip save, use existing
      -> save updated prompt to agent_prompts
    -> _chain_task_processing()      # always proceeds now
      -> TaskWorker processes unprocessed emails
```

## Files to Modify

### 1. `zylch/agents/trainers/task_email.py`

**Current state:** `EmailTaskAgentTrainer.build_task_prompt()`
always does a full generation from scratch using the last 20
threads. The `TASK_AGENT_META_PROMPT` is a single monolithic
prompt that generates the entire task detection prompt.

**Changes:**

#### a) Add `TASK_AGENT_UPDATE_PROMPT` (new constant)

A shorter meta-prompt for incremental updates. Receives:
- The existing generated prompt (the one stored in
  `agent_prompts`)
- Only NEW emails since last prompt generation
- Instructions: "Update the prompt if these emails reveal
  new patterns. If no meaningful changes, respond with
  exactly `NO_CHANGES_NEEDED`."

```
TASK_AGENT_UPDATE_PROMPT = """You are reviewing new emails
to decide if a task detection prompt needs updating.

=== CURRENT PROMPT ===
{existing_prompt}

=== NEW EMAILS SINCE LAST UPDATE ({new_email_count}) ===
{new_threads}

=== NEW MEMORY BLOBS ===
{new_blobs}

Analyze the new emails. Does the existing prompt need
changes? Consider:
1. New contact patterns not captured
2. New ignore/noise patterns
3. Language shifts
4. New FAQ topics
5. Changed response timing patterns

If the prompt is still accurate, respond with exactly:
NO_CHANGES_NEEDED

If updates are needed, output the COMPLETE updated prompt
(not a diff). Include all existing patterns plus new ones.
OUTPUT ONLY THE PROMPT TEXT or NO_CHANGES_NEEDED."""
```

#### b) Add `build_task_prompt_incremental()` method

New method on `EmailTaskAgentTrainer`:

```python
async def build_task_prompt_incremental(
    self,
    existing_prompt: Optional[str],
    emails_since: Optional[datetime],
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Incrementally update task prompt.

    Args:
        existing_prompt: Current prompt (None = first time)
        emails_since: Only analyze emails after this time

    Returns:
        (new_prompt, metadata) or (None, metadata) if no
        changes needed.
    """
```

Logic:
- If `existing_prompt is None`: delegate to existing
  `build_task_prompt()` (full generation, first time).
- If `existing_prompt` is set:
  - Fetch only emails with `date_timestamp >` the
    `emails_since` value.
  - If zero new emails: return `(None, {"skipped":
    "no_new_emails"})`.
  - Format new emails (reuse `_format_threads()`).
  - Get blobs for new contacts only.
  - Call LLM with `TASK_AGENT_UPDATE_PROMPT`.
  - If response is `NO_CHANGES_NEEDED`: return
    `(None, {"skipped": "no_changes_needed"})`.
  - Otherwise: return `(updated_prompt, metadata)`.

#### c) Add `_get_recent_threads_since()` method

```python
def _get_recent_threads_since(
    self,
    since: datetime,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Get threads with emails newer than `since`."""
```

Uses `storage.get_emails_since(owner_id, since, limit)`
(new storage method, see below).

#### d) Derive `user_email` from `oauth_tokens`

Currently `get_my_emails()` in `task_creation.py` reads from
`settings.my_emails` (env var `MY_EMAILS`). This is a
hardcoded config value that doesn't work in multi-tenant.

The trainer already receives `user_email` as a constructor
param. The caller (`_refresh_task_prompt`) will resolve it
from `storage.get_user_email_from_token(owner_id)` which
reads `oauth_tokens.email` for Google/Microsoft tokens.

No change needed in the trainer itself; the change is in the
caller (job_executor).

### 2. `zylch/services/job_executor.py`

**Current state:** `_chain_processing_after_sync()` checks
`has_task_agent` and skips task processing if False.
`_chain_task_processing()` also gates on `has_task_agent`.

**Changes:**

#### a) Add `_refresh_task_prompt()` method

```python
async def _refresh_task_prompt(
    self,
    owner_id: str,
    api_key: str,
    llm_provider: str,
    user_email: str,
) -> bool:
    """Refresh task prompt before task processing.

    Returns True if a valid prompt exists after refresh.
    """
```

Logic:
1. Load existing prompt via
   `storage.get_agent_prompt(owner_id, 'task_email')`.
2. Load metadata via
   `storage.get_agent_prompt_metadata(owner_id,
   'task_email')` to get `updated_at` timestamp.
3. Resolve `user_email`: if empty, try
   `storage.get_user_email_from_token(owner_id)`.
4. If no `user_email` at all: log warning, return False
   (can't generate prompt without knowing user's email).
5. Create `EmailTaskAgentTrainer` instance.
6. Call `build_task_prompt_incremental(existing_prompt,
   emails_since=updated_at)`.
7. If result prompt is not None: save with
   `storage.store_agent_prompt(...)`.
8. Return True (prompt exists, either new or unchanged).

Runs in thread pool (same pattern as `_execute_task_train`).

#### b) Modify `_chain_processing_after_sync()`

Replace the `has_task_agent` gate. Instead of:

```python
has_task_agent = (
    storage.get_agent_prompt(owner_id, 'task_email')
    is not None
)
# ... skip if not has_task_agent
```

Change to:

```python
# Refresh/generate task prompt before processing
has_task_agent = await self._refresh_task_prompt(
    owner_id, api_key, llm_provider, user_email
)
if not has_task_agent:
    logger.info(
        f"[SYNC-CHAIN] Could not generate task prompt"
        f" for {owner_id} (no email configured?)"
    )
    return
```

Remove the notification telling user to run
`/agent task train email`.

#### c) Modify `_chain_task_processing()`

Same change: replace the `has_task_agent` check with a call
to `_refresh_task_prompt()` so task processing always has a
fresh prompt, even when called without prior memory step.

#### d) Modify `_execute_task_process()`

Remove the hard gate in `_sync_process()`:

```python
# REMOVE this block:
if not worker.has_task_prompt():
    raise ValueError(
        "No personalized task detection agent found. "
        "Run `/agent task train` first."
    )
```

Replace with prompt refresh call before creating the worker,
or let the worker handle missing prompt gracefully (generate
on the fly). The simplest approach: call
`_refresh_task_prompt()` before entering the thread pool.

### 3. `zylch/workers/task_creation.py`

**Current state:** `TaskWorker._get_task_prompt()` returns
None if no prompt exists, and `_analyze_recent_events()`
raises `ValueError` if no prompt. `has_task_prompt()` is
used as a gate by callers.

**Changes:**

#### a) Remove `get_my_emails()` function

This reads from `settings.my_emails` (global env var).
Replace all usages with `self.user_email` which is already
passed to the constructor and derived from oauth_tokens by
the caller.

In `_analyze_recent_events()`, replace:

```python
user_emails = get_my_emails()
```

With:

```python
user_emails = {self.user_email} if self.user_email else set()
```

And in `_is_user_email()`, remove the `get_my_emails()` call
in Check 2. The method already has Check 1 (exact match)
and Check 3 (domain match), which suffice when `user_email`
is correctly set from oauth_tokens.

#### b) Keep `has_task_prompt()` but change semantics

`has_task_prompt()` stays as a check, but callers no longer
use it as a hard gate. It's informational only (e.g., for
`/tasks --help` display).

### 4. `zylch/storage/storage.py`

**Changes:**

#### a) Add `get_emails_since()` method

```python
def get_emails_since(
    self,
    owner_id: str,
    since: datetime,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Get emails received after a given timestamp.

    Used by incremental prompt generation to only analyze
    new emails since last prompt update.
    """
```

Query: `Email.owner_id == owner_id AND
Email.date_timestamp > since.timestamp()`, ordered by
`date_timestamp DESC`, limited to `limit`.

Returns same dict format as `get_emails()`.

### 5. `zylch/services/command_handlers.py`

**Changes:**

#### a) Deprecate `/agent task train email`

Don't remove the command yet (backward compat), but change
its behavior:
- Instead of being required, it becomes a "force full
  regeneration" command.
- Update help text: "Forces a full regeneration of the task
  detection prompt. Normally this runs automatically after
  each sync."
- Remove all "Run `/agent task train email` first" messages
  throughout the file.

#### b) Update `/tasks` help text

Remove the "Setup" step mentioning training. The flow
becomes:
1. `/sync` - Fetch emails
2. `/tasks` - View actionable items

#### c) Clean up notifications

Remove the notification text:
```
"New emails synced but task detection is not configured.
Run `/agent task train email` to enable automatic task
creation."
```

## Implementation Order

1. **storage.py**: Add `get_emails_since()` method.
   Small, no dependencies. Can be tested independently.

2. **task_email.py**: Add `TASK_AGENT_UPDATE_PROMPT`,
   `build_task_prompt_incremental()`, and
   `_get_recent_threads_since()`. Depends on step 1.

3. **job_executor.py**: Add `_refresh_task_prompt()`,
   modify `_chain_processing_after_sync()`,
   `_chain_task_processing()`, `_execute_task_process()`.
   Depends on steps 1-2.

4. **task_creation.py**: Remove `get_my_emails()`,
   update `_analyze_recent_events()` and
   `_is_user_email()`. Independent of steps 1-3.

5. **command_handlers.py**: Update help texts and
   deprecate training command. Independent cleanup.

## Edge Cases

### First-time user (no prompt, no emails)
- `_refresh_task_prompt()` calls
  `build_task_prompt_incremental(None, None)`.
- This delegates to `build_task_prompt()` (full gen).
- If user has zero emails: `_get_recent_threads()` returns
  empty list. The meta-prompt gets "No threads available."
  The LLM still generates a generic prompt. This is fine;
  it will be updated on next sync when emails exist.

### First-time user with emails (first sync just completed)
- `existing_prompt` is None, so full generation runs.
- Uses all available emails (up to 20 threads).
- Takes ~30s. User sees "Processing..." notification.

### Subsequent sync, no new patterns
- `existing_prompt` exists, `emails_since` = last
  `updated_at`.
- Fetches only new emails since last update.
- LLM responds `NO_CHANGES_NEEDED` (~5s, minimal tokens).
- Prompt unchanged, task processing proceeds immediately.

### Subsequent sync, new patterns detected
- LLM generates updated prompt incorporating new patterns.
- ~10-15s. Saved to `agent_prompts`.

### No API key
- `_chain_processing_after_sync()` already checks for API
  key before calling `_refresh_task_prompt()`. No change
  needed for this path.

### No oauth_tokens (user hasn't connected email)
- `get_user_email_from_token()` returns None.
- `user_email` param may also be empty.
- `_refresh_task_prompt()` returns False, logs warning.
- Task processing skipped (correct: no email = no tasks).

### Concurrent syncs
- `create_background_job()` already prevents duplicate
  running jobs of the same type. The prompt refresh runs
  inside the sync chain, which is serialized per user.

## Metrics to Track

- `task_prompt_refresh_duration_seconds`: histogram of
  prompt refresh time (first-time vs incremental).
- `task_prompt_refresh_result`: counter with labels
  `{result=generated|updated|no_changes|skipped|error}`.
- Log all outcomes at INFO level for debugging.

## Risks

1. **LLM cost on every sync**: Incremental check uses
   ~500-1000 tokens input + ~50 tokens output when no
   changes needed. At $3/M input tokens (Claude), this is
   ~$0.003 per sync. Acceptable.

2. **Latency on first run**: ~30s for full generation.
   User sees a notification. Subsequent syncs add ~5s.
   Acceptable since sync itself takes 10-60s.

3. **Prompt quality regression**: The incremental update
   may produce lower quality than full regeneration.
   Mitigation: the `/agent task train email` command
   remains available for force-regeneration.

4. **Race condition**: If user manually runs
   `/agent task train email` while a sync-triggered
   refresh is running, two LLM calls compete. The last
   one to save wins. Both are valid prompts, so this is
   safe (not corrupting). Low probability.
