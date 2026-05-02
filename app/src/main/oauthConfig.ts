// Public configuration for the "Continue with Google" button on the
// Firebase signin gate. Edit this file when the OAuth client changes,
// commit, ship.
//
// Why this is OK to commit
// ------------------------
// Google OAuth Client IDs for "Desktop app" clients are public-by-
// design — same security model as the Firebase apiKey hardcoded in
// `renderer/firebase/config.ts`. The ID identifies the application,
// not the bearer; PKCE + the `127.0.0.1` loopback redirect URI close
// the abuse vectors. Desktop OAuth clients have no client_secret, so
// embedding the ID here doesn't leak anything.
//
// To create / rotate
// ------------------
// 1. Google Cloud Console → APIs & Services → Credentials, in the
//    `talkmeapp-e696c` project (the one Firebase Auth is wired to).
// 2. *Create credentials → OAuth client ID*.
// 3. Application type: **Desktop app** (no client_secret, no redirect
//    URI registration needed — Google accepts any 127.0.0.1 loopback
//    for installed-app clients).
// 4. Paste the resulting Client ID below and commit.
//
// Empty string means "Continue with Google" is not configured for this
// build; the IPC returns a friendly error rather than silently failing.
//
// The project-number prefix `375340415237` matches the
// `messagingSenderId` in `renderer/firebase/config.ts`, confirming the
// client lives in the same Google Cloud project as Firebase Auth — so
// the resulting id_token's audience is accepted without an external
// whitelist step.
export const GOOGLE_SIGNIN_CLIENT_ID =
  '375340415237-jl3hl6hcu15po65oo7dovl1lb3a960ni.apps.googleusercontent.com'

// Companion `client_secret` for the Desktop OAuth client. Google's
// token endpoint requires it during the authorization-code exchange
// even on the PKCE flow — testing without it returns
// `400 invalid_request: client_secret is missing`.
//
// Per Google's docs the secret isn't confidential for installed-app
// clients (it ships in the binary anyway), and PKCE is the real
// security boundary. BUT GitHub Secret Scanning autodetects the
// `GOCSPX-` prefix and triggers an automatic Google-side revocation
// minutes after any commit lands. So the actual value lives in the
// gitignored sibling `oauthSecrets.ts`, populated locally (postinstall
// copies the `.example` template) and in CI (a workflow step writes
// it from a repo secret before `npm run dist`).
export { GOOGLE_SIGNIN_CLIENT_SECRET } from './oauthSecrets'
