---
description: |
  JSON-RPC method surface between the Electron app (client) and the
  Python sidecar (server). Source of truth for method names, payload
  shapes, and notification streams. Updated whenever either side
  changes a method signature.
---

# IPC Contract — Engine ↔ App

Transport: line-delimited JSON-RPC over stdio. The main process spawns
the sidecar (`engine/zylch/rpc/server.py`) and bridges renderer calls
through `ipcMain.handle('rpc:call', method, params, timeout)`.

- **Server**: `engine/zylch/rpc/methods.py` (dispatch table, line ~1480) + per-domain modules (`email_actions.py`, `task_queries.py`).
- **Client**: `app/src/preload/index.ts` exposes `window.zylch.*` to the renderer; `app/src/main/` brokers stdio.
- **Owner identity**: every call resolves `owner_id` server-side from the active profile — the client never sends it.

This file is incomplete. It tracks methods that have been touched
recently or have non-obvious payload shape; older methods live in
code as the source of truth until they're touched.

## Conventions

- Method names use dot-namespacing: `<domain>.<verb>` (`tasks.complete`, `emails.archive`, `update.run`).
- Payloads are JSON objects. Optional params are documented with `?`.
- Notifications use `<method>.<event>` (`tasks.solve.event`, `update.run.progress`).
- Errors are returned as `{ ok: false, error: string }` for "expected" failures (task not found, validation) and as JSON-RPC `error` objects for unexpected exceptions.
- Owner-scoped calls do NOT carry `owner_id` — the server resolves it from the active profile lock.

## Methods

### `tasks.complete(task_id, note?)`

| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `task_id` | string | yes | TaskItem UUID |
| `note` | string \| null | no | Optional free-text closing reason. Stored on `task_items.close_note`. **Display-only — never injected into the task-detection prompt or any other LLM context.** Whitespace-only notes are stored as NULL. |

Returns `{ ok: boolean }`.

Auto-close paths (worker, reanalyze sweep, task_interactive) call this
with `note=None` so closing reasons are never fabricated by the LLM.

### `tasks.reopen(task_id)`

Returns `{ ok: boolean }`. Clears `completed_at` AND `close_note` so a
reopened task starts fresh.

### `tasks.list(include_completed?, include_skipped?, limit?)`

Returns an array of `TaskItem` dicts. Each row includes (when present):
- standard fields (id, owner_id, event_type, contact_email, …)
- `close_note: string | null`
- `pinned: boolean`
- `sources: { emails: string[], blobs: string[], calendar_events: string[], thread_id?: string | null }`

### `emails.search(query, folder?, limit?, offset?)`

| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `query` | string | yes | Gmail-style query (see below). Empty/whitespace returns the same result as `emails.list_inbox` (or `…list_sent`) for the requested folder. |
| `folder` | `"inbox" \| "sent" \| "all"` | no | Default `"inbox"`. Same coarse filter the listing endpoints use; `all` searches both directions. |
| `limit` | int | no | Default 50. |
| `offset` | int | no | Default 0. Pagination is over the matching thread list, not over messages. |

Returns `{ threads: InboxThread[] }` — same dict shape as
`emails.list_inbox` / `emails.list_sent`, so the renderer reuses the
existing thread row component.

**Operator language** (parsed by `engine/zylch/services/email_search.py`):

| Operator | Matches |
|----------|---------|
| `from:foo` | substring of `from_email` or `from_name` |
| `to:foo` | substring of `to_email` |
| `cc:foo` | substring of `cc_email` |
| `subject:foo` | substring of `subject` |
| `body:foo` | substring of `body_plain` |
| `has:attachment` (also `attach`/`attachments`/`file`) | `has_attachments == True` |
| `filename:foo` | substring inside any `attachment_filenames` entry |
| `is:unread` | `read_at IS NULL` and message is not user-sent |
| `is:read` | `read_at IS NOT NULL` |
| `is:pinned` | `pinned_at IS NOT NULL` |
| `is:auto` | `is_auto_reply == True` |
| `before:YYYY-MM-DD` / `after:YYYY-MM-DD` | UTC date comparison |
| `older_than:Nd|w|m|y` / `newer_than:…` | relative cutoff against `date` |
| bare term | substring of subject / body / snippet / from |

Quote phrases with `"…"`. Prefix any predicate with `-` to negate.
Multiple predicates of the same operator OR together (Gmail-style);
different operators AND. Unknown `key:value` pairs degrade silently
to free-text terms — searches never fail because of a typo'd
operator.

A thread is included if **any** of its non-archived/non-deleted
messages matches; the thread summary still reflects the latest
message of the thread (not the matching one), mirroring
`list_inbox_threads`.

### `account.balance()`

Forwards to `mrcall-agent`'s `GET /api/desktop/llm/balance` with the
cached Firebase ID token (`auth: <jwt>` header). Returns the proxy's
payload verbatim — server is the source of truth for the response shape:

```jsonc
{
  "balance_credits": 123,         // integer credits remaining (1 credit = €0.01)
  "balance_micro_usd": 1500000,   // wallet-side µUSD ledger value
  "balance_usd": 1.5,             // convenience float
  "granularity_micro_usd": 11000, // µUSD per credit unit (markup × value)
  "estimate_messages_remaining": 80
}
```

Errors:
- No Firebase session → JSON-RPC error code `-32010` (`NoActiveSession`).
- 401 from the proxy → `{ "error": "auth_expired" }` (renderer should
  trigger a Firebase token refresh and call again).
- Other transport / 5xx → JSON-RPC error.

Used by the `LLMProviderCard` in `views/Settings.tsx` (BYOK ↔ MrCall
credits toggle) on mount and on every window `focus` event so a top-up
done in another tab is reflected when the user returns. Preload binding
at `app/src/preload/index.ts` has a 15 s timeout.

### `tasks.solve(task_id, instructions?)`

Agentic loop on a single task. Builds the SOLVE_SYSTEM_PROMPT with
the task's `build_task_context` (original email, memory blobs,
personal data section, language directive), then runs
`TaskExecutor` for up to 10 turns of LLM + tool use. Approval-gated
tools (`send_email`, `send_whatsapp`, `send_sms`, `update_memory`,
`run_python`) emit `tasks.solve.event` notifications of type
`tool_call_pending` and pause until the renderer calls
`tasks.solve.approve`. Read-only tools auto-execute and emit
`tool_use_start` + `tool_result` events.

| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `task_id` | string | yes | Must reference an OPEN task. `get_task_items` here does NOT pass `include_completed=True` — solve is for active work; closed tasks return `{ok: false, error: "task not found"}`. |
| `instructions` | string | no | Optional extra user instructions appended to the LLM's user-message context. The renderer currently passes empty string. |

Returns `{ok: boolean, result?: {messages: list, cancelled?: boolean}, error?: string}` after the run completes / errors / is cancelled.

**Concurrency**: `asyncio.Lock` engine-side — a second `tasks.solve`
call while one is active raises `SolveInProgressError` (custom code).
Renderer guards by not firing solve when busy.

**10-minute timeout** on the renderer side
(`app/src/main/index.ts:'tasks.solve'`), matching the executor's
`max_turns=10`.

### `tasks.solve.approve(tool_use_id, approved, edited_input?)`

Resolves a pending approval future inside the active solve. The
renderer's approval card in `Workspace.tsx` calls this when the
user clicks the primary button ("Invia email" / "Invia WhatsApp" /
…). The "Annulla" button instead calls `tasks.solve.cancel` —
declining with `approved=false` would cause the engine to feed
"User declined this action." back to the LLM, which then proposes
alternatives.

Returns `{ok: boolean}`. `ok=false` only when no solve is active or
the `tool_use_id` doesn't match a pending future.

### `tasks.solve.cancel()`

Aborts the active solve, if any. Sets `asyncio.CancelledError` on
every pending approval future; the executor catches it inside
`TaskExecutor.run()` and emits a clean `done` event (with
`result.cancelled: True`) — NOT an `error` event, so the renderer
doesn't show a `⚠` bubble on user-initiated abort.

Returns `{ok: boolean, cancelled_pending?: number, error?: string}`.
Best-effort: if no futures are pending (the LLM is mid-call), the
cancel only takes effect when the LLM call returns and the loop
hits the next `await fut`. The 10-minute RPC timeout is the
final backstop.

### `tasks.solve.event` (notification stream)

Emitted by the engine throughout the lifetime of a `tasks.solve`
call. The renderer's listener in `Workspace.tsx` consumes this
stream into chat bubbles + narration + approval card. Engine
guarantees one solve at a time, so events route to whichever
conversation is active at the moment.

Event union (see `app/src/renderer/src/types.ts:SolveEvent`):

```jsonc
// Model produced a text block (between tool calls or final answer)
{ "type": "thinking", "text": string }

// Read-only or approval-gated tool is about to run. UI hint to swap
// "Sto pensando…" for "Sto cercando nella memoria…" etc.
{ "type": "tool_use_start", "tool_use_id": string, "name": string }

// Approval-gated tool reached, executor paused on
// _pending[tool_use_id] future. UI must render an approval card
// and respond via tasks.solve.approve OR tasks.solve.cancel.
{
  "type": "tool_call_pending",
  "tool_use_id": string,
  "name": string,
  "input": object,
  "preview": string   // human-readable, from format_approval_preview()
}

// Tool finished. Currently not rendered as a chat bubble — the
// model's next `thinking` block is what the user reads. The
// renderer DOES clear the narration on this event so the stale
// "Sto cercando…" line doesn't outlast the actual operation.
{
  "type": "tool_result",
  "tool_use_id": string,
  "name": string,
  "output": string,
  "approved": boolean
}

// Clean completion (incl. user-cancelled).
{ "type": "done", "result": { "messages": list, "cancelled"?: boolean } }

// Unexpected exception in run(). CancelledError does NOT come
// through here — it's caught and emitted as `done` with
// `result.cancelled: True`.
{ "type": "error", "message": string }
```

### `tasks.topic_dedup_now()`

Manual trigger for the F9 cross-contact topic dedup sweep. Same
worker that runs automatically inside `update.run`; this RPC exists
so a Settings button ("Pulizia profonda") can fire it on demand.

Returns the worker summary verbatim:

```jsonc
{
  "examined": 30,                    // active open tasks sent to the LLM
  "clusters_with_dups": 2,           // clusters of size >= 2 the model returned
  "tasks_closed": 4,
  "skipped_recently_reopened": 0,    // dedup_skip_until in the future
  "skipped_too_few_tasks": false,    // < MIN_TASKS_FOR_TOPIC_DEDUP=4
  "skipped_too_many_tasks": false,   // > MAX_TASKS_FOR_TOPIC_DEDUP=120
  "no_llm": false                    // true if no Anthropic key + no Firebase session
}
```

Idempotent: a second call right after the first returns
`clusters_with_dups: 0, tasks_closed: 0`. One Opus 4.6 call per
invocation (~$0.30 list price on a 50-task profile).

The companion F8 endpoint `tasks.dedup_now()` (same-contact /
blob-overlap deterministic dedup) remains. Both are exposed; the
"Pulizia profonda" button could call either or both. F9 is the one
that catches the cross-channel "ONE problem from 3 senders" case.

### Other methods

For the rest of the surface (emails.\*, chat.\*, update.\*, settings.\*,
profile.\*, files.\*, narration.\*, etc.) see:
- `app/src/preload/index.ts` — typed client signatures
- `app/src/renderer/src/types.ts` — `ZylchAPI` interface
- `engine/zylch/rpc/methods.py` — server dispatch table

These are the source of truth. This document tracks recent additions
and deltas; bringing the full surface into this file is a separate
documentation push.

## Out of scope: renderer-only IPCs

A separate set of IPC channels run entirely in the Electron main
process and never reach the Python sidecar. They are NOT part of this
contract and live only in `app/src/preload/index.ts` /
`app/src/renderer/src/types.ts`. As of 2026-05-02:

- Profile / window: `profile:current`, `profiles:list`,
  `window:openForProfile`, `sidecar:restart`.
- Onboarding: `onboarding:isFirstRun`, `onboarding:createProfile`,
  `onboarding:createProfileForFirebaseUser`, `onboarding:finalize`.
- Identity (Firebase signin): `signin:googleStart`,
  `signin:googleCancel`, `auth:bindProfile`.
- Filesystem dialogs / shell: `dialog:selectFiles`,
  `dialog:selectDirectories`, `shell:openExternal`.

Don't document them here — add new entries to `app/docs/active-context.md`
under "IPC client (preload)" instead.
