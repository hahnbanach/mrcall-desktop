/**
 * Inline section that owns the "Connect WhatsApp" UX.
 *
 * Mirrors `ConnectGoogleCalendar.tsx` shape so it slots into the
 * Onboarding step-2 flow and the Settings → Integrations group
 * without bespoke layout. The engine does all the work via neonize:
 * we kick off `whatsapp.connect`, wait for a `whatsapp.qr_ready`
 * notification (PNG base64, fallback raw text), render it, then await
 * the connect promise's resolution which fires when the user scans.
 *
 * "Disconnect" closes the active socket. "Forget device" additionally
 * removes the session DB so the next connect needs a fresh QR — the
 * equivalent of a logout from the user's WhatsApp account.
 */
import { useEffect, useState } from 'react'
import { errorMessage } from '../lib/errors'

type Status =
  | { phase: 'loading' }
  | { phase: 'idle'; connected: boolean; hasSession: boolean; jid: string | null }
  | {
      phase: 'connecting'
      qrPng: string | null
      qrText: string | null
    }
  | { phase: 'error'; message: string }

export default function ConnectWhatsApp(): JSX.Element {
  const [state, setState] = useState<Status>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false
    window.zylch.whatsapp
      .status()
      .then((r) => {
        if (cancelled) return
        setState({
          phase: 'idle',
          connected: r.connected,
          hasSession: r.has_session,
          jid: r.jid ?? null
        })
      })
      .catch((e) => {
        if (cancelled) return
        setState({ phase: 'error', message: errorMessage(e) })
      })
    return () => {
      cancelled = true
    }
  }, [])

  const refresh = async (): Promise<void> => {
    try {
      const r = await window.zylch.whatsapp.status()
      setState({
        phase: 'idle',
        connected: r.connected,
        hasSession: r.has_session,
        jid: r.jid ?? null
      })
    } catch (e) {
      setState({ phase: 'error', message: errorMessage(e) })
    }
  }

  const connect = async (): Promise<void> => {
    setState({ phase: 'connecting', qrPng: null, qrText: null })
    // Listen for the QR payload the engine publishes once neonize
    // produces one. The notification can fire BEFORE this listener is
    // wired in pathological races, but in practice neonize takes
    // hundreds of ms to spawn the Go runtime — plenty of headroom.
    const off = window.zylch.onNotification('whatsapp.qr_ready', (params: unknown) => {
      const p = params as { png_base64?: string | null; qr_text?: string | null }
      setState((prev) =>
        prev.phase === 'connecting'
          ? {
              phase: 'connecting',
              qrPng: p.png_base64 ?? null,
              qrText: p.qr_text ?? null
            }
          : prev
      )
    })
    try {
      const r = await window.zylch.whatsapp.connect()
      if (r.ok) {
        await refresh()
      } else {
        setState({
          phase: 'error',
          message: r.reason || 'WhatsApp connect failed'
        })
      }
    } catch (e) {
      setState({ phase: 'error', message: errorMessage(e) })
    } finally {
      off()
    }
  }

  const disconnect = async (forget = false): Promise<void> => {
    try {
      await window.zylch.whatsapp.disconnect(forget)
      await refresh()
    } catch (e) {
      setState({ phase: 'error', message: errorMessage(e) })
    }
  }

  const cancelConnect = async (): Promise<void> => {
    try {
      await window.zylch.whatsapp.cancel()
    } catch {
      /* surfaced via the connect promise */
    }
  }

  return (
    <section className="bg-white border border-brand-mid-grey rounded-lg shadow-sm p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-brand-black">WhatsApp</h3>
          <p className="text-xs text-brand-grey-80 mt-0.5">
            Local connection via the WhatsApp Linked Devices flow. Messages and contacts stay
            on this machine — nothing routes through a third-party server.
          </p>
        </div>
        <div className="shrink-0">
          {state.phase === 'loading' && (
            <span className="text-xs text-brand-grey-80">Checking…</span>
          )}
          {state.phase === 'idle' && state.connected && (
            <div className="flex gap-2">
              <button
                onClick={() => disconnect(false)}
                className="px-3 py-1.5 text-xs border rounded text-brand-grey-80 hover:bg-brand-light-grey"
              >
                Disconnect
              </button>
              <button
                onClick={() => disconnect(true)}
                className="px-3 py-1.5 text-xs border rounded text-brand-grey-80 hover:bg-brand-danger/10 hover:text-brand-danger"
                title="Disconnect AND remove the local session — next connect requires a new QR scan."
              >
                Forget device
              </button>
            </div>
          )}
          {state.phase === 'idle' && !state.connected && (
            <button
              onClick={connect}
              className="px-3 py-1.5 text-xs bg-brand-black text-white rounded"
            >
              {state.hasSession ? 'Reconnect WhatsApp' : 'Connect WhatsApp'}
            </button>
          )}
          {state.phase === 'connecting' && (
            <button
              onClick={cancelConnect}
              className="px-3 py-1.5 text-xs border rounded text-brand-grey-80 hover:bg-brand-light-grey"
            >
              Cancel
            </button>
          )}
        </div>
      </div>

      {state.phase === 'idle' && state.connected && state.jid && (
        <p className="text-xs text-brand-grey-80 mt-2">
          Connected as <strong>+{state.jid}</strong>
        </p>
      )}

      {state.phase === 'connecting' && (
        <div className="mt-3 border-t pt-3">
          <p className="text-xs text-brand-grey-80 mb-3">
            On your phone open <strong>WhatsApp → Settings → Linked Devices → Link a Device</strong>{' '}
            and scan this code (refreshes every 20s).
          </p>
          {state.qrPng ? (
            <img
              src={`data:image/png;base64,${state.qrPng}`}
              alt="WhatsApp QR code"
              className="block w-[256px] h-[256px] border border-brand-mid-grey rounded bg-white"
            />
          ) : state.qrText ? (
            <pre className="p-2 bg-brand-light-grey rounded text-[10px] leading-tight overflow-auto">
              {state.qrText}
            </pre>
          ) : (
            <div className="text-xs text-brand-grey-80">Generating QR code…</div>
          )}
        </div>
      )}

      {state.phase === 'error' && (
        <div className="mt-2 flex items-center justify-between gap-2">
          <p className="text-xs text-brand-danger flex-1">{state.message}</p>
          <button
            onClick={() => void refresh()}
            className="px-2 py-1 text-xs border rounded text-brand-grey-80 hover:bg-brand-light-grey"
          >
            Retry
          </button>
        </div>
      )}
    </section>
  )
}
