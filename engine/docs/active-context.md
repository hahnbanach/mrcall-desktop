---
description: |
  Engine-side state of mrcall-desktop. Current focus + recent landings +
  known issues. Older context lives in git history, `execution-plans/`,
  and `features/`. This file is a working list, not a changelog — keep
  it ≤ ~150 lines. /doc-endsession prunes anything older than ~2 weeks.
---

# Active Context — Engine

## Current focus (as of 2026-05-20)

**MrCall channel cleanup + customer-service lookup (Livello A).** The legacy MrCall delegated/PKCE OAuth2 auth is gone (−~3000 LOC: the delegated flow in `tools/mrcall/oauth.py`, the `/mrcall` slash-command surface in `command_handlers.py`, `mrcall_link` storage, the dead configurator domain). StarChat is reached purely via the Firebase JWT now (`make_starchat_client_from_firebase_session`). New read-only RPC `mrcall.search_businesses` (CrmBusinessSearch filters — email/name/phone/VAT/status; StarChat role-scopes: admin sees cross-owner, owner own-only) backs the desktop "simplified dashboard". `sync_mrcall` is a graceful no-op pending a Firebase-path reimplementation (**Livello B** — phone-call memory ingestion). Live-verified by Mario 2026-05-20. Plan: [mrcall-pipeline-parity.md](../../docs/execution-plans/mrcall-pipeline-parity.md).

WhatsApp parity is structurally complete through Phase 4. Residual work-in-flight is **live verification** of the 2026-05-15 stack (Update staged progress, Calendar self-healing) + the MrCall-credits v1 round-trip (pending proxy at `https://zylch-test.mrcall.ai`).

## Recent landings (last ~2 weeks)

| Date | What | Refs |
|---|---|---|
| 2026-05-26 | New RPC `agents.train_all` (`zylch/rpc/agents.py`) runs the 3 personalised trainers serially (memory_message → task_email → emailer) with `agents.train.progress` notifications. `MessageMemoryAgentTrainer.build_memory_message_prompt` now also samples 1-on-1 WhatsApp chats where the user has replied (`_get_recent_whatsapp_chats` / `_format_whatsapp_samples`), and the meta-prompt has a new `=== SAMPLE OF RECENT WHATSAPP CHATS ===` section. `metadata.whatsapp_chats_analyzed` exposed alongside `threads_analyzed`. | _pending live verification_ |
| 2026-05-20 | MrCall delegated/PKCE OAuth + `/mrcall` command surface + `mrcall_link` removed (−~3000 LOC); StarChat via Firebase JWT only; `sync_mrcall` graceful no-op (Livello B TODO) | `770522e8` · `6f02f7ef` |
| 2026-05-20 | `mrcall.search_businesses` RPC (CrmBusinessSearch filters) for customer-service lookup; 13 stale SaaS-era test files removed (suite collectable again, 207 passed) | `a28c5533` · `c40dd41b` · `dd6863ca` |
| 2026-05-15 | Phase 4 cross-channel: `update_task_item(whatsapp_chat_jid=…)` stamps `sources.whatsapp_chat_jid` (idempotent), TaskWorker WA path stamps on CREATE + UPDATE | `b57fcc4f` |
| 2026-05-15 | Update pipeline staged progress callback (sync 5%, WA 20%, memory 30%, tasks 60%, sweeps 80/90%, render 95%) + rewritten `_estimate_update_eta` (memory + tasks + WA + F4/F8/F9 + first-sync proxy + setup) | `0b33fdf4` · `cb91901b` |
| 2026-05-15 | Calendar self-healing — `ensureEngineSession()` re-pushes Firebase token + verifies via `account.whoAmI()` before Calendar RPCs; initial token push retries 3× with backoff | `a03f6831` · `1c60aebf` |
| 2026-05-13 | Phase 3b: `TaskWorker._analyze_recent_whatsapp_events` (dedup by chat_jid, user_replied detection, F7 via `whatsapp_blobs`, Fix-D guard, channel-agnostic `get_tasks_by_thread`) | `87a806f7` |
| 2026-05-13 | Fix-D restricted to same-thread candidates — F7 topical-blob siblings stay as LLM context, never auto-merge a CREATE onto an unrelated customer's task | `f5196e7f` |
| 2026-05-13 | Phase 3a: `task_items.contact_phone` indexed column, `_infer_task_channel` learns `whatsapp`, `update_task_item(add_source_whatsapp_message=…)`, `get_tasks_by_contact_phone`, watermark helpers | `e6fcd940` |
| 2026-05-12 | WhatsApp pipeline parity Phase 2 a/b/c — `whatsapp_blobs` join + `memory_message` trainer + WA memory extraction wired into update pipeline | `91421d2e` |
| 2026-05-12 | Attachment reading — native PDF/DOCX/XLSX in `read_document` (no more `run_python` approval prompt) | `528c5d6b` |
| 2026-05-11/12 | Agentic task "Open" — proactive solve flow: SOLVE_SYSTEM_PROMPT rewrite, `USER_LANGUAGE`, `tasks.solve.cancel` RPC, APPROVAL_TOOLS coherence fix, `tool_use_start` event | `df1e1fb1..b36e15b3` · [proactive-task-open.md](../../docs/execution-plans/proactive-task-open.md) |
| 2026-05-08 | Cross-channel person identity Phase 1c (identifier-clustered reconsolidation + `migrate_blob_references`) | `6ae8a5fa` |
| 2026-05-07 | Phases 1a + 1b — `person_identifiers` index + backfill + identifier-first match in `_upsert_entity` | `d0baa6b1` · `315c56d1` |

## In progress

- **Live verification** of the 2026-05-13/15 stack — see Current focus.
- **MrCall-credits v1 round-trip** — needs proxy deployment at test URL.
- **Mac validation backlog** — IMAP archive against real Gmail/Outlook/iCloud/Fastmail; Open → Tasks filter (0/N tasks, Clear filter); close-note composer; end-to-end memory tool round-trip in chat.

## Next steps

1. Click Update → observe staged progress: 5/20/30/60/80-90/95/100 with ETA evolving and elapsed counter ticking.
2. Settings → Connect Google Calendar on a session where the initial token push was missed → confirm the recovery path closes the loop (no raw `_NotSignedInError` shown).
3. Wire `tools/calendar_sync.py` to read tokens from `provider='google_calendar'` (current 469-line module is partial scaffolding — never fetches events from Google API).
4. Split oversized files: `services/command_handlers.py` (5427), `workers/task_creation.py` (well over 1100 after Fase 3b additions), `tools/gmail_tools.py` (1002), `workers/memory.py` (916).

## Known issues

- **Firebase round-trip not fully live-verified** — Calendar self-healing landed but recovery path hasn't been observed end-to-end on Mario's machine.
- **MrCall-credits v1 not live-verified.**
- Oversized files (see Next Steps #4).
- `tools/calendar_sync.py` partial scaffolding — wiring to OAuth tokens pending.
- Legacy trained prompts with `{from_email}` placeholders fall back to old behaviour (new prompts use cached system prompt).
- neonize "Press Ctrl+C to exit" line printed by Go runtime — not suppressible from Python.
- WhatsApp session DB (`~/.zylch/whatsapp.db`) is global, not per-profile — multi-profile with different WA accounts not supported.
- Slash-separated phones (`02 316562 / 338 594946`) parsed as one value — tracked in [`harness-backlog.md`](harness-backlog.md).
- `LID:` kind not indexed on profiles that haven't retrained memory agent (cross-channel match still works via `Phone:` resolved from `whatsapp_contacts`).
- `tests/workers/test_task_worker_bugs.py` broken at HEAD since 2026-05-04 transport refactor (15 errors, mocks out of sync) — to be **rewritten**, not deleted; tracked in [`harness-backlog.md`](harness-backlog.md). (13 truly-stale SaaS-era test files were removed 2026-05-20; the suite collects again, 207 passed.)
- **`sandbox_service` dangling import** — `command_handlers.py:171` and `chat_service.py:399` import `zylch.services.sandbox_service`, a module that no longer exists (absent on main too). Lazy local imports, so no boot/import error, but the branch crashes if reached. Pre-existing; candidate cleanup.

## Where stable state lives

| What | Where |
|---|---|
| Module map, dependency direction, data flow | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Code style, patterns, logging, security | [`CONVENTIONS.md`](CONVENTIONS.md) |
| Tech stack, dependency rules, imperatives | [`system-rules.md`](system-rules.md) |
| Module quality assessment + live test ledger | [`quality-grades.md`](quality-grades.md) |
| Enforcement / tooling gaps | [`harness-backlog.md`](harness-backlog.md) |
| Per-feature reference docs | [`features/`](features/) |
| Active execution plans | [`execution-plans/`](execution-plans/) |
| JSON-RPC method surface | [`../../docs/ipc-contract.md`](../../docs/ipc-contract.md) |
| Cross-cutting recent state | [`../../docs/active-context.md`](../../docs/active-context.md) |
| App-side recent state | [`../../app/docs/active-context.md`](../../app/docs/active-context.md) |
| Firebase auth, BYOK vs MrCall credits, transport model | [`../CLAUDE.md`](../CLAUDE.md) (already in the static cacheable layer) |
