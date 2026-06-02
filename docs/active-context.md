---
description: |
  Cross-cutting state of mrcall-desktop — things that span engine ↔ app
  or the repo as a whole (JSON-RPC contract drift, release pipeline,
  brand/rename rollout, monorepo conventions). Engine-only state lives
  in `../engine/docs/active-context.md`; app-only state in
  `../app/docs/active-context.md`. Keep this file ≤ ~130 lines.
  /doc-endsession prunes anything older than ~2 weeks.
---

# Active Context — Cross-cutting

## Current focus (as of 2026-05-31)

**MrCall credits routing now actually consumes credits.** Five-part fix split across `mrcall-desktop` and `mrcall-agent`. Desktop side: `ANTHROPIC_API_KEY` shell-env leak closed (engine reads ONLY the profile `.env`); defensive gzip-SSE inflate in the proxy client; Firebase JWT redacted in the RPC dispatcher's DEBUG `params=` line (was being shipped to Anthropic via the renderer's narration pipeline); `LOG_LEVEL` default flipped to DEBUG; balance card self-heals via shared `ensureEngineSession`. Server side (`mrcall-agent/production` already deployed): `accept-encoding: identity` upstream + `aiter_bytes()` forward so the proxy stops leaking gzipped bytes downstream; pricing YAML aligned with Anthropic 2026-05 (Opus 4.7 mispriced at $15/$75 = Opus 4.1 pricing; Haiku 4.5 dated ID `claude-haiku-4-5-20251001` was missing from the allowlist).

**Tasks reanalyze sees WhatsApp threads + user aliases.** New `EMAIL_ALIASES` config (engine + UI Settings) lets `_is_user_email` recognise secondary identities; `build_whatsapp_thread_history` feeds the same reanalyze prompt that already handled email; deterministic urgency cap demotes medium/high to low when the last non-auto turn is the user's (proactive nudge policy, reason annotated).

**Solve loop becomes opt-in + self-closing.** Open from Tasks no longer auto-fires `tasks.solve`; the user clicks the new lightbulb on the chat composer to trigger the agent loop with optional typed instructions. After a mutating solve the engine auto-runs `reanalyze_task` and decorates the `done` event with `auto_reanalyzed = {action, reason}`; the renderer flips the conversation to read-only on `closed` and refreshes `tasks.list`. Outbound `send_email`/`send_whatsapp` now mirror their row into the local store so reanalyze sees the user's reply without waiting for IMAP-Sent / WA echo.

**Live verification status.** Engine path verified end-to-end via `npm run dev` against the production `mrcall-agent` proxy (real credits consumption, real reanalyze, real Solve). Packaged DMG/EXE has NOT seen any of 2026-05-31's changes — a fresh `v*` tag is the next release gate. Continue-with-Google signin paths, cross-channel `ThreadPanel`, and Mac packaged-bundle bring-up all still pending.

## Recent landings (last ~2 weeks)

| Date | What | Spans | Refs |
|---|---|---|---|
| 2026-05-31 | **MrCall credits — leak fix, gzip SSE, secret redaction, balance self-heal, DEBUG default** + companion server-side fixes in `mrcall-agent/production` (allowlist + identity encoding + aiter_bytes). End-to-end verified: 10 230 in / 264 out / 3 303 cache_creation on a Sonnet 4.5 reanalyze actually billed. | engine + app + server | `ed6eeef8` |
| 2026-05-31 | **Solve lightbulb + auto-reanalyze + outbound mirror.** Open from Tasks idle; Lightbulb button → `tasks.solve(task_id, instructions)`. Engine emits `tasks.solve.event.done.result.auto_reanalyzed`; renderer closes conversation + refreshes Tasks. `_send_email` / `_send_whatsapp` mirror outbound into local store. | engine + app + IPC | `9be36c9b` · [`ipc-contract.md`](ipc-contract.md) §`tasks.solve.event` |
| 2026-05-31 | **Tasks reanalyze with WhatsApp history + urgency cap + EMAIL_ALIASES.** `build_whatsapp_thread_history` parity with email side; cap medium/high → low when user replied last (proactive nudge); `EMAIL_ALIASES` config recognised by `_is_user_email` + thread renderer. | engine | `109bfd99` |
| 2026-05-31 | **WhatsApp end-to-end live refresh.** `whatsapp.threads.changed` notification (renderer subscribes + 600 ms trailing debounce); `SourceWebMsg.messageTimestamp` fallback for offline catch-up; `HistorySync.Data` field name fix; `_run_whatsapp_sync` reuses persistent client (kills the per-Update `<conflict type="replaced"/>`); `_resolve_wa_sender` prefers rubric `name` over Pushname. | engine + app + IPC | `0e576197` · [`ipc-contract.md`](ipc-contract.md) §`whatsapp.threads.changed` |
| 2026-05-28 | Onboarding hub on the Update view (3 cards Sync → Train → Update with `setup.state` gating; default view `'update'`). New RPCs `sync.run` + `setup.state`. Engine trainers async to keep loop responsive during `agents.train_all`. | engine + app + IPC | `d3de37ac` · [`ipc-contract.md`](ipc-contract.md) §`sync.run` §`setup.state` |
| 2026-05-26 | WhatsApp tab gains send + search; solve attachment fix (RFC822 Message-ID + multi-folder IMAP search); Onboarding `_resolve_host` defaults to Google for unknown domains; memory `template:<owner>` namespace + `entry_type` guard; Update view surfaces structured errors via `humanize_error`. | engine + app + IPC | `ca784d0d..4e243bdb` merged via `436bb291` |
| 2026-05-26 | "Train assistant" button (`agents.train_all` RPC + `agents.train.progress` notifications); `MessageMemoryAgentTrainer` ingests WhatsApp 1-on-1 chats alongside email samples. | engine + app + IPC | `3c152cc7` |
| 2026-05-22 | Current datetime injected into EVERY LLM request (single LLMClient chokepoint + chat_compaction bypass). | engine | `5f5c73e8` |
| 2026-05-20 | MrCall channel: delegated/PKCE OAuth + `/mrcall` removed (Firebase-JWT only); MrCall tab lists + searches businesses; onboarding unblocked for MrCall-only users; in-wizard Calendar session fix. | engine + app + IPC | `770522e8..2b0a54ce` |
| 2026-05-20 | WhatsApp voice-note transcription — event-time download + deferred faster-whisper `small`/int8 pass; archived chats excluded from memory/task analysis. Live download + packaged bundling still pending. | engine + app + IPC | [`../engine/docs/execution-plans/whatsapp-voice-transcription.md`](../engine/docs/execution-plans/whatsapp-voice-transcription.md) |
| 2026-05-15 | Cross-channel Source-panel toggle; Calendar self-healing Firebase session; Update view staged progress + ETA rewrite + elapsed timer; WhatsApp source panel Fase 4a+4b. | engine + app | `b57fcc4f` · `a03f6831` · `0b33fdf4` · `2a8bc2c3` |

## In progress

- End-to-end live verification of Firebase signin paths in `npm run dev` and packaged DMG/EXE.
- `GOOGLE_SIGNIN_CLIENT_SECRET` repo secret creation. Until done, packaged builds with Google signin fail at the materialise step.
- Mac validation of the 3-card Update flow + Calendar self-healing.
- Mac validation of the new Solve / auto-reanalyze / outbound-mirror loop on a packaged DMG.

## Next steps

1. Cut a fresh `v*` tag so the PyInstaller-bundled sidecar carries the 2026-05-31 fixes (leak, gzip, redaction, DEBUG, threads.changed, solve auto-reanalyze).
2. Wire `humanize_error` into the remaining RPC surfaces that still raise raw `httpx`/`imaplib` tracebacks (`rpc/account.py:account.balance`, Settings test-connection, chat tools, solve tools).
3. Add `GOOGLE_SIGNIN_CLIENT_SECRET` repo secret at *Settings → Secrets and variables → Actions*.
4. Configure `GOOGLE_CALENDAR_CLIENT_ID` in profile Settings → "Connect Google Calendar" → confirm consent + token persistence + self-healing recovery path.
5. Wire `engine/zylch/tools/calendar_sync.py` to the new `provider='google_calendar'` tokens.
6. Open **MrCall pipeline parity Livello B** workstream — phone-call memory ingestion. Plan: [`execution-plans/mrcall-pipeline-parity.md`](execution-plans/mrcall-pipeline-parity.md).

## Known issues

- **One-time JWT leak in Anthropic + zylch.log historical** — pre-`_redact_params` runs shipped the full Firebase id_token through narration. Tokens expire ~1h → no rotation needed; the redactor closes the channel going forward.
- **No live end-to-end verification of any Firebase signin path** (still).
- **No automated contract test for IPC method/payload changes** — TypeScript catches signature mismatches inside the renderer but not engine↔preload divergence. Tracked in [`harness-backlog.md`](harness-backlog.md).
- **No contract test for desktop ↔ mrcall-agent transport** — the gzip-SSE-without-Content-Encoding regression slipped through silently. Tracked.
- **No CI for `engine/make lint` and `app/npm run typecheck`** — Tracked.
- **No CI for `pytest` on engine** — Tracked.
- **No E2E test for multi-window Firebase auth flows** — Tracked.
- **Release workflow doesn't fail when one arch's installer is missing** — Tracked.
- **No CI gate prevents committing the OAuth Client secret (`GOCSPX-`)** — Tracked.

## Where stable state lives

| What | Where |
|---|---|
| JSON-RPC method surface (engine ↔ app contract) | [`ipc-contract.md`](ipc-contract.md) |
| Firebase Auth as desktop identity | [`../CLAUDE.md`](../CLAUDE.md) "Identity (Firebase)" |
| LLM billing modes (BYOK ↔ MrCall credits) | [`../CLAUDE.md`](../CLAUDE.md) "LLM billing modes" |
| Brand / rename rollout (zylch → mrcall) | [`../CLAUDE.md`](../CLAUDE.md) "Naming and identifiers" |
| Release pipeline (electron-builder, signing, sidecar bundling, OAuth-secret CI step) | [`execution-plans/release-and-rename-l2.md`](execution-plans/release-and-rename-l2.md) |
| Continue-with-Google sign-in details | [`execution-plans/google-signin.md`](execution-plans/google-signin.md) |
| Engine architecture, code style, conventions | [`../engine/docs/`](../engine/docs/) |
| App architecture (lives in `app/CLAUDE.md` for now) | [`../app/CLAUDE.md`](../app/CLAUDE.md) |
| Enforcement / tooling gaps | [`harness-backlog.md`](harness-backlog.md) + per-tree backlogs |
