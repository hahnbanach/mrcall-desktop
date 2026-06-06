---
description: |
  App-side state of mrcall-desktop. Electron + React shell that embeds the
  Python sidecar via JSON-RPC over stdio. Current focus + recent landings
  + known issues; engine internals live in `../../engine/docs/active-context.md`,
  cross-cutting state in `../../docs/active-context.md`. Keep this file ≤
  ~120 lines. /doc-endsession prunes anything older than ~2 weeks.
---

# Active Context — App

## Current focus (as of 2026-06-02)

**Remote backend (cross-machine).** The renderer can now drive an engine running on another machine over `wss://`. `main/index.ts`'s sidecar spawn became a transport factory keyed on `main/backendConfig.ts` (`~/.zylch/backend-config.json`, machine-global): `StdioRpcClient` (local, unchanged) or `WebSocketRpcClient` (`main/wsRpcClient.ts`, remote). The WS client connects to `<base>/ws/<uid>` — one base URL, per-window routing — with the Firebase token in an `Authorization: Bearer` handshake header (main caches it out-of-band via the `account:pushToken` IPC, since the token is needed before the RPC channel exists). `Settings → BackendLocationCard` (Local / Remote + Test connection). Live: production@examplebiz over `wss://desktop.mrcall.ai`, no tunnel. Fixes: WS client queues early RPCs + flushes on open (was hiding the Email tab); `bufferutil`/`utf-8-validate` marked `external` in `electron.vite.config.ts`; reconnect crash on `terminate()` of a CONNECTING socket; no retry-loop on 403.

**Solve button on the chat composer.** `views/Workspace.tsx` no longer auto-fires `tasks.solve` on Open — the conversation opens idle. `ChatComposer.tsx` renders a lightbulb button (`Icon.solve = Lightbulb`) next to "Invia" when an `onSolve` callback is provided. Clicking it pipes the typed text into `tasks.solve(task_id, instructions=text)`; empty text replicates the legacy auto-trigger. The renderer subscribes to the `tasks.solve.event` `done` payload's new `auto_reanalyzed` field — when the engine ran a mutating solve and the post-run reanalyze returned `action: 'closed'`, the conversation flips to `taskCompleted=true` AND `useTasks().refresh()` is called so the Tasks tab updates without a manual reload. `store/conversations.ts` exposes `markSolveStarted`/`markSolveFinished` for explicit in-flight tracking (closeConversation uses it to fire a targeted `solveCancel(task_id)`).

**WhatsApp tab live refresh.** `views/WhatsApp.tsx` subscribes to `whatsapp.threads.changed` and debounces 600 ms before re-fetching `whatsapp.list_threads` + the active chat's messages. `reloadActiveMessages` extracted into a `useCallback` so the subscriber and the `activeJid` effect share the same path.

**Settings credit-balance self-heal.** `firebase/authUtils.ts` exposes a shared `ensureEngineSession()` (re-push token + verify via `account.whoAmI()`). `views/ConnectGoogleCalendar.tsx` drops its local copy; `views/Settings.tsx`'s `LLMProviderCard` uses it before every `account.balance()` call and retries once on `auth_expired`. Closes the "balance frozen at last successful fetch" loop Mario hit when the sidecar restarted before the token push.

Residual live verification: every Firebase signin path from a fresh state, packaged DMG/EXE behaviour, Update staged progress UI on the 3-card flow.

## Recent landings (last ~2 weeks)

| Date | What | Refs |
|---|---|---|
| 2026-06-02 | **Cross-machine thin client**: `main/rpcClient.ts` interface + `StdioRpcClient`/`WebSocketRpcClient` (`main/wsRpcClient.ts`); transport factory in `index.ts` keyed on `main/backendConfig.ts`; `account:pushToken` out-of-band token cache; `Settings` `BackendLocationCard` (Local/Remote + Test); WS client appends `/ws/<uid>`. Fixes: early-RPC queue, ws-natives `external`, terminate-on-CONNECTING crash, 403 no-loop. | [cross-machine-transport.md](../../docs/execution-plans/cross-machine-transport.md) |
| 2026-05-31 | `views/Settings.tsx`'s `LLMProviderCard.refreshBalance` self-heals via shared `ensureEngineSession`. `firebase/authUtils` exports the helper; `ConnectGoogleCalendar` migrates to it. | `ed6eeef8` |
| 2026-05-31 | `views/Workspace.tsx` gains `solve()` handler + auto-reanalyzed handling (✓ closed bubble / ℹ updated bubble + `useTasks().refresh()`). `store/conversations.openTaskChat` no longer auto-fires solve; `markSolveStarted`/`markSolveFinished` track in-flight explicitly. `components/ChatComposer` gains optional `onSolve` prop + Lightbulb button (`Icon.solve`). `types.ts` SolveEvent.done.result.auto_reanalyzed added. | `9be36c9b` |
| 2026-05-31 | `views/WhatsApp.tsx` subscribes to `whatsapp.threads.changed` (600 ms trailing debounce → loadThreads + active-chat reload). `reloadActiveMessages` extracted as useCallback. | `0e576197` |
| 2026-05-28 | `views/Update.tsx` rebuilt as 3 ordered cards (Sync → Train → Update) gated by `setup.state`; Quick-start banner; default `View` is now `'update'` after the splash. New preload bindings `window.zylch.sync.run` + `window.zylch.setup.state`. Update card refetches `setup.state` on mount, after each Sync/Train/Update completion, and on `engine.ready` revival. | `d3de37ac` |
| 2026-05-26 | `views/WhatsApp.tsx` composer (Enter=send, Shift+Enter=newline) + search bar (Enter=search, Esc=clear) with `match_snippet` on hits. `views/Update.tsx` renders `result.errors[]` as red/amber blocks (replaces false-green "No changes"). `views/Onboarding.tsx` `inferHosts` defaults unknown email domains to Google. | `ca784d0d..4e243bdb` |
| 2026-05-26 | "Train assistant" card above Update — Train button + progress bar + per-agent result row driven by `window.zylch.agents.trainAll()`. Subscribes to `agents.train.progress`. | `3c152cc7` |
| 2026-05-20 | MrCall tab live: `views/Mrcall.tsx` lists businesses + search-by-field with subscription-status dropdown + expandable anagraphic/billing cards. | `ed9ca585` |
| 2026-05-20 | Onboarding unblocked for MrCall-only users (`ProfileFormFields includeGroups`); Calendar session fix (`installEngineTokenPusher` after `finalize`); Email tab gated on `IMAP_HOST`. | `2b0a54ce` |
| 2026-05-20 | WhatsApp voice-note transcripts in the Source panel — 🎤 marker + "vocale trascritta" hint; `[vocale]` placeholder while pending. | [`../../engine/docs/execution-plans/whatsapp-voice-transcription.md`](../../engine/docs/execution-plans/whatsapp-voice-transcription.md) |
| 2026-05-15 | Cross-channel Source-panel toggle; Calendar self-healing UI; Update view elapsed timer + overshot hint; WhatsApp source panel Fase 4a+4b. | `b57fcc4f` · `a03f6831` · `0b33fdf4` · `2a8bc2c3` |

## In progress

- Click-test every signin path in `npm run dev` (Continue with Google + email/password).
- Click-test on a packaged DMG/EXE (blocked on `GOOGLE_SIGNIN_CLIENT_SECRET` repo secret).
- Mac validation of cross-channel task UI (needs a real cross-channel task).
- Mac validation of Update staged progress emissions on the 3-card flow.
- Mac validation of pre-existing UI flows (close-note composer, IMAP archive, Open → Tasks filter, end-to-end memory tool round-trip in chat).

## Next steps

1. `cd app && npm run dev` → exercise Continue with Google + email/password → IdentityBanner correct → `auth:bindProfile` attaches sidecar or routes to Onboarding.
2. Open a task → click Solve with typed instructions → approve send_email → bubble "✓ Task chiusa automaticamente" → tab Tasks reflects the closure without a refresh click.
3. Settings → balance should refresh on focus AND after an Update grosso (delta visible).
4. Trigger `/update` in the dev build → confirm progress emissions at 5/20/30/60/80-90/95/100 and the elapsed timer ticks.
5. Add `GOOGLE_SIGNIN_CLIENT_SECRET` repo secret at *Settings → Secrets and variables → Actions*.

## Known issues

- **Packaged DMG hasn't seen any of 2026-05-31's changes yet** — `npm run dev` flows worked; PyInstaller bundle needs a fresh `v*` tag.
- **Open no longer auto-solves**: users expecting the old behaviour need to click the lightbulb (empty-text Solve reproduces the legacy auto-trigger).
- **`tasks.complete` / `tasks.skip` / `tasks.reopen` have no `*.changed` notification** — other windows on the same profile won't update their task list until manual refresh. The new `auto_reanalyzed` field on `tasks.solve.event.done` partially addresses this for the Solve-then-close path; the other paths are still silent.
- **Cross-channel `ThreadPanel` mode not exercised** on a real task.
- **No live end-to-end verification of any Firebase signin path** from this machine.
- **Update staged progress and Calendar self-healing not live-verified** end-to-end.
- **Onboarding-mode invariants not stress-tested** on a fresh Mac with empty `~/.zylch/profiles/`.
- No unit test coverage on the renderer side. IPC contract is the only enforcement; payload-shape mismatches surface only at runtime.

## Where stable state lives

| What | Where |
|---|---|
| App index, dev workflow, packaging, IPC client architecture | [`../CLAUDE.md`](../CLAUDE.md) |
| JSON-RPC method surface | [`../../docs/ipc-contract.md`](../../docs/ipc-contract.md) |
| Cross-cutting recent state (Firebase / billing / release / brand) | [`../../docs/active-context.md`](../../docs/active-context.md) |
| Engine-side recent state | [`../../engine/docs/active-context.md`](../../engine/docs/active-context.md) |
| Release pipeline (signing, OAuth secret CI step, single-arch fix) | [`../../docs/execution-plans/release-and-rename-l2.md`](../../docs/execution-plans/release-and-rename-l2.md) |
| Continue-with-Google sign-in plan + setup runbook | [`../../docs/execution-plans/google-signin.md`](../../docs/execution-plans/google-signin.md) |
