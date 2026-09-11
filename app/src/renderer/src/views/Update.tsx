/** Fetch messages separately from bounded, paid analysis. */
import { useEffect, useRef, useState } from 'react'
import type { SidecarStatusEvent } from '../types'
import { errorMessage, isProfileLockedError } from '../lib/errors'
import { useTasks } from '../store/tasks'
import PreparationPanel from '../components/PreparationPanel'

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
function ProgressBlock({ pct, message }: { pct: number; message: string; running?: boolean }): JSX.Element {
  return <div className="mt-4" role="status">
    <progress className="w-full" value={pct} max={100} />
    <p className="text-sm">{pct}% — {message}</p>
  </div>
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
  const setupGeneration = useRef(0)
  const accountGeneration = useRef(0)
  const [setupError, setSetupError] = useState<string | null>(null)
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

  const [preparationRunning, setPreparationRunning] = useState(false)
  const [preparationSupported, setPreparationSupported] = useState(false)
  const [preparationPaused, setPreparationPaused] = useState(true)
  const trainUnsubRef = useRef<(() => void) | null>(null)
  const syncUnsubRef = useRef<(() => void) | null>(null)
  const { refresh: refreshTasks } = useTasks()

  // Refresh setup.state. Called on mount, after every completed action,
  // and on sidecar revival (so a profile that came back from a crash
  // re-checks its state).
  const refreshSetup = async (): Promise<void> => {
    const request = ++setupGeneration.current
    try {
      const s = await window.zylch.setup.state()
      if (request !== setupGeneration.current) return
      setSetup(s)
      setSetupError(null)
    } catch (e) {
      // setup.state can fail on a freshly-spawned sidecar that's still
      // warming up; let the caller decide whether to retry. We don't
      // surface the error inline because the cards still render in a
      // sensible (gated) state without a snapshot.
      if (request !== setupGeneration.current) return
      setSetup(null)
      setSetupError('Could not check preparation. Check your engine connection in Settings, then retry.')
    }
  }

  useEffect(() => {
    void refreshSetup()
  }, [])

  useEffect(() => {
    const off = window.zylch.onSidecarStatus((s: SidecarStatusEvent) => {
      accountGeneration.current++
      setSyncRunning(false); setTrainRunning(false)
      setSyncResult(null); setTrainResult(null)
      setSyncError(null); setTrainError(null)
      setSyncPct(0); setTrainPct(0)
      syncUnsubRef.current?.(); trainUnsubRef.current?.()
      if (!s.alive || !s.ready) { setupGeneration.current++; setSetup(null) }
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
      setupGeneration.current++
      accountGeneration.current++
      trainUnsubRef.current?.()
      syncUnsubRef.current?.()
    }
  }, [])

  const runSync = async (): Promise<void> => {
    const account = accountGeneration.current
    setSyncRunning(true)
    setSyncPct(0)
    setSyncMessage('Starting…')
    setSyncResult(null)
    setSyncError(null)
    const unsub = window.zylch.onNotification('sync.progress', (p: any) => {
      if (account !== accountGeneration.current) return
      if (typeof p?.pct === 'number') setSyncPct(p.pct)
      if (typeof p?.message === 'string') setSyncMessage(p.message)
    })
    syncUnsubRef.current = unsub
    try {
      const r = await window.zylch.sync.run({})
      if (account !== accountGeneration.current) return
      setSyncResult(r)
      setSyncPct(100)
      setSyncMessage(r.success ? 'Done' : 'Sync failed')
    } catch (e: unknown) {
      if (account !== accountGeneration.current) return
      if (isProfileLockedError(e)) {
        setSyncError(null)
      } else {
        setSyncError(errorMessage(e))
      }
    } finally {
      unsub()
      if (account !== accountGeneration.current) return
      syncUnsubRef.current = null
      setSyncRunning(false)
      // A successful sync may have unlocked the Train card — refresh.
      void refreshSetup()
    }
  }

  const runTrain = async (): Promise<void> => {
    const account = accountGeneration.current
    setTrainRunning(true)
    setTrainPct(0)
    setTrainMessage('Starting…')
    setTrainResult(null)
    setTrainError(null)
    const unsub = window.zylch.onNotification('agents.train.progress', (p: any) => {
      if (account !== accountGeneration.current) return
      if (typeof p?.pct === 'number') setTrainPct(p.pct)
      if (typeof p?.message === 'string') setTrainMessage(p.message)
    })
    trainUnsubRef.current = unsub
    try {
      const r = await window.zylch.agents.trainAll()
      if (account !== accountGeneration.current) return
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
      if (account !== accountGeneration.current) return
      if (isProfileLockedError(e)) {
        setTrainError(null)
      } else {
        setTrainError(errorMessage(e))
      }
    } finally {
      unsub()
      if (account !== accountGeneration.current) return
      trainUnsubRef.current = null
      setTrainRunning(false)
      // A successful train may have unlocked the Update card — refresh.
      void refreshSetup()
    }
  }

  const anyRunning = syncRunning || trainRunning || preparationRunning

  // Gating booleans. `setup === null` while the first fetch is in
  // flight; default to "gated" in that case rather than flashing the
  // buttons enabled and then disabled half a tick later.
  const trainEnabled = !!setup?.has_synced

  const trainGateTitle = sidecarLocked
    ? 'Sidecar is locked — see banner above'
    : anyRunning
      ? 'Wait for the current action to finish'
      : !trainEnabled
        ? 'Run Sync first — Train needs at least one email or WhatsApp message to learn from.'
        : undefined

  return (
    <div className="p-6 max-w-3xl mx-auto">
      {setupError && <div role="alert" className="mb-4 p-3 border rounded text-sm">{setupError} <button className="underline" onClick={() => void refreshSetup()}>Retry checks</button></div>}
      <h1 className="text-2xl font-semibold mb-2">Prepare your data</h1>
      <p className="text-sm text-brand-grey-80 mb-6">First download messages, then analyze a small batch. You choose when paid AI runs.</p>
      {/* ───── Sync card ─────────────────────────────────────── */}
      <h2 className="text-xl font-semibold mb-2">Download messages</h2>
      <p className="text-sm text-brand-grey-80 mb-3">
        Fetch new emails (IMAP) and WhatsApp messages into the engine database. No paid AI
        runs here.
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

      <PreparationPanel disabled={syncRunning || trainRunning || sidecarLocked}
        hasData={!!setup?.has_synced} onBusy={setPreparationRunning}
        onFinished={() => { void refreshSetup(); void refreshTasks() }}
        onAvailability={(supported, paused) => { setPreparationSupported(supported); setPreparationPaused(paused) }} />
      <hr className="my-8 border-brand-mid-grey" />
      {/* ───── Train card ────────────────────────────────────── */}
      <h1 className="text-2xl font-semibold mb-2">Train assistant</h1>
      <p className="text-sm text-brand-grey-80 mb-3">
        Optional: regenerate assistant guidance from your synced history. This uses paid AI.
        Missing guidance is created automatically by Analyze next batch.
      </p>
      <button
        onClick={() => void runTrain()}
        disabled={!trainEnabled || anyRunning || sidecarLocked || !preparationSupported || preparationPaused}
        title={trainGateTitle}
        className="px-4 py-2 bg-brand-black text-white rounded disabled:bg-brand-mid-grey"
      >
        {trainRunning ? 'Training…' : 'Regenerate guidance'}
      </button>
      {preparationPaused && <p className="text-xs text-brand-grey-80 mt-2">Manual retraining is disabled while analysis is paused. Analyze next batch can create missing guidance.</p>}
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

    </div>
  )
}
