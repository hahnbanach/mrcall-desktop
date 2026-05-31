/**
 * Update view — onboarding hub for new profiles AND maintenance hub for
 * existing ones. Three ordered cards:
 *
 *   1. **Sync**   — IMAP + WhatsApp fetch. Always actionable.
 *   2. **Train**  — generate personalised agent prompts. Gated on ≥1
 *                   message of synced data being present.
 *   3. **Update** — memory extraction + task detection across the synced
 *                   data. Gated on at least one agent prompt having been
 *                   trained.
 *
 * The gating state is per-profile (it comes from ``setup.state``, which
 * reads the profile's SQLite DB). Once the user crosses a threshold,
 * the next card unlocks without needing a manual refresh: every
 * completed action refetches ``setup.state``.
 *
 * The full pipeline (``update.run``) still auto-trains internally if a
 * prompt is missing — so a user who insists on clicking "Update" first
 * isn't stuck. The card gating is guidance, not enforcement.
 */
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

type SyncResult = {
  success: boolean
  summary: string
  result: {
    sync_new: number
    wa_messages: number
    wa_contacts: number
    wa_skipped_reason?: string | null
  }
  errors: Array<{
    severity?: string
    title?: string
    detail?: string
    action?: string
  }>
}

type SetupState = {
  has_synced: boolean
  has_trained: boolean
  emails_count: number
  whatsapp_messages_count: number
  agents_trained: string[]
}

const AGENT_LABELS: Record<string, string> = {
  memory_message: 'Memory (email + WhatsApp)',
  task_email: 'Task detection',
  emailer: 'Writing style'
}

// Small reusable progress bar block shared between the three cards.
function ProgressBlock({
  pct,
  message,
  eta,
  running,
  elapsed,
  overshot
}: {
  pct: number
  message: string
  eta?: string
  running?: boolean
  elapsed?: number
  overshot?: boolean
}): JSX.Element {
  return (
    <div className="mt-4">
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
            {running && elapsed != null && elapsed > 0 && ` · elapsed ${formatElapsed(elapsed)}`}
          </span>
        )}
        {!eta && running && elapsed != null && elapsed > 0 && (
          <span className="ml-2 text-brand-grey-80">· elapsed {formatElapsed(elapsed)}</span>
        )}
      </div>
      {running && overshot && (
        <div className="text-xs text-brand-orange mt-1">
          Running longer than the initial estimate — large memory or task sweeps in
          progress. Check the Logs tab if it stays here for more than a few extra
          minutes.
        </div>
      )}
    </div>
  )
}

function StageErrors({
  errors
}: {
  errors: Array<{ severity?: string; title?: string; detail?: string; action?: string }>
}): JSX.Element {
  return (
    <>
      {errors.map((er, i) => {
        const isErr = er.severity !== 'warning'
        return (
          <div
            key={i}
            className={
              'mt-3 p-3 rounded border whitespace-pre-wrap ' +
              (isErr
                ? 'bg-brand-danger/10 border-brand-danger/30 text-brand-danger'
                : 'bg-brand-orange/10 border-brand-orange/40 text-brand-orange')
            }
          >
            <div className="font-semibold">{'⚠ ' + (er.title || 'Error')}</div>
            {er.detail && <div className="text-sm mt-0.5">{er.detail}</div>}
            {er.action && <div className="text-sm mt-1 font-medium">{'→ ' + er.action}</div>}
          </div>
        )
      })}
    </>
  )
}

export default function Update(): JSX.Element {
  // Setup snapshot driving the gating between the three cards. ``null``
  // until the first fetch resolves — while null we leave the buttons
  // gated (safer than enabling everything and then disabling).
  const [setup, setSetup] = useState<SetupState | null>(null)

  // Track sidecar liveness so we can disable every action when the
  // profile is locked. Without this the user can keep clicking each
  // card's button, every click producing a fresh failed RPC.
  const [sidecarLocked, setSidecarLocked] = useState(false)

  // ── Sync state ──────────────────────────────────────────────
  const [syncRunning, setSyncRunning] = useState(false)
  const [syncPct, setSyncPct] = useState(0)
  const [syncMessage, setSyncMessage] = useState<string>('')
  const [syncResult, setSyncResult] = useState<SyncResult | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)

  // ── Train state ─────────────────────────────────────────────
  const [trainRunning, setTrainRunning] = useState(false)
  const [trainPct, setTrainPct] = useState(0)
  const [trainMessage, setTrainMessage] = useState<string>('')
  const [trainResult, setTrainResult] = useState<TrainResult | null>(null)
  const [trainError, setTrainError] = useState<string | null>(null)

  // ── Update state ────────────────────────────────────────────
  const [running, setRunning] = useState(false)
  const [pct, setPct] = useState(0)
  const [message, setMessage] = useState<string>('')
  const [eta, setEta] = useState<string>('')
  const [elapsed, setElapsed] = useState<number>(0)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)

  const unsubRef = useRef<(() => void) | null>(null)
  const startRef = useRef<number | null>(null)
  const tickerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const trainUnsubRef = useRef<(() => void) | null>(null)
  const syncUnsubRef = useRef<(() => void) | null>(null)
  const { refresh: refreshTasks } = useTasks()

  // Refresh setup.state. Called on mount, after every completed action,
  // and on sidecar revival (so a profile that came back from a crash
  // re-checks its state).
  const refreshSetup = async (): Promise<void> => {
    try {
      const s = await window.zylch.setup.state()
      setSetup(s)
    } catch (e) {
      // setup.state can fail on a freshly-spawned sidecar that's still
      // warming up; let the caller decide whether to retry. We don't
      // surface the error inline because the cards still render in a
      // sensible (gated) state without a snapshot.
      console.warn('[Update] setup.state failed:', e)
    }
  }

  useEffect(() => {
    void refreshSetup()
  }, [])

  useEffect(() => {
    const off = window.zylch.onSidecarStatus((s: SidecarStatusEvent) => {
      const locked = !s.alive && s.code === 'profile_locked'
      setSidecarLocked(locked)
      if (s.alive && s.ready) {
        // Sidecar just came (back) up — refresh our snapshot so the
        // gating reflects the fresh DB.
        void refreshSetup()
      }
    })
    return off
  }, [])

  useEffect(() => {
    return () => {
      unsubRef.current?.()
      trainUnsubRef.current?.()
      syncUnsubRef.current?.()
      if (tickerRef.current) clearInterval(tickerRef.current)
    }
  }, [])

  const runSync = async (): Promise<void> => {
    setSyncRunning(true)
    setSyncPct(0)
    setSyncMessage('Starting…')
    setSyncResult(null)
    setSyncError(null)
    const unsub = window.zylch.onNotification('sync.progress', (p: any) => {
      if (typeof p?.pct === 'number') setSyncPct(p.pct)
      if (typeof p?.message === 'string') setSyncMessage(p.message)
    })
    syncUnsubRef.current = unsub
    try {
      const r = await window.zylch.sync.run({})
      setSyncResult(r)
      setSyncPct(100)
      setSyncMessage(r.success ? 'Done' : 'Sync failed')
    } catch (e: unknown) {
      if (isProfileLockedError(e)) {
        setSyncError(null)
      } else {
        setSyncError(errorMessage(e))
      }
    } finally {
      unsub()
      syncUnsubRef.current = null
      setSyncRunning(false)
      // A successful sync may have unlocked the Train card — refresh.
      void refreshSetup()
    }
  }

  const runTrain = async (): Promise<void> => {
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
          r.error ?? 'One or more agents failed to train — see the per-agent results below.'
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
      // A successful train may have unlocked the Update card — refresh.
      void refreshSetup()
    }
  }

  const runUpdate = async (): Promise<void> => {
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
      void refreshTasks()
    } catch (e: unknown) {
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
      // Update may have created agent prompts via the auto-train fallback
      // path; refresh so the next pageload reflects it.
      void refreshSetup()
    }
  }

  const upper = eta ? etaUpperBoundSeconds(eta) : null
  const overshot = upper != null && elapsed > upper
  const anyRunning = syncRunning || trainRunning || running

  // Gating booleans. `setup === null` while the first fetch is in
  // flight; default to "gated" in that case rather than flashing the
  // buttons enabled and then disabled half a tick later.
  const trainEnabled = !!setup?.has_synced
  const updateEnabled = !!setup?.has_trained

  const trainGateTitle = sidecarLocked
    ? 'Sidecar is locked — see banner above'
    : anyRunning
      ? 'Wait for the current action to finish'
      : !trainEnabled
        ? 'Run Sync first — Train needs at least one email or WhatsApp message to learn from.'
        : undefined

  const updateGateTitle = sidecarLocked
    ? 'Sidecar is locked — see banner above'
    : anyRunning
      ? 'Wait for the current action to finish'
      : !updateEnabled
        ? 'Train the assistant first — Update needs the trained prompts to process messages.'
        : undefined

  return (
    <div className="p-6 max-w-3xl mx-auto">
      {/* Onboarding pointer — shown until the user has set everything up.
          Disappears once both gates are open. */}
      {setup && (!setup.has_synced || !setup.has_trained) && (
        <div className="mb-5 p-3 bg-brand-blue/10 border border-brand-blue/40 text-brand-black rounded text-sm">
          <div className="font-semibold mb-1">Quick start</div>
          <ol className="list-decimal list-inside space-y-0.5">
            <li className={setup.has_synced ? 'opacity-50 line-through' : ''}>
              Click <strong>Sync</strong> to fetch your emails and WhatsApp messages.
            </li>
            <li className={setup.has_trained ? 'opacity-50 line-through' : ''}>
              Click <strong>Train assistant</strong> so it learns your style and contacts.
            </li>
            <li>
              Click <strong>Update</strong> to extract memory and detect action items.
            </li>
          </ol>
        </div>
      )}

      {/* ───── Sync card ─────────────────────────────────────── */}
      <h1 className="text-2xl font-semibold mb-2">Sync</h1>
      <p className="text-sm text-brand-grey-80 mb-3">
        Fetch new emails (IMAP) and WhatsApp messages into the local database. No AI
        runs here. Always available.
      </p>
      <button
        onClick={() => void runSync()}
        disabled={anyRunning || sidecarLocked}
        title={
          sidecarLocked
            ? 'Sidecar is locked — see banner above'
            : anyRunning && !syncRunning
              ? 'Wait for the current action to finish'
              : undefined
        }
        className="px-4 py-2 bg-brand-black text-white rounded disabled:bg-brand-mid-grey"
      >
        {syncRunning ? 'Syncing…' : 'Sync now'}
      </button>

      {(syncRunning || syncPct > 0) && (
        <ProgressBlock pct={syncPct} message={syncMessage} running={syncRunning} />
      )}

      {syncError && (
        <div className="mt-3 p-3 bg-brand-danger/10 border border-brand-danger/30 text-brand-danger rounded whitespace-pre-wrap">
          {syncError}
        </div>
      )}

      {syncResult && (
        <div className="mt-3">
          <StageErrors errors={syncResult.errors || []} />
          {syncResult.success && (
            <div className="mt-2 p-3 bg-white border rounded text-sm">
              {syncResult.summary}
            </div>
          )}
        </div>
      )}

      {setup && (
        <div className="text-xs text-brand-grey-80 mt-2">
          Currently stored: {setup.emails_count} email
          {setup.emails_count === 1 ? '' : 's'}, {setup.whatsapp_messages_count} WhatsApp
          message{setup.whatsapp_messages_count === 1 ? '' : 's'}.
        </div>
      )}

      <hr className="my-8 border-brand-mid-grey" />

      {/* ───── Train card ────────────────────────────────────── */}
      <h1 className="text-2xl font-semibold mb-2">Train assistant</h1>
      <p className="text-sm text-brand-grey-80 mb-3">
        Teach the assistant who you are from your synced email + WhatsApp history.
        Re-train when you want it to relearn your style and priorities.
      </p>
      <button
        onClick={() => void runTrain()}
        disabled={!trainEnabled || anyRunning || sidecarLocked}
        title={trainGateTitle}
        className="px-4 py-2 bg-brand-black text-white rounded disabled:bg-brand-mid-grey"
      >
        {trainRunning ? 'Training…' : 'Train now'}
      </button>
      {!trainEnabled && !sidecarLocked && setup && (
        <div className="text-xs text-brand-grey-80 mt-2">
          Run <strong>Sync</strong> above first — Train needs at least one email or
          WhatsApp message to learn from.
        </div>
      )}

      {(trainRunning || trainPct > 0) && (
        <ProgressBlock pct={trainPct} message={trainMessage} running={trainRunning} />
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

      {/* ───── Update card ───────────────────────────────────── */}
      <h1 className="text-2xl font-semibold mb-2">Update</h1>
      <p className="text-sm text-brand-grey-80 mb-3">
        Extract memory and detect action items across your synced messages. Also runs
        sync first, so this is the one-click "do everything" button.
      </p>
      <button
        onClick={() => void runUpdate()}
        disabled={!updateEnabled || anyRunning || sidecarLocked}
        title={updateGateTitle}
        className="px-4 py-2 bg-brand-black text-white rounded disabled:bg-brand-mid-grey"
      >
        {running ? 'Updating…' : 'Update now'}
      </button>
      {!updateEnabled && !sidecarLocked && setup && (
        <div className="text-xs text-brand-grey-80 mt-2">
          {setup.has_synced
            ? 'Run Train above first — Update uses the trained prompts to process messages.'
            : 'Run Sync and Train above first.'}
        </div>
      )}

      {(running || pct > 0) && (
        <ProgressBlock
          pct={pct}
          message={message}
          eta={eta}
          running={running}
          elapsed={elapsed}
          overshot={overshot}
        />
      )}
      {running && (
        <div className="text-xs text-brand-grey-80 mt-1">
          Safe to close — progress is saved, will resume from where it left off.
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
          {Array.isArray(result.errors) && <StageErrors errors={result.errors} />}
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
