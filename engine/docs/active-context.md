---
description: |
  Engine-side state of mrcall-desktop as of 2026-05-02. Profile-aware CLI,
  Firebase signin (renderer-driven, in-memory token bridge), Google
  Calendar OAuth (PKCE :19275), Electron desktop (validated), prompt
  caching in chat, user notes injection, memory tool pair (LLM decides
  update vs create), inbox/sent views, email archive/delete RPCs,
  Open-email → thread-filtered Tasks view, RealStep/cafe124 task
  auto-close fixes, optional close_note column on task_items. App-side
  state lives in ../../app/docs/active-context.md; cross-cutting state
  in ../../docs/active-context.md.
---

# Active Context

## What Is Built and Working

### Core
- **CLI**: `zylch` via click — init, update, sync, dream, tasks, status, profiles, telegram
- **Profile system**: multi-profile with `-p/--profile`, exact match, flock-based liveness (stale-lock check via flock, not PID)
- **Storage**: SQLite at `~/.zylch/profiles/<name>/zylch.db`, 19+ ORM models, WAL mode
- **Config**: Pydantic Settings from profile `.env`, `zylch init` wizard (rclone-style), DOWNLOADS_DIR with picker hint
- **LLM**: BYOK (Anthropic, OpenAI) via direct SDK calls (aisuite dropped); also MrCall-credits mode (`provider="mrcall"`) routing through `mrcall-agent`'s proxy and billing the user's `CALLCREDIT` pool — see "MrCall-credits v1" below.

### Electron Desktop (end-to-end working)
- `zylch-desktop` launches on Mac, validated by user on 2026-04-13
- 3 views (chat, tasks, emails) talk to Python sidecar via RPC
- `update.run` no longer blocks the sidecar; rough ETA + "progress is saved" notice during long updates

### Email
- IMAP client with auto-detect presets (Gmail, Outlook, Yahoo, iCloud)
- Email archive with SQLite FTS, incremental sync
- `zylch sync` does synchronous IMAP fetch
- **Inbox / Sent views**: `emails.list_inbox`, `emails.list_sent`, thread pin, read tracking (`c56634a`)
- **HTML body rendering**: `emails.list_by_thread` returns `body_html` (`65185fc`)
- Draft preview shows full body verbatim, not a summary (`108572b`)
- **Archive + Delete (this session)**: `emails.archive(thread_id)` IMAP MOVE to provider archive folder (SPECIAL-USE `\All` / `\Archive`, fallback provider names), UID MOVE with COPY+EXPUNGE fallback. `emails.delete(thread_id)` soft-delete locally only (preserves provenance for linked tasks, IMAP untouched). New columns `archived_at` / `deleted_at` on Email model, applied via existing `_apply_column_migrations` at boot. `list_inbox_threads` / `list_sent_threads` filter out flagged threads. Desktop: Archive + Delete buttons in ThreadReadingPane with optimistic removal + rollback on error. RPC lives in `zylch/rpc/email_actions.py` (not `command_handlers.py`).

### WhatsApp
- neonize (whatsmeow) client with QR code login
- Sync on demand: connect → fetch history → derive contacts from messages → disconnect
- Timestamp guard for corrupted values; contacts derived from saved messages

### Telegram / MrCall
- Telegram bot via python-telegram-bot, proactive 8am/8pm digest
- MrCall StarChat HTTP client with OAuth2 flow

### Firebase auth (desktop signin, 2026-05-02 landing)
- `zylch/auth/` package — `FirebaseSession` singleton (uid, email, id_token, expires_at_ms) held in process memory only. Thread-safe via a module-level lock; never persisted to disk. `set_session`, `clear_session`, `get_session`, `require_session` (raises `NoActiveSession` mapped to JSON-RPC -32010).
- `zylch/rpc/account.py` — `account.set_firebase_token`, `account.sign_out`, `account.who_am_i`. The renderer pushes the token after Firebase signin and on every 50-min refresh; `who_am_i` never echoes the token back.
- `zylch/tools/starchat_firebase.py` — `make_starchat_client_from_firebase_session(realm?, timeout=30)` returns a `StarChatClient(auth_type="firebase")` with `auth: <jwt>` header, mirroring the dashboard's call shape.
- `zylch/rpc/mrcall_actions.py` — `mrcall.list_my_businesses(offset, limit)` POSTs to `/mrcall/v1/{realm}/crm/business/search` with the active JWT. First reachable smoke-test of the signin → JWT → StarChat path.
- The legacy CLI MrCall PKCE flow on `:19274` (`zylch.tools.mrcall.oauth`, used by `cli/setup.py`) is untouched.

### Google Calendar OAuth (incremental, 2026-05-02 landing)
- `zylch/tools/google/calendar_oauth.py` — PKCE flow on `127.0.0.1:19275`, scope `openid email https://www.googleapis.com/auth/calendar.readonly`, `access_type=offline` + `prompt=consent` so we always get a refresh_token. `DEFAULT_CALENDAR_ID = "primary"` — the user's main Google calendar (the one tied to the consenting Google account).
- `zylch/rpc/google_actions.py` — `google.calendar.connect / disconnect / status / cancel`. `connect` emits a `google.calendar.auth_url_ready` notification with the consent URL right before awaiting the callback; the renderer opens that URL via `shell:openExternal`. 5-minute consent timeout. Tokens stored encrypted via `Storage.save_provider_credentials(uid, "google_calendar", …)`.
- `config.py` — `google_calendar_client_id` field (env `GOOGLE_CALENDAR_CLIENT_ID`) plus `google_calendar_client_id_default` (env `GOOGLE_CALENDAR_CLIENT_ID_DEFAULT`). The default is populated by the Electron main process from the same Desktop OAuth client used by "Continue with Google" sign-in (`app/src/main/oauthConfig.ts:GOOGLE_SIGNIN_CLIENT_ID`) — Desktop OAuth clients accept any 127.0.0.1 loopback redirect, so the same client works for the Calendar :19275 flow without a separate Cloud Console entry. `get_google_client_id()` returns the explicit value when set and falls back to the default; both unset → original "configure GOOGLE_CALENDAR_CLIENT_ID first" error. No client_secret — the desktop is a public OAuth client and Google's PKCE flow doesn't use one. Surfaced in Settings via `services/settings_schema.py` (label updated to "(override)" — the field is now optional in packaged builds).

### Profile-by-Firebase-UID
- New profiles created via the desktop signin are keyed by the immutable Firebase UID at `~/.zylch/profiles/<firebase_uid>/`. The `.env` carries `OWNER_ID=<uid>` (so engine owner-scoped storage binds to it) plus `EMAIL_ADDRESS=<email>` (display only). Created via the new `onboarding:createProfileForFirebaseUser` IPC.
- Legacy email-keyed profiles still work; `engine/scripts/migrate_profile_to_uid.py --email <e> --uid <uid>` upgrades them on demand (atomic dir rename + .env patch + `--dry-run` / `--force`).

### Update Pipeline (`zylch update`)
- [1/5] Email sync (IMAP, 60 days default)
- [2/5] WhatsApp sync (connect/fetch/disconnect)
- [3/5] Memory extraction (auto-trains, parallel 5x, prompt caching)
- [4/5] Task detection — LLM analyzes every non-user email; self-sent also goes through LLM (no hardcoded rules)
- [5/5] Show action items

### Tasks — view filters
- **Open-email → thread-filtered Tasks view (this session)**: clicking `✉ Open` on an Inbox thread no longer opens the thread chat. It navigates to the Tasks view with a `taskThreadFilter` applied (always, even for 0 or 1 tasks — no picker, no shortcut). Banner "Tasks for thread: <subject>" + "✕ Clear filter"; empty state when the thread has no tasks. Backend RPC `tasks.list_by_thread(thread_id)` in `zylch/rpc/task_queries.py` wraps `Storage.get_tasks_by_thread`. Desktop: `openSelected()` in `views/Email.tsx` sets the thread filter and calls `onOpenTasks` (renamed from `onOpenWorkspace`); `Tasks.tsx` supports the filter mode with live mutations (pin/skip/close/reopen/update) operating on the filtered list.

### Task Detection
- **Incremental**: analyzes only unprocessed emails, preserves existing tasks
- **LLM-driven**: every non-user email (including self-sent) goes through the LLM (`958b6b5`, `c3db306`)
- **USER_NOTES + USER_SECRET_INSTRUCTIONS injected into detector prompt** (`f887f5d`) — user-specific context steers detection
- **Reopen**: `tasks.reopen` RPC + storage method — close isn't final (`843362a`). Reopen now also clears `close_note`.
- `tasks.list` honours `include_completed` (`50aa4bd`)
- **Close with optional note**: `tasks.complete(task_id, note?)` accepts a free-text reason stored on `task_items.close_note`. Display-only — never injected into detector or any LLM prompt. Auto-close paths (worker, reanalyze sweep) leave note=None so closing reasons aren't fabricated.

### Task auto-close — RealStep / cafe124 fixes (baseline since 2026-05-01)
Three coupled fixes in `zylch/workers/task_creation.py` + reanalyze sweep:

- **F1 — Cc fallback in user_reply.** Per-recipient close in user_reply iterates `to_email + cc_email` (was: `to_email` only). `storage.get_unprocessed_emails_for_task` SELECTs `cc_email`.
- **F2 — Disabled "Forcing update on stale task" branch.** When LLM returns `task_action="none"` with non-empty `suggested_action`, the worker logs WARNING and skips the update instead of overwriting existing task fields with the LLM advisory text. Email still marked task_processed via the unconditional `_mark_thread_nonuser_processed`.
- **F3 — Diagnostic log when `get_tasks_by_thread` returns empty in user_reply.** Captures `thread_id`, `email_id`, `from_email` for the next-occurrence reproducer of RC-1 (root cause not reproduced).
- **F4 — Bounded reanalyze sweep at end of `_run_tasks`.** `services/process_pipeline.py:_reanalyze_sweep` picks up to `REANALYZE_CAP=10` open tasks (oldest first) whose `analyzed_at` (or `created_at` fallback) is older than `REANALYZE_MIN_AGE_HOURS=24`. Tolerates per-task exceptions; logs `[TASK] Reanalyze sweep: N of M eligible …`. Cost: up to 10 extra LLM calls per `update`. Surfaces in the return string as `"N action items detected (M reanalyzed)"`.

Tests: `tests/workers/test_task_worker_bugs.py` (14 cases, all green) + `tests/services/test_reanalyze_sweep.py` (6 cases, all green) — 20/20 across both files.

### Chat (Assistant)
- **Prompt caching in chat**: `zylch/assistant/core.py` + `llm/client.py` mark system/tools as `cache_control: ephemeral` (`1358594`)
- **USER_NOTES injection**: user notes loaded into the chat system prompt
- **Compaction**: `zylch/services/chat_compaction.py` summarises old turns when context grows
- Three manual cache deliverable tests under `tests/manual_test_cache_deliverable*.py`

### Memory
- Entity-centric blob storage with fastembed (ONNX, 384-dim)
- In-memory vector search: numpy cosine similarity
- Hybrid search (text + semantic), reconsolidation via LLM (merge uses prompt caching)
- **Memory tool pair (this session, `0b9e4e8`)**:
  - `update_memory_tool.py`: requires exact `blob_id` + `new_content`; no internal search; errors if id missing
  - `create_memory_tool.py`: companion, stores under `user:<owner_id>` namespace
  - `SearchLocalMemoryTool` exposes `blob_id` per result, drops stale `<owner>:<assistant>:contacts` filter
  - Assistant prompt documents the save/correct workflow: search → LLM picks → update(blob_id) or create(content)

### Dream System (`zylch dream`)
- Three-gate trigger: time (4h), items (5 unprocessed), file lock
- Four phases: orient → gather → consolidate → prune
- Cron-friendly

### Settings
- `settings_io` quotes values with dotenv-style escapes, not shlex (`3117cd4`)
- `USER_SECRET_INSTRUCTIONS` unmasked in settings schema; `scripts/repair_env.py` repairs mis-quoted `.env` files (`32fc4bc`)
- `DOWNLOADS_DIR` field with directory-picker hint (`02401a4`)

### MrCall-credits v1 — engine side (branch `feat/mrcall-credits-v1`, tip `3001844`)

A second LLM billing mode alongside BYOK. When the user picks `SYSTEM_LLM_PROVIDER=mrcall`, every Anthropic call is routed through `mrcall-agent`'s `POST /api/desktop/llm/proxy` and billed against the user's `CALLCREDIT` balance on StarChat — the same unified pool that funds phone-call minutes and the configurator chat. There is **no** separate LLM-only category.

- `zylch/llm/proxy_client.py` (NEW, 536 lines) — `MrCallProxyClient` mimicking `anthropic.Anthropic().messages.create` (sync + async + streaming context manager). Httpx-based; parses Anthropic SSE; reconstructs Message/event objects with `.content`, `.usage`, `.stop_reason`. Typed exceptions: `MrCallInsufficientCredits(available, topup_url)`, `MrCallAuthError`, `MrCallProxyError`. Auth header is `auth: <jwt>` (no Bearer prefix), value pulled from `zylch.auth.session.id_token`. `stream` is forced to True on the wire regardless of caller intent.
- `zylch/llm/client.py` (MODIFIED) — `LLMClient.__init__` branches on `provider == "mrcall"`: requires a live Firebase session (raises `RuntimeError("MrCall credits require Firebase signin. Use Settings → Sign In.")` if absent) and constructs `MrCallProxyClient(proxy_base_url=settings.mrcall_proxy_url, firebase_session=session)`. Reuses the existing `_call_anthropic` codepath because the proxy returns Anthropic-format objects.
- `zylch/llm/providers.py` (MODIFIED) — `"mrcall"` entry in `PROVIDER_MODELS` (model from `settings.mrcall_credits_model`) and in `PROVIDER_FEATURES` with `is_metered=True` (`tool_calling`, `web_search`, `prompt_caching`, `vision` all True — pass-through to Anthropic). Same `is_metered` flag (with `False`) added to `anthropic` and `openai` for consistent caller branching. `PROVIDER_API_KEY_NAMES` deliberately omits `"mrcall"` — the credential is the Firebase session, not an env var.
- `zylch/rpc/account.py` (MODIFIED) + `rpc/methods.py` (MODIFIED) — new JSON-RPC method `account.balance()` that calls `GET /api/desktop/llm/balance` on `mrcall-agent` with the in-memory Firebase ID token from the session. Returns the server payload verbatim. 401 → `{"error": "auth_expired"}` for the renderer to refresh + retry. Total live methods: 34 (was 33).
- `zylch/config.py` (MODIFIED) — adds `mrcall_proxy_url` (env `MRCALL_PROXY_URL`, default `https://zylch.mrcall.ai` — the production `mrcall-agent` deployment; override to `https://zylch-test.mrcall.ai` for development against test StarChat) and `mrcall_credits_model` (env `MRCALL_CREDITS_MODEL`, default `claude-sonnet-4-5`).
- `zylch/services/settings_schema.py` (MODIFIED) — `"mrcall"` added to `LLM_PROVIDER` choices so the Settings UI surfaces it.

Tests: `engine/tests/llm/test_proxy_client.py` (NEW, 8 cases: happy SSE, 401 → `MrCallAuthError`, 402 → `MrCallInsufficientCredits` with parsed `available` / `topup_url`, auth header shape, body forwarding, streaming reconstruction). 8/8 green.

The Anthropic API key is server-side on `mrcall-agent` — never on the desktop client. The desktop only ever sends the Firebase JWT. Top-up happens on `https://dashboard.mrcall.ai/plan`; the desktop "Top up" button (renderer side) just opens that URL via `shell.openExternal`.

Pricing math (server-side; documented here for reference): `units = ceil(actual_µUSD × 1.5 / 11000)` — markup × value-of-1-credit-in-µUSD. 1 credit = €0.01.

### Transport model — Anthropic + direct/proxy (2026-05-04, refactor)

The engine has **one provider (Anthropic) over two transports**:

- ``direct`` — BYOK. The user's ``ANTHROPIC_API_KEY`` from the profile
  ``.env`` is used to call ``anthropic.Anthropic(...)`` directly.
- ``proxy`` — MrCall credits. Calls are routed through ``mrcall-agent``
  via ``MrCallProxyClient`` and billed against the user's MrCall credit
  balance. Credential is the in-memory Firebase ID token held by
  :mod:`zylch.auth.session`.

Both transports return Anthropic-shape ``Message`` objects, so the
rest of the engine — workers, agents, trainers, tools, services —
sees a single uniform :class:`zylch.llm.LLMClient`.

`zylch/llm/client.py:make_llm_client()` is the single entry point
that every caller uses. Resolution is presence-based: an
``ANTHROPIC_API_KEY`` in ``.env`` flips to ``direct``, else proxy. If
no Firebase session is live in proxy mode, the factory raises
``RuntimeError("No LLM configured: …")``. Background workers that
should silently skip use ``try_make_llm_client()``.

This refactor collapsed a muddled three-provider model
(``anthropic`` / ``openai`` / ``mrcall``) plus a
``MRCALL_SESSION_SENTINEL`` placeholder string. OpenAI was dead code
in the desktop product — its ``_call_openai`` branch in
``LLMClient``, ``OPENAI_API_KEY`` config field, ``openai_model``
field, the ``"openai"`` schema option, and ``settings_schema.py``
entry are all removed. ``zylch/llm/providers.py`` is gone (the
``PROVIDER_MODELS`` / ``PROVIDER_FEATURES`` / ``PROVIDER_API_KEY_NAMES``
maps were the last vestiges of the legacy multi-provider scaffolding).
``zylch.api.token_storage.get_active_llm_provider`` is gone too —
every caller either uses ``make_llm_client()`` directly or surfaces
``"No LLM configured"`` via ``try_make_llm_client() is None``.

Concretely the refactor touched ~25 files and dropped
``api_key``/``provider`` parameters from: ``SpecializedAgent``,
``EmailerAgent``, ``TaskOrchestratorAgent``, ``MemoryWorker``,
``TaskWorker``, ``LLMMergeService``, ``BaseAgentTrainer``,
``EmailMemoryAgentTrainer``, ``EmailTaskAgentTrainer``,
``EmailerAgentTrainer``, ``EmailSyncManager``, ``CalendarSyncManager``,
``ZylchAIAgent``, ``ComposeEmailTool``, ``WebSearchTool``, every
``JobExecutor._execute_*`` method, every ``_handle_*`` helper in
``command_handlers.py``, every direct ``LLMClient(api_key=…, provider=…)``
construction in ``rpc/methods.py``, and ``cli/setup.py`` (the legacy
CLI wizard now prompts only for an optional Anthropic key).

Backward compat: pydantic ignores unknown env keys
(``extra="ignore"``), so old profiles with ``SYSTEM_LLM_PROVIDER=…``
and ``OPENAI_API_KEY=…`` keep booting; those values are simply
ignored. A user with ``ANTHROPIC_API_KEY`` set keeps BYOK behaviour
identically. A user who explicitly chose ``SYSTEM_LLM_PROVIDER=mrcall``
and also has an Anthropic key in ``.env`` will silently flip to BYOK —
the only meaningful behaviour change. Documented in
``docs/active-context.md``.

## What Was Completed This Session

**Firebase signin landing — engine side (commits `25e668b..11f4cbe` on `main`, all pushed).**

- New packages: `zylch/auth/` (`FirebaseSession` singleton + `NoActiveSession`), `zylch/tools/google/` (PKCE Calendar OAuth on :19275).
- New RPC modules merged into the dispatch table at `zylch/rpc/methods.py`: `account.py` (3 methods), `mrcall_actions.py` (1 method), `google_actions.py` (4 methods). Total live methods: 33.
- New StarChat factory: `zylch/tools/starchat_firebase.py:make_starchat_client_from_firebase_session()`.
- New setting: `google_calendar_client_id` in `config.py` + matching schema row in `services/settings_schema.py` ("Google" group).
- Migration script: `engine/scripts/migrate_profile_to_uid.py` (live-tested in a sandbox HOME).
- **`zylch.tools.mrcall` package init repaired (`d62506c`)**: stripped four imports of never-tracked sibling modules (`variable_utils`, `llm_helper`, `config_tools`, `feature_context_tool`); the `tools/mrcall/__init__.py` had been broken since the subtree merge that built this monorepo. `oauth.py` (the only real submodule) re-exports remain. Move details in commit body.
- **Cleanup brief landed at `docs/execution-plans/cleanup-mrcall-configurator-deadcode.md`** (in mrcall-desktop, not engine) — `command_handlers.py` `/mrcall config` / `/mrcall train` / `/mrcall feature` handlers + `tools/factory.py:_create_mrcall_tools` + `tests/test_mrcall_integration.py` reference symbols that were never tracked. Currently graceful-degraded; recommends DELETE in a follow-up PR.

Verification: dispatcher METHODS count is 33 post-landing; every `account.*` / `mrcall.*` / `google.calendar.*` error path without a session returns -32010. Real round-trip against Firebase / StarChat / Google not run from this machine.

## What Is In Progress

- **MrCall-credits v1 live verification** — branch `feat/mrcall-credits-v1` (tip `3001844`) is green at the unit-test layer (8/8 in `tests/llm/test_proxy_client.py`); the real round-trip — Firebase signin → renderer flips Settings to "MrCall credits" → first chat through `MrCallProxyClient` → balance refresh in the Settings card → 402 path on a depleted account → top-up on dashboard → balance updates — has not been clicked end-to-end. Needs `mrcall-agent` deployed at `https://zylch-test.mrcall.ai` with `/api/desktop/llm/proxy` + `/api/desktop/llm/balance` live, and a signed-in user with at least 1 `CALLCREDIT` unit.
- **Live verification of the Firebase landing in the running Electron app** — only smoke tests cover the new RPCs; the real round-trip needs `npm run dev` + signin + StarChat call + Calendar OAuth (with a configured `GOOGLE_CALENDAR_CLIENT_ID`).
- **Mac validation of pre-existing UI flows still pending**: IMAP archive (real thread on Gmail / Outlook / iCloud / Fastmail), Open → Tasks filter (0-task, N-task, Clear filter, sidebar back-nav), close-note composer, end-to-end memory tool round-trip in chat.
- **Custom124 cleanup follow-up** — re-run `scripts/diag_custom124.py` after a few `update` cycles to confirm `USER_NOTES`-driven detection stopped duplicates from recurring.
- .docx / .pptx native parsing (current fallback: `run_python`).

## Immediate Next Steps

1. Live-test the Firebase signin path in the running app: `cd app && npm run dev`, sign in with the dashboard account, exercise `mrcall.list_my_businesses`. End-to-end against real Firebase + StarChat is the only meaningful verification of the JWT round-trip.
2. Configure a `GOOGLE_CALENDAR_CLIENT_ID` (Desktop-app or Web OAuth client with redirect `http://127.0.0.1:19275/oauth2/google/callback`) in Settings, then "Connect Google Calendar" in Settings; verify token persistence in `OAuthToken` (provider `google_calendar`).
3. Wire `tools/calendar_sync.py` to read the new `google_calendar` tokens. Current sync code (469 lines) is partial scaffolding — it composes events into the `calendar_events` table but never fetches them; reading the token from `Storage.get_provider_credentials(uid, "google_calendar")` is the missing piece.
4. Open the follow-up PR per `docs/execution-plans/cleanup-mrcall-configurator-deadcode.md` (the brief is self-contained for a fresh agent).
5. Validate the previously pending UI flows on Mac (close-note composer, archive/delete, Open → Tasks filter).
6. Split oversized files: `command_handlers.py` (5427), `workers/task_creation.py` (1149), `tools/gmail_tools.py` (1002), `workers/memory.py` (916).
7. Keep `tests/` directory renewal slow-burn — current live tests are the manual cache deliverables + `tests/workers/test_task_worker_bugs.py` + `tests/services/test_reanalyze_sweep.py`. `tests/test_mrcall_integration.py` is part of the dead-configurator brief.

## Known Issues

- **Firebase round-trip not live-verified** — only smoke tests cover the new RPCs.
- **Dead `MrCallConfiguratorTrainer` references** (`command_handlers.py` `/mrcall config`/`train`/`feature` handlers, `tools/factory.py:_create_mrcall_tools`, `tests/test_mrcall_integration.py`) — gracefully degraded but still present. Brief at `docs/execution-plans/cleanup-mrcall-configurator-deadcode.md` (in mrcall-desktop tree).
- `services/command_handlers.py` (5427 lines) — 10x over 500-line guideline
- `tools/gmail_tools.py` (1002), `workers/task_creation.py` (1149), `workers/memory.py` (916) — all above guideline
- `services/sync_service.py` (574) — slightly over
- `tools/calendar_sync.py` is partial scaffolding — never fetched events from Google API; will be wired to the new OAuth tokens in a follow-up.
- Legacy trained prompts with `{from_email}` placeholders fall back to old behavior (new prompts use cached system prompt)
- neonize "Press Ctrl+C to exit" line printed by Go runtime — not suppressible from Python
- Most tests in `tests/` are stale (except `tests/workers/test_task_worker_bugs.py` and the manual cache deliverables)
- WhatsApp session DB (`~/.zylch/whatsapp.db`) is global, not per-profile — multi-profile with different WA accounts not supported
- `oauth_tokens.last_sync` still never written by any code path
