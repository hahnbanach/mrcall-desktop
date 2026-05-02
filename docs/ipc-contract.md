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

### Other methods

For the rest of the surface (emails.\*, chat.\*, update.\*, settings.\*,
profile.\*, files.\*, narration.\*, etc.) see:
- `app/src/preload/index.ts` — typed client signatures
- `app/src/renderer/src/types.ts` — `ZylchAPI` interface
- `engine/zylch/rpc/methods.py` — server dispatch table

These are the source of truth. This document tracks recent additions
and deltas; bringing the full surface into this file is a separate
documentation push.
