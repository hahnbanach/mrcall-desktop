import { useEffect, useRef, useState } from 'react'

/**
 * useNarration — live first-person Italian narration of what the sidecar
 * is doing, synthesized from its stderr by a tiny Haiku call.
 *
 * Rules:
 *  - Subscribes to window.zylch.onStderr once on mount.
 *  - Keeps a rolling buffer (last BUFFER_CAP lines).
 *  - When `seed` changes, the seed string is shown immediately.
 *  - While `busy` is true, every POLL_MS ms, if there's at least one new
 *    non-DEBUG non-empty line since the last call, it invokes
 *    narration.summarize with the full current buffer + `context`.
 *    A non-empty response overwrites the current narration.
 *  - Transitions busy true -> false clear the narration.
 */

const BUFFER_CAP = 50
const POLL_MS = 4000

export function useNarration(busy: boolean, context: string, seed: string): string {
  const [narration, setNarration] = useState<string>('')
  const bufferRef = useRef<string[]>([])
  const lastSeenCountRef = useRef<number>(0)
  const totalLinesRef = useRef<number>(0)
  const inFlightRef = useRef<boolean>(false)

  useEffect(() => {
    const onStderr = (window as any).zylch?.onStderr
    if (typeof onStderr !== 'function') return
    const off = onStderr((chunk: string) => {
      const parts = String(chunk).split(/\r?\n/)
      for (const raw of parts) {
        const s = raw.trim()
        if (!s) continue
        bufferRef.current.push(s)
        totalLinesRef.current += 1
      }
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

  useEffect(() => {
    if (!busy) {
      setNarration('')
      lastSeenCountRef.current = totalLinesRef.current
      return
    }
    if (seed) setNarration(seed)
  }, [busy, seed])

  useEffect(() => {
    if (!busy) return

    let cancelled = false
    const tick = async (): Promise<void> => {
      if (cancelled || inFlightRef.current) return
      const lines = bufferRef.current
      const newCount = totalLinesRef.current
      if (newCount <= lastSeenCountRef.current) return
      const hasSignal = lines.some((l) => l && !/ DEBUG /.test(l))
      if (!hasSignal) {
        lastSeenCountRef.current = newCount
        return
      }
      inFlightRef.current = true
      const snapshot = [...lines]
      lastSeenCountRef.current = newCount
      try {
        const res = await (window as any).zylch?.narration?.summarize(snapshot, context)
        if (!cancelled && res && typeof res.text === 'string') {
          const t = res.text.trim()
          if (t) setNarration(t)
        }
      } catch (e) {
        // eslint-disable-next-line no-console
        console.warn('[useNarration] summarize failed', e)
      } finally {
        inFlightRef.current = false
      }
    }

    const iv = setInterval(tick, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(iv)
    }
  }, [busy, context])

  return narration
}
