/**
 * Google sign-in via PKCE loopback OAuth, used by the Firebase signin
 * gate's "Continue with Google" button.
 *
 * Why PKCE-in-main and not Firebase signInWithPopup
 * --------------------------------------------------
 * Firebase JS SDK's signInWithPopup is fragile in Electron: the renderer
 * is loaded from `file://` (or the dev server) and Firebase needs a
 * same-origin postMessage with its auth handler at
 * <project>.firebaseapp.com. The recommended pattern for desktop apps is
 * a system-browser PKCE flow, exchange the code in the host process
 * (Node), then call `signInWithCredential` in the renderer with the
 * resulting Google id_token. This mirrors what the post-signin Calendar
 * OAuth on :19275 already does — the only difference is that this flow
 * runs BEFORE any Python sidecar exists (onboarding mode), so it lives
 * in the main process instead.
 *
 * Configuration
 * -------------
 * `GOOGLE_SIGNIN_CLIENT_ID` env var must point at a Google OAuth client
 * (Desktop or Web type) configured in the same Google Cloud project as
 * Firebase Auth (`talkmeapp-e696c`) with `http://127.0.0.1:19276/oauth2/google/signin-callback`
 * authorized as a redirect URI. The id_token's `aud` claim must be
 * accepted by Firebase Auth's Google provider — clients in the same
 * Cloud project are accepted by default; clients from other projects
 * need to be added to "Whitelist client IDs from external projects" in
 * the Firebase console. No client secret is used (Google's PKCE flow
 * for installed apps).
 *
 * See `docs/execution-plans/google-signin.md` for the full setup runbook.
 */

import { createHash, randomBytes } from 'crypto'
import {
  createServer,
  type IncomingMessage,
  type Server,
  type ServerResponse
} from 'http'

const CALLBACK_HOST = '127.0.0.1'
// Distinct from :19275 (post-signin Calendar OAuth in the engine) so a
// dev-time mistake can't cause the two flows to collide on the same port.
const CALLBACK_PORT = 19276
const CALLBACK_PATH = '/oauth2/google/signin-callback'
const REDIRECT_URI = `http://${CALLBACK_HOST}:${CALLBACK_PORT}${CALLBACK_PATH}`
const GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
const GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
// Sign-in only — `openid` returns the id_token, `email`+`profile`
// populate it. No calendar / drive scopes here; those come later via
// the engine's incremental OAuth flows after a profile exists.
const SCOPES = 'openid email profile'
// 5 min ceiling matches the post-signin Calendar flow. Long enough for
// 2FA, short enough that an abandoned browser tab releases :19276.
const CONSENT_TIMEOUT_MS = 5 * 60 * 1000

export interface GoogleSigninResult {
  idToken: string
  email: string | null
}

interface ActiveFlow {
  cancel: () => void
}

let active: ActiveFlow | null = null

function base64UrlEncode(buf: Buffer): string {
  return buf.toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function pkce(): { verifier: string; challenge: string } {
  // 64 random bytes → 86-char base64url verifier — well above Google's
  // 43-min / 128-max bounds for code_verifier.
  const verifier = base64UrlEncode(randomBytes(64))
  const challenge = base64UrlEncode(createHash('sha256').update(verifier).digest())
  return { verifier, challenge }
}

function buildAuthUrl(clientId: string, challenge: string, state: string): string {
  const p = new URLSearchParams({
    response_type: 'code',
    client_id: clientId,
    redirect_uri: REDIRECT_URI,
    scope: SCOPES,
    state,
    code_challenge: challenge,
    code_challenge_method: 'S256',
    // `select_account` so a user with multiple Google accounts can pick
    // which one to use, even if Chrome has remembered their default.
    prompt: 'select_account'
  })
  return `${GOOGLE_AUTH_URL}?${p.toString()}`
}

async function exchangeCode(
  clientId: string,
  clientSecret: string,
  code: string,
  verifier: string
): Promise<GoogleSigninResult> {
  const body = new URLSearchParams({
    code,
    client_id: clientId,
    redirect_uri: REDIRECT_URI,
    grant_type: 'authorization_code',
    code_verifier: verifier
  })
  // Google's token endpoint enforces client_secret for Desktop OAuth
  // clients during the authorization-code exchange, even with PKCE.
  // Public-by-design per Google's docs (see oauthConfig.ts). Sent only
  // when configured so a future PKCE-only flow keeps working.
  if (clientSecret) {
    body.set('client_secret', clientSecret)
  }
  const res = await fetch(GOOGLE_TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString()
  })
  if (!res.ok) {
    const txt = await res.text()
    // Truncate to keep secrets / large payloads out of logs without
    // hiding the diagnostic head of the response.
    throw new Error(`Google token exchange failed (${res.status}): ${txt.slice(0, 240)}`)
  }
  const data = (await res.json()) as { id_token?: string; error?: string }
  if (!data.id_token) {
    throw new Error(data.error || 'Google token response missing id_token')
  }

  // Best-effort email parse from the id_token's payload — used purely
  // for log lines and the post-callback browser confirmation. The
  // canonical identity comes from Firebase after signInWithCredential.
  let email: string | null = null
  try {
    const seg = data.id_token.split('.')[1]
    if (seg) {
      const decoded = Buffer.from(seg, 'base64url').toString('utf-8')
      const json = JSON.parse(decoded) as Record<string, unknown>
      if (typeof json.email === 'string') email = json.email
    }
  } catch {
    // non-fatal; email stays null
  }
  return { idToken: data.id_token, email }
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    c === '&' ? '&amp;'
      : c === '<' ? '&lt;'
      : c === '>' ? '&gt;'
      : c === '"' ? '&quot;'
      : '&#39;'
  )
}

function consentDoneHtml(message: string): string {
  // Minimal — no scripts, no styles. Browser tab shows it for ~1s before
  // the user switches back to the app; readability matters more than
  // brand polish here.
  return `<!doctype html><html><head><meta charset="utf-8"><title>MrCall Desktop</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; padding: 32px;">
<h2>${escapeHtml(message)}</h2>
</body></html>`
}

/** Cancel any in-flight signin flow. Returns true iff one was cancelled. */
export function cancelGoogleSignin(): boolean {
  const a = active
  active = null
  if (!a) return false
  a.cancel()
  return true
}

/**
 * Run the full PKCE flow. Resolves with the Google id_token for the
 * renderer to pass into `signInWithCredential(GoogleAuthProvider.credential(idToken))`.
 *
 * Concurrent calls cancel any in-flight prior flow first so :19276 can
 * be re-bound cleanly.
 */
export function startGoogleSignin(opts: {
  clientId: string
  clientSecret: string
  onAuthUrl: (url: string) => void
}): Promise<GoogleSigninResult> {
  cancelGoogleSignin()

  return new Promise<GoogleSigninResult>((resolve, reject) => {
    const { verifier, challenge } = pkce()
    const state = base64UrlEncode(randomBytes(24))
    let settled = false
    let server: Server | null = null

    const settleResolve = (v: GoogleSigninResult): void => {
      if (settled) return
      settled = true
      if (active === thisFlow) active = null
      cleanup()
      resolve(v)
    }
    const settleReject = (e: Error): void => {
      if (settled) return
      settled = true
      if (active === thisFlow) active = null
      cleanup()
      reject(e)
    }

    const thisFlow: ActiveFlow = {
      cancel: () => settleReject(new Error('cancelled'))
    }

    const timer = setTimeout(
      () => settleReject(new Error('Google sign-in timed out (no consent in 5 minutes).')),
      CONSENT_TIMEOUT_MS
    )

    function cleanup(): void {
      clearTimeout(timer)
      if (server) {
        try {
          server.close()
        } catch {
          // server may already be closing; non-fatal
        }
      }
    }

    async function handleCallback(req: IncomingMessage, res: ServerResponse): Promise<void> {
      try {
        const hostHeader = req.headers.host || `${CALLBACK_HOST}:${CALLBACK_PORT}`
        const url = new URL(req.url ?? '/', `http://${hostHeader}`)
        if (url.pathname !== CALLBACK_PATH) {
          res.writeHead(404, { 'Content-Type': 'text/plain' })
          res.end('Not found')
          return
        }
        const params = url.searchParams
        const errorParam = params.get('error')
        const code = params.get('code')
        const receivedState = params.get('state')

        if (errorParam) {
          res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
          res.end(
            consentDoneHtml(
              `Sign-in cancelled (${errorParam}). You can close this window.`
            )
          )
          settleReject(new Error(`google_oauth_error: ${errorParam}`))
          return
        }
        if (!code) {
          res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
          res.end(consentDoneHtml('No authorization code received.'))
          settleReject(new Error('no authorization code in callback'))
          return
        }
        if (receivedState !== state) {
          res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
          res.end(
            consentDoneHtml(
              'State mismatch — possible CSRF. Try again from MrCall Desktop.'
            )
          )
          settleReject(new Error('state_mismatch'))
          return
        }

        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
        res.end(
          consentDoneHtml(
            'Signed in. You can close this window and return to MrCall Desktop.'
          )
        )

        const result = await exchangeCode(opts.clientId, opts.clientSecret, code, verifier)
        settleResolve(result)
      } catch (e) {
        try {
          res.writeHead(500, { 'Content-Type': 'text/plain' })
          res.end('Internal error')
        } catch {
          // headers may already be written
        }
        settleReject(e instanceof Error ? e : new Error(String(e)))
      }
    }

    server = createServer((req, res) => {
      void handleCallback(req, res)
    })
    server.on('error', (err) => settleReject(err))
    server.listen(CALLBACK_PORT, CALLBACK_HOST, () => {
      active = thisFlow
      try {
        opts.onAuthUrl(buildAuthUrl(opts.clientId, challenge, state))
      } catch (e) {
        console.error('[main][google-signin] onAuthUrl threw', e)
      }
    })
  })
}
