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
  `signin:googleCancel`. Imports `GOOGLE_SIGNIN_CLIENT_ID` from
  `oauthConfig.ts`; surfaces a friendly "not configured" error if the
  constant is empty.
- **`app/src/main/oauthConfig.ts`** — single committed source of truth
  for the Client ID. Public-by-design (Desktop OAuth clients have no
  client_secret), edited and committed when the client rotates.
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

1. **Create the OAuth client.**
   - Open <https://console.cloud.google.com/apis/credentials> in the
     `talkmeapp-e696c` project (the one Firebase Auth is wired to).
   - *Create credentials → OAuth client ID*.
   - **Application type**: **Desktop app** (no client_secret, PKCE
     built-in, no redirect-URI registration needed — Google accepts
     any `http://127.0.0.1:<port>` loopback for installed apps).
   - **Name**: anything memorable, e.g. `mrcall-desktop-signin`.
   - Copy the resulting **Client ID** (looks like
     `1234567890-abcdefg.apps.googleusercontent.com`).

2. **(Only if the client lives in a different Cloud project.)**
   For `talkmeapp-e696c` this step is a no-op — the client is in the
   same project as Firebase Auth, so Firebase already trusts it.
   Otherwise: Firebase console → *Authentication → Sign-in method →
   Google → Web SDK configuration → Whitelist client IDs from
   external projects → add the new client ID*.

3. **Paste it into `app/src/main/oauthConfig.ts` and commit.**
   ```ts
   export const GOOGLE_SIGNIN_CLIENT_ID = '1234567890-abcdefg.apps.googleusercontent.com'
   ```
   That's it. Same file is used for `npm run dev`, packaged DMG / EXE
   builds, and CI. Public-by-design: Google OAuth Client IDs for
   Desktop clients are not secrets (parallel to the Firebase apiKey
   already committed in `renderer/firebase/config.ts`).

## Status

| Step | State |
|------|-------|
| Main-process PKCE flow (`app/src/main/googleSignin.ts`) | done |
| IPC registration (`signin:googleStart` / `signin:googleCancel`) | done |
| Preload + renderer typings | done |
| "Continue with Google" button on `SignIn.tsx` | done |
| Committed config file (`app/src/main/oauthConfig.ts`) | done — pending the actual Client ID value |
| End-to-end live test in `npm run dev` | **pending — needs the Client ID pasted into `oauthConfig.ts`** |
| End-to-end live test on a packaged DMG / EXE | pending |
| Renderer-side surfacing of "not configured" error in plain language | covered by the inline error string returned by main, no extra UX yet |

## Known follow-ups

- **`auth/account-exists-with-different-credential`** — the SignIn
  screen now maps the code, but we don't auto-link the credential. If
  a user already has an email/password account on the same address,
  they have to sign in with email/password to merge. Acceptable
  short-term; Firebase has a `linkWithCredential` API for the proper
  fix.
- **Onboarding-mode stress test.** Verify that opening the app with an
  empty `~/.zylch/profiles/` and clicking Continue with Google produces
  a working signin: no sidecar exists yet, so any IPC path that quietly
  expects one would fail here. The implementation deliberately keeps
  the flow in main process to avoid this dependency.
- **Cancellation UX.** `signin:googleCancel` exists on the preload but
  the SignIn screen doesn't yet wire a Cancel button. Low priority — the
  5-minute timeout cleans up automatically.
