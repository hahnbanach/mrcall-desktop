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

## Workspace + agentic Open flow (2026-05-11/12)

The Tasks-list `Open` button no longer pre-fills the chat input
with a static template (`"Aiutami a gestire questa task. …"` — the
`buildTemplate` helper is gone). It calls `openTaskChat(t)` which
upserts a `task-<id>` conversation AND fires
`window.zylch.tasks.solve(task.id)`. The engine streams events on
`tasks.solve.event`; `Workspace.tsx` listens and renders.

### Renderer flow

- `store/conversations.ts:openTaskChat`:
  - Reads `task.sources.thread_id` → `Conversation.threadId`
    (Source panel uses this directly — no longer routes through
    `useThread` global store for the panel itself, only for
    inter-view coordination).
  - Reads `task.completed_at` → `Conversation.taskCompleted`.
  - `shouldStartSolve = !taskCompleted && (!existing || (history empty AND no pendingApproval))`.
    Skips solve on closed tasks unconditionally; skips on
    already-populated convs so a second `Open` doesn't burn
    ~$0.025 of Sonnet inadvertently.
  - When solve is fired, `window.zylch.tasks.solve(taskId)` runs
    fire-and-forget, busy=true is set, and `solvesInFlight` (a
    module-level Set) tracks the conv id for `closeConversation`
    to issue `tasks.solveCancel` if the user closes mid-run.
- `views/Tasks.tsx:Open` button calls `openTaskChat(t)`
  **unconditionally** (no `if (!exists)` branch). The store's
  upsert preserves history and refreshes `threadId` +
  `taskCompleted` from the latest `tasks.list` payload — legacy
  convs in localStorage converge to the new shape on first Open.
- `views/Workspace.tsx`:
  - Listens to `tasks.solve.event`. `thinking` → assistant bubble;
    `tool_use_start` → narration swap ("Sto cercando nella
    memoria…" / "Sto eseguendo il codice…" / …, mapped by
    `narrationForTool`); `tool_call_pending` → set
    `pendingApproval.mode='solve'`; `tool_result` → clear
    narration (output not rendered to keep chat clean); `done` →
    busy false; `error` → `⚠ <message>` bubble + busy false.
  - `onApproval` discriminates on `pending.mode`:
    - chat → `chat.approve({ mode: 'once'|'session'|'deny' })` (3 buttons).
    - solve → `'once'` calls `tasks.solveApprove({ approved: true })`;
      `'deny'` calls `tasks.solveCancel()` (NOT
      `solveApprove({approved:false})` — that would let the engine
      feed "User declined" back into the LLM and the model would
      propose alternatives, defeating the user's intent).
  - `ApprovalCard` is mode-aware: solve mode hides the "Allow for
    session" button (solves are one-shot) and renames the primary
    button to a tool-specific label ("Invia email" / "Invia
    WhatsApp" / "Esegui" / "Aggiorna memoria") via `labelForSolve`.
    Cancel button reads "Annulla".

### Read-only on closed tasks

A `Conversation` with `taskCompleted=true` opens in view-only mode:
- History + Source panel visible.
- Composer disabled with placeholder *"Task chiusa — riaprila per
  scrivere."*.
- `openTaskChat`'s `shouldStartSolve` short-circuits to false →
  no LLM call.
- Header button reads "Riapri" (calls `tasks.reopen` →
  `patchConversation(id, {taskCompleted: false})` flips the conv
  to active in place; composer unlocks; no automatic solve — user
  decides what to do next).

The Conversation context now exposes `patchConversation(id, patch)`
for partial mutations that don't change `activeId` (used by the
Riapri handler and by the mount-time backfill). Reducer-level
`PATCH_CONV` action.

### Source panel persistence

`Conversation.threadId` (set by `openTaskChat` from
`task.sources.thread_id`, populated by engine's 2026-04-17
`_backfill_task_thread_id`) is the priority source for
`Workspace.tsx:sourceThreadId`. Fallback: thread store's
`activeThreadId` (only when `activeTaskId` matches active conv —
used for the Tasks → Open path). The `useEffect` on `active.id`
mirrors `active.threadId` into the global thread store so Email
view's open-from-thread shortcut stays in sync.

**Mount-time backfill** in `ConversationsProvider`: when
`profileKey` resolves, scans persisted task-convs for missing
`threadId` and/or missing `taskCompleted`, calls `tasks.list`
once with `include_completed: true`, patches both fields per
conv. Fire-and-forget; failures degrade silently. Covers the
case where Mario merged the refactor on top of a populated
localStorage and would otherwise have empty Source panels on
every pre-refactor conv until reopened from Tasks.

### Closed-task UX gotcha

The legacy `buildTemplate` precompiled prompt is gone, but old
convs persisted in localStorage retain the stale `draftInput`
string. `loadPersisted` resets `draftInput` to `""` on any
task-conv with empty history — covers the transition without a
forced cache wipe. Free-chat conversations (no taskId) keep
their drafts.

### Engine-side counterpart

- `tasks.solve(task_id)` builds the prompt with
  `SOLVE_SYSTEM_PROMPT` + `get_personal_data_section(owner_id)` +
  `get_user_language_directive()` (reads `USER_LANGUAGE` env,
  defaults to "match incoming message", Italian as final
  tiebreaker).
- `TaskExecutor` emits `tool_use_start` before every tool
  (including read-only ones — fix for "nessun segnale di vita"
  during a `search_memory` or `run_python`).
- `APPROVAL_TOOLS` includes the SOLVE_TOOLS naming
  (`send_email`, `send_whatsapp`) AND the ChatService factory
  naming (`send_draft`, `send_whatsapp_message`) — both surfaces
  share the gate. Was a latent safety gap before this session.
- `CancelledError` caught separately in `run()`: yields a clean
  `done` event with `result.cancelled=True` instead of `error`.

Full IPC contract in [`../../docs/ipc-contract.md`](../../docs/ipc-contract.md).
Cross-cutting recap in [`../../docs/active-context.md`](../../docs/active-context.md).
Engine prompt + helpers in [`../../engine/docs/active-context.md`](../../engine/docs/active-context.md).

Recent commits (newest first):
- `b36e15b3` fix: Annulla on solve approval cancels the run.
- `a1896df6` feat(app): closed tasks read-only; Riapri ↔ Marca come fatta.
- `336bc152` fix: Source panel + progress narration for solve.
- `4cd8ec39` fix(app): Source panel follows sidebar switches.
- `df1e1fb1` feat: proactive task "Open" — first cut.

## What Is Built and Working

### Identity (Firebase, 2026-05-02)
- `FirebaseAuthGate` in `App.tsx` wraps the entire app. Unsigned-in users see `views/SignIn.tsx` — **email/password and "Continue with Google"** (PKCE → Firebase `signInWithCredential`); magic links remain deferred.
- Firebase config hard-coded in `firebase/config.ts` (project `talkmeapp-e696c`, same as the dashboard — single MrCall account spans both surfaces). **Persistence is `inMemoryPersistence` (post-`bc011be`)**: every app launch shows the SignIn screen. The previous indexedDB/local-storage persistence let a stale Firebase session silently survive across launches and decouple from the on-disk profile, so a wrong-account state could surface.
- `firebase/authUtils.ts` listens to `onAuthStateChanged`, pushes the ID token to the engine via `window.zylch.account.setFirebaseToken` on every signin and on a 50-min proactive refresh interval.
- **UID-keyed profile binding (post-`bc011be`).** Every BrowserWindow now boots into an *auth-pending* state with NO sidecar. After Firebase signin the renderer calls `window.zylch.auth.bindProfile(uid)`; main attaches a sidecar bound to `~/.zylch/profiles/<firebase_uid>/`. If the dir doesn't exist, the renderer routes to `Onboarding.tsx` which creates it via `onboarding.createProfileForFirebaseUser(uid, email, values)` and the same window then attaches in-place — Firebase auth state preserved, no second signin. Sign-out + re-signin as a different user swaps the sidecar in-place.
- **IdentityBanner** at the top of every authenticated window: "Signed in as `<email>` (uid `<prefix>…`)" + one-click *Sign out*. Wrong-account state surfaces in seconds.
- **No legacy escape hatch (removed 2026-05-12).** Every window goes through `FirebaseAuthGate`. The "Other profiles" dropdown opens a fresh auth-pending window with the picked profile's email pre-filled in SignIn (`?email=` URL hint, hint-only — bindProfile uses the signed-in UID). "+ Sign in to another account" opens an auth-pending window with no pre-fill.
- `Settings.tsx` carries an **AccountCard** (Firebase email + uid + Sign-out) and an **Integrations** section with `views/ConnectGoogleCalendar.tsx` (Connect / Disconnect / status badge).
- `Onboarding.tsx` pre-fills the email field from `auth.currentUser` and writes the profile to `~/.zylch/profiles/<firebase_uid>/` (keyed by immutable UID, not email).

### Views
- **Chat** — assistant conversation, attachments, prompt-cached system prompt.
- **Tasks** — open/closed toggle, search, pin, skip, close (with optional note), reopen, reanalyze, open-in-workspace. Thread-filter mode when entered from Inbox "Open".
- **Emails** — Inbox + Sent tabs, thread reading pane with HTML body in sandboxed iframe, archive (IMAP MOVE) + delete (local soft-delete) buttons, "Open" jumps to Tasks filtered by thread. **Gmail-style search bar** above the thread list (under the folder toolbar): submit on Enter, clear with × or Escape, "?" pops a help panel listing operators. Backed by the new `emails.search` JSON-RPC; resets when the user switches folder so the box never carries a stale query into a folder that won't honour it. Drafts hide the search bar (no backend support).
- **Settings** — schema-driven editor over the engine's profile `.env`. `USER_SECRET_INSTRUCTIONS` unmasked. `DOWNLOADS_DIR` shown with directory picker hint. **AccountCard + Integrations sections at the top (Firebase signin + Google Calendar OAuth)**. **`LLMProviderCard` at the top of the LLM group (BYOK vs MrCall credits — see "MrCall credits v1" below)**.
- **Onboarding wizard** — Firebase-aware: shows the signed-in user's email + uid prefix at the top, pre-fills the form, writes a UID-keyed profile dir. **No LLM provider / API-key fields (since 2026-05-04)**: profiles are created with no `SYSTEM_LLM_PROVIDER` and no key in `.env`, so the engine resolver defaults them to MrCall credits. To opt into BYOK the user adds `ANTHROPIC_API_KEY=…` to `~/.zylch/profiles/<uid>/.env` after setup, or flips the `LLMProviderCard` toggle in Settings.
- **SignIn screen** — email/password + "Continue with Google". Friendly error mapping for `auth/network-request-failed`, `auth/invalid-credential`, `auth/account-exists-with-different-credential`, `auth/popup-closed-by-user`, `auth/cancelled-popup-request`. Inline busy state for Google flow ("Opening Google sign-in in your browser…" → "Signing in to Firebase…").

### MrCall credits v1 (2026-05-03, branch `feat/mrcall-credits-v1`, tip `3001844`)

- `views/Settings.tsx` carries an `LLMProviderCard` at the top of the LLM settings group. **As of the 2026-05-04 transport refactor** the card mirrors the engine's rule directly: it shows **BYOK (Anthropic key)** when `ANTHROPIC_API_KEY` is set in `.env`, otherwise **MrCall credits**. There is no `SYSTEM_LLM_PROVIDER` setting anymore — the card only exposes a "Switch to MrCall credits" action that clears the key, and reveals the schema-driven `ANTHROPIC_API_KEY` field below for paste-in. OpenAI as a separate option is gone (it was dead code in the engine).
- "MrCall credits" requires a live Firebase signin; the card disables itself with an explanatory hint when `auth.currentUser` is null. Picking BYOK keeps whichever of `anthropic` / `openai` was last selected (defaulting to `anthropic`).
- Balance display: when "MrCall credits" is active and the user is signed in, the card calls `window.zylch.account.balance()` on mount and on every `window` `focus` event (so a top-up done in another tab updates the displayed balance once the user returns). Loading / error / `auth_expired` states each render their own line — no silent failure.
- "Top up" button: `shell.openExternal('https://dashboard.mrcall.ai/plan')` — bare `/plan`, no `business_id` (the dashboard resolves the active business from the user's Firebase auth state). The constant lives in `views/Settings.tsx` as `TOPUP_URL`.
- Preload binding: `window.zylch.account.balance(): Promise<BalancePayload | { error: 'auth_expired' }>` at `app/src/preload/index.ts` (15 s timeout). Returns the proxy's payload verbatim — `balance_credits`, `balance_micro_usd`, `balance_usd`, `granularity_micro_usd?`, `estimate_messages_remaining?` — so a server-side schema change doesn't require a desktop release.
- Renderer types: `account.balance` typed on `ZylchAPI` in `app/src/renderer/src/types.ts`.
- The Anthropic API key lives server-side on `mrcall-agent`; the desktop only sends the Firebase JWT (engine-side, via `MrCallProxyClient` — see `../../engine/docs/active-context.md` "MrCall-credits v1 — engine side"). All credits live in StarChat's existing `CALLCREDIT` pool — there is no separate LLM-only category. 1 credit = €0.01.
- Live verification pending: full round-trip needs `npm run dev` + Firebase signin + flip Settings to "MrCall credits" + send a chat message + observe the balance ticker drop + exhaust to 402 + click "Top up" + balance refresh on return.

### "Continue with Google" (2026-05-02 first cut, commits `057d9de..b6739d5`)
- `app/src/main/googleSignin.ts` runs PKCE OAuth on `127.0.0.1:19276` in the main process — no sidecar dependency, so the flow works during onboarding/auth-pending boot. Single in-flight flow at a time; concurrent calls cancel the prior. 5-min consent timeout.
- IPC `signin:googleStart` opens the consent URL in the system browser via `shell.openExternal`, awaits the loopback callback, exchanges the code at `oauth2.googleapis.com/token`, returns `{ idToken, email }`. `signin:googleCancel` aborts an in-flight flow.
- Renderer hands the resulting Google id_token to Firebase via `signInWithCredential(auth, GoogleAuthProvider.credential(idToken))`. `FirebaseAuthGate` then sees `auth.currentUser` and unmounts the SignIn screen.
- Token exchange POST includes `client_secret` — Google enforces it for Desktop OAuth clients even on the PKCE flow (returns `400 invalid_request: client_secret is missing` otherwise). See "OAuth secret management" section above.
- **CSP** unchanged — `signInWithCredential` reaches the already-allowed `identitytoolkit.googleapis.com`; consent runs in the system browser; token exchange runs in Node. Plan: [`../../docs/execution-plans/google-signin.md`](../../docs/execution-plans/google-signin.md).

### IPC client (preload)
- Engine RPCs go through `ipcRenderer.invoke('rpc:call', method, params, timeout)` to the per-window sidecar. Single chokepoint at `app/src/preload/index.ts`.
- Renderer-only IPCs (no engine involvement) use named channels: `shell:openExternal`, `signin:googleStart` / `signin:googleCancel`, `auth:bindProfile`, `onboarding:isFirstRun`, `onboarding:createProfile`, `onboarding:createProfileForFirebaseUser`, `onboarding:finalize`, `dialog:selectFiles`, `dialog:selectDirectories`, `profile:current`, `profiles:list`, `window:openForProfile`, `sidecar:restart`. These run in main process and never reach the sidecar.
- Notification fan-out for streaming RPCs (`tasks.solve.event`, `update.run` progress, `google.calendar.auth_url_ready`).
- Optional timeout per method — pin/reanalyze/listByThread have explicit longer timeouts; `google.calendar.connect` gets 5.5 min for the user to consent; `signin:googleStart` allows up to 5 min for browser consent.
- Renderer-side namespace organisation: `tasks`, `chat`, `update`, `emails`, `files`, `profile`, `profiles`, `window`, `narration`, `settings`, `sidecar`, `account`, `mrcall`, `google.calendar`, `shell`, `signin`, `auth`, `onboarding`.

### Profile picker — emails instead of raw UIDs (this session)
- After the UID-keyed profile binding (`bc011be`), every "+ New Window for Profile" picker, the sidebar `ProfilesDropdown`, the window title, and the `IdentityBanner` derived label all rendered the directory name — which for fresh post-Firebase profiles is the Firebase UID (long hex string), not an email. Confirmed visually on the Mac clone today.
- Fix: `profile:current` and `profiles:list` IPC return shape changed from `string` / `string[]` to `{id: string; email: string | null}` / array thereof. Email is parsed from each profile's `.env` (`EMAIL_ADDRESS=…`) by a tiny dotenv reader added to `main/profileFS.ts:readProfileEnvValue` (mirror of the existing `dotenvQuote` writer — handles single-quote shlex style, double-quote escapes, and bare values). `listProfilesWithEmail()` wraps the directory enumeration. Renderer call sites (`App.tsx` mount, `ProfilePickerDialog`, `ProfilesDropdown`, `store/conversations.ts`) now display the email and key state by id; the dir id stays the lookup key for `window.openForProfile(id)` and the localStorage bucket so neither breaks when EMAIL_ADDRESS changes.
- Fallback: when `.env` is missing or unreadable, the picker falls back to the dir id as the label (same as the old behaviour) and `email` is null. A tooltip shows `Profile dir: <id>` whenever email is present so the UID is still discoverable.
- Live test: typecheck clean; node smoke script verified the .env reader against 4 fixtures (UID+plain email, UID+shlex-quoted email, legacy email-as-dir, missing .env). The actual Mac picker behaviour is the next click — not exercised from this machine.

### Sidecar lifecycle (main)
- Sidecar binary path resolves from `ZYLCH_BINARY` env or default `~/private/zylch-standalone/venv/bin/zylch` (dev). Packaged builds use the bundled `app/bin/zylch`.
- `cwd` defaults to `homedir()` (`f1969bb5`) so signed/notarized builds don't reach into a dev path.
- **Auth-pending boot.** Every window opens with NO sidecar; the sidecar attaches after `auth.bindProfile(uid)` resolves a profile dir. Sign-out + re-signin can swap the sidecar in-place on the same window. No escape hatch — all windows go through Firebase signin (post 2026-05-12 cleanup).
- Profile-aware: each window owns one profile. Profile dir is locked via fcntl by the sidecar.

### OAuth secret management (Google sign-in, 2026-05-02)
- The Desktop OAuth client lives in `talkmeapp-e696c` Google Cloud project; Client ID is committed in `app/src/main/oauthConfig.ts`, Client secret stays out of git.
- `app/src/main/oauthSecrets.ts` is **gitignored** (see `app/.gitignore:15`). Holds `GOOGLE_SIGNIN_CLIENT_SECRET`. Postinstall (`scripts/setup-oauth-secrets.mjs`) seeds it from the committed `oauthSecrets.example.ts` template on first `npm install` so a fresh clone builds.
- The `GOCSPX-` prefix is autodetected by GitHub Secret Scanning, which would notify Google → auto-revoke within minutes — the gitignore is mandatory regardless of what Google's docs say about installed-app secrets being "non-confidential".
- Dev: developer pastes the real value into the local `oauthSecrets.ts`.
- CI / packaged builds: `release.yml` runs `node scripts/write-oauth-secrets.mjs` between `npm ci` and `npm run dist`. The script reads `GOOGLE_SIGNIN_CLIENT_SECRET` from the workflow env (sourced from a repo secret), validates the `GOCSPX-` prefix, writes the file. Vite/Rollup inlines the constant during `electron-vite build`; the secret rides inside the bundled `out/main/index.js` → `.dmg` / `.exe`. End users install and click "Continue with Google" without local setup.

### Packaging
- electron-builder produces `MrCall Desktop-<ver>-arm64.dmg` (macOS Apple Silicon), `MrCall Desktop-<ver>-x64.dmg` (macOS Intel, opt-in via `v*-intel` tag), `MrCall Desktop-Setup-<ver>-x64.exe` (Windows NSIS).
- macOS code-signed + notarized via afterSign hook (`3a3eb522`). Windows installers not yet signed.
- Sidecar built by `.github/workflows/release.yml` via PyInstaller in the same run, downloaded into `app/bin/` before electron-builder runs.

### WhatsApp tab — privacy gate + auto-reconnect awareness (2026-05-07, commit `9eee73c2`)
- `views/WhatsApp.tsx`: chat list rendered ONLY when `r.connected === true`. Previously the renderer used `r.connected || r.has_session` which kept the last-known thread list visible after Disconnect or while the session was expired (privacy issue: anyone glancing at the screen saw all contacts even though we were offline). SQLite rows are kept on disk; the renderer just refuses to draw them until the socket is back live.
- The connected state is **polled every 3s** while we are offline. As soon as the engine's auto-reconnect at sidecar boot completes, or the user clicks Reconnect, the renderer flips from the `ConnectWhatsApp` card to the live thread list without forcing a tab switch. Polling stops as soon as `connected === true`.
- `views/ConnectWhatsApp.tsx` now states the WhatsApp history limitation right under the standard "local connection" copy: *"WhatsApp only delivers messages to a linked device from the moment it is paired onward, plus a short offline backlog (typically days, at most a couple of weeks). Older history stays on your phone — MrCall Desktop cannot fetch it."* Sets honest expectations for distribution. Live-verified by Mario.
- The privacy gate depends on the engine's `whatsapp.status` returning `connected = is_connected AND is_logged_in` (engine commit in same SHA). Without that fix the renderer would still flash the list during the QR-emit phase.

## What Was Completed This Session (2026-05-02)

Recent commits on `main` (newest last):

- `451526a` **CSP fix.** Added `connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com` to `app/src/renderer/index.html`. Email/password signin was hitting `auth/network-request-failed` because `default-src 'self'` blocked all Firebase Auth traffic.
- `057d9de` **"Continue with Google" first cut.** `app/src/main/googleSignin.ts` (PKCE on :19276), `signin:googleStart` / `signin:googleCancel` IPC, preload + types, button on `SignIn.tsx`. Initial config via `GOOGLE_SIGNIN_CLIENT_ID` env var.
- `642fdae` **Refactor to single config file.** Replaced env-var lookup with `import { GOOGLE_SIGNIN_CLIENT_ID } from './oauthConfig'`. Operator edits one committed file.
- `b2af895` **Wired actual Client ID** into `oauthConfig.ts` (`375340415237-jl3hl6hcu15po65oo7dovl1lb3a960ni.apps.googleusercontent.com`). Project number prefix matches `messagingSenderId` so Firebase trusts the audience.
- `bc011be` **UID-keyed profile binding (by another agent).** In-memory Firebase persistence; auth-pending boot with no sidecar; `auth:bindProfile(uid)` IPC; IdentityBanner; `?legacy=1` escape hatch. Closes the silent identity-drift gap.
- `f5bbf2c` **`client_secret` plumbing + isolation from git.** Google's token endpoint enforces `client_secret` for Desktop OAuth clients — a secret-less request returns `400 client_secret is missing`. Architecture: `oauthConfig.ts` re-exports `GOOGLE_SIGNIN_CLIENT_SECRET` from gitignored `oauthSecrets.ts`; postinstall (`scripts/setup-oauth-secrets.mjs`) seeds from `.example`; developer pastes the real value locally. `googleSignin.exchangeCode` includes the secret in the POST when set.
- `b6739d5` **CI step for packaged releases.** New step in `release.yml` runs `node scripts/write-oauth-secrets.mjs` between `npm ci` and `npm run dist`; reads `GOOGLE_SIGNIN_CLIENT_SECRET` repo secret, validates the `GOCSPX-` prefix, writes `oauthSecrets.ts`. Vite inlines the value into `out/main/index.js`; the `.dmg` / `.exe` ship with the secret embedded — end users don't configure anything.

Verified: `npm run typecheck` clean at every commit; build smoke test confirmed the Vite-only inject + the new CI script writer both produce the expected `out/main/index.js`. Real `npm run dev` end-to-end Google signin NOT exercised from this machine.

## What Is In Progress

- **End-to-end live verification of "Continue with Google" in `npm run dev` — pending.** All plumbing is in place; needs the user to run the dev server with the populated local `oauthSecrets.ts` and click the button. Watch for `auth/account-exists-with-different-credential` if the user already has an email/password account on the same address, and for `redirect_uri_mismatch` (means the client wasn't created as Desktop type).
- **End-to-end live test on a packaged DMG / EXE — pending.** Requires the `GOOGLE_SIGNIN_CLIENT_SECRET` repo secret to be created (Settings → Secrets and variables → Actions) and a `v*` tag push.
- **Live verification of the Firebase email/password signin — pending.** CSP fix is in; needs a user click to confirm.
- Mac validation of pre-existing flows still pending: close-note UI (composer keyboard shortcuts, closed-view rendering, reopen clears note), IMAP archive folder discovery, Open → Tasks filter behaviour.

## Immediate Next Steps

1. `cd app && npm run dev` → click "Continue with Google" → verify the system browser opens consent → `signInWithCredential` succeeds → `IdentityBanner` shows the right email + uid prefix → `auth:bindProfile` either attaches a sidecar or routes to onboarding. Email/password signin can be smoke-tested in the same run.
2. Add `GOOGLE_SIGNIN_CLIENT_SECRET` as a repo secret at *Settings → Secrets and variables → Actions* so a future `v*` tag push produces a packaged build with Google signin baked in.
3. Configure `GOOGLE_CALENDAR_CLIENT_ID` in Settings and exercise "Connect Google Calendar" → confirm consent + token persistence.
4. Bundle the Mac validations for the prior UI flows (close-note, archive, Open→Tasks) once Firebase signin is green.

## Known Issues

- **No live end-to-end verification of any Firebase signin path.** Email/password, Continue with Google, and the engine round-trip after `auth:bindProfile` all compile + typecheck but have not been clicked from this machine.
- **MrCall-credits v1 not live-verified** (branch `feat/mrcall-credits-v1`). Settings card renders, `account.balance` is wired, `MrCallProxyClient` has 8/8 unit tests green, but the live round-trip (signin → flip to credits → chat → balance update → 402 path → top-up) needs the proxy deployed at `https://zylch-test.mrcall.ai` and a click from a real signed-in user.
- **Onboarding-mode invariants not stress-tested.** Auth-pending boot with no sidecar, then `auth:bindProfile` either attaching or routing to onboarding, is the entire signin UX — needs verification on a fresh Mac with empty `~/.zylch/profiles/`.
- Renderer's `tasks.complete` notification path: there is no `tasks.complete.changed` notification, so other windows on the same profile won't update their task list until the user refreshes. (Same gap as `tasks.skip`, `tasks.reopen`.)
- No unit test coverage on the renderer side. The IPC contract is the only enforcement; payload shape mismatches surface only at runtime.
