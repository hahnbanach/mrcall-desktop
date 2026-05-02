---
description: |
  App-side state of mrcall-desktop as of 2026-05-02. Electron + React shell
  embeds the Python sidecar via JSON-RPC over stdio. This file captures
  what is in flight on the UI/preload/main side — engine internals live
  in ../../engine/docs/active-context.md, cross-cutting state in
  ../../docs/active-context.md.
---

# Active Context — App

This file is young: app-side state historically lived inside
`engine/docs/active-context.md` (which doubled as the monorepo's
freshest source). Facts migrate here as they get touched.

## What Is Built and Working

### Identity (Firebase, 2026-05-02 landing)
- `FirebaseAuthGate` in `App.tsx` wraps the entire app. Unsigned-in users see `views/SignIn.tsx` (email/password; Google + magic links deferred).
- Firebase config hard-coded in `firebase/config.ts` (project `talkmeapp-e696c`, same as the dashboard — single MrCall account spans both surfaces). Persistence via `[indexedDBLocalPersistence, browserLocalPersistence]`.
- `firebase/authUtils.ts` listens to `onAuthStateChanged`, pushes the ID token to the engine via `window.zylch.account.setFirebaseToken` on every signin and on a 50-min proactive refresh interval.
- `Settings.tsx` carries an **AccountCard** (Firebase email + uid + Sign-out) and an **Integrations** section with `views/ConnectGoogleCalendar.tsx` (Connect / Disconnect / status badge).
- `Onboarding.tsx` pre-fills the email field from `auth.currentUser` and routes through the new `window.zylch.onboarding.createProfileForFirebaseUser(uid, email, values)` IPC, which writes the profile to `~/.zylch/profiles/<firebase_uid>/` (keyed by immutable UID, not email).

### Views
- **Chat** — assistant conversation, attachments, prompt-cached system prompt.
- **Tasks** — open/closed toggle, search, pin, skip, close (with optional note), reopen, reanalyze, open-in-workspace. Thread-filter mode when entered from Inbox "Open".
- **Emails** — Inbox + Sent tabs, thread reading pane with HTML body in sandboxed iframe, archive (IMAP MOVE) + delete (local soft-delete) buttons, "Open" jumps to Tasks filtered by thread.
- **Settings** — schema-driven editor over the engine's profile `.env`. `USER_SECRET_INSTRUCTIONS` unmasked. `DOWNLOADS_DIR` shown with directory picker hint. **AccountCard + Integrations sections at the top (Firebase signin + Google Calendar OAuth)**.
- **Onboarding wizard** — Firebase-aware: shows the signed-in user's email + uid prefix at the top, pre-fills the form, writes a UID-keyed profile dir.
- **SignIn screen** — email/password gate wrapping everything else.

### IPC client (preload)
- All `window.zylch.*` calls go through `ipcRenderer.invoke('rpc:call', method, params, timeout)`. Single chokepoint at `app/src/preload/index.ts`.
- Notification fan-out for streaming RPCs (`tasks.solve.event`, `update.run` progress, `google.calendar.auth_url_ready`).
- Optional timeout per method — pin/reanalyze/listByThread have explicit longer timeouts; `google.calendar.connect` gets 5.5 min for the user to consent.
- New namespaces this session: `account.{setFirebaseToken,signOut,whoAmI}`, `mrcall.listMyBusinesses`, `google.calendar.{connect,disconnect,status,cancel}`, `shell.openExternal`. Plus `onboarding.createProfileForFirebaseUser(uid, email, values)`.

### Sidecar lifecycle (main)
- Sidecar binary path resolves from `ZYLCH_BINARY` env or default `~/private/zylch-standalone/venv/bin/zylch` (dev). Packaged builds use the bundled `app/bin/zylch`.
- `cwd` defaults to `homedir()` (`f1969bb5`) so signed/notarized builds don't reach into a dev path.
- Profile-aware: each Electron window owns one profile (one email). Profile dir is locked via fcntl by the sidecar.

### Packaging
- electron-builder produces `MrCall Desktop-<ver>-arm64.dmg` (macOS Apple Silicon), `MrCall Desktop-<ver>-x64.dmg` (macOS Intel, opt-in via `v*-intel` tag), `MrCall Desktop-Setup-<ver>-x64.exe` (Windows NSIS).
- macOS code-signed + notarized via afterSign hook (`3a3eb522`). Windows installers not yet signed.
- Sidecar built by `.github/workflows/release.yml` via PyInstaller in the same run, downloaded into `app/bin/` before electron-builder runs.

## What Was Completed This Session

**Firebase signin landing — app side (commits `25e668b..11f4cbe`, all pushed).**

- `firebase/config.ts`, `firebase/authUtils.ts`, `views/SignIn.tsx`, `views/ConnectGoogleCalendar.tsx` — new files. `firebase` SDK added to `package.json`.
- `App.tsx` wraps the existing `AppRouter` in `FirebaseAuthGate`; exports `performSignOut()` (clears engine session via `account.signOut`, then Firebase `signOut`); `setTokenPusher` wired so the renderer keeps the engine's in-memory session fresh.
- `Onboarding.tsx` — Firebase-aware: pre-fills email from `auth.currentUser`, routes new profiles through `createProfileForFirebaseUser(uid, email, values)`, shows "Signed in as …" header + Sign-out shortcut.
- `Settings.tsx` — added `AccountCard` and `Integrations` sections at the top.
- `preload/index.ts` + `renderer/src/types.ts` — new namespaces `account`, `mrcall`, `google.calendar`, `shell`. Plus `onboarding.createProfileForFirebaseUser`.
- `main/index.ts` — new IPC `shell:openExternal` (validates http(s), delegates to Electron `shell.openExternal`); new `onboarding:createProfileForFirebaseUser` handler.
- `main/profileFS.ts` — new `createProfileForFirebaseUser` that writes `~/.zylch/profiles/<firebase_uid>/.env` with `OWNER_ID + EMAIL_ADDRESS`. `KNOWN_KEYS` gains `OWNER_ID` and `GOOGLE_CALENDAR_CLIENT_ID`.

Verified: `npm run typecheck` clean at every commit; `npm run dev` end-to-end NOT exercised from this machine.

## What Is In Progress

- **Live verification of the Firebase landing in the running Electron app — pending.** Compiles + typechecks; a real signin / engine round-trip / Calendar OAuth needs the user to run `npm run dev`. No automated harness for this.
- Mac validation of pre-existing flows still pending: close-note UI (composer keyboard shortcuts, closed-view rendering, reopen clears note), IMAP archive folder discovery, Open → Tasks filter behaviour.

## Immediate Next Steps

1. `cd app && npm run dev` → sign in with the dashboard account → verify `account.who_am_i` returns the expected uid/email + `mrcall.list_my_businesses` returns the businesses.
2. Configure `GOOGLE_CALENDAR_CLIENT_ID` in Settings (Desktop-app or Web OAuth client with redirect `http://127.0.0.1:19275/oauth2/google/callback`), click "Connect Google Calendar" in Settings → confirm consent flow + token persistence.
3. Bundle the Mac validations for the prior UI flows (close-note, archive, Open→Tasks) once the Firebase end-to-end is green.

## Known Issues

- **No live end-to-end verification of the Firebase landing.** Smoke covers dispatcher + error paths only.
- **Onboarding flow has no sidecar yet.** When the FirebaseAuthGate is satisfied but the user is in onboarding (no profile dir → no sidecar), `account.setFirebaseToken` calls fail; the wired pusher swallows the error at debug level. Token gets pushed for real once the post-onboarding window spawns its sidecar. Acceptable; documented in the App.tsx comment.
- Renderer's `tasks.complete` notification path: there is no `tasks.complete.changed` notification, so other windows on the same profile won't update their task list until the user refreshes. (Same gap as `tasks.skip`, `tasks.reopen`.)
- No unit test coverage on the renderer side. The IPC contract is the only enforcement; payload shape mismatches surface only at runtime.
