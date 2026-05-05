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
