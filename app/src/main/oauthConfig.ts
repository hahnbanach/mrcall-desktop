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
export const GOOGLE_SIGNIN_CLIENT_ID = ''
