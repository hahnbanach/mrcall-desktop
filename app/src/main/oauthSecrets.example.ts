// Template for the gitignored `oauthSecrets.ts`. The `postinstall`
// script copies this file to `oauthSecrets.ts` on first `npm install`
// so the build doesn't break on a fresh clone; the real values land
// in the gitignored copy.
//
// Why this lives outside `oauthConfig.ts`
// ---------------------------------------
// `oauthConfig.ts` carries the public Google OAuth Client ID, which
// is safe to commit to a public repo. The `client_secret` below is
// considered "not confidential" by Google for installed-app clients,
// but GitHub's Secret Scanning autodetects the `GOCSPX-` prefix and
// triggers an automatic Google-side revocation within minutes of any
// commit. So the secret has to stay out of git, even for an MIT/public
// project. This split keeps the architecture in source while moving
// the actual secret to a gitignored sibling.
//
// To bring the dev environment online
// -----------------------------------
//   1. Run `npm install` (the postinstall hook copies this file to
//      `oauthSecrets.ts`), or copy manually:
//        cp src/main/oauthSecrets.example.ts src/main/oauthSecrets.ts
//   2. Open `src/main/oauthSecrets.ts` and paste the Client secret
//      from Google Cloud Console (visible in the Desktop OAuth client
//      detail page, next to the Client ID).
//   3. Restart `npm run dev` so the new value is picked up.
//
// For packaged release builds the same file has to exist before
// `npm run dist`. The simplest path is for CI to write it from a
// GitHub repo secret right before the build step — see
// `docs/execution-plans/google-signin.md`.
export const GOOGLE_SIGNIN_CLIENT_SECRET = ''
