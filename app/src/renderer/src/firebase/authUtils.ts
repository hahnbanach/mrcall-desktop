import { onAuthStateChanged, type User } from 'firebase/auth'
import { auth } from './config'

// Firebase ID tokens expire 1 hour after issue. Refresh proactively at
// 50 minutes — same cadence as mrcall-dashboard so users never see a
// 401 round-trip on a token they could have refreshed.
const REFRESH_INTERVAL_MS = 50 * 60 * 1000

let refreshInterval: ReturnType<typeof setInterval> | null = null

// Renderer-side handler that ships a fresh Firebase token out of the
// renderer. Wired in App.tsx to `window.zylch.account.pushToken` — the
// out-of-band path to the MAIN process (cross-machine transport): main
// caches it per window for the remote-WS handshake and, in local mode,
// forwards it into the engine via `account.set_firebase_token`. Kept as a
// hook here so this module stays transport-agnostic.
type TokenPusher = (info: {
  uid: string
  email: string | null
  idToken: string
  expiresAtMs: number
  // Firebase REFRESH token (long-lived). Sent alongside the ID token so
  // the engine can refresh the ID token server-side for headless / remote
  // operation (used by the WS `auth.refresh` RPC and the local
  // `account.set_firebase_token` path). Never persisted to disk.
  refreshToken: string
}) => Promise<void> | void

let tokenPusher: TokenPusher | null = null

export function setTokenPusher(fn: TokenPusher | null): void {
  tokenPusher = fn
}

async function pushToken(user: User): Promise<void> {
  try {
    const result = await user.getIdTokenResult(true)
    const expiresAtMs = Date.parse(result.expirationTime) || Date.now() + 3600_000
    if (tokenPusher) {
      await tokenPusher({
        uid: user.uid,
        email: user.email,
        idToken: result.token,
        expiresAtMs,
        refreshToken: user.refreshToken
      })
    }
  } catch (e) {
    console.error('[firebase/authUtils] token push failed', e)
  }
}

function startProactiveRefresh(): void {
  stopProactiveRefresh()
  refreshInterval = setInterval(async () => {
    const user = auth.currentUser
    if (!user || user.isAnonymous) {
      stopProactiveRefresh()
      return
    }
    await pushToken(user)
  }, REFRESH_INTERVAL_MS)
}

function stopProactiveRefresh(): void {
  if (refreshInterval) {
    clearInterval(refreshInterval)
    refreshInterval = null
  }
}

export function setupAuthListener(onUserChange?: (user: User | null) => void): () => void {
  const unsub = onAuthStateChanged(auth, async (user) => {
    if (user && !user.isAnonymous) {
      // Initial token push on every signin / app reload while signed in.
      await pushToken(user)
      startProactiveRefresh()
    } else {
      stopProactiveRefresh()
    }
    if (onUserChange) onUserChange(user)
  })
  return unsub
}

export async function refreshAuthToken(): Promise<string | null> {
  const user = auth.currentUser
  if (!user) return null
  try {
    const token = await user.getIdToken(true)
    await pushToken(user)
    return token
  } catch (e) {
    console.error('[firebase/authUtils] refresh failed', e)
    return null
  }
}

// Force a token push for the currently-signed-in user. Used after
// `auth:bindProfile` attaches a sidecar to a previously sidecar-less
// window — the initial push from setupAuthListener would have failed
// silently (no RPC channel), so we re-push now that the channel
// exists. No-op if no user is signed in.
export async function repushTokenForCurrentUser(): Promise<void> {
  const user = auth.currentUser
  if (!user || user.isAnonymous) return
  await pushToken(user)
}

/**
 * Re-push the Firebase token to the engine and verify the engine sees
 * us as signed-in via `account.whoAmI`. Returns true when the engine
 * confirms the session, false otherwise.
 *
 * Why this exists: the engine holds the Firebase token in-memory only
 * (per `app/CLAUDE.md` "Identity (Firebase)"). Every sidecar restart
 * starts session-less. Calls like `account.balance` /
 * `mrcall.list_my_businesses` require an active session and raise
 * `NoActiveSession` (code -32010) until the renderer's auth listener
 * gets around to pushing the token again. Views that depend on the
 * session can call this helper FIRST to self-heal instead of letting
 * a stale RPC fail in the user's face.
 *
 * Shared by `ConnectGoogleCalendar.tsx` (calendar wiring) and
 * `Settings.tsx`'s `LLMProviderCard` (credit balance refresh) — both
 * hit account.* on mount/focus immediately after a sidecar swap.
 */
export async function ensureEngineSession(): Promise<boolean> {
  const user = auth.currentUser
  if (!user || user.isAnonymous) return false
  try {
    await repushTokenForCurrentUser()
  } catch (e) {
    console.warn('[firebase/authUtils] token re-push failed:', e)
    // Continue — the engine may still have a usable session from a
    // prior push. The whoAmI check below is the real arbiter.
  }
  try {
    const who = await window.zylch.account.whoAmI()
    return !!who.signed_in
  } catch (e) {
    console.warn('[firebase/authUtils] account.whoAmI failed:', e)
    return false
  }
}
