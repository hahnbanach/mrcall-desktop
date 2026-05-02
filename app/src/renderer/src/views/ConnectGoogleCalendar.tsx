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
 */
import { useEffect, useState } from 'react'
import { errorMessage } from '../lib/errors'

type Status =
  | { phase: 'loading' }
  | { phase: 'idle'; connected: boolean; email: string | null }
  | { phase: 'connecting' }
  | { phase: 'error'; message: string }

export default function ConnectGoogleCalendar(): JSX.Element {
  const [state, setState] = useState<Status>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false
    window.zylch.google.calendar
      .status()
      .then((r) => {
        if (cancelled) return
        setState({
          phase: 'idle',
          connected: r.connected,
          email: r.email ?? null
        })
      })
      .catch((e) => {
        if (cancelled) return
        // -32010 (no signed-in session) is a soft state — the user
        // simply isn't signed in yet; render as "idle, not connected".
        const msg = errorMessage(e)
        if (msg.toLowerCase().includes('sign in')) {
          setState({ phase: 'idle', connected: false, email: null })
        } else {
          setState({ phase: 'error', message: msg })
        }
      })
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
        </div>
      </div>
      {state.phase === 'idle' && state.connected && state.email && (
        <p className="text-xs text-brand-grey-80 mt-2">
          Connected as <strong>{state.email}</strong>
        </p>
      )}
      {state.phase === 'error' && (
        <p className="text-xs text-brand-danger mt-2">{state.message}</p>
      )}
    </section>
  )
}
