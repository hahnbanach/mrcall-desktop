/**
 * Inline section that owns the "Connect Google Calendar" UX:
 *   - Reads google.calendar.status() on mount.
 *   - Connect button: starts the OAuth flow on the engine, listens for
 *     the `google.calendar.auth_url_ready` notification, opens the URL
 *     in the user's default browser, then awaits the connect call's
 *     resolution (engine completes the PKCE round-trip).
 *   - Disconnect button when already connected.
 *
 * Designed to slot into Settings.tsx — no top-level layout, just a
 * card-shaped section.
 *
 * Engine-session recovery: the Firebase ID token is pushed to the
 * sidecar via `account.set_firebase_token` from the auth gate (see
 * App.tsx:780). That single push can fail silently for transient
 * reasons (sidecar not fully attached yet, RPC dispatcher race). The
 * 50-min proactive refresh is the only retry. To stop this view from
 * surfacing the cryptic engine error `_NotSignedInError: No active
 * Firebase session — sign in first`, we re-push the token before
 * every Calendar RPC, and recover from a `signed_in: false` status
 * the same way.
 */
import { useEffect, useState } from 'react'
import { auth } from '../firebase/config'
import { repushTokenForCurrentUser } from '../firebase/authUtils'
import { errorMessage } from '../lib/errors'

type Status =
  | { phase: 'loading' }
  | { phase: 'idle'; connected: boolean; email: string | null }
  | { phase: 'connecting' }
  | { phase: 'signin-required' }
  | { phase: 'error'; message: string }

/**
 * Ensure the engine has a current Firebase token in memory. Returns
 * true when the engine reports `signed_in: true` after the push.
 *
 * Used as a defensive guard before every Calendar RPC because the
 * one-shot push at auth-bind time can fail silently.
 */
async function ensureEngineSession(): Promise<boolean> {
  const user = auth.currentUser
  if (!user || user.isAnonymous) return false
  try {
    await repushTokenForCurrentUser()
  } catch (e) {
    console.warn('[ConnectGoogleCalendar] token re-push failed:', e)
    // Continue — the engine may still have a usable session from a
    // prior push. The whoAmI check below is the real arbiter.
  }
  try {
    const who = await window.zylch.account.whoAmI()
    return !!who.signed_in
  } catch (e) {
    console.warn('[ConnectGoogleCalendar] account.whoAmI failed:', e)
    return false
  }
}

export default function ConnectGoogleCalendar(): JSX.Element {
  const [state, setState] = useState<Status>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        let r = await window.zylch.google.calendar.status()
        // The engine may report `signed_in: false` if the auth-bind
        // push lost its race with this view's mount. Try a recovery
        // push and re-read before giving up.
        if (!r.signed_in) {
          const ok = await ensureEngineSession()
          if (cancelled) return
          if (ok) {
            r = await window.zylch.google.calendar.status()
          } else {
            setState({ phase: 'signin-required' })
            return
          }
        }
        if (cancelled) return
        setState({
          phase: 'idle',
          connected: r.connected,
          email: r.email ?? null
        })
      } catch (e) {
        if (cancelled) return
        setState({ phase: 'error', message: errorMessage(e) })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const connect = async (): Promise<void> => {
    setState({ phase: 'connecting' })
    // Listen for the consent URL the engine will publish before
    // awaiting the loopback callback. Open it in the user's default
    // browser the moment we see it.
    const off = window.zylch.onNotification(
      'google.calendar.auth_url_ready',
      (params: unknown) => {
        const url = (params as { auth_url?: string })?.auth_url
        if (typeof url === 'string' && url) {
          void window.zylch.shell.openExternal(url).catch(() => {
            /* surfaced via the connect call's error path */
          })
        }
      }
    )
    try {
      // Recovery push first — closes the silent-failure gap that
      // surfaces here as `_NotSignedInError`.
      const sessionOk = await ensureEngineSession()
      if (!sessionOk) {
        setState({ phase: 'signin-required' })
        return
      }
      const r = await window.zylch.google.calendar.connect()
      setState({
        phase: 'idle',
        connected: !!r.ok,
        email: r.email || null
      })
    } catch (e) {
      setState({ phase: 'error', message: errorMessage(e) })
    } finally {
      off()
    }
  }

  const disconnect = async (): Promise<void> => {
    setState({ phase: 'connecting' })
    try {
      const sessionOk = await ensureEngineSession()
      if (!sessionOk) {
        setState({ phase: 'signin-required' })
        return
      }
      await window.zylch.google.calendar.disconnect()
      setState({ phase: 'idle', connected: false, email: null })
    } catch (e) {
      setState({ phase: 'error', message: errorMessage(e) })
    }
  }

  return (
    <section className="bg-white border border-brand-mid-grey rounded-lg shadow-sm p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-brand-black">Google Calendar</h3>
          <p className="text-xs text-brand-grey-80 mt-0.5">
            Read-only access to your calendar so the assistant can answer questions about
            upcoming events. Tokens are stored encrypted on this machine and never leave it.
          </p>
        </div>
        <div className="shrink-0">
          {state.phase === 'loading' && (
            <span className="text-xs text-brand-grey-80">Checking…</span>
          )}
          {state.phase === 'connecting' && (
            <span className="text-xs text-brand-grey-80">Working…</span>
          )}
          {state.phase === 'idle' && state.connected && (
            <button
              onClick={disconnect}
              className="px-3 py-1.5 text-xs border rounded text-brand-grey-80 hover:bg-brand-light-grey"
            >
              Disconnect
            </button>
          )}
          {state.phase === 'idle' && !state.connected && (
            <button
              onClick={connect}
              className="px-3 py-1.5 text-xs bg-brand-black text-white rounded"
            >
              Connect Google Calendar
            </button>
          )}
          {state.phase === 'signin-required' && (
            <button
              onClick={connect}
              className="px-3 py-1.5 text-xs bg-brand-black text-white rounded"
            >
              Retry
            </button>
          )}
        </div>
      </div>
      {state.phase === 'idle' && state.connected && state.email && (
        <p className="text-xs text-brand-grey-80 mt-2">
          Connected as <strong>{state.email}</strong>
        </p>
      )}
      {state.phase === 'signin-required' && (
        <p className="text-xs text-brand-orange mt-2">
          The engine isn't seeing your Firebase session. This usually clears
          itself — click Retry. If it persists, sign out from the top-right
          menu and sign back in.
        </p>
      )}
      {state.phase === 'error' && (
        <p className="text-xs text-brand-danger mt-2">{state.message}</p>
      )}
    </section>
  )
}
