/**
 * Logs view — live tail of the sidecar's stderr stream with structured
 * colouring.
 *
 * Source: the main process tails `<profileDir>/zylch.log` (the engine's
 * DEBUG+ file handler — stderr alone is too quiet because the console
 * handler is gated to WARNING+ and the Logs view would look broken on a
 * healthy session). We fetch the scrollback once on mount via
 * `window.zylch.logs.tail()` (seeded from the last ~256 KB of the file)
 * and subscribe to new chunks via `window.zylch.onLogLine(cb)`.
 *
 * Colouring keys off the engine's structured prefix:
 *     YYYY-MM-DD HH:MM:SS module LEVEL message
 * (regex on a structured prefix, not free prose — the forbidden case in
 * the harness rules.) Unstructured continuation lines (Python tracebacks,
 * neonize Go output, third-party warnings) inherit the level of the most
 * recent structured line so a 30-line traceback all reads as one ERROR
 * block instead of a mix of red + plain grey.
 */
import { useEffect, useMemo, useRef, useState } from 'react'

type Level = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL'

interface ParsedLine {
  raw: string
  // `level` is the line's OWN level when it has a structured prefix, or
  // the level CARRIED FORWARD from the previous structured line (so a
  // traceback inherits the ERROR that introduced it). `null` only when no
  // ancestor level is known (e.g. very first lines of an unrelated
  // third-party warning).
  level: Level | null
  // Whether the line itself carried the structured zylch prefix. Used to
  // decide whether to show the module column.
  structured: boolean
  module?: string
  time?: string
  message?: string
}

// Matches the engine's logging.Formatter prefix. The console (stderr)
// handler uses `HH:MM:SS module LEVEL msg` (no date), the file handler
// uses `YYYY-MM-DD HH:MM:SS module LEVEL msg` — both anchored, the date
// prefix is optional. Anchored on a structured prefix, not free prose.
const ZYLCH_LOG_RE =
  /^((?:\d{4}-\d{2}-\d{2} )?\d{2}:\d{2}:\d{2}(?:[,.]\d{3})?) ([\w.]+) (DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+(.*)$/

function parseLines(rawLines: string[]): ParsedLine[] {
  const out: ParsedLine[] = []
  let carry: Level | null = null
  for (const raw of rawLines) {
    const m = raw.match(ZYLCH_LOG_RE)
    if (m) {
      const level = m[3] as Level
      carry = level
      out.push({ raw, level, structured: true, time: m[1], module: m[2], message: m[4] })
    } else {
      out.push({ raw, level: carry, structured: false })
    }
  }
  return out
}

const ALL_LEVELS: Level[] = ['ERROR', 'WARNING', 'INFO', 'DEBUG']

function levelClasses(level: Level | null): string {
  switch (level) {
    case 'CRITICAL':
    case 'ERROR':
      return 'text-brand-danger'
    case 'WARNING':
      return 'text-brand-orange'
    case 'INFO':
      return 'text-brand-black'
    case 'DEBUG':
      return 'text-brand-grey-80'
    default:
      return 'text-brand-grey-80'
  }
}

export default function Logs(): JSX.Element {
  const [rawLines, setRawLines] = useState<string[]>([])
  // DEBUG defaults OFF — the engine logs DEBUG very chattily (e.g. the
  // `whatsapp.status` poll fires every 3 s while the WA tab is mounted)
  // and the user almost never cares. They can enable it on demand.
  const [enabled, setEnabled] = useState<Record<Level, boolean>>({
    ERROR: true,
    WARNING: true,
    INFO: true,
    DEBUG: false,
    CRITICAL: true
  })
  const [paused, setPaused] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  // Track whether the user has manually scrolled away from the bottom.
  // If they have, we don't yank the view back on every new line.
  const stuckToBottomRef = useRef(true)

  // Initial scrollback + live subscription.
  useEffect(() => {
    let cancelled = false
    void window.zylch.logs.tail().then((lines) => {
      if (!cancelled) setRawLines(lines)
    })
    const off = window.zylch.onLogLine((chunk: string) => {
      setRawLines((prev) => {
        const incoming = chunk.split('\n').filter((l) => l.length > 0)
        if (incoming.length === 0) return prev
        const next = prev.concat(incoming)
        // Match main's cap (2000) so the in-process state can't grow
        // unbounded across long sessions.
        if (next.length > 2000) return next.slice(next.length - 2000)
        return next
      })
    })
    return () => {
      cancelled = true
      off()
    }
  }, [])

  // Auto-scroll on new content, unless the user is paused or has manually
  // scrolled away from the bottom.
  useEffect(() => {
    if (paused) return
    const el = scrollRef.current
    if (!el) return
    if (stuckToBottomRef.current) {
      el.scrollTop = el.scrollHeight
    }
  }, [rawLines, paused])

  const parsed = useMemo(() => parseLines(rawLines), [rawLines])
  const visible = useMemo(
    () =>
      parsed.filter((p) => {
        // Lines with a known (own or carried) level are filtered by that.
        // Lines with no level at all always show — they're rare bootstrap
        // noise the user probably wants to see.
        if (!p.level) return true
        return enabled[p.level]
      }),
    [parsed, enabled]
  )

  const counts = useMemo(() => {
    let e = 0
    let w = 0
    for (const p of parsed) {
      if (!p.structured) continue
      if (p.level === 'ERROR' || p.level === 'CRITICAL') e++
      else if (p.level === 'WARNING') w++
    }
    return { errors: e, warnings: w, total: parsed.length }
  }, [parsed])

  const onScroll = (): void => {
    const el = scrollRef.current
    if (!el) return
    // 24 px slack — Chrome subpixel scroll rounding makes exact-bottom
    // comparison flaky.
    stuckToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
  }

  const onClear = async (): Promise<void> => {
    setRawLines([])
    await window.zylch.logs.clear().catch(() => {})
    stuckToBottomRef.current = true
  }

  const onCopyAll = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(visible.map((p) => p.raw).join('\n'))
    } catch {
      /* ignore — some platforms gate clipboard without user gesture */
    }
  }

  const toggle = (level: Level): void =>
    setEnabled((s) => ({ ...s, [level]: !s[level], CRITICAL: s.CRITICAL || level === 'CRITICAL' }))

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between border-b border-brand-mid-grey/60 px-4 py-2 gap-3 flex-wrap">
        <h1 className="text-lg font-semibold">Logs</h1>
        <div className="flex items-center gap-1 text-xs">
          {ALL_LEVELS.map((lv) => (
            <label
              key={lv}
              className={
                'px-2 py-1 rounded border cursor-pointer select-none ' +
                (enabled[lv]
                  ? 'bg-white border-brand-mid-grey'
                  : 'bg-transparent border-brand-mid-grey/40 text-brand-grey-80 line-through')
              }
            >
              <input
                type="checkbox"
                className="sr-only"
                checked={enabled[lv]}
                onChange={() => toggle(lv)}
              />
              <span className={levelClasses(lv)}>{lv}</span>
            </label>
          ))}
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span
            className={
              'tabular-nums ' +
              (counts.errors > 0 ? 'text-brand-danger font-semibold' : 'text-brand-grey-80')
            }
            title={`${counts.errors} ERROR · ${counts.warnings} WARNING · ${counts.total} righe`}
          >
            {counts.errors} err · {counts.warnings} warn · {counts.total} righe
          </span>
          <button
            onClick={() => setPaused((v) => !v)}
            className="px-2 py-1 border border-brand-mid-grey rounded hover:bg-brand-light-grey"
            title={paused ? 'Riprendi auto-scroll' : 'Pausa auto-scroll'}
          >
            {paused ? '▶ Riprendi' : '⏸ Pausa'}
          </button>
          <button
            onClick={() => void onCopyAll()}
            className="px-2 py-1 border border-brand-mid-grey rounded hover:bg-brand-light-grey"
            title="Copia tutto il visibile negli appunti"
          >
            Copia
          </button>
          <button
            onClick={() => void onClear()}
            className="px-2 py-1 border border-brand-mid-grey rounded hover:bg-brand-light-grey"
            title="Pulisci la view (il file zylch.log su disco resta intatto)"
          >
            Clear
          </button>
        </div>
      </div>
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="flex-1 overflow-auto bg-white font-mono text-[12px] leading-snug p-3"
      >
        {visible.length === 0 ? (
          <div className="text-brand-grey-80 text-xs italic">
            Nessuna riga nel buffer ancora. Il sidecar non ha scritto stderr (o hai appena fatto
            Clear). Le righe nuove appaiono qui in tempo reale.
          </div>
        ) : (
          visible.map((p, i) => (
            <div
              key={i}
              className={
                'whitespace-pre-wrap break-words py-px ' +
                levelClasses(p.level) +
                (p.level === 'ERROR' || p.level === 'CRITICAL'
                  ? ' bg-brand-danger/5'
                  : p.level === 'WARNING'
                    ? ' bg-brand-orange/5'
                    : '')
              }
            >
              {p.raw}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
