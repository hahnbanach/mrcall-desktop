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
let authGeneration = 0
let revokedUser: User | null = null
const invalidationListeners = new Set<() => void>()

export function onAuthSessionInvalidated(listener: () => void): () => void {
  invalidationListeners.add(listener)
  return () => { invalidationListeners.delete(listener) }
}

export function isAuthSessionActive(): boolean {
  const user = auth.currentUser
  return !!user && !user.isAnonymous && revokedUser !== user
}

export function setTokenPusher(fn: TokenPusher | null): void {
  tokenPusher = fn
}

export function invalidateAuthSession(): void {
  authGeneration++
  revokedUser = auth.currentUser
  tokenPusher = null
  stopProactiveRefresh()
  // Invalidate outstanding UI lookups even if Firebase sign-out fails offline.
  for (const listener of invalidationListeners) {
    try { listener() } catch { console.warn('[firebase/authUtils] session invalidation listener failed') }
  }
}

function sessionIsCurrent(user: User, generation: number): boolean {
  return (
    generation === authGeneration && auth.currentUser === user &&
    revokedUser !== user && !user.isAnonymous
  )
}

async function pushToken(user: User, generation = authGeneration): Promise<string> {
  const pusher = tokenPusher
  if (!sessionIsCurrent(user, generation)) throw new Error('Authentication session changed')
  if (!pusher) throw new Error('Token forwarding unavailable')
  const result = await user.getIdTokenResult(true)
  if (!sessionIsCurrent(user, generation) || tokenPusher !== pusher) {
    throw new Error('Authentication session changed')
  }
  const expiresAtMs = Date.parse(result.expirationTime)
  if (!Number.isFinite(expiresAtMs) || expiresAtMs <= Date.now()) {
    throw new Error('Fresh authentication token unavailable')
  }
  await pusher({
    uid: user.uid,
    email: user.email,
    idToken: result.token,
    expiresAtMs,
    refreshToken: user.refreshToken
  })
  if (!sessionIsCurrent(user, generation)) throw new Error('Authentication session changed')
  return result.token
}

function startProactiveRefresh(): void {
  stopProactiveRefresh()
  refreshInterval = setInterval(async () => {
    const user = auth.currentUser
    if (!user || user.isAnonymous) {
      stopProactiveRefresh()
      return
    }
    try {
      await pushToken(user)
    } catch {
      console.warn('[firebase/authUtils] proactive token push failed')
    }
  }, REFRESH_INTERVAL_MS)
}

function stopProactiveRefresh(): void {
  if (refreshInterval) {
    clearInterval(refreshInterval)
    refreshInterval = null
  }
}

export function setupAuthListener(onUserChange?: (user: User | null) => void): () => void {
  let active = true
  const offRefresh = window.zylch.account.onTokenRefreshRequest(async (uid) => {
    const user = auth.currentUser
    if (!active || !user || user.isAnonymous || user.uid !== uid) return false
    try {
      await pushToken(user)
      return active
    } catch {
      return false
    }
  })
  const unsub = onAuthStateChanged(auth, (user) => {
    if (!active || auth.currentUser !== user) return
    authGeneration++
    stopProactiveRefresh()
    if (user && revokedUser === user) return
    revokedUser = null
    onUserChange?.(user)
    if (user && !user.isAnonymous) {
      startProactiveRefresh()
      if (tokenPusher) {
        void pushToken(user).catch(() => {
          console.warn('[firebase/authUtils] initial token push failed')
        })
      }
    }
  })
  return () => {
    if (!active) return
    active = false
    authGeneration++
    stopProactiveRefresh()
    offRefresh()
    unsub()
  }
}

export async function refreshAuthToken(): Promise<string | null> {
  const user = auth.currentUser
  if (!user || user.isAnonymous) return null
  try {
    return await pushToken(user)
  } catch {
    console.warn('[firebase/authUtils] refresh failed')
    return null
  }
}

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
  const generation = authGeneration
  if (!user || !sessionIsCurrent(user, generation)) return false
  try {
    await repushTokenForCurrentUser()
  } catch {
    console.warn('[firebase/authUtils] token re-push failed')
    // Continue — the engine may still have a usable session from a
    // prior push. The whoAmI check below is the real arbiter.
  }
  try {
    const who = await window.zylch.account.whoAmI()
    return sessionIsCurrent(user, generation) && !!who.signed_in && who.uid === user.uid
  } catch {
    console.warn('[firebase/authUtils] account.whoAmI failed')
    return false
  }
}
