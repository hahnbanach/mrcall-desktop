import { useEffect, useRef, useState } from 'react'
import type { SidecarStatusEvent } from '../types'
import { errorMessage, isProfileLockedError } from '../lib/errors'

export default function Update() {
  const [running, setRunning] = useState(false)
  const [pct, setPct] = useState(0)
  const [message, setMessage] = useState<string>('')
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  // Track sidecar liveness so we can disable the Update button (and
  // its de-facto Retry behaviour) when the profile is locked. Without
  // this the user can keep clicking "Update now", each click producing
  // a fresh failed RPC and a flash of the (now-suppressed) toast.
  const [sidecarLocked, setSidecarLocked] = useState(false)
  const unsubRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    const off = window.zylch.onSidecarStatus((s: SidecarStatusEvent) => {
      setSidecarLocked(!s.alive && s.code === 'profile_locked')
    })
    return off
  }, [])

  useEffect(() => {
    return () => {
      unsubRef.current?.()
    }
  }, [])

  const run = async () => {
    setRunning(true)
    setPct(0)
    setMessage('Starting…')
    setResult(null)
    setError(null)
    const unsub = window.zylch.onNotification('update.progress', (p: any) => {
      if (typeof p?.pct === 'number') setPct(p.pct)
      if (typeof p?.message === 'string') setMessage(p.message)
    })
    unsubRef.current = unsub
    try {
      const r = await window.zylch.update.run()
      setResult(r)
      setPct(100)
      setMessage('Done')
    } catch (e: unknown) {
      // Don't render the verbose RPC error inline when the sidecar is
      // dead because of a profile lock — the top-of-window banner is
      // already explaining it.
      if (isProfileLockedError(e)) {
        setError(null)
      } else {
        setError(errorMessage(e))
      }
    } finally {
      unsub()
      unsubRef.current = null
      setRunning(false)
    }
  }

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold mb-4">Update</h1>
      <button
        onClick={run}
        disabled={running || sidecarLocked}
        title={sidecarLocked ? 'Sidecar is locked — see banner above' : undefined}
        className="px-4 py-2 bg-slate-900 text-white rounded disabled:bg-slate-400"
      >
        {running ? 'Updating…' : 'Update now'}
      </button>

      {(running || pct > 0) && (
        <div className="mt-6">
          <div className="h-2 bg-slate-200 rounded overflow-hidden">
            <div
              className="h-full bg-slate-900 transition-all"
              style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
            />
          </div>
          <div className="text-sm text-slate-600 mt-2">
            {pct}% — {message}
          </div>
        </div>
      )}

      {error && (
        <div className="mt-4 p-3 bg-red-50 border border-red-200 text-red-800 rounded whitespace-pre-wrap">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-6">
          <h2 className="text-sm font-semibold uppercase text-slate-600 mb-2">Result</h2>
          <pre className="p-3 bg-white border rounded text-xs whitespace-pre-wrap overflow-auto">
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
