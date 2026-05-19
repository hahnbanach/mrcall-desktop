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

## Current focus (as of 2026-05-19)

WhatsApp pipeline parity spans engine + app + IPC through Phase 4 cross-channel — a task carrying both `sources.emails` and `sources.whatsapp_messages` triggers a per-task Email/WhatsApp toggle in the Workspace Source panel (engine stamps `sources.whatsapp_chat_jid`; renderer reads it). The IPC contract gained `sources.whatsapp_messages` and `sources.whatsapp_chat_jid` on the `tasks.list` payload. **Cross-channel toggle live-verified 2026-05-19 via a synthetic SQL setup** (Birger Lie email task + Ivan Marchese WA chat, reverted post-test).

The work-in-flight is **live verification** of the rest of the recently-landed stack:

- Update view staged progress emissions ([Update stage progress] cb91901b/0b33fdf4) reaching the UI.
- Calendar "Connect Google Calendar" self-healing (a03f6831/1c60aebf) recovering from a missed initial Firebase-token push.
- **MrCall-credits v1 round-trip** — still pending `mrcall-agent` deployed at `https://zylch-test.mrcall.ai`.

The release pipeline still has open hardening items in [`harness-backlog.md`](harness-backlog.md) — chiefly the workflow not failing when one arch's installer is missing (PyInstaller 6.20 silent-break across v0.1.31..v0.1.32 went unnoticed for a week).

## Recent landings (last ~2 weeks)

| Date | What | Spans | Refs |
|---|---|---|---|
| 2026-05-15 | Cross-channel Source-panel toggle — engine stamps `sources.whatsapp_chat_jid`; ThreadPanel renders Email/WhatsApp tab pills with counters, parallel fetch, instant tab switch | engine + app + IPC | `b57fcc4f` |
| 2026-05-15 | Calendar self-healing Firebase session — `ensureEngineSession()` re-pushes token + verifies via `account.whoAmI()` before Calendar RPCs; initial token push retries 3× with backoff | engine + app | `a03f6831` · `1c60aebf` |
| 2026-05-15 | Update view staged progress emissions + ETA rewrite + elapsed timer (engine progress callback, renderer 1 s ticker + overshot hint) | engine + app | `0b33fdf4` · `cb91901b` |
| 2026-05-15 | WhatsApp source panel in Workspace (Fase 4a + 4b) — `ThreadSourceType` widened to `'email' \| 'whatsapp'`; WA branch renders bubbles via `whatsapp.listMessages` | app | `2a8bc2c3` |
| 2026-05-13 | WhatsApp task creation pipeline (Fase 3b) — `TaskWorker._analyze_recent_whatsapp_events`, channel-agnostic `get_tasks_by_thread`, cross-channel F7 via `whatsapp_blobs` | engine + IPC (`sources.whatsapp_messages`) | `87a806f7` · `e6fcd940` |
| 2026-05-13 | Fix-D create→update restricted to same-thread candidates (F7 topical siblings stay as LLM context only) | engine | `f5196e7f` |
| 2026-05-12 | Agentic task "Open" — `tasks.solve` direct from Tasks list (no template), `tasks.solve.cancel` RPC, contextual header button, read-only closed tasks, Annulla cancels run | engine + app + IPC | `b36e15b3..df1e1fb1` · [proactive-task-open.md](execution-plans/proactive-task-open.md) (status: completed) |
| 2026-05-12 | Pre-Firebase legacy code removed (`inMemoryPersistence`, every window through Firebase, `?legacy=1` + `ZYLCH_PROFILE` bypasses deleted, -558 lines) | app + cross-cut | `c43ff35e` |
| 2026-05-12 | WhatsApp pipeline parity Phase 2 a/b/c — memory extraction wired into update pipeline (engine-only, no IPC change) | engine | `91421d2e` |
| 2026-05-12 | PyInstaller pin to 6.13.0 in release workflow (silent Win-x64 break across v0.1.31..v0.1.32) | release | `362e1cda` · [harness-backlog.md](harness-backlog.md) |
| 2026-05-06 | Task-list cleanup ("4 task per UN problema"): F9 cross-contact topic dedup + `_apply_data_backfills` early-return fix. New RPC `tasks.topic_dedup_now()` | engine + IPC | `ec61067` + `557e65b` · [`../engine/docs/execution-plans/topic-dedup-playbook.md`](../engine/docs/execution-plans/topic-dedup-playbook.md) |
| 2026-05-05 | Email-tab search: `emails.search` RPC (Gmail-style operators) + UI search bar | engine + app + IPC | — |

## In progress

- End-to-end live verification of Firebase signin paths (email/password, Continue with Google) in `npm run dev` and in packaged DMG/EXE.
- `GOOGLE_SIGNIN_CLIENT_SECRET` repo secret creation at *Settings → Secrets and variables → Actions*. Until done, packaged builds with Google signin will fail at the materialise step.
- Mac validation of MrCall-credits v1 round-trip — needs the proxy deployed at the test URL.
- Mac validation of Update staged progress and Calendar self-healing.

## Next steps

1. Live-test signin paths in `npm run dev` — IdentityBanner correct, `auth:bindProfile` attaches sidecar or routes to Onboarding.
2. Add `GOOGLE_SIGNIN_CLIENT_SECRET` repo secret so the next `v*` tag push produces a working packaged build.
3. Configure `GOOGLE_CALENDAR_CLIENT_ID` in profile Settings → "Connect Google Calendar" → confirm consent + token persistence + self-healing recovery path.
4. Wire `engine/zylch/tools/calendar_sync.py` to the new `provider='google_calendar'` tokens.

## Known issues

- **No live end-to-end verification of any Firebase signin path.**
- **MrCall-credits v1 not live-verified.**
- **No automated contract test for IPC method/payload changes** — tracked in [`harness-backlog.md`](harness-backlog.md). TypeScript catches signature mismatches inside the renderer but not engine↔preload divergence.
- **No CI for `engine/make lint` and `app/npm run typecheck`** — tracked in [`harness-backlog.md`](harness-backlog.md).
- **No CI for `pytest` on engine** — tracked in [`harness-backlog.md`](harness-backlog.md).
- **No E2E test for multi-window Firebase auth flows** — tracked in [`harness-backlog.md`](harness-backlog.md).
- **Release workflow doesn't fail when one arch's installer is missing** — Win-x64 break across v0.1.31..v0.1.32 silent for a week; tracked in [`harness-backlog.md`](harness-backlog.md).
- **No CI gate prevents committing the OAuth Client secret (`GOCSPX-`)** — tracked in [`harness-backlog.md`](harness-backlog.md).

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
