---
description: |
  Engine-side state of mrcall-desktop. Current focus + recent landings +
  known issues. Older context lives in git history, `execution-plans/`,
  and `features/`. This file is a working list, not a changelog — keep
  it ≤ ~150 lines. /doc-endsession prunes anything older than ~2 weeks.
---

# Active Context — Engine

## Current focus (as of 2026-05-28)

**Post-signup onboarding hub + asyncio-loop fairness during training.** The Update view now exposes the three pipeline phases as separate, ordered RPCs (`sync.run`, `agents.train_all`, `update.run`); the new `setup.state` RPC reports `has_synced` / `has_trained` so the renderer can gate the Train + Update cards until the prerequisite data exists. The trainers themselves no longer monopolise the asyncio loop: `_generate_prompt` and `build_task_prompt_incremental` now `await self.client.create_message(...)` (the existing `run_in_executor` wrapper around `create_message_sync`), so `whatsapp.status` polls and any other concurrent RPC keep flowing during a `agents.train_all`. Live-verify pending.

**MrCall channel cleanup + customer-service lookup (Livello A).** The legacy MrCall delegated/PKCE OAuth2 auth is gone (−~3000 LOC: the delegated flow in `tools/mrcall/oauth.py`, the `/mrcall` slash-command surface in `command_handlers.py`, `mrcall_link` storage, the dead configurator domain). StarChat is reached purely via the Firebase JWT now (`make_starchat_client_from_firebase_session`). New read-only RPC `mrcall.search_businesses` (CrmBusinessSearch filters — email/name/phone/VAT/status; StarChat role-scopes: admin sees cross-owner, owner own-only) backs the desktop "simplified dashboard". `sync_mrcall` is a graceful no-op pending a Firebase-path reimplementation (**Livello B** — phone-call memory ingestion). Live-verified by Mario 2026-05-20. Plan: [mrcall-pipeline-parity.md](../../docs/execution-plans/mrcall-pipeline-parity.md).

WhatsApp parity is structurally complete through Phase 4. Residual work-in-flight is **live verification** of the 2026-05-15 stack (Update staged progress, Calendar self-healing) + the MrCall-credits v1 round-trip (pending proxy at `https://zylch-test.mrcall.ai`).

## 2026-05-20 — WhatsApp voice-note transcription

On-device STT for WA voice notes: download the ogg/opus at WhatsApp **event time** (URLs expire server-side) → cache to `<profile>/wa_media/<msg_id>.ogg`, then **defer** transcription to the `update` pipeline (faster-whisper `small`, int8, CPU) before memory extraction. Language follows `USER_LANGUAGE` (else auto-detect — no hardcoded Italian). `transcription`/`media_path` columns added to WhatsAppMessage; `workers/memory.py` uses `transcription or text` and bypasses the `len<20` skip gate for transcribed voice notes (plain short text still skipped). Server-side STT rejected (StarChat doesn't bill STT credits yet). **Dev-verified (97 green, incl. real on-device STT)**; live neonize download + packaged-build bundling of ctranslate2 + av (PyInstaller) still pending. New `whatsapp/transcription.py`. See [`execution-plans/whatsapp-voice-transcription.md`](execution-plans/whatsapp-voice-transcription.md).

## Recent landings (last ~2 weeks)

| Date | What | Refs |
|---|---|---|
| 2026-05-27 | New `rpc/setup.py` ships `sync.run` (email + WA only, emits `sync.progress`, returns `{success, summary, result, errors}` with the same `humanize_error` envelope as `update.run`) and `setup.state` (`{has_synced, has_trained, emails_count, whatsapp_messages_count, agents_trained}`). New public `services/process_pipeline.run_sync_only(owner_id, *, days_back, progress, errors_out)` reuses the existing `_run_sync` + `_run_whatsapp_sync` helpers. Three trainers (`base.py`, `memory_message.py`, `task_email.py`) now `await self.client.create_message(...)` instead of calling `create_message_sync` directly — fixes `whatsapp.status` timeouts during `agents.train_all`. Live-verify pending. | uncommitted |
| 2026-05-26 | New `services/error_messages.humanize_error` classifier (by exception TYPE + `__cause__` walk; never prose parsing — dns/auth/imap/network/timeout/tls/credits/no_llm/unknown). `handle_process` gains an `errors_out` collector; `update.run` returns `{success, errors[], summary, updated_tasks}` and no longer reports a false "Update complete" on stage failure. Memory: new 3rd home `template:<owner>` for behavioral rules (read by `_get_learned_preferences` together with legacy `prefs:`); `create_memory(entry_type="behavioral_rule")` forces routing to `template:`, `update_memory` blocks behavioral_rule on `user:` contact blobs. `_resolve_host` defaults unknown domains to Google. `IMAPClient.fetch_attachments` searches INBOX → All Mail → Sent. `solve_tools._download_attachment` uses `email["message_id_header"]`. New `services/whatsapp_search.py` (`build_thread_rows` + `search_thread_jids`) backs `whatsapp.send_message` + `whatsapp.search_messages`. | `ca784d0d..4e243bdb` merged via `436bb291` (2026-05-27) |
| 2026-05-26 | New RPC `agents.train_all` (`zylch/rpc/agents.py`) runs the 3 personalised trainers serially (memory_message → task_email → emailer) with `agents.train.progress` notifications. `MessageMemoryAgentTrainer.build_memory_message_prompt` now also samples 1-on-1 WhatsApp chats where the user has replied (`_get_recent_whatsapp_chats` / `_format_whatsapp_samples`), and the meta-prompt has a new `=== SAMPLE OF RECENT WHATSAPP CHATS ===` section. `metadata.whatsapp_chats_analyzed` exposed alongside `threads_analyzed`. | `3c152cc7` |
| 2026-05-22 | WA revoke (delete-for-everyone) purges the target row locally; archived chats excluded from memory + task analysis (UI unaffected); `list_mrcall_assistants` chat tool + dashboard URL anchored in the assistant prompt; current datetime injected into EVERY LLM request | `56488528` · `140793c6` · `63f05b2a` · `5f5c73e8` |
| 2026-05-20 | MrCall delegated/PKCE OAuth + `/mrcall` command surface + `mrcall_link` removed (−~3000 LOC); StarChat via Firebase JWT only; `sync_mrcall` graceful no-op (Livello B TODO) | `770522e8` · `6f02f7ef` |
| 2026-05-20 | `mrcall.search_businesses` RPC (CrmBusinessSearch filters) for customer-service lookup; 13 stale SaaS-era test files removed (suite collectable again, 207 passed) | `a28c5533` · `c40dd41b` · `dd6863ca` |
| 2026-05-20 | WhatsApp voice-note transcription — event-time download + deferred faster-whisper `small`/int8 pass; `transcription`/`media_path` cols; memory uses `transcription or text`, voice bypasses `len<20` gate | [whatsapp-voice-transcription.md](execution-plans/whatsapp-voice-transcription.md) |
| 2026-05-15 | Phase 4 cross-channel: `update_task_item(whatsapp_chat_jid=…)` stamps `sources.whatsapp_chat_jid` (idempotent), TaskWorker WA path stamps on CREATE + UPDATE | `b57fcc4f` |
| 2026-05-15 | Update pipeline staged progress callback (sync 5%, WA 20%, memory 30%, tasks 60%, sweeps 80/90%, render 95%) + rewritten `_estimate_update_eta` (memory + tasks + WA + F4/F8/F9 + first-sync proxy + setup) | `0b33fdf4` · `cb91901b` |
| 2026-05-15 | Calendar self-healing — `ensureEngineSession()` re-pushes Firebase token + verifies via `account.whoAmI()` before Calendar RPCs; initial token push retries 3× with backoff | `a03f6831` · `1c60aebf` |

## In progress

- **Live verification** of the 2026-05-13/15 stack — see Current focus.
- **MrCall-credits v1 round-trip** — needs proxy deployment at test URL.
- **Mac validation backlog** — IMAP archive against real Gmail/Outlook/iCloud/Fastmail; Open → Tasks filter (0/N tasks, Clear filter); close-note composer; end-to-end memory tool round-trip in chat.

## Next steps

1. Wire `humanize_error` into the other RPC surfaces that today still surface raw `httpx`/`imaplib` tracebacks (`rpc/account.py:account.balance`, Settings test-connection, chat tools, solve tools) — the classifier exists, only `update.run` consumes it today.
3. Click Update → observe staged progress: 5/20/30/60/80-90/95/100 with ETA evolving and elapsed counter ticking.
4. Settings → Connect Google Calendar on a session where the initial token push was missed → confirm the recovery path closes the loop (no raw `_NotSignedInError` shown).
5. Wire `tools/calendar_sync.py` to read tokens from `provider='google_calendar'` (current 469-line module is partial scaffolding — never fetches events from Google API).
6. Split oversized files: `services/command_handlers.py` (5427), `workers/task_creation.py` (well over 1100 after Fase 3b additions), `tools/gmail_tools.py` (1002), `workers/memory.py` (916).

## Known issues

- **`humanize_error` wired only to `update.run` + `sync.run`** — `account.balance` (and any other httpx caller) still raises through JSON-RPC and the server logs the full traceback (the `httpcore.ConnectError` → `httpx.ConnectError` chain). The classifier already understands these via `__cause__` walk; just needs catch/wrap at the RPC handler. Tracked in [`harness-backlog.md`](harness-backlog.md).
- **Trainer async fix not live-verified** — the move from `create_message_sync` to `await create_message` is the only thing standing between `agents.train_all` and the `whatsapp.status` timeout Mario hit; needs a real Train run with the WhatsApp tab open to confirm the loop stays responsive. Other engine-side `create_message_sync` callers (`memory/llm_merge.py:76`, `services/solve_tools.py:481`, etc.) are inside workers / `run_in_executor` lambdas and are NOT believed to block, but the audit wasn't exhaustive — re-investigate if a similar timeout reappears under a different RPC.
- **Behavioral_rule guard depends on the model declaring `entry_type`** — if the model omits it, `update_memory` on a contact blob is NOT blocked. The approval card on `update_memory` is the human backstop. Content-classification fallback (LLM) deliberately deferred.
- **WA voice transcription dev-verified only** — live neonize `download_any` path (real voice-note bytes from a connected WhatsApp) and packaged-build bundling of ctranslate2 + av (PyInstaller, +~50–100 MB) not verified; tracked in [`harness-backlog.md`](harness-backlog.md).
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
