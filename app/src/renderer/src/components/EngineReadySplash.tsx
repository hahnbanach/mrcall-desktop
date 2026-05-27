/**
 * Splash shown while the sidecar is booting but `engine.ready` has not
 * yet arrived. First-boot of a brand-new profile imports the full engine
 * (neonize Go runtime, fastembed ONNX, SQLAlchemy schema, initial WAL),
 * which can take 30–60 seconds. Without this gate the renderer fires
 * mount-time RPCs against a busy sidecar and the first batch
 * (`account.set_firebase_token`, `settings.get`, `settings.schema`,
 * `mrcall.list_my_businesses`) all time out at 60 s.
 *
 * The splash shows an elapsed timer + the latest log line streaming from
 * the file tailer (so the user sees the engine is actually doing
 * something). After ~30 s a "Show Logs" escape opens the Logs tab
 * (`bypass=true`); after ~3 min the copy switches to "this is taking
 * unusually long" and offers a sidecar restart.
 */
import { useEffect, useRef, useState } from 'react'

interface Props {
  onShowLogs: () => void
}

function formatElapsed(secs: number): string {
  const m = Math.floor(secs / 60)
  const s = secs % 60
  if (m === 0) return `${s}s`
  return `${m}m${s.toString().padStart(2, '0')}s`
}

export default function EngineReadySplash({ onShowLogs }: Props): JSX.Element {
  const [elapsed, setElapsed] = useState(0)
  const [lastLog, setLastLog] = useState<string>('')
  const [restarting, setRestarting] = useState(false)
  const startedAtRef = useRef<number>(Date.now())

  useEffect(() => {
    const t = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAtRef.current) / 1000))
    }, 250)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    const off = window.zylch.onLogLine((chunk: string) => {
      const lines = chunk.split('\n').filter((l) => l.length > 0)
      if (lines.length > 0) setLastLog(lines[lines.length - 1])
    })
    return off
  }, [])

  const showBypass = elapsed >= 30
  const veryLong = elapsed >= 180

  const onRestart = async (): Promise<void> => {
    setRestarting(true)
    try {
      await window.zylch.sidecar.restart()
    } finally {
      setRestarting(false)
    }
  }

  return (
    <div className="flex-1 flex items-center justify-center bg-brand-light-grey">
      <div className="max-w-md w-full px-8 text-center">
        <div className="flex justify-center mb-5">
          <div
            className="animate-spin h-10 w-10 rounded-full border-[3px] border-brand-mid-grey border-t-brand-black"
            aria-hidden="true"
          />
        </div>
        <h2 className="text-xl font-semibold text-brand-black">
          {veryLong ? 'Avvio dell’assistant… (lento)' : 'Avvio dell’assistant…'}
        </h2>
        <p className="text-sm text-brand-grey-80 mt-2">
          {veryLong
            ? 'Sembra che ci stia mettendo molto. Apri i Logs per vedere cosa sta facendo, o riavvia il sidecar.'
            : 'Carico l’engine, il DB del profilo e gli embedding. Al primo avvio di un account questo dura un minuto.'}
        </p>
        <div className="text-xs text-brand-grey-80 mt-4 tabular-nums">
          {formatElapsed(elapsed)}
        </div>
        {lastLog && (
          <div
            className="text-[11px] font-mono text-brand-grey-80 mt-5 truncate px-3 py-2 rounded border border-brand-mid-grey/40 bg-white text-left"
            title={lastLog}
          >
            {lastLog}
          </div>
        )}
        {(showBypass || veryLong) && (
          <div className="mt-6 flex items-center justify-center gap-3">
            <button
              onClick={onShowLogs}
              className="px-3 py-1.5 text-sm border border-brand-mid-grey rounded hover:bg-white"
            >
              Vedi Logs
            </button>
            {veryLong && (
              <button
                onClick={() => void onRestart()}
                disabled={restarting}
                className="px-3 py-1.5 text-sm bg-brand-black text-white rounded disabled:bg-brand-mid-grey"
              >
                {restarting ? 'Riavvio…' : 'Riavvia sidecar'}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
