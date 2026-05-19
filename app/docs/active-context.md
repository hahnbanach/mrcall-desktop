---
description: |
  App-side state of mrcall-desktop. Electron + React shell that embeds the
  Python sidecar via JSON-RPC over stdio. Current focus + recent landings
  + known issues; engine internals live in `../../engine/docs/active-context.md`,
  cross-cutting state in `../../docs/active-context.md`. Keep this file ≤
  ~120 lines. /doc-endsession prunes anything older than ~2 weeks.
---

# Active Context — App

## Current focus (as of 2026-05-19)

Live verification of the recently-landed UI stack is the gating work:

- **Cross-channel Source-panel toggle** (`b57fcc4f`) — needs a real task with both `sources.emails` and `sources.whatsapp_messages` to exercise the Email/WhatsApp tab pills in `ThreadPanel.tsx`. Current gmail profile has 0 cross-channel tasks.
- **WhatsApp source panel** (`2a8bc2c3`, Fase 4a + 4b) — Mario confirmed bubbles render correctly on a WA-only task; cross-channel rendering not yet exercised on a real task.
- **Update view staged progress + elapsed timer** (`0b33fdf4`) — 1 s ticker + overshot hint compile but need a real `/update` run to confirm engine emissions land at the right percentages.
- **Calendar self-healing** (`a03f6831`) — `ensureEngineSession()` + 3× backoff on initial token push compile; recovery path needs to be observed.

Beyond that, the pre-Firebase legacy cleanup (`c43ff35e`) and `inMemoryPersistence` (`bc011be`) need one more pass of "every signin path clicked from a fresh state" — email/password and "Continue with Google" still untested from this machine.

## Recent landings (last ~2 weeks)

| Date | What | Refs |
|---|---|---|
| 2026-05-15 | Cross-channel Source-panel toggle — `ZylchTask.sources.whatsapp_chat_jid?`, `Conversation.waChatJid?`, `ThreadPanel` API `{ emailThreadId?, whatsappChatJid? }` with three modes (email-only / whatsapp-only / cross-channel); cross-channel header shows `Email (N) / WhatsApp (M)` tab pills with counters + parallel fetch + instant tab switch | `b57fcc4f` |
| 2026-05-15 | Calendar self-healing UI — `ConnectGoogleCalendar.tsx` gains `ensureEngineSession()` + `signin-required` phase with Retry button; `App.tsx` initial token push retries 3× with backoff | `a03f6831` |
| 2026-05-15 | Update view elapsed timer (1 s ticker, "· elapsed 1m23s") + overshot hint ("Running longer than the initial estimate") | `0b33fdf4` |
| 2026-05-15 | WhatsApp source panel (Fase 4a + 4b) — `ThreadSourceType` widened to `'email' \| 'whatsapp'`; WA branch via `whatsapp.listMessages({ chat_jid, limit: 200 })`, bubble alignment by `is_from_me`, header shows resolved phone for `@s.whatsapp.net` jids | `2a8bc2c3` |
| 2026-05-12 | Agentic task "Open" — `openTaskChat` fires `tasks.solve` directly, `Conversation.threadId` + `taskCompleted` carried in store, Source-panel persistence with mount-time backfill for legacy convs, contextual header button (Riapri ↔ Marca come fatta), Annulla calls `tasks.solve.cancel` (not approve(false)), ApprovalCard mode-aware | `df1e1fb1..b36e15b3` |
| 2026-05-12 | Pre-Firebase legacy code removed (`inMemoryPersistence`, every window through Firebase, `?legacy=1` + `ZYLCH_PROFILE` bypasses deleted, `NewProfileWizard.tsx` deleted, -558 lines) | `c43ff35e` |
| 2026-05-11 | Profile picker shows email instead of raw Firebase UID — `profile:current` / `profiles:list` return `{id, email}` | — |
| 2026-05-07 | WhatsApp tab privacy gate — chat list rendered ONLY when `r.connected === true`; 3 s poll while offline; `ConnectWhatsApp` view explains the history limitation | `9eee73c2` |
| 2026-05-05 | Email-tab Gmail-style search bar (above thread list, submit-on-Enter, `?` help panel, Esc to clear) | — |
| 2026-05-03 | MrCall-credits v1 `LLMProviderCard` in Settings + `account.balance` preload binding + "Top up" via `shell.openExternal('https://dashboard.mrcall.ai/plan')` | branch `feat/mrcall-credits-v1` |
| 2026-05-02 | Firebase Auth gate + IdentityBanner + UID-keyed profile binding + "Continue with Google" PKCE on :19276 + CSP fix | `25e668b..b6739d5` · [`../../docs/execution-plans/google-signin.md`](../../docs/execution-plans/google-signin.md) |

## In progress

- Click-test every signin path in `npm run dev`.
- Click-test on a packaged DMG/EXE (blocked on `GOOGLE_SIGNIN_CLIENT_SECRET` repo secret).
- Mac validation of cross-channel task UI (needs a real cross-channel task).
- Mac validation of Update staged progress emissions.
- Mac validation of Calendar self-healing recovery path.
- Mac validation of pre-existing UI flows (close-note composer, IMAP archive, Open → Tasks filter, end-to-end memory tool round-trip in chat).

## Next steps

1. `cd app && npm run dev` → exercise Continue with Google + email/password → IdentityBanner correct → `auth:bindProfile` attaches sidecar or routes to Onboarding.
2. Trigger `/update` in the dev build → confirm progress emissions at 5/20/30/60/80-90/95/100 and the elapsed timer ticks.
3. Settings → "Connect Google Calendar" on a session where the initial token push was missed → confirm the recovery path closes the loop (no raw `_NotSignedInError`).
4. Produce a cross-channel task (synthetic SQL or fresh Update) → confirm the Email/WhatsApp toggle in `ThreadPanel` renders both tabs with correct counters.
5. Add `GOOGLE_SIGNIN_CLIENT_SECRET` repo secret at *Settings → Secrets and variables → Actions*.

## Known issues

- **No live end-to-end verification of any Firebase signin path** from this machine.
- **MrCall-credits v1 not live-verified.**
- **Cross-channel `ThreadPanel` mode not exercised** on a real task.
- **Update staged progress and Calendar self-healing not live-verified.**
- **Onboarding-mode invariants not stress-tested** on a fresh Mac with empty `~/.zylch/profiles/`.
- `tasks.complete` / `tasks.skip` / `tasks.reopen` have no `*.changed` notification — other windows on the same profile won't update their task list until manual refresh.
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
