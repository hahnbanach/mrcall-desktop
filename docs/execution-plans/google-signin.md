---
status: in-progress
created: 2026-05-02
---

# "Continue with Google" on the Firebase signin gate

## Goal

Let the user sign in to MrCall Desktop with their Google account
(in addition to email/password) so the same identity that already works
in the dashboard works here without setting a separate password.
Same Firebase project (`talkmeapp-e696c`); the resulting `User` object
is identical to one obtained via email/password — `FirebaseAuthGate`,
the renderer-to-engine token push, and StarChat calls all keep working
unchanged.

## Why PKCE-in-main and not signInWithPopup

The Firebase JS SDK's `signInWithPopup` is brittle in Electron. The
renderer is loaded from `file://` (or the dev server origin), and
Firebase needs a same-origin postMessage with its auth handler at
`<project>.firebaseapp.com`. The official desktop / installed-app
recommendation is:

  1. Run a PKCE OAuth flow in the system browser.
  2. Receive the auth code on a `127.0.0.1:<port>` loopback.
  3. Exchange it for a Google id_token in the host process.
  4. Hand the id_token to Firebase via
     `signInWithCredential(GoogleAuthProvider.credential(idToken))`.

This mirrors the post-signin Calendar OAuth flow on `:19275` already
implemented in the engine. The only structural difference is that
**this flow runs before any Python sidecar exists** (onboarding mode,
or the brief window between FirebaseAuthGate showing the SignIn screen
and the user picking a profile), so it has to live in the Electron
main process rather than the engine.

## Architecture

```
┌──────────────────┐        IPC               ┌──────────────────┐
│  renderer        │ ───── signin:           │  main process    │
│  (SignIn.tsx)    │       googleStart       │  (googleSignin)  │
│                  │ ←──── { idToken } ───── │  127.0.0.1:19276 │
│                  │                          │                  │
│  signInWith-     │                          │  shell.openExt   │
│  Credential      │                          │  → system browser│
│   ↓              │                          │                  │
│  Firebase Auth   │                          │  POST /token     │
│  identitytoolkit │ ──── signInWithIdp ───→  │  oauth2.googleapis │
└──────────────────┘                          └──────────────────┘
```

- **`app/src/main/googleSignin.ts`** — owns the PKCE state machine,
  the loopback HTTP server on `127.0.0.1:19276`, the `code → id_token`
  exchange. Single in-flight flow at a time; concurrent calls cancel
  the prior one. 5-minute consent timeout matches the Calendar flow.
- **`app/src/main/index.ts`** — registers IPC `signin:googleStart` and
  `signin:googleCancel`. Reads `GOOGLE_SIGNIN_CLIENT_ID` from env at
  startup; surfaces a friendly "not configured" error if missing.
- **`app/src/preload/index.ts`** + **`app/src/renderer/src/types.ts`** —
  expose `window.zylch.signin.googleStart()` / `googleCancel()` to the
  renderer.
- **`app/src/renderer/src/views/SignIn.tsx`** — adds a "Continue with
  Google" button above the email/password form. On success, calls
  `signInWithCredential(auth, GoogleAuthProvider.credential(idToken))`;
  `FirebaseAuthGate` then observes `onAuthStateChanged` and unmounts
  the SignIn screen.

CSP is unchanged — the existing `connect-src` already covers
`identitytoolkit.googleapis.com` (which `signInWithCredential` hits);
Google's `accounts.google.com` consent UI runs in the system browser,
not in the renderer; the `oauth2.googleapis.com/token` exchange runs in
Node (main process), not the renderer.

## One-time setup the user has to do

The desktop binary ships without an embedded OAuth client because the
client ID needs to be paired with redirect URIs we control in the user's
own Google Cloud project. **Until the user creates one and configures
the env var, the "Continue with Google" button surfaces an inline error
explaining what to do.**

Steps:

1. **Pick or create the OAuth client.**
   - Open <https://console.cloud.google.com/apis/credentials> in the
     `talkmeapp-e696c` project (the one Firebase Auth is wired to).
   - Click *Create credentials → OAuth client ID*.
   - **Application type**: prefer **Desktop app** (no client secret,
     PKCE built-in). A **Web application** also works — Google's PKCE
     flow accepts loopback redirects without a client_secret for
     installed-app patterns — but desktop is the cleaner match.
   - **Name**: anything memorable, e.g. `mrcall-desktop-signin`.
2. **Authorize the loopback redirect** (Web client only — Desktop
   clients don't need this).
   - Add `http://127.0.0.1:19276/oauth2/google/signin-callback` under
     "Authorized redirect URIs". Save.
3. **Whitelist for Firebase** (only if the OAuth client is in a
   *different* Google Cloud project from Firebase Auth — for
   `talkmeapp-e696c` this step is a no-op, the client is already in
   the same project).
   - Firebase console → *Authentication → Sign-in method → Google →
     Web SDK configuration → Whitelist client IDs from external
     projects → add the new client ID*.
4. **Run the desktop app with the env var set**:
   ```bash
   cd app
   GOOGLE_SIGNIN_CLIENT_ID=<the client ID> npm run dev
   ```

For packaged builds the env var is not present at runtime — that is a
follow-up: either bake the client ID into the bundle at build time
(Vite `define`) or read it from the user's Settings.

## Status

| Step | State |
|------|-------|
| Main-process PKCE flow (`app/src/main/googleSignin.ts`) | done |
| IPC registration (`signin:googleStart` / `signin:googleCancel`) | done |
| Preload + renderer typings | done |
| "Continue with Google" button on `SignIn.tsx` | done |
| `GOOGLE_SIGNIN_CLIENT_ID` documented as a dev-time env var | done |
| End-to-end live test in `npm run dev` | **pending — needs a configured client ID** |
| Packaged-build configuration story (env var doesn't survive bundling) | not started |
| Renderer-side surfacing of "not configured" error in plain language | covered by the inline error string returned by main, no extra UX yet |

## Known follow-ups

- **`auth/account-exists-with-different-credential`** — the SignIn
  screen now maps the code, but we don't auto-link the credential. If
  a user already has an email/password account on the same address,
  they have to sign in with email/password to merge. Acceptable
  short-term; Firebase has a `linkWithCredential` API for the proper
  fix.
- **Packaged build configuration.** `process.env.GOOGLE_SIGNIN_CLIENT_ID`
  is not a thing in a notarized DMG. The cleanest path is a build-time
  Vite `define` that bakes the client ID into `main/index.ts`, exposed
  through `electron.vite.config.ts`. Alternative: read from a
  per-machine config file the first time the app launches.
- **Onboarding-mode stress test.** Verify that opening the app with an
  empty `~/.zylch/profiles/` and clicking Continue with Google produces
  a working signin: no sidecar exists yet, so any IPC path that quietly
  expects one would fail here. The implementation deliberately keeps
  the flow in main process to avoid this dependency.
- **Cancellation UX.** `signin:googleCancel` exists on the preload but
  the SignIn screen doesn't yet wire a Cancel button. Low priority — the
  5-minute timeout cleans up automatically.
