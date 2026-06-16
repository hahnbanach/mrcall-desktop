---
description: |
  JSON-RPC method surface between the Electron app (client) and the
  Python sidecar (server). Source of truth for method names, payload
  shapes, and notification streams. Updated whenever either side
  changes a method signature.
---

# IPC Contract — Engine ↔ App

Transport: JSON-RPC 2.0, transport-agnostic on the engine side
(`engine/zylch/rpc/dispatch.py` parses one frame and routes it; the
read/write of bytes is the adapter's job). Two adapters:

- **Local (default)** — line-delimited over stdio. Main spawns the sidecar
  (`engine/zylch/rpc/server.py`) and bridges renderer calls through
  `ipcMain.handle('rpc:call', method, params, timeout)`. Client:
  `app/src/main/sidecar.ts` (`StdioRpcClient`).
- **Remote (cross-machine, Phase 2)** — one JSON object per WebSocket TEXT
  message, against an engine running `zylch -p <uid> serve --ws HOST:PORT`
  (loopback + SSH tunnel) or `serve --unix /run/mrcalld/<uid>.sock` — the
  production multi-profile deploy, where Caddy routes `/ws/<uid>` to the per-uid
  socket (see [`remote-backend.md`](remote-backend.md))
  (`engine/zylch/rpc/server_ws.py`). The upgrade carries `Authorization:
  Bearer <firebaseIdToken>`; the engine verifies it (RS256) and gates
  `token.sub == profile OWNER_ID`, rejecting with HTTP **401** (no/invalid
  token) or **403** (valid token, wrong owner). Token renewal via
  `auth.refresh`; expiry closes the socket with code **4401**. Client:
  `app/src/main/wsRpcClient.ts` (`WebSocketRpcClient`). The two clients
  share the `RpcClient` interface (`app/src/main/rpcClient.ts`) so main is
  transport-agnostic; the choice is per-installation
  (`~/.zylch/backend-config.json`).

The method surface, payload shapes, and notification streams below are
**identical across both transports** — only the framing differs.

- **Server**: `engine/zylch/rpc/methods.py` (dispatch table, line ~1480) + per-domain modules (`email_actions.py`, `task_queries.py`).
- **Client**: `app/src/preload/index.ts` exposes `window.zylch.*` to the renderer; `app/src/main/` brokers stdio or WebSocket.
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
- `contact_phone: string | null` — populated for WhatsApp tasks; F8 dedup clusters on `contact_email OR contact_phone`
- `channel: 'email' | 'phone' | 'calendar' | 'whatsapp' | null`
- `close_note: string | null`
- `pinned: boolean`
- `sources: { emails: string[], whatsapp_messages?: string[], blobs: string[], calendar_events: string[], thread_id?: string | null, whatsapp_chat_jid?: string | null }`

`sources.whatsapp_messages` carries WhatsAppMessage row PKs; `sources.whatsapp_chat_jid` is stamped on the FIRST WA touchpoint to the task (engine: `update_task_item(whatsapp_chat_jid=…)` is idempotent — subsequent WA messages don't overwrite). Renderer uses it as the explicit pointer for the cross-channel Source-panel toggle so it doesn't have to sniff a `thread_id` suffix.

### `whatsapp.list_messages(chat_jid, limit?)`

Returns an array of WhatsAppMessage dicts for one chat (renderer:
`whatsapp.listMessages({ chat_jid, limit })`). Each row includes (when
present):
- standard fields (id, chat_jid, `text`, `is_from_me`, timestamp, …)
- `media_type: 'voice' | 'audio' | … | null` — set when the message carried media
- `transcription: string | null` — on-device STT text for a downloaded
  voice/audio note (faster-whisper, deferred to the `update` pipeline).
  `null` until transcribed; the renderer shows `[vocale]` meanwhile and a
  🎤-marked transcript once present. Engine wires it via
  `rpc/whatsapp_actions.py`. See [`../engine/docs/execution-plans/whatsapp-voice-transcription.md`](../engine/docs/execution-plans/whatsapp-voice-transcription.md).

### `whatsapp.search_messages(query, limit?)`

| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `query` | string | yes | Free-text. Whitespace-only → `{ threads: [] }`. |
| `limit` | int | no | Default 200. Caps the number of matching chats. |

Returns `{ threads: WhatsAppThread[], query: string, error?: string }`.
Each thread row is the SAME shape as `whatsapp.list_threads` (so the
renderer reuses the thread-row component) plus an optional
`match_snippet: string | null` — the matching message text (the
transcript for a voice-note hit, never the `[voice]` placeholder).

A chat matches when any of its messages' `text` / `transcription` /
`sender_name` contains the query, OR a contact row for the chat matches
on `name` / `push_name` / `phone_number`, OR (when the query has a digit
run ≥ 4) the chat_jid or contact phone contains those digits. Results are
newest-first by latest activity. Mirrors `list_threads`' exclusion of
`@broadcast` / `@newsletter` / empty-jid rows, so search never surfaces a
chat the listing would hide. SQLite-only — no live socket required.
Implemented in `engine/zylch/services/whatsapp_search.py` (shared
`build_thread_rows` + `search_thread_jids`), exposed via
`rpc/whatsapp_actions.py`.

### `whatsapp.send_message(chat_jid, text)`

| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `chat_jid` | string | yes | The chat to send to — `<digits>@s.whatsapp.net`, `@g.us` (group), or `@lid`. The recipient JID is rebuilt from this, server preserved. |
| `text` | string | yes | Trimmed server-side; empty → `{ ok: false, error }`. |

Returns `{ ok: boolean, message?: WhatsAppMessage, error?: string }`. On
success, `message` is the just-sent row in `whatsapp.list_messages` shape
(`is_from_me: true`) so the renderer appends it without a full reload.

Sends over the **live** persistent connection (`_active_client` kept
alive by `whatsapp.connect`) — never a throwaway client like the LLM
`send_whatsapp` tool, since two neonize clients on one session DB clash.
Requires the socket up AND logged in (else `{ ok: false, error:
"WhatsApp not connected" }`). The blocking neonize FFI send runs in a
thread executor. The outgoing row is persisted keyed on the real
`SendResponse.ID`, so if the live socket later echoes the message
(`deviceSentMessage`) the existing `_upsert_message` dedup collapses it
onto the same row. This is a direct user action (typed + sent), so it is
**not** approval-gated — unlike the LLM-initiated `send_whatsapp` inside
`tasks.solve`. Preload binding has a 30 s timeout.

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

### `sms.get_sender()` / `sms.set_sender(sender)`

Read/write the **SMS sender** (`SMS_FROM`, the alphanumeric "from" shown to
recipients), used by the credits-proxy `send_sms` path. It is a **per-business
StarChat variable stored server-side** — NOT the profile `.env`. Both forward
the Firebase ID token in the bare `auth:` header (same convention as
`account.balance`) to mrcall-agent, which proxies StarChat:

- `sms.get_sender()` → `GET {MRCALL_PROXY_URL}/api/desktop/sms/sender`
- `sms.set_sender(sender)` → `PUT …/api/desktop/sms/sender` with `{sender}`

| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `sender` | string | yes (set) | Trimmed, truncated to **≤11 chars** server-side. Empty/whitespace → `ValueError` (JSON-RPC error). |

Both return the proxy payload verbatim — `{ "sender": string, "business_id": string }` — or `{ "error": "auth_expired" }` on a 401 (renderer refreshes the token and retries). No Firebase session → `require_session()` raises. Engine: `engine/zylch/rpc/sms_actions.py` (registered in `methods.py`). Client: `window.zylch.sms.getSender()` / `setSender(sender)` (`app/src/preload/index.ts`), backing the SMS-sender card in `views/Settings.tsx`.

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

// Clean completion (incl. user-cancelled). When the executor ran at
// least one mutating tool (send_email, send_whatsapp, send_sms,
// update_memory, run_python), the engine kicks off `tasks.reanalyze`
// before emitting `done` and decorates the payload with
// `auto_reanalyzed`. Renderer uses `auto_reanalyzed.action='closed'`
// to flip the conversation to read-only and refresh `tasks.list`;
// pure-research solves omit the field entirely (no extra LLM call).
{
  "type": "done",
  "result": {
    "messages": list,
    "cancelled"?: boolean,
    "auto_reanalyzed"?: {
      "action": "kept" | "closed" | "updated" | "skipped",
      "reason"?: string,
      "error"?: string
    }
  }
}

// Unexpected exception in run(). CancelledError does NOT come
// through here — it's caught and emitted as `done` with
// `result.cancelled: True`.
{ "type": "error", "message": string }
```

### `whatsapp.threads.changed` (notification, no payload)

Emitted by the engine after a successful `_on_message` (live MessageEv)
or `_on_history` (HistorySyncEv batch) stores at least one row into
`whatsapp_messages`. The renderer's `views/WhatsApp.tsx` subscribes and
debounces (~600 ms trailing) before re-fetching `whatsapp.list_threads`
+ the active chat's messages. Without this, the thread list reflected
the state at first connect and never updated — Mario reported 4-hour-old
messages still showing "6d ago" because no fresh `loadThreads()` ran.

Important nuance: the engine boot-time auto-reconnect in
`rpc/server.py:_auto_reconnect_whatsapp` must use the real
`_make_notify()` (not a no-op) for these notifications to reach the
renderer on the most common path.

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

### `agents.train_all()`

Runs the three personalised-agent trainers serially:

| Step | Key | Trainer | What |
|---|---|---|---|
| 1 | `memory_message` | `MessageMemoryAgentTrainer.build_memory_message_prompt` | Channel-aware entity extraction prompt. Trainer now ingests email samples **+ 1-on-1 WhatsApp chats** where the user has replied, so the prompt sees the user's voice across both registers. |
| 2 | `task_email` | `EmailTaskAgentTrainer.build_task_prompt` | Personalised task-detection prompt from email threads + memory blobs. |
| 3 | `emailer` | `EmailerAgentTrainer.build_emailer_prompt` | Writing-style prompt for email composition (greetings, sign-offs, tone, language). |

Returns:

```jsonc
{
  "ok": true,
  "results": {
    "memory_message": { "ok": true, "threads_analyzed": 20, "whatsapp_chats_analyzed": 4 },
    "task_email":     { "ok": true, "threads_analyzed": 20 },
    "emailer":        { "ok": true }
  }
}
```

`ok` is `false` if **any** step failed; per-step `results[<key>].ok` carries the granular status and `error` string. The dispatcher does not stop on a single failure — subsequent steps still run.

If no LLM is configured (no Anthropic key + no Firebase session) the method short-circuits with `{ ok: false, error: "No LLM configured…", results: {} }` and emits a single explanatory progress event.

Notification stream — `agents.train.progress`:

```jsonc
{
  "pct": 0..100,
  "step": 1..3,
  "total": 3,
  "current": "memory_message" | "task_email" | "emailer",
  "message": string
}
```

Backs the "Train assistant" card in `Update.tsx` (above the Update button). 30-minute RPC timeout in `app/src/preload/index.ts`.

### `sync.run(days_back?)`

Data-fetch phase of the pipeline (IMAP email + WhatsApp). Skips memory
extraction and task detection — those still belong to `update.run`.
Backs the new **Sync** card on the Update view; the full `update.run`
button calls this implicitly as its first step.

| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `days_back` | int | no | Default 60. Same semantics as the CLI `/process --days N`. |

Returns:

```jsonc
{
  "success": true,                       // false only on a FATAL stage (email_sync)
  "summary": "12 new emails, 4 WhatsApp messages",
  "result": {
    "sync_new": 12,
    "wa_messages": 4,
    "wa_contacts": 0,
    "wa_skipped_reason": null            // string when WA wasn't configured
  },
  "errors": [                            // one entry per failed stage, humanized
    { "severity": "error"|"warning", "title": "...", "detail": "...", "action": "..." }
  ]
}
```

WhatsApp failures are non-fatal (`severity: "warning"`) and don't flip
`success`. Email-sync failure is fatal. Email credentials missing →
short-circuits with a single structured error (does NOT raise).

Notification stream — `sync.progress`:

```jsonc
{ "pct": 0..100, "message": string }
```

12-hour RPC timeout (same as `update.run` — a first sync on a busy
inbox is the slow part). Implementation: `engine/zylch/rpc/setup.py`
delegating to `process_pipeline.run_sync_only`.

### `setup.state()`

Read-only snapshot driving the gating of the Train + Update cards on
the Update view. Each card's enabled state derives from a different
field of this payload (Sync is always enabled).

Returns:

```jsonc
{
  "has_synced": true,                    // ≥1 email OR WA msg in this profile's DB
  "has_trained": true,                   // ≥1 agent_prompts row exists
  "emails_count": 1234,
  "whatsapp_messages_count": 0,
  "agents_trained": ["memory_message", "task_email", "emailer"]
}
```

Per-profile (driven by the active SQLite DB), so a brand-new profile
starts gated even if a sibling profile on the same machine is fully
set up. Cheap (one COUNT + three indexed lookups) — the renderer
refetches on mount, after every Sync/Train/Update completion, and on
`engine.ready` revival.

### `mrcall.list_my_businesses(offset?, limit?)`

Lists the businesses visible to the signed-in user via StarChat
`POST /mrcall/v1/{realm}/crm/business/search` with the Firebase JWT
(`auth:` header, no Bearer prefix). StarChat role-scopes the result
(`ResellerOwnerResolver`): `admin` sees all businesses cross-owner,
`owner` only their own — the desktop adds no permission logic. Returns
`{ businesses: CrmBusiness[], role: string }` (`role` from the
`x-mrcall-role` response header). Errors: no Firebase session → JSON-RPC
`-32010` (`NoActiveSession`); 401 from StarChat → same `-32010` ("Sign in
again"). Backs the MrCall tab business list.

### `mrcall.search_businesses(<filters>, offset?, limit?)`

Filtered variant for customer-service lookup — same endpoint, same
`{ businesses, role }` shape, same role-scoping and errors. Recognised
filters: `emailAddress`, `name`, `surname`, `companyName`, `nickname`,
`businessPhoneNumber`, `vatId`, `businessId`, `address`, `countryAlpha2`,
`subscriptionStatus`. Only non-empty filters are forwarded; they AND
together server-side. `owner` / `owners` are deliberately NOT accepted
(StarChat derives owner scope from the caller's role, so a client-supplied
owner is ignored). Backs the MrCall tab's search bar + status dropdown.

### `auth.refresh(id_token)`

Cross-machine transport (WebSocket backend). Verifies a fresh Firebase ID
token server-side (RS256 against Google's certs — unlike
`account.set_firebase_token`, which trusts the caller) and replaces the
engine's in-memory session. The WebSocket client
(`app/src/main/wsRpcClient.ts`) calls this on a ~30-min timer to keep the
remote session alive well inside the token's ~1h lifetime; the engine
otherwise closes the socket with code **4401** when the token lapses, and
the client reconnects with a freshly-minted token.

| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `id_token` | string | yes | A current Firebase ID token. `expires_at_ms` is derived from the token's own `exp` (not client-supplied). |

Returns `{ ok: true, uid: string, expires_at_ms: int }`. Token
verification failure → JSON-RPC error code `-32011`. **Harmless over
stdio** (the local engine simply re-installs the session); it exists for
parity so the same client code path works on both transports.

Engine: `engine/zylch/rpc/account.py::auth_refresh` (registered in
`engine/zylch/rpc/dispatch.py::METHODS`). The same notification set
(`tasks.solve.event`, `update.progress`, `chat.pending_approval`, …)
flows over WebSocket exactly as over stdio — only the framing differs (one
JSON object per WS TEXT message instead of one per stdout line). The WS
engine does NOT emit `engine.ready` (stdio-only); the client synthesises
the renderer's ready signal when the socket reaches OPEN.

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
- **Token + transport (cross-machine, Phase 2):**
  - `account:pushToken({uid, email, idToken, expiresAtMs})` — the
    CANONICAL Firebase-token path. The renderer pushes the token
    out-of-band to MAIN (not in-band over `account.set_firebase_token`)
    because main needs it to open the remote WebSocket handshake BEFORE
    any RPC channel exists. Main caches it per window; in **local** mode it
    forwards into the engine via `account.set_firebase_token` (preserving
    the pre-Phase-2 effect — the local engine needs the in-memory token
    for outbound StarChat / mrcall calls); in **remote** mode the WS
    client uses it as the `Authorization: Bearer` handshake header and for
    `auth.refresh`. The legacy in-band `account.set_firebase_token` IPC
    stays exported for back-compat. Never persisted to disk.
  - `settings:getBackendLocation()` → `{ location: 'local' | 'remote',
    url? }` and `settings:setBackendLocation(location, url?)` — the
    per-installation backend choice, persisted machine-global in
    `~/.zylch/backend-config.json` (NOT in the profile `.env` — it's a
    property of THIS machine). Read at window-creation time to choose the
    transport. Default (and fresh-install value) is `{ location: 'local'
    }`.
  - `backend:testConnection(url)` → `{ ok: true, signedIn, uid?, email? }
    | { ok: false, code, message }` — opens a TRANSIENT WS to `url` with
    the window's cached Firebase token and probes identity via
    `account.who_am_i`. Diagnostic only (the Settings "Test connection"
    button); never touches the saved config or the live client.

Don't document them here — add new entries to `app/docs/active-context.md`
under "IPC client (preload)" instead.
