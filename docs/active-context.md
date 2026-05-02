---
description: |
  Cross-cutting state of mrcall-desktop as of 2026-05-02. Things that span
  the engine ↔ app boundary or the repo as a whole — JSON-RPC contract
  drift, release pipeline, brand/rename rollout, monorepo conventions.
  Engine-only state lives in ../engine/docs/active-context.md; app-only
  state in ../app/docs/active-context.md.
---

# Active Context — Cross-cutting

This file is young. Cross-cutting facts historically lived inside
`engine/docs/active-context.md` (the engine doc tree played a dual role).
Facts migrate here as they get touched.

## What Is Built and Working

### Firebase Auth as desktop identity (2026-05-02 landing)
- The renderer is gated by `FirebaseAuthGate` (in `app/src/renderer/src/App.tsx`) on top of `auth.currentUser`. Unsigned-in state shows `views/SignIn.tsx` (email/password); Google + magic-link signins are deferred.
- Same Firebase project as the dashboard (`talkmeapp-e696c`) so a single account works on both surfaces. Config hard-coded in `app/src/renderer/src/firebase/config.ts` (public-by-design — the Firebase JS SDK ships its config).
- Renderer pushes the ID token to the engine over JSON-RPC (`account.set_firebase_token`); engine holds it in-memory only (`zylch/auth/session.py` singleton). 50-min proactive refresh in `firebase/authUtils.ts` re-pushes on the same RPC. Sign-out clears both ends.
- Profiles created post-signin are keyed by **immutable Firebase UID** at `~/.zylch/profiles/<firebase_uid>/`. The `.env` carries `OWNER_ID=<uid>` + `EMAIL_ADDRESS=<email>` so engine owner-scoped storage (`OAuthToken` etc.) binds to the same identifier the renderer pushes. Legacy email-keyed profiles still work; `engine/scripts/migrate_profile_to_uid.py` upgrades them on demand.
- StarChat calls from the engine ride this session: `engine/zylch/tools/starchat_firebase.py:make_starchat_client_from_firebase_session()` returns a `StarChatClient(auth_type="firebase")`. First reachable surface: `mrcall.list_my_businesses` RPC (mirrors the dashboard's `Business.checkUserHasBusinesses`).
- Google Calendar adds an *incremental* OAuth — separate from Firebase signin. PKCE flow on `127.0.0.1:19275`, `calendar.readonly` scope, `access_type=offline` + `prompt=consent` so refresh_token always issued. Tokens persisted via `Storage.save_provider_credentials(uid, "google_calendar", …)`. The Calendar ID the desktop reads from is `DEFAULT_CALENDAR_ID = "primary"` (single Google account → primary calendar; secondary calendars out of scope).
- Settings exposes `GOOGLE_CALENDAR_CLIENT_ID` (no client secret — Google's PKCE flow doesn't use one for desktop / installed-app clients).
- Legacy CLI MrCall PKCE flow on `:19274` (`zylch init` wizard) is untouched — orthogonal to the desktop signin.

### JSON-RPC contract (engine ↔ app)
- Server: `engine/zylch/rpc/methods.py` (dispatch table) + per-domain modules (`email_actions.py`, `task_queries.py`, `account.py`, `mrcall_actions.py`, `google_actions.py`).
- Client: `app/src/preload/index.ts` (`window.zylch.*` surface) + main-process bridge (`ipcMain.handle('rpc:call', …)`).
- Transport: stdio JSON-RPC. Sidecar spawned by main process.
- Notification fan-out: streaming methods (`tasks.solve.event`, `update.run` progress, `google.calendar.auth_url_ready`) emit `notify` events that the main process forwards to the renderer via `webContents.send`.
- New surfaces this session: `account.{set_firebase_token,sign_out,who_am_i}`, `mrcall.list_my_businesses`, `google.calendar.{connect,disconnect,status,cancel}`, `shell:openExternal` IPC (renderer-side; for opening consent URLs in the user's default browser). Total methods: 33.
- Method surface tracked in [`ipc-contract.md`](ipc-contract.md).

### Release pipeline
- Tag-driven matrix: `v*` → macOS arm64 + Windows x64; `v*-intel` → also macOS Intel x64 on a paid larger runner.
- Sidecar built in-flight via PyInstaller in `engine/`, copied to `app/bin/` before electron-builder runs. No external sidecar repo to fetch from.
- macOS code-signed + notarized via the afterSign hook (`3a3eb522`); APPLE_TEAM_ID passed explicitly to notarytool (`5b8ad979`); creds validated before build (`2477b23a`).
- Windows installers not yet code-signed.
- Plan: [`execution-plans/release-and-rename-l2.md`](execution-plans/release-and-rename-l2.md) (status: in-progress).

### Brand / rename rollout (Level 2)
- User-visible everywhere: "MrCall Desktop". `appId = ai.mrcall.desktop`.
- Engine-internal (intentional, deferred to Level 3 sweep): `zylch.*` Python package, `zylch` CLI, `~/.zylch/` data dir, `ZYLCH_*` env vars. Treat as synonyms; do not introduce new `zylch` strings.

### Documentation structure (three-tree model)
- Three `docs/` trees parallel to three `CLAUDE.md` files:
  - `./docs/` — cross-cutting (this file lives here)
  - `./engine/docs/` — Python sidecar
  - `./app/docs/` — Electron + React frontend
- Single set of `/doc-startsession`, `/doc-intrasession`, `/doc-endsession` slash commands at `.claude/commands/` — they read from and write to all three trees, routing each fact to the tree that owns it.

## What Was Completed This Session

**Firebase signin landing (commits `25e668b..11f4cbe` on `main`, all pushed).** Five phases plus a follow-up package-init fix and a migration script:

- **Phase 1 `25e668b`** — Firebase JS SDK in renderer; `FirebaseAuthGate` wraps the whole app; `views/SignIn.tsx` for email/password.
- **Phase 2 `35eecdf`** — engine `zylch.auth.FirebaseSession` singleton + `account.set_firebase_token / sign_out / who_am_i` RPCs; renderer wires `setTokenPusher` via `firebase/authUtils.ts` to push tokens on signin and on every 50-min refresh.
- **Phase 3 `812dafd`** — `engine/zylch/tools/starchat_firebase.py` factory + `mrcall.list_my_businesses` RPC (renderer-callable via `window.zylch.mrcall.listMyBusinesses`). Lives outside `tools/mrcall/` because that package's `__init__.py` was broken.
- **Phase 4 `48ab6b2`** — `engine/zylch/tools/google/calendar_oauth.py` (PKCE on `127.0.0.1:19275`) + `google.calendar.{connect,disconnect,status,cancel}` RPCs; `shell:openExternal` IPC for opening consent URLs in the default browser; `GOOGLE_CALENDAR_CLIENT_ID` setting.
- **Phase 5 `cc62084`** — `createProfileForFirebaseUser(uid, email, values)` IPC; `Onboarding.tsx` pre-fills email from `auth.currentUser`; `views/ConnectGoogleCalendar.tsx` + `AccountCard` in `Settings.tsx`. Doc updates at `mrcall-desktop/CLAUDE.md` (Firebase Identity section), meta-repo `docs/ARCHITECTURE.md` + `docs/system-rules.md` + `CLAUDE.md` (committed in meta-repo as `e562271`).
- **Cleanup `d62506c`** — `zylch.tools.mrcall` package init unbroken: stripped four imports of never-tracked sibling modules (`variable_utils`, `llm_helper`, `config_tools`, `feature_context_tool`); moved the new factory back into `tools/mrcall/starchat_firebase.py`. Verified via `git log --all --diff-filter=A` that those modules were never present.
- **Migration script `7bfcd93`** — `engine/scripts/migrate_profile_to_uid.py --email <e> --uid <uid>` atomically renames `~/.zylch/profiles/<email>/` → `<uid>/` and patches `.env` with `OWNER_ID + EMAIL_ADDRESS`. `--dry-run` and `--force` supported. Live-tested in a sandbox HOME (rename + .env patch + bad-input rejection + `--force` overwrite).
- **Calendar default + cleanup brief `11f4cbe`** — added `DEFAULT_CALENDAR_ID = "primary"` constant. New brief `docs/execution-plans/cleanup-mrcall-configurator-deadcode.md` (`status: planned`) covering the dead `MrCallConfiguratorTrainer` references in `command_handlers.py` + `factory.py:_create_mrcall_tools` + `tests/test_mrcall_integration.py` — recommends DELETE over IMPLEMENT, audit trail via commit `d62506c`, with verification steps.

## What Is In Progress

- **"Continue with Google" on the Firebase signin gate (2026-05-02).** First cut landed: `app/src/main/googleSignin.ts` runs PKCE OAuth on `127.0.0.1:19276` in the main process (engine isn't up yet in onboarding mode), main-process IPC `signin:googleStart` / `signin:googleCancel`, preload + types, "Continue with Google" button on `SignIn.tsx` that trades the Google id_token for a Firebase session via `signInWithCredential`. CSP unchanged — `signInWithCredential` hits the already-allowed `identitytoolkit.googleapis.com`; Google consent runs in the system browser; token exchange runs in Node (not the renderer). Configured at runtime via `GOOGLE_SIGNIN_CLIENT_ID` env var in dev. Plan: [`execution-plans/google-signin.md`](execution-plans/google-signin.md). End-to-end live test still pending — needs the user to create a Google OAuth client and run `GOOGLE_SIGNIN_CLIENT_ID=… npm run dev`.
- **CSP fix for Firebase signin (commit `451526a`, pushed to `main` 2026-05-02).** `connect-src` was missing, so the renderer's `default-src 'self'` blocked all Firebase Auth requests; the JS SDK threw `auth/network-request-failed` and the SignIn screen rendered "Network error reaching Firebase. Check your connection." Added `connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com`. Live verification of email/password signin still pending.
- **Live verification of the Firebase landing in the running Electron app — pending.** Smoke tests cover dispatcher registration + every `account.*` / `mrcall.*` / `google.calendar.*` error path without a session, but the real `npm run dev` + signin + StarChat round-trip + Calendar OAuth (with a configured `GOOGLE_CALENDAR_CLIENT_ID`) was not exercised. This is the user's call.
- Cleanup of dead `MrCallConfiguratorTrainer` references — brief landed (`docs/execution-plans/cleanup-mrcall-configurator-deadcode.md`), execution deferred to a dedicated PR.
- Release pipeline: see `execution-plans/release-and-rename-l2.md`. Tag-driven matrix done; signing on macOS done; Windows signing pending; Level 3 rename sweep pending.

## Immediate Next Steps

1. Live test the Firebase landing: `cd app && npm run dev`, sign in with the dashboard account, confirm `account.who_am_i` returns the expected uid/email, exercise `mrcall.list_my_businesses` against StarChat.
2. Configure `GOOGLE_CALENDAR_CLIENT_ID` (Desktop-app or Web OAuth client with redirect `http://127.0.0.1:19275/oauth2/google/callback`) and run "Connect Google Calendar" from Settings; verify token persistence in `OAuthToken` (`provider='google_calendar'`).
3. Open a follow-up PR per `cleanup-mrcall-configurator-deadcode.md` once the Firebase round-trip is validated. Self-contained — fresh agent should pick it up cold.
4. Wire `engine/zylch/tools/calendar_sync.py` to the new `provider='google_calendar'` tokens (current sync code is partial pre-existing scaffolding; reading from the encrypted store is a small change).

## Known Issues

- **No live end-to-end verification.** The Firebase / StarChat / Calendar surface compiles and dispatches correctly, but the real round-trip in a browser/Electron context has not been exercised from this machine.
- **Dead configurator references.** `command_handlers.py` (`/mrcall config`, `/mrcall train`, `/mrcall feature`) and `factory.py:_create_mrcall_tools` reference `MrCallConfiguratorTrainer`, `GetAssistantCatalogTool`, `ConfigureAssistantTool`, etc. — symbols that were never tracked in this repo. Currently graceful-degraded (`/mrcall config` short-circuits with "MrCall is not available"). `engine/tests/test_mrcall_integration.py` is similarly dead. Brief at `docs/execution-plans/cleanup-mrcall-configurator-deadcode.md`.
- **No automated contract test for IPC method/payload changes.** Tracked in [`harness-backlog.md`](harness-backlog.md). The 8 RPC methods added this session are typed on the renderer side via `app/src/renderer/src/types.ts`, but engine ↔ preload divergence still surfaces only at runtime.
- **Legacy email-keyed profiles** are not auto-migrated. Users who signed in with email pre-2026-05 keep working, but their on-disk profile dir name is the email. Use `engine/scripts/migrate_profile_to_uid.py` to upgrade.
