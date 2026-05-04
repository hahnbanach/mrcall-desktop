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

### Firebase Auth as desktop identity
- The renderer is gated by `FirebaseAuthGate` (`app/src/renderer/src/App.tsx`) on `auth.currentUser`. Unsigned-in state shows `views/SignIn.tsx` — **email/password and "Continue with Google"** (PKCE → `signInWithCredential`); magic links remain deferred.
- Same Firebase project as the dashboard (`talkmeapp-e696c`) so a single account works on both surfaces. Config hard-coded in `app/src/renderer/src/firebase/config.ts` (public-by-design — the Firebase JS SDK ships its config).
- **Persistence is `inMemoryPersistence` (post-`bc011be`).** Every app launch shows the SignIn screen. The previous indexedDB/local-storage persistence let a stale Firebase session silently survive across launches and decouple from the on-disk profile, so a wrong-account state could surface (typing user A's credentials and ending up on user B's data).
- Renderer pushes the ID token to the engine via `account.set_firebase_token`; engine holds it in-memory only (`zylch/auth/session.py` singleton). 50-min proactive refresh in `firebase/authUtils.ts`. Sign-out clears both ends.
- **UID-keyed profile binding.** Every BrowserWindow boots into an *auth-pending* state with NO sidecar. After Firebase signin the renderer calls `auth:bindProfile(uid)`; main attaches a sidecar bound to `~/.zylch/profiles/<firebase_uid>/`. If the dir doesn't exist, the renderer routes to `Onboarding.tsx` which creates it via `onboarding:createProfileForFirebaseUser` and the same window then attaches in-place — Firebase auth state preserved, no second signin. Sign-out + re-signin as a different user swaps the sidecar in-place.
- **IdentityBanner** at the top of every authenticated window: "Signed in as `<email>` (uid `<prefix>…`)" + one-click *Sign out*. Wrong-account state surfaces in seconds.
- **CSP**: `app/src/renderer/index.html` carries `connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com` — Firebase Auth signin, signup, password reset, and 50-min token refresh all need these endpoints; without them the SDK throws `auth/network-request-failed`.
- **Legacy escape hatch.** `?legacy=1` query (used by "+ New Window for Profile") and the `ZYLCH_PROFILE` env var skip the Firebase gate. StarChat / `mrcall.*` won't work in those windows until the user signs in via Settings — acceptable, those profiles are pre-Firebase. `engine/scripts/migrate_profile_to_uid.py` upgrades a legacy email-keyed profile to UID-keyed on demand.
- **StarChat from the engine.** Rides the Firebase session: `engine/zylch/tools/mrcall/starchat_firebase.py:make_starchat_client_from_firebase_session()` returns a `StarChatClient(auth_type="firebase")`. First reachable surface: `mrcall.list_my_businesses` RPC (mirrors the dashboard's `Business.checkUserHasBusinesses`).
- **Google Calendar** is an *incremental* OAuth — separate from Firebase signin. PKCE flow on `127.0.0.1:19275` in the engine (post-signin only), `calendar.readonly` scope, `access_type=offline` + `prompt=consent`. Tokens persisted via `Storage.save_provider_credentials(uid, "google_calendar", …)`. `DEFAULT_CALENDAR_ID = "primary"`. Settings exposes `GOOGLE_CALENDAR_CLIENT_ID` (no client_secret — distinct from Google sign-in, which does need one).
- Legacy CLI MrCall PKCE flow on `:19274` (`zylch init` wizard) is untouched — orthogonal to the desktop signin.

### Transport model — Anthropic + direct/proxy (2026-05-04, refactor)

Replaces the muddled three-provider model
(`anthropic`/`openai`/`mrcall`) with **one provider — Anthropic — over
two transports**:

- `direct` — BYOK. `ANTHROPIC_API_KEY` in the profile `.env` calls
  `anthropic.Anthropic(...)` directly.
- `proxy` — MrCall credits. Calls go through `mrcall-agent`'s proxy
  with the in-memory Firebase JWT as credential.

Selection is presence-based and lives in one function,
`zylch.llm.client.make_llm_client()`. Set the key → BYOK; leave it
out → credits. The desktop Onboarding wizard writes neither
`SYSTEM_LLM_PROVIDER` nor any API key, so fresh profiles default to
credits.

What's gone:
- `zylch/llm/providers.py` (the `PROVIDER_MODELS` / `PROVIDER_FEATURES`
  / `PROVIDER_API_KEY_NAMES` legacy maps).
- `zylch.api.token_storage.get_active_llm_provider` and the
  `MRCALL_SESSION_SENTINEL` placeholder string.
- `OPENAI_API_KEY` / `openai_model` config fields and the entire
  `_call_openai` branch in `LLMClient`. OpenAI was dead code in this
  product (no caller exercised it; prompt caching is Anthropic-only).
- `SYSTEM_LLM_PROVIDER` in the settings schema and in `KNOWN_KEYS` on
  both sides (`profileFS.ts`, `settings_schema.py`).

What changed in the app:
- `views/Settings.tsx`'s `LLMProviderCard` now mirrors the engine's
  rule: it shows BYOK or Credits based on whether
  `ANTHROPIC_API_KEY` is set, and the "Switch to MrCall credits"
  button just clears the key. No `SYSTEM_LLM_PROVIDER` setting is
  written.
- `views/Onboarding.tsx` and `views/NewProfileWizard.tsx` no longer
  collect any LLM credentials.

Backward compat: pydantic ignores unknown env keys, so old profiles
with `SYSTEM_LLM_PROVIDER=…` / `OPENAI_API_KEY=…` keep booting; the
values are silently ignored. A user with `ANTHROPIC_API_KEY` keeps
BYOK identically. The only behaviour change is for a profile that had
explicit `SYSTEM_LLM_PROVIDER=mrcall` *and* an Anthropic key — it now
flips to BYOK. Documented because rare.

Engine-side details: see `engine/docs/active-context.md`. App-side
LLM card behaviour: see `app/docs/active-context.md`. Live
verification (sign in fresh, send chat, paste a key in Settings,
confirm transport switch) pending.

### MrCall credits — second LLM billing mode (2026-05-03, branch `feat/mrcall-credits-v1`)

The desktop now has **two LLM billing modes** instead of BYOK-only:

- **BYOK** (`anthropic` / `openai`) — unchanged. User supplies their own API key in the profile `.env`; direct SDK calls.
- **Use MrCall credits** (`mrcall`) — new. Calls route through `mrcall-agent`'s `POST /api/desktop/llm/proxy`; charges the user's `CALLCREDIT` balance on StarChat. **Same unified pool** that funds phone calls and the configurator chat — there is no separate LLM-only category. The Anthropic API key lives server-side on `mrcall-agent`; the desktop only sends the Firebase JWT (`auth: <jwt>` header, no Bearer prefix — same convention StarChat uses).

Pricing math (server-side; documented here for reference): `units = ceil(actual_µUSD × 1.5 / 11000)` — markup × value-of-1-credit-in-µUSD. 1 credit = €0.01.

Engine pieces (full detail in [`../engine/docs/active-context.md`](../engine/docs/active-context.md) "MrCall-credits v1"):

- `engine/zylch/llm/proxy_client.py` — `MrCallProxyClient`, drop-in for the subset of `anthropic.Anthropic().messages.create` `LLMClient` uses (sync + async + streaming context manager). Httpx + Anthropic SSE → reconstructed Message. Typed exceptions: `MrCallInsufficientCredits(available, topup_url)`, `MrCallAuthError`, `MrCallProxyError`.
- `engine/zylch/llm/client.py` — `LLMClient.__init__` branches on `provider == "mrcall"`, requires `zylch.auth.session`, reuses `_call_anthropic` codepath (proxy returns Anthropic-format objects).
- `engine/zylch/llm/providers.py` — `is_metered=True` on `mrcall`, `False` on `anthropic` / `openai`.
- `engine/zylch/rpc/account.py` — new JSON-RPC `account.balance()` → `GET /api/desktop/llm/balance`. Schema in [`ipc-contract.md`](ipc-contract.md).
- `engine/zylch/config.py` — `MRCALL_PROXY_URL` (default `https://zylch.mrcall.ai`, production `mrcall-agent`; override to `https://zylch-test.mrcall.ai` for dev), `MRCALL_CREDITS_MODEL` (default `claude-sonnet-4-5`).
- Tests: `engine/tests/llm/test_proxy_client.py` (8 cases, all green).

App pieces (full detail in [`../app/docs/active-context.md`](../app/docs/active-context.md) "MrCall credits v1"):

- `app/src/preload/index.ts` — `account.balance` binding (15 s timeout).
- `app/src/renderer/src/types.ts` — `account.balance` typed on `ZylchAPI`.
- `app/src/renderer/src/views/Settings.tsx` — new `LLMProviderCard` with the BYOK ↔ MrCall-credits radio, balance display (refresh on mount + on window `focus`), "Top up" button via `shell.openExternal('https://dashboard.mrcall.ai/plan')`, disabled state when not signed in.

### "Continue with Google" sign-in (2026-05-02)
- Architecture: PKCE OAuth in the **main process** on `127.0.0.1:19276`, not in the engine. Reason: the SignIn screen renders before any sidecar exists in onboarding / auth-pending mode, so engine RPCs aren't available. Mirrors the post-signin Calendar flow on `:19275` structurally; both run in different lifecycle phases.
- Renderer click "Continue with Google" → `signin:googleStart` IPC → main spins up a one-shot HTTP server on :19276, opens consent URL via `shell.openExternal`, awaits loopback callback, exchanges code at `oauth2.googleapis.com/token`, returns `{ idToken, email }` → renderer calls `signInWithCredential(auth, GoogleAuthProvider.credential(idToken))` → `FirebaseAuthGate` observes `onAuthStateChanged`. CSP unchanged (`identitytoolkit.googleapis.com` is already allowed; consent runs in system browser; token POST runs in Node).
- **OAuth client config split**: public Client ID hardcoded in `app/src/main/oauthConfig.ts` (parallel to the Firebase apiKey already committed in `firebase/config.ts`); Client secret in gitignored `app/src/main/oauthSecrets.ts` (postinstall seeds from `oauthSecrets.example.ts`; CI writes from a repo secret). Google's token endpoint enforces `client_secret` for Desktop OAuth clients even on PKCE — without it the exchange returns `400 client_secret is missing`.
- The `GOCSPX-` prefix triggers GitHub Secret Scanning + Google-side auto-revoke within minutes of any commit, so the gitignore is mandatory regardless of Google's docs claiming installed-app secrets are "non-confidential". This is the operative reason — not the conceptual one.
- Plan + setup runbook: [`execution-plans/google-signin.md`](execution-plans/google-signin.md). Live test pending.

### JSON-RPC contract (engine ↔ app)
- Server: `engine/zylch/rpc/methods.py` (dispatch table) + per-domain modules (`email_actions.py`, `task_queries.py`, `account.py`, `mrcall_actions.py`, `google_actions.py`).
- Client: `app/src/preload/index.ts` (`window.zylch.*` surface) + main-process bridge (`ipcMain.handle('rpc:call', …)`).
- Transport: stdio JSON-RPC. Sidecar spawned by main process.
- Notification fan-out: streaming methods (`tasks.solve.event`, `update.run` progress, `google.calendar.auth_url_ready`) emit `notify` events that the main process forwards to the renderer via `webContents.send`.
- **Renderer-only IPCs** are a parallel surface — not part of this contract. They run entirely in main and never reach the sidecar: `signin:googleStart`, `signin:googleCancel`, `auth:bindProfile`, `shell:openExternal`, `dialog:selectFiles`, `dialog:selectDirectories`, `profile:current`, `profiles:list`, `window:openForProfile`, `sidecar:restart`, `onboarding:isFirstRun`, `onboarding:createProfile`, `onboarding:createProfileForFirebaseUser`, `onboarding:finalize`. Their schemas live in `app/src/preload/index.ts` and `app/src/renderer/src/types.ts` only.
- Engine RPC method surface tracked in [`ipc-contract.md`](ipc-contract.md).

### Release pipeline
- Tag-driven matrix: `v*` → macOS arm64 + Windows x64; `v*-intel` → also macOS Intel x64 on a paid larger runner.
- Sidecar built in-flight via PyInstaller in `engine/`, copied to `app/bin/` before electron-builder runs. No external sidecar repo to fetch from.
- macOS code-signed + notarized via the afterSign hook (`3a3eb522`); APPLE_TEAM_ID passed explicitly to notarytool (`5b8ad979`); creds validated before build (`2477b23a`).
- **OAuth secret materialisation step** (`b6739d5`): between `npm ci` and `npm run dist`, the workflow runs `node scripts/write-oauth-secrets.mjs` which reads the `GOOGLE_SIGNIN_CLIENT_SECRET` repo secret, validates the `GOCSPX-` prefix, and writes `app/src/main/oauthSecrets.ts`. Vite/Rollup inlines the constant during `electron-vite build` so the secret rides inside `out/main/index.js` → `.dmg` / `.exe`. End users install and click "Continue with Google" without local setup. The repo secret still has to be created at *Settings → Secrets and variables → Actions*.
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

## What Was Completed This Session (2026-05-02, post-Firebase landing)

Recent commits on `main` (newest last):

- `451526a` **CSP fix for Firebase signin.** Renderer's CSP was `default-src 'self'` with no `connect-src`, so the Firebase JS SDK couldn't reach Google. Email/password threw `auth/network-request-failed` ("Network error reaching Firebase"). Added `connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com`.
- `057d9de` **"Continue with Google" first cut.** PKCE OAuth on `127.0.0.1:19276` in main process, `signin:googleStart` / `signin:googleCancel` IPC, preload + types, button on SignIn screen, `signInWithCredential` wiring on success.
- `642fdae` **Single config file architecture.** Replaced `process.env.GOOGLE_SIGNIN_CLIENT_ID` lookup with import from `oauthConfig.ts`. Operator edits one committed file.
- `b2af895` **Wired Client ID** (`375340415237-jl3hl6hcu15po65oo7dovl1lb3a960ni.apps.googleusercontent.com`). Project-number prefix matches `messagingSenderId` so Firebase trusts the audience without external-projects whitelist step.
- `bc011be` **UID-keyed profile binding (by another agent).** `inMemoryPersistence` for Firebase; auth-pending boot with no sidecar; `auth:bindProfile(uid)` IPC attaches a sidecar after signin or routes to onboarding; `IdentityBanner` always-visible; `?legacy=1` escape hatch for "+ New Window for Profile" + `ZYLCH_PROFILE` for engine tests. Closes the silent identity-drift gap (typing user A's credentials and ending up on user B's data).
- `f5bbf2c` **`client_secret` plumbing + isolation from git.** Google's token endpoint enforces `client_secret` for Desktop OAuth clients even on PKCE — `400 client_secret is missing` otherwise. Architecture: `oauthConfig.ts` re-exports `GOOGLE_SIGNIN_CLIENT_SECRET` from gitignored `oauthSecrets.ts`; postinstall (`scripts/setup-oauth-secrets.mjs`) seeds from `oauthSecrets.example.ts` so a fresh clone builds. Per Google's docs the secret is "non-confidential" for installed apps, but GitHub Secret Scanning + Google's auto-revoke API make the gitignore mandatory.
- `b6739d5` **CI step for packaged releases.** New step in `release.yml` runs `node scripts/write-oauth-secrets.mjs` between `npm ci` and `npm run dist`. Reads `GOOGLE_SIGNIN_CLIENT_SECRET` from a repo secret, validates the `GOCSPX-` prefix, writes `oauthSecrets.ts`. Vite inlines the value into `out/main/index.js`; `.dmg` / `.exe` ship with the secret embedded. End users don't configure anything.

Verified: `npm run typecheck` clean at every commit; `electron-vite build` smoke test confirmed the Vite-only inject produces the expected literal in `out/main/index.js` (string-marker test, `out/` then deleted). Real `npm run dev` end-to-end Google signin NOT exercised from this machine.

The previous session's Firebase signin landing (`25e668b..11f4cbe`) is now folded into the "What Is Built and Working" sections above.

## What Is In Progress

- **End-to-end live verification of "Continue with Google" + email/password signin in `npm run dev` — pending.** All plumbing landed; needs the user to start the dev server with the populated local `oauthSecrets.ts` and click both signin paths. Watch for: `redirect_uri_mismatch` (means client wasn't created as Desktop type), `auth/account-exists-with-different-credential` (existing email/password account), or `auth/invalid-credential` (id_token audience not accepted by Firebase — would mean the OAuth client lives outside `talkmeapp-e696c`).
- **Packaged-build live test — pending.** Requires the `GOOGLE_SIGNIN_CLIENT_SECRET` repo secret to be created at *Settings → Secrets and variables → Actions* and a `v*` tag push.
- **End-to-end Firebase / StarChat / Calendar OAuth round-trip — pending.** Smoke tests cover dispatcher + error paths, the real `npm run dev` + signin + `mrcall.list_my_businesses` + Calendar consent (with `GOOGLE_CALENDAR_CLIENT_ID` configured in profile Settings) was not exercised.
- Cleanup of dead `MrCallConfiguratorTrainer` references — brief landed (`docs/execution-plans/cleanup-mrcall-configurator-deadcode.md`), execution deferred to a dedicated PR.
- Release pipeline: see `execution-plans/release-and-rename-l2.md`. Tag-driven matrix done; signing on macOS done; OAuth secret CI step done; Windows signing pending; Level 3 rename sweep pending.

## Immediate Next Steps

1. `cd app && npm run dev` → click both signin paths (email/password and "Continue with Google") → `IdentityBanner` shows the right email + uid prefix → `auth:bindProfile` either attaches a sidecar or routes to onboarding.
2. Add the `GOOGLE_SIGNIN_CLIENT_SECRET` repo secret at *Settings → Secrets and variables → Actions* so the next `v*` tag push produces a packaged build with Google signin baked in.
3. Configure `GOOGLE_CALENDAR_CLIENT_ID` in profile Settings (Desktop-app OAuth client with redirect `http://127.0.0.1:19275/oauth2/google/callback`) and exercise "Connect Google Calendar"; verify token persistence in `OAuthToken` (`provider='google_calendar'`).
4. Open a follow-up PR per `cleanup-mrcall-configurator-deadcode.md` once Firebase signin is validated. Self-contained — fresh agent should pick it up cold.
5. Wire `engine/zylch/tools/calendar_sync.py` to the new `provider='google_calendar'` tokens (current sync code is partial pre-existing scaffolding; reading from the encrypted store is a small change).

## Known Issues

- **No live end-to-end verification of any signin path.** Email/password, Continue with Google, the post-signin `auth:bindProfile` round-trip, and the engine `mrcall.list_my_businesses` + Calendar OAuth all compile + typecheck but have not been clicked from this machine.
- **`GOOGLE_SIGNIN_CLIENT_SECRET` repo secret not yet created.** Until it is, packaged release builds will fail at the "Materialise Google OAuth client_secret" step (the writer script exits 1 on missing env var — fail-loud rather than ship a broken signin button).
- **Dead configurator references.** `command_handlers.py` (`/mrcall config`, `/mrcall train`, `/mrcall feature`) and `factory.py:_create_mrcall_tools` reference `MrCallConfiguratorTrainer`, `GetAssistantCatalogTool`, `ConfigureAssistantTool`, etc. — symbols that were never tracked in this repo. Currently graceful-degraded (`/mrcall config` short-circuits with "MrCall is not available"). `engine/tests/test_mrcall_integration.py` is similarly dead. Brief at `docs/execution-plans/cleanup-mrcall-configurator-deadcode.md`.
- **No automated contract test for IPC method/payload changes.** Tracked in [`harness-backlog.md`](harness-backlog.md). The renderer-only IPCs added this session (`signin:googleStart`, `signin:googleCancel`, `auth:bindProfile`) and the engine RPC methods added across recent sessions are typed on the renderer side via `app/src/renderer/src/types.ts`, but engine ↔ preload divergence still surfaces only at runtime.
- **Legacy email-keyed profiles** are not auto-migrated. Users who signed in with email pre-2026-05 keep working, but their on-disk profile dir name is the email. Use `engine/scripts/migrate_profile_to_uid.py` to upgrade.
- **MrCall-credits v1 not live-verified** (branch `feat/mrcall-credits-v1`, tip `3001844`). 8/8 unit tests on `MrCallProxyClient`; preload + Settings card compile + typecheck. Live round-trip — Firebase signin → flip Settings to MrCall credits → chat → balance update → 402 path → top-up on dashboard → balance refresh — pending. Needs `mrcall-agent` deployed at `https://zylch-test.mrcall.ai` with `/api/desktop/llm/proxy` + `/api/desktop/llm/balance` reachable.
