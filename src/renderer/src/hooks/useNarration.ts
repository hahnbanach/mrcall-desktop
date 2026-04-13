import { useEffect, useRef, useState } from 'react'

/**
 * useNarration — live first-person Italian narration of what the sidecar
 * is doing, synthesized from its stderr by a tiny Haiku call.
 *
 * Rules:
 *  - Subscribes to window.zylch.onStderr once on mount.
 *  - Keeps a rolling buffer (last BUFFER_CAP lines).
 *  - While `busy` is true, every POLL_MS ms, if there's at least one new
 *    non-DEBUG non-empty line since the last call, it invokes
 *    narration.summarize with the full current buffer + `context`.
 *  - Transitions busy true -> false clear the narration.
 *
 * Returns the latest narration string ("" when idle or nothing to say).
 */

const BUFFER_CAP = 40
const POLL_MS = 2500

export function useNarration(busy: boolean, context: string): string {
  const [narration, setNarration] = useState<string>('')
  const bufferRef = useRef<string[]>([])
  // Number of lines we had processed when we last fired a summarize call.
  const lastSeenCountRef = useRef<number>(0)
  // Monotonic total lines received (independent of buffer trimming).
  const totalLinesRef = useRef<number>(0)
  const inFlightRef = useRef<boolean>(false)

  // Subscribe once to stderr.
  useEffect(() => {
    const onStderr = (window as any).zylch?.onStderr
    if (typeof onStderr !== 'function') return
    const off = onStderr((chunk: string) => {
      // Split on newlines; each chunk can contain multiple lines.
      const parts = String(chunk).split(/\r?\n/)
      for (const raw of parts) {
        const s = raw.trim()
        if (!s) continue
        bufferRef.current.push(s)
        totalLinesRef.current += 1
      }
      // Trim buffer to cap.
      if (bufferRef.current.length > BUFFER_CAP) {
        bufferRef.current = bufferRef.current.slice(-BUFFER_CAP)
      }
    })
    return () => {
      try {
        off?.()
      } catch {
        /* ignore */
      }
    }
  }, [])

  // While busy: poll; when busy->false, clear.
  useEffect(() => {
    if (!busy) {
      setNarration('')
      lastSeenCountRef.current = totalLinesRef.current
      return
    }

    let cancelled = false
    const tick = async () => {
      if (cancelled || inFlightRef.current) return
      const lines = bufferRef.current
      // Anything new since last call?
      const newCount = totalLinesRef.current
      if (newCount <= lastSeenCountRef.current) return
      // Check buffer has ≥1 non-DEBUG non-empty line.
      const hasSignal = lines.some(
        (l) => l && !/ DEBUG /.test(l)
      )
      if (!hasSignal) {
        lastSeenCountRef.current = newCount
        return
      }
      inFlightRef.current = true
      const snapshot = [...lines]
      lastSeenCountRef.current = newCount
      try {
        const res = await (window as any).zylch?.narration?.summarize(
          snapshot,
          context
        )
        if (!cancelled && res && typeof res.text === 'string') {
          const t = res.text.trim()
          if (t) setNarration(t)
        }
      } catch (e) {
        // Never surface — narration is best-effort.
        // eslint-disable-next-line no-console
        console.warn('[useNarration] summarize failed', e)
      } finally {
        inFlightRef.current = false
      }
    }

    // Fire once immediately-ish, then poll.
    const firstTimer = setTimeout(tick, 500)
    const iv = setInterval(tick, POLL_MS)
    return () => {
      cancelled = true
      clearTimeout(firstTimer)
      clearInterval(iv)
    }
  }, [busy, context])

  return narration
}
