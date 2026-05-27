import { useEffect, useRef, useState } from 'react'
import type { SidecarStatusEvent } from '../types'
import { errorMessage, isProfileLockedError } from '../lib/errors'
import { useTasks } from '../store/tasks'

// Coarse ETA buckets returned by the engine map to an upper-bound
// seconds value. We use this to detect when the run has overshot its
// own estimate and to nudge the UI copy from "expected" to "running long".
const ETA_UPPER_BOUND_SECONDS: Array<{ pattern: RegExp; upper: number }> = [
  { pattern: /^under 1 minute$/i, upper: 60 },
  { pattern: /^1-2 minutes$/i, upper: 2 * 60 },
  { pattern: /^2-5 minutes$/i, upper: 5 * 60 },
  { pattern: /^5-15 minutes$/i, upper: 15 * 60 },
  { pattern: /^15-30 minutes$/i, upper: 30 * 60 },
  { pattern: /^30-60 minutes$/i, upper: 60 * 60 },
  { pattern: /^1-2 hours$/i, upper: 2 * 60 * 60 },
  { pattern: /^2\+ hours/i, upper: Number.POSITIVE_INFINITY },
]

function etaUpperBoundSeconds(eta: string): number | null {
  for (const { pattern, upper } of ETA_UPPER_BOUND_SECONDS) {
    if (pattern.test(eta.trim())) return upper
  }
  return null
}

function formatElapsed(secs: number): string {
  if (secs < 60) return `${secs}s`
  const m = Math.floor(secs / 60)
  const s = secs % 60
  if (m < 60) return s === 0 ? `${m}m` : `${m}m${s.toString().padStart(2, '0')}s`
  const h = Math.floor(m / 60)
  const mm = m % 60
  return `${h}h${mm.toString().padStart(2, '0')}m`
}

type TrainResultEntry = {
  ok: boolean
  error?: string
  threads_analyzed?: number
  whatsapp_chats_analyzed?: number
}

type TrainResult = {
  ok: boolean
  error?: string
  results: Record<string, TrainResultEntry>
}

const AGENT_LABELS: Record<string, string> = {
  memory_message: 'Memory (email + WhatsApp)',
  task_email: 'Task detection',
  emailer: 'Writing style'
}

export default function Update() {
  const [running, setRunning] = useState(false)
  const [pct, setPct] = useState(0)
  const [message, setMessage] = useState<string>('')
  const [eta, setEta] = useState<string>('')
  const [elapsed, setElapsed] = useState<number>(0)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  // Training state — separate from the update state so the user can see
  // both cards on the same page even if one is mid-run. Only one of the
  // two actions can be in-flight at a time (button disable below).
  const [trainRunning, setTrainRunning] = useState(false)
  const [trainPct, setTrainPct] = useState(0)
  const [trainMessage, setTrainMessage] = useState<string>('')
  const [trainResult, setTrainResult] = useState<TrainResult | null>(null)
  const [trainError, setTrainError] = useState<string | null>(null)
  // Track sidecar liveness so we can disable the Update button (and
  // its de-facto Retry behaviour) when the profile is locked. Without
  // this the user can keep clicking "Update now", each click producing
  // a fresh failed RPC and a flash of the (now-suppressed) toast.
  const [sidecarLocked, setSidecarLocked] = useState(false)
  const unsubRef = useRef<(() => void) | null>(null)
  const startRef = useRef<number | null>(null)
  const tickerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const trainUnsubRef = useRef<(() => void) | null>(null)
  // Shared tasks store — we call `refresh()` after a successful run so
  // Dashboard re-fetches instead of showing stale data.
  const { refresh: refreshTasks } = useTasks()

  useEffect(() => {
    const off = window.zylch.onSidecarStatus((s: SidecarStatusEvent) => {
      setSidecarLocked(!s.alive && s.code === 'profile_locked')
    })
    return off
  }, [])

  useEffect(() => {
    return () => {
      unsubRef.current?.()
      trainUnsubRef.current?.()
      if (tickerRef.current) clearInterval(tickerRef.current)
    }
  }, [])

  const runTrain = async () => {
    setTrainRunning(true)
    setTrainPct(0)
    setTrainMessage('Starting…')
    setTrainResult(null)
    setTrainError(null)
    const unsub = window.zylch.onNotification('agents.train.progress', (p: any) => {
      if (typeof p?.pct === 'number') setTrainPct(p.pct)
      if (typeof p?.message === 'string') setTrainMessage(p.message)
    })
    trainUnsubRef.current = unsub
    try {
      const r = await window.zylch.agents.trainAll()
      setTrainResult(r)
      setTrainPct(100)
      if (!r.ok) {
        setTrainError(
          r.error ??
            'One or more agents failed to train — see the per-agent results below.'
        )
      } else {
        setTrainMessage('Done')
      }
    } catch (e: unknown) {
      if (isProfileLockedError(e)) {
        setTrainError(null)
      } else {
        setTrainError(errorMessage(e))
      }
    } finally {
      unsub()
      trainUnsubRef.current = null
      setTrainRunning(false)
    }
  }

  const run = async () => {
    setRunning(true)
    setPct(0)
    setMessage('Starting…')
    setEta('')
    setElapsed(0)
    setResult(null)
    setError(null)
    startRef.current = Date.now()
    if (tickerRef.current) clearInterval(tickerRef.current)
    tickerRef.current = setInterval(() => {
      if (startRef.current == null) return
      setElapsed(Math.floor((Date.now() - startRef.current) / 1000))
    }, 1000)
    const unsub = window.zylch.onNotification('update.progress', (p: any) => {
      if (typeof p?.pct === 'number') setPct(p.pct)
      if (typeof p?.message === 'string') setMessage(p.message)
      if (typeof p?.eta === 'string' && p.eta) setEta(p.eta)
    })
    unsubRef.current = unsub
    try {
      const r = await window.zylch.update.run()
      setResult(r)
      setPct(100)
      setMessage(r?.success === false ? 'Update failed' : 'Done')
      // Invalidate the Dashboard's cached tasks — the pipeline may
      // have created, closed or updated rows. Fire-and-forget; do not
      // let a refresh failure block the Update's success UI.
      void refreshTasks()
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
      if (tickerRef.current) {
        clearInterval(tickerRef.current)
        tickerRef.current = null
      }
      setRunning(false)
    }
  }

  const upper = eta ? etaUpperBoundSeconds(eta) : null
  const overshot = upper != null && elapsed > upper

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold mb-4">Train assistant</h1>
      <p className="text-sm text-brand-grey-80 mb-3">
        Teach the assistant who you are from your email + WhatsApp history. Re-train after
        a fresh profile or whenever you want it to relearn your style and priorities.
      </p>
      <button
        onClick={runTrain}
        disabled={trainRunning || running || sidecarLocked}
        title={
          sidecarLocked
            ? 'Sidecar is locked — see banner above'
            : running
              ? 'Wait for the current update to finish'
              : undefined
        }
        className="px-4 py-2 bg-brand-black text-white rounded disabled:bg-brand-mid-grey"
      >
        {trainRunning ? 'Training…' : 'Train now'}
      </button>

      {(trainRunning || trainPct > 0) && (
        <div className="mt-4">
          <div className="h-2 bg-brand-mid-grey rounded overflow-hidden">
            <div
              className="h-full bg-brand-black transition-all"
              style={{ width: `${Math.min(100, Math.max(0, trainPct))}%` }}
            />
          </div>
          <div className="text-sm text-brand-grey-80 mt-2">
            {trainPct}% — {trainMessage}
          </div>
        </div>
      )}

      {trainError && (
        <div className="mt-3 p-3 bg-brand-danger/10 border border-brand-danger/30 text-brand-danger rounded whitespace-pre-wrap">
          {trainError}
        </div>
      )}

      {trainResult && (
        <div className="mt-4">
          <h2 className="text-sm font-semibold uppercase text-brand-grey-80 mb-2">
            Training result
          </h2>
          <ul className="p-3 bg-white border rounded text-sm space-y-1">
            {Object.entries(trainResult.results).map(([key, entry]) => (
              <li key={key} className="flex items-start gap-2">
                <span className={entry.ok ? 'text-green-600' : 'text-brand-danger'}>
                  {entry.ok ? '✓' : '✗'}
                </span>
                <span className="flex-1">
                  <span className="font-medium">{AGENT_LABELS[key] ?? key}</span>
                  {entry.ok ? (
                    <>
                      {typeof entry.threads_analyzed === 'number' && (
                        <span className="text-brand-grey-80">
                          {' '}
                          — {entry.threads_analyzed} email threads
                        </span>
                      )}
                      {typeof entry.whatsapp_chats_analyzed === 'number' &&
                        entry.whatsapp_chats_analyzed > 0 && (
                          <span className="text-brand-grey-80">
                            {' '}
                            + {entry.whatsapp_chats_analyzed} WhatsApp chats
                          </span>
                        )}
                    </>
                  ) : (
                    <span className="text-brand-danger"> — {entry.error}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <hr className="my-8 border-brand-mid-grey" />

      <h1 className="text-2xl font-semibold mb-4">Update</h1>
      <button
        onClick={run}
        disabled={running || trainRunning || sidecarLocked}
        title={
          sidecarLocked
            ? 'Sidecar is locked — see banner above'
            : trainRunning
              ? 'Wait for the training to finish'
              : undefined
        }
        className="px-4 py-2 bg-brand-black text-white rounded disabled:bg-brand-mid-grey"
      >
        {running ? 'Updating…' : 'Update now'}
      </button>

      {(running || pct > 0) && (
        <div className="mt-6">
          <div className="h-2 bg-brand-mid-grey rounded overflow-hidden">
            <div
              className="h-full bg-brand-black transition-all"
              style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
            />
          </div>
          <div className="text-sm text-brand-grey-80 mt-2">
            {pct}% — {message}
            {eta && (
              <span className="ml-2 text-brand-grey-80">
                · ~{eta}
                {running && ` · elapsed ${formatElapsed(elapsed)}`}
              </span>
            )}
            {!eta && running && elapsed > 0 && (
              <span className="ml-2 text-brand-grey-80">· elapsed {formatElapsed(elapsed)}</span>
            )}
          </div>
          {running && overshot && (
            <div className="text-xs text-brand-orange mt-1">
              Running longer than the initial estimate — large memory or task sweeps in
              progress. Check sidecar logs if it stays here for more than a few extra
              minutes.
            </div>
          )}
          {running && (
            <div className="text-xs text-brand-grey-80 mt-1">
              Safe to close — progress is saved, will resume from where it left off.
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="mt-4 p-3 bg-brand-danger/10 border border-brand-danger/30 text-brand-danger rounded whitespace-pre-wrap">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-6">
          <h2 className="text-sm font-semibold uppercase text-brand-grey-80 mb-2">Result</h2>
          {/* Structured errors / warnings from the pipeline — one per stage
              that failed. Red = fatal (run blocked), amber = non-fatal
              (e.g. WhatsApp). Replaces the old false-green "No changes". */}
          {Array.isArray(result.errors) &&
            result.errors.map(
              (
                er: { severity?: string; title?: string; detail?: string; action?: string },
                i: number
              ) => {
                const isErr = er.severity !== 'warning'
                return (
                  <div
                    key={i}
                    className={
                      'mb-2 p-3 rounded border whitespace-pre-wrap ' +
                      (isErr
                        ? 'bg-brand-danger/10 border-brand-danger/30 text-brand-danger'
                        : 'bg-brand-orange/10 border-brand-orange/40 text-brand-orange')
                    }
                  >
                    <div className="font-semibold">{'⚠ ' + (er.title || 'Error')}</div>
                    {er.detail && <div className="text-sm mt-0.5">{er.detail}</div>}
                    {er.action && (
                      <div className="text-sm mt-1 font-medium">{'→ ' + er.action}</div>
                    )}
                  </div>
                )
              }
            )}
          {/* Diff summary box — only on a clean / partial-success run. On a
              fatal failure the error block above already carries the message. */}
          {result.success !== false &&
          typeof result?.summary === 'string' &&
          result.summary.length > 0 ? (
            <div className="p-3 bg-white border rounded text-sm whitespace-pre-wrap">
              {result.summary}
            </div>
          ) : result.success === false ? null : (
            <pre className="p-3 bg-white border rounded text-xs whitespace-pre-wrap overflow-auto">
              {JSON.stringify(result, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}
