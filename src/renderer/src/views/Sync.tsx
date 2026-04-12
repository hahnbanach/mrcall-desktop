import { useEffect, useRef, useState } from 'react'

export default function Sync() {
  const [running, setRunning] = useState(false)
  const [pct, setPct] = useState(0)
  const [message, setMessage] = useState<string>('')
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const unsubRef = useRef<(() => void) | null>(null)

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
    const unsub = window.zylch.onNotification('sync.progress', (p: any) => {
      if (typeof p?.pct === 'number') setPct(p.pct)
      if (typeof p?.message === 'string') setMessage(p.message)
    })
    unsubRef.current = unsub
    try {
      const r = await window.zylch.sync.run()
      setResult(r)
      setPct(100)
      setMessage('Done')
    } catch (e: any) {
      setError(e.message || String(e))
    } finally {
      unsub()
      unsubRef.current = null
      setRunning(false)
    }
  }

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold mb-4">Sync</h1>
      <button
        onClick={run}
        disabled={running}
        className="px-4 py-2 bg-slate-900 text-white rounded disabled:bg-slate-400"
      >
        {running ? 'Syncing…' : 'Sync now'}
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
