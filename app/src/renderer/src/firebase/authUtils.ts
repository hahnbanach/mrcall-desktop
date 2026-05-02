import { onAuthStateChanged, type User } from 'firebase/auth'
import { auth } from './config'

// Firebase ID tokens expire 1 hour after issue. Refresh proactively at
// 50 minutes — same cadence as mrcall-dashboard so users never see a
// 401 round-trip on a token they could have refreshed.
const REFRESH_INTERVAL_MS = 50 * 60 * 1000

let refreshInterval: ReturnType<typeof setInterval> | null = null

// Renderer-side handler that pushes a fresh token to the engine over
// JSON-RPC. Phase 2 wires this up via window.zylch.account.setFirebaseToken;
// Phase 1 leaves it as a hook so the surface is stable.
type TokenPusher = (info: {
  uid: string
  email: string | null
  idToken: string
  expiresAtMs: number
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
        expiresAtMs
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
