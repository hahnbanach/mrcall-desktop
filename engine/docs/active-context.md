---
description: |
  Engine-side state of mrcall-desktop. Current focus + recent landings +
  known issues. Older context lives in git history, `execution-plans/`,
  and `features/`. This file is a working list, not a changelog — keep
  it ≤ ~150 lines. /doc-endsession prunes anything older than ~2 weeks.
---

# Active Context — Engine

## Current focus (as of 2026-05-19)

WhatsApp pipeline parity is **structurally complete through Phase 4 cross-channel**: WA messages flow end-to-end (sync → memory → tasks → UI), and a task carrying BOTH `sources.emails` and `sources.whatsapp_messages` renders the per-task Email/WhatsApp toggle in the Workspace Source panel (engine stamps `sources.whatsapp_chat_jid`, app reads it).

Cross-channel toggle live-verified 2026-05-19 via a synthetic SQL setup (Birger Lie email task + Ivan Marchese WA chat) — pills, body swap, count display all confirmed by Mario. Reverted post-test; profile has 0 cross-channel tasks again until a natural match lands.

The work-in-flight is **live verification** of the rest of the 2026-05-15 stack:

1. Update view's staged progress emissions reaching the UI ([Update stage progress] cb91901b/0b33fdf4).
2. Calendar "Connect Google Calendar" self-healing path (a03f6831/1c60aebf) — confirm the renderer's `ensureEngineSession()` recovers from a missed initial token push.
3. **MrCall-credits v1 round-trip** (branch `feat/mrcall-credits-v1`, tip `3001844`) — still pending the proxy deployed at `https://zylch-test.mrcall.ai`.

## 2026-05-20 — WhatsApp voice-note transcription

On-device STT for WA voice notes: download the ogg/opus at WhatsApp **event time** (URLs expire server-side) → cache to `<profile>/wa_media/<msg_id>.ogg`, then **defer** transcription to the `update` pipeline (faster-whisper `small`, int8, CPU) before memory extraction. Language follows `USER_LANGUAGE` (else auto-detect — no hardcoded Italian). `transcription`/`media_path` columns added to WhatsAppMessage; `workers/memory.py` uses `transcription or text` and bypasses the `len<20` skip gate for transcribed voice notes (plain short text still skipped). Server-side STT rejected (StarChat doesn't bill STT credits yet). **Dev-verified (97 green, incl. real on-device STT)**; live neonize download + packaged-build bundling of ctranslate2 + av (PyInstaller) still pending. New `whatsapp/transcription.py`. See [`execution-plans/whatsapp-voice-transcription.md`](execution-plans/whatsapp-voice-transcription.md).

## Recent landings (last ~2 weeks)

| Date | What | Refs |
|---|---|---|
| 2026-05-20 | WhatsApp voice-note transcription — event-time download + deferred faster-whisper `small`/int8 pass; `transcription`/`media_path` cols; memory uses `transcription or text`, voice bypasses `len<20` gate | [whatsapp-voice-transcription.md](execution-plans/whatsapp-voice-transcription.md) |
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
| 2026-05-07 | WhatsApp privacy gate + LID contact resolution from whatsmeow session DB + auto-reconnect at sidecar boot | `9eee73c2` |
| 2026-05-06 | `_apply_data_backfills` early-return fix + F9 cross-contact topic dedup + `tasks.topic_dedup_now` RPC | `557e65b` · `ec61067` · [topic-dedup-playbook.md](execution-plans/topic-dedup-playbook.md) |
| 2026-05-06 | Task pipeline overhaul Fase 1.1–4 (plural `get_tasks_by_contact`, `analyzed_at` bump, calendar `task_action`, F8 dedup sweep, `email_blobs` index, `task_items.channel`, 30d phone auto-close, `[update.summary]` log) | [task-pipeline-overhaul.md](execution-plans/task-pipeline-overhaul.md) |

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
- `tests/workers/test_task_worker_bugs.py` broken at HEAD since 2026-05-04 transport refactor — tracked in [`harness-backlog.md`](harness-backlog.md).

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
