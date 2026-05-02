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
- **`app/src/main/oauthConfig.ts`** — committed source of truth for the
  public Client ID; re-exports `GOOGLE_SIGNIN_CLIENT_SECRET` from the
  gitignored sibling.
- **`app/src/main/oauthSecrets.ts`** (gitignored) — holds the Google
  Client secret. Postinstall (`scripts/setup-oauth-secrets.mjs`) seeds
  it from `oauthSecrets.example.ts` on a fresh clone so the build
  doesn't fail; the developer pastes the real value locally.
  CI populates it from a repo secret right before `npm run dist`.
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
   - **Application type**: **Desktop app**. Google issues both a
     Client ID and a Client secret for Desktop clients, and the token
     endpoint enforces both during the authorization-code exchange
     even on the PKCE flow — testing with secret missing returns
     `400 invalid_request: client_secret is missing`.
   - **Name**: anything memorable, e.g. `mrcall-desktop-signin`.
   - Copy the **Client ID** (looks like
     `1234567890-abcdefg.apps.googleusercontent.com`) and the **Client
     secret** (looks like `GOCSPX-...`) from the detail page.

2. **(Only if the client lives in a different Cloud project.)**
   For `talkmeapp-e696c` this step is a no-op — the client is in the
   same project as Firebase Auth, so Firebase already trusts it.
   Otherwise: Firebase console → *Authentication → Sign-in method →
   Google → Web SDK configuration → Whitelist client IDs from
   external projects → add the new client ID*.

3. **Paste the public Client ID into `app/src/main/oauthConfig.ts` and
   commit.** Public-by-design (parallel to the Firebase apiKey already
   committed in `renderer/firebase/config.ts`):
   ```ts
   export const GOOGLE_SIGNIN_CLIENT_ID =
     '1234567890-abcdefg.apps.googleusercontent.com'
   ```

4. **Paste the Client secret into the gitignored
   `app/src/main/oauthSecrets.ts`. Do NOT commit.**
   The file is created on first `npm install` by
   `scripts/setup-oauth-secrets.mjs`, which copies the committed
   `oauthSecrets.example.ts` template. Edit it in place:
   ```ts
   export const GOOGLE_SIGNIN_CLIENT_SECRET = 'GOCSPX-...'
   ```
   Why gitignore: the `GOCSPX-` prefix is autodetected by GitHub
   Secret Scanning, which would trigger Google to auto-revoke the
   secret minutes after any push — even though Google's docs say
   installed-app client_secrets aren't really confidential. Restart
   `npm run dev` after editing.

5. **For packaged release builds:** add `GOOGLE_SIGNIN_CLIENT_SECRET`
   as a repo secret at *Settings → Secrets and variables → Actions →
   New repository secret*, and add a step to `release.yml` that writes
   it to `app/src/main/oauthSecrets.ts` before `npm run dist`. Not
   wired yet — see Status table.

## Status

| Step | State |
|------|-------|
| Main-process PKCE flow (`app/src/main/googleSignin.ts`) | done |
| IPC registration (`signin:googleStart` / `signin:googleCancel`) | done |
| Preload + renderer typings | done |
| "Continue with Google" button on `SignIn.tsx` | done |
| Committed config file (`app/src/main/oauthConfig.ts`) | done — Client ID `375340415237-jl3hl6hcu15po65oo7dovl1lb3a960ni…` already wired |
| Gitignored secret file (`app/src/main/oauthSecrets.ts`) + postinstall seeder | done — developer pastes the value locally |
| `client_secret` plumbed through `googleSignin.exchangeCode` | done |
| End-to-end live test in `npm run dev` | **pending — needs `oauthSecrets.ts` populated locally** |
| End-to-end live test on a packaged DMG / EXE | pending — also needs CI step that materialises `oauthSecrets.ts` from a repo secret before `npm run dist` |
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
