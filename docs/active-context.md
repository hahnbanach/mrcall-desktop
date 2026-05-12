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

## 2026-05-12 — Agentic task "Open" — proactive solve flow

The desktop's Tasks-list `Open` button no longer pre-fills the chat
input with `"Aiutami a gestire questa task. …"` (template removed).
It fires `tasks.solve(task_id)` directly. The engine streams events
back via `tasks.solve.event`; the renderer renders them as
assistant bubbles, tool-progress narration, and approval cards.
Goal: three clicks to act (Open → "Invia email" on the approval
card → done) instead of seven.

Spans engine + app + IPC. Detail lives in each tree:

- **Engine state** — see `engine/docs/active-context.md`
  "Agentic task Open" (SOLVE_SYSTEM_PROMPT rewrite, USER_LANGUAGE,
  draft_email removed from SOLVE_TOOLS, APPROVAL_TOOLS naming fix,
  new `tool_use_start` event, new `tasks.solve.cancel` RPC, clean
  cancel via CancelledError).
- **App state** — see `app/docs/active-context.md`
  "Workspace + agentic Open flow" (no template, Conversation
  gains `threadId` + `taskCompleted`, contextual header button,
  read-only on closed tasks, Annulla cancels run instead of
  declining the tool).
- **IPC contract** — `ipc-contract.md` carries the full
  `tasks.solve` / `tasks.solve.approve` / `tasks.solve.cancel` /
  `tasks.solve.event` surface.

Execution plan: [`execution-plans/proactive-task-open.md`](execution-plans/proactive-task-open.md) (status: completed).

**Live test status** (Mario, 2026-05-11/12 on Mac dev build):
solve flow proven on real tasks (ISTAT, Aleide payment reminder,
Google Workspace closed task). Source panel persistence and
contextual button verified on legacy localStorage convs. Cancel
flow verified. Live-cost not measured systematically — first
Open on a fresh task costs roughly the Sonnet input on
SOLVE_SYSTEM_PROMPT + tool defs + task context (~5-8k input,
~500 output, ~$0.005 cached / ~$0.025 cold).

Recent commits (newest first):
- `b36e15b3` Annulla on solve approval cancels the run.
- `a1896df6` Closed tasks read-only; header toggles Riapri ↔ Marca come fatta.
- `336bc152` Source panel + progress narration for solve flow.
- `4cd8ec39` Source panel follows sidebar conversation switches.
- `df1e1fb1` Proactive task "Open" — first cut.

## 2026-05-12 — WhatsApp pipeline parity Phase 2 landed (engine-only)

Commit `91421d2e` lands the end-to-end WhatsApp memory extraction
pipeline (Phase 2 a/b/c of `engine/docs/execution-plans/whatsapp-pipeline-parity.md`).
**Engine-only change**: no app code touched, no JSON-RPC contract
change, no release-pipeline change. Engine-side facts (new
`whatsapp_blobs` table, `memory_email → memory_message` trainer
rename with back-compat, `process_whatsapp_message` worker + LID→phone
resolution via `whatsapp_contacts`, parser hardening, live verification
on the gmail profile) all live in [`../engine/docs/active-context.md`](../engine/docs/active-context.md)
"WhatsApp pipeline parity — Phase 2 a/b/c". Next phase (3) targets
task creation from WhatsApp and DOES touch the JSON-RPC contract
(`task_items.sources.whatsapp_messages`, `channel='whatsapp'`).

## 2026-05-12 — pre-Firebase legacy code removed (`inMemoryPersistence` + every window through Firebase)

Pre-alpha cleanup. The desktop now enforces "every window signs in with
Firebase" structurally — no special cases, no escape hatches:

- **`inMemoryPersistence`** restored (`app/src/renderer/src/firebase/config.ts`). Each
  BrowserWindow has its own auth state — no cross-window IndexedDB
  bleed possible. Every app launch shows SignIn.
- **`?legacy=1` URL bypass removed** (`app/src/main/index.ts`, `App.tsx`).
- **`ZYLCH_PROFILE` env-var bypass removed.** `bootFirstWindow` always
  creates an auth-pending window. (The engine sidecar still takes
  `--profile <id>` internally for wiring, but it can't shortcut signin.)
- **`createWindowForProfile` deleted.** Its callers — the picker and
  the env-var hatch — now go through `createAuthPendingWindow`.
- **`isLegacyWindow()` / `lib/legacy.ts` deleted.** No legacy-vs-Firebase
  branching anywhere in the renderer.
- **`NewProfileWizard.tsx` deleted.** It created email-keyed profiles
  via `profiles.create`. Replaced by "+ Sign in to another account" in
  the "Other profiles" dropdown, which opens a fresh auth-pending window.
- **`engine/scripts/migrate_profile_to_uid.py` deleted.** Pre-Firebase
  email-keyed profiles aren't a supported state.
- **"Other profiles" picker behavior changed.** Clicking a profile opens
  a new auth-pending window with the profile's email pre-filled in
  SignIn (via `?email=` URL hint); the actual profile binding is keyed
  off the signed-in Firebase UID, so the pre-fill is hint-only — Firebase
  identity verification can't be short-circuited.
- **`Onboarding.tsx` Path B (legacy email-keyed) removed.**
  `FirebaseAuthGate` is the only mount path, so `firebaseUid && firebaseEmail`
  is always present.

Net delta: -558 lines. Typecheck clean. Live-verified by Mario:
boot → SignIn; signin → bound app; "Other profiles" → support@mrcall.ai
→ new window with email pre-filled → support signin → support's data
appears; "+ Sign in to another account" → fresh SignIn with empty email.

## 2026-05-06 evening — task-list cleanup ("4 task per UN problema") finally fixed

User report (verbatim, frustrated, after 5 prior sessions had each
declared "tutto risolto" without testing):

> Da stamattina abbiamo questi 3 task: Salamone email, AiFOS noreply,
> MrCall missed-call (in realtà 2 missed-calls). Tutti per lo stesso
> problema (corso sicurezza CNIT). Non dovrebbero proprio esserci, e
> se proprio devono esserci, devono essere uno.

**Two distinct bugs landed this session, both pushed to `origin/main`:**

1. `557e65b fix(storage): unblock Fase 3.1/3.2 backfills` — the row-level
   backfills added on 2026-05-06 morning (`email_blobs` index,
   `task_items.channel` column population) were never running on any
   real install. Cause: `_apply_data_backfills` had a `return` early
   inside the first backfill body that short-circuited the whole
   dispatcher when the first backfill had nothing to do. Fix is a
   pure refactor (lift the early-return into its own function).
   Engine details: see [`../engine/docs/active-context.md`](../engine/docs/active-context.md) "Bug fix — `_apply_data_backfills` early-return".

2. `ec61067 feat(tasks): F9 cross-contact topic dedup` — new step in the
   `update` pipeline. F8 dedup only catches duplicates that share
   `contact_email` or memory-blob overlap; the user's real case has
   ONE problem reaching the task list via 3+ different senders /
   channels (person, automated platform notifier, MrCall missed-call
   notifier). F9 sends ALL active-open tasks in one Opus call, asks
   the model to cluster by underlying topic, closes non-keepers.
   Engine details: see [`../engine/docs/active-context.md`](../engine/docs/active-context.md) "F9 Topic Dedup".

**Live verification done (the kind of test the prior sessions skipped):**

- Modified the actual live DB at
  `~/.zylch/profiles/HxiZhWEBoRUarPzqX8eRWP21FuJ3/zylch.db`
  (user explicitly authorised: "il db lo puoi far esplodere").
- Reopened the 3 corso-sicurezza tasks (set `completed_at=NULL`,
  `dedup_skip_until=NULL`).
- Ran `process_pipeline._reanalyze_only` — the exact code path
  `update.run` invokes when there are no new emails.
- Verified via the real JSON-RPC `tasks.list` (the call the renderer
  issues) that the affected rows disappeared.
- Counts: 57 → 30 active open. The 4 sicurezza tasks → 1 keeper
  (Salamone email).

**Playbook for the next session if it breaks again:**
[`../engine/docs/execution-plans/topic-dedup-playbook.md`](../engine/docs/execution-plans/topic-dedup-playbook.md). It contains the diagnostic order, the live-reproduction recipe (no IMAP needed), the constants and where to tune them, and what F9 does NOT cover.

**New JSON-RPC method:** `tasks.topic_dedup_now()`. See
[`ipc-contract.md`](ipc-contract.md) "Maintenance".

## What Is Built and Working

### Firebase Auth as desktop identity
- The renderer is gated by `FirebaseAuthGate` (`app/src/renderer/src/App.tsx`) on `auth.currentUser`. Unsigned-in state shows `views/SignIn.tsx` — **email/password and "Continue with Google"** (PKCE → `signInWithCredential`); magic links remain deferred.
- Same Firebase project as the dashboard (`talkmeapp-e696c`) so a single account works on both surfaces. Config hard-coded in `app/src/renderer/src/firebase/config.ts` (public-by-design — the Firebase JS SDK ships its config).
- **Persistence is `inMemoryPersistence` (post-`bc011be`).** Every app launch shows the SignIn screen. The previous indexedDB/local-storage persistence let a stale Firebase session silently survive across launches and decouple from the on-disk profile, so a wrong-account state could surface (typing user A's credentials and ending up on user B's data).
- Renderer pushes the ID token to the engine via `account.set_firebase_token`; engine holds it in-memory only (`zylch/auth/session.py` singleton). 50-min proactive refresh in `firebase/authUtils.ts`. Sign-out clears both ends.
- **UID-keyed profile binding.** Every BrowserWindow boots into an *auth-pending* state with NO sidecar. After Firebase signin the renderer calls `auth:bindProfile(uid)`; main attaches a sidecar bound to `~/.zylch/profiles/<firebase_uid>/`. If the dir doesn't exist, the renderer routes to `Onboarding.tsx` which creates it via `onboarding:createProfileForFirebaseUser` and the same window then attaches in-place — Firebase auth state preserved, no second signin. Sign-out + re-signin as a different user swaps the sidecar in-place.
- **IdentityBanner** at the top of every authenticated window: "Signed in as `<email>` (uid `<prefix>…`)" + one-click *Sign out*. Wrong-account state surfaces in seconds.
- **CSP**: `app/src/renderer/index.html` carries `connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com` — Firebase Auth signin, signup, password reset, and 50-min token refresh all need these endpoints; without them the SDK throws `auth/network-request-failed`.
- **No legacy escape hatch.** Every window goes through `FirebaseAuthGate` — no `?legacy=1`, no `ZYLCH_PROFILE` env-var bypass (both removed 2026-05-12). The "Other profiles" picker opens a fresh auth-pending window with the picked profile's email as a SignIn pre-fill; binding is keyed off the signed-in UID, never off the picker selection.
- **StarChat from the engine.** Rides the Firebase session: `engine/zylch/tools/mrcall/starchat_firebase.py:make_starchat_client_from_firebase_session()` returns a `StarChatClient(auth_type="firebase")`. First reachable surface: `mrcall.list_my_businesses` RPC (mirrors the dashboard's `Business.checkUserHasBusinesses`).
- **Google Calendar** is an *incremental* OAuth — separate from Firebase signin. PKCE flow on `127.0.0.1:19275` in the engine (post-signin only), `calendar.readonly` scope, `access_type=offline` + `prompt=consent`. Tokens persisted via `Storage.save_provider_credentials(uid, "google_calendar", …)`. `DEFAULT_CALENDAR_ID = "primary"`. The Calendar Client ID defaults to the same Desktop OAuth client as "Continue with Google" sign-in: `app/src/main/index.ts:spawnSidecar` injects `GOOGLE_CALENDAR_CLIENT_ID_DEFAULT=GOOGLE_SIGNIN_CLIENT_ID` into the sidecar env, and the engine's `get_google_client_id()` falls back to it when `GOOGLE_CALENDAR_CLIENT_ID` is unset. Profile `.env` `GOOGLE_CALENDAR_CLIENT_ID` overrides it. No client_secret — distinct from Google sign-in, which does need one.
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
- **Single-arch-per-runner fix (v0.1.27 incident).** `package.json` `mac.target` / `win.target` now omit `arch`. Until v0.1.27 those carried `arch: ["arm64", "x64"]` / `arch: ["x64"]` and the workflow's `-- --${matrix.arch}` flag was assumed to constrain — it doesn't. electron-builder treats CLI archs as **additive** when the target config declares its own arch list, so the default `v*` macos-14 runner was building **both** arm64 and x64 dmgs. Two visible failure modes: (a) the x64 dmg shipped an arm64 sidecar (silent corruption noted as the "v0.1.25 bug" in `c99af97`); (b) v0.1.27 actually crashed when GitHub's DNS hiccuped between the arm64 and x64 electron downloads. Removing the arch lists makes the matrix flag the sole source of truth — the macos-14 runner builds arm64 only, macos-13-large (`-intel` tags) builds x64 only.
- **PyInstaller pin (v0.1.31→v0.1.32 Win-x64 silent break, commit `362e1cda`).** The workflow's `Install Python deps` step ran `pip install pyinstaller` unpinned. PyInstaller 6.20.0 (released upstream between the v0.1.29 green build on 2026-05-05 and the v0.1.31 build on 2026-05-07) segfaults with `ACCESS_VIOLATION` (0xC0000005, raw exit code 3221225477) inside its isolated subprocess while enumerating `neonize`'s submodules via `collect_all('neonize')` in `engine/zylch.spec:13`. Every Windows sidecar build from v0.1.31, v0.1.31-intel, and v0.1.32 failed at the PyInstaller step — only the macOS arm64 DMG was reaching the GitHub Release. Mac-arm64 never tripped the bug, which is why the regression slipped past notice for a week. Fix pins `pyinstaller==6.13.0` in the workflow (the last 6.x line known to work end-to-end here). If a future PyInstaller release fixes the upstream regression, raise the pin or remove it; do NOT go back to unpinned. Live verification needs the next `v*` tag push (v0.1.33+) to run the workflow end-to-end on Windows — pending.
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

## Assistant tool surface (updated 2026-05-05)

- **Email-tab search** (renderer-side): new JSON-RPC `emails.search(query, folder?, limit?, offset?)`. Gmail-style operators backed by `engine/zylch/services/email_search.py` parser+matcher. Returns the same `InboxThread[]` shape as `emails.list_inbox` so the renderer renders unchanged. UI is a Gmail-style bar above the thread list with submit-on-Enter, `?` help panel, Esc to clear.
- **Chat assistant** (LLM-side): new tool `search_local_emails(query, folder?, limit?, offset?)` covering the *full* local mailbox (no 1-year IMAP cap) with the same Gmail syntax. Sits between `search_local_memory` (entity blobs) and `search_provider_emails` (IMAP) in the cascade documented in `engine/zylch/assistant/prompts.py`. The cascade now also asks the assistant to report explicitly which surfaces it checked when both come up empty, instead of saying "I checked the local database" when only the blob store was queried.
- **Cap-bug fixes** in two existing tools while we were there: `SearchLocalMemoryTool` 5→50, `SearchEmailsTool` 20→50, both with the limit exposed as a parameter so a future call can scale up. Both caps were silently dropping relevant matches off the bottom of the ranked list.

Test ledger this session:

- `engine/tests/services/test_email_search.py` — 24/24 (parser + matcher).
- App typecheck clean.
- Engine `tests/workers/test_task_worker_bugs.py` — 14 errors at HEAD, **pre-existing** from the 2026-05-04 transport refactor (tests still mock `zylch.workers.task_creation.LLMClient`, attribute removed). Unchanged by this session's work; tracked but not fixed here.
- Live verification of the new RPC method and the new LLM tool against a running sidecar **NOT** done — needs `npm run dev` + a "find emails about X" chat turn + a UI search.

## Known Issues

- **No live end-to-end verification of any signin path.** Email/password, Continue with Google, the post-signin `auth:bindProfile` round-trip, and the engine `mrcall.list_my_businesses` + Calendar OAuth all compile + typecheck but have not been clicked from this machine.
- **`GOOGLE_SIGNIN_CLIENT_SECRET` repo secret not yet created.** Until it is, packaged release builds will fail at the "Materialise Google OAuth client_secret" step (the writer script exits 1 on missing env var — fail-loud rather than ship a broken signin button).
- **Dead configurator references.** `command_handlers.py` (`/mrcall config`, `/mrcall train`, `/mrcall feature`) and `factory.py:_create_mrcall_tools` reference `MrCallConfiguratorTrainer`, `GetAssistantCatalogTool`, `ConfigureAssistantTool`, etc. — symbols that were never tracked in this repo. Currently graceful-degraded (`/mrcall config` short-circuits with "MrCall is not available"). `engine/tests/test_mrcall_integration.py` is similarly dead. Brief at `docs/execution-plans/cleanup-mrcall-configurator-deadcode.md`.
- **No automated contract test for IPC method/payload changes.** Tracked in [`harness-backlog.md`](harness-backlog.md). The renderer-only IPCs added this session (`signin:googleStart`, `signin:googleCancel`, `auth:bindProfile`) and the engine RPC methods added across recent sessions are typed on the renderer side via `app/src/renderer/src/types.ts`, but engine ↔ preload divergence still surfaces only at runtime.
- **MrCall-credits v1 not live-verified** (branch `feat/mrcall-credits-v1`, tip `3001844`). 8/8 unit tests on `MrCallProxyClient`; preload + Settings card compile + typecheck. Live round-trip — Firebase signin → flip Settings to MrCall credits → chat → balance update → 402 path → top-up on dashboard → balance refresh — pending. Needs `mrcall-agent` deployed at `https://zylch-test.mrcall.ai` with `/api/desktop/llm/proxy` + `/api/desktop/llm/balance` reachable.
