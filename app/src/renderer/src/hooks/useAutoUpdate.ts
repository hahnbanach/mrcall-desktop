import { useEffect, useRef } from 'react'
import { useTasks } from '../store/tasks'
import type { SidecarStatusEvent } from '../types'

const DEFAULT_INTERVAL_MIN = 30
const MIN_INTERVAL_MIN = 5
const MAX_INTERVAL_MIN = 360

function parseIntervalMinutes(raw: string | undefined | null): number {
  if (!raw) return DEFAULT_INTERVAL_MIN
  const n = parseInt(raw, 10)
  if (!Number.isFinite(n) || Number.isNaN(n)) return DEFAULT_INTERVAL_MIN
  return Math.max(MIN_INTERVAL_MIN, Math.min(MAX_INTERVAL_MIN, n))
}

function isEnabled(raw: string | undefined | null): boolean {
  // Default ON. Anything that isn't a clear "n" / "no" / "false" / "0"
  // is treated as enabled — keeps the toggle robust to capitalisation
  // and old `y`/`n` style choices.
  if (raw == null) return true
  const v = String(raw).trim().toLowerCase()
  if (!v) return true
  return !(v === 'n' || v === 'no' || v === 'false' || v === '0' || v === 'off')
}

/**
 * Re-runs the engine's `update.run` (IMAP + WhatsApp + memory + task
 * detection) on an interval while the desktop window is open and bound
 * to a profile.
 *
 * Driven by two settings in the active profile's `.env`:
 *   - AUTO_UPDATE_ENABLED          (y / n, default y)
 *   - AUTO_UPDATE_INTERVAL_MINUTES (5–360, default 30)
 *
 * Behaviour:
 *   - Reads settings at mount (interval scheduling) and at every tick
 *     (enable flag), so flipping the toggle off via Settings stops the
 *     loop on the next tick without needing a restart. Changing the
 *     INTERVAL requires a window restart — documented in the schema
 *     help text.
 *   - Skips a tick if the previous run is still in flight, or if the
 *     sidecar is dead because another window holds the profile lock.
 *   - Manual Update via the Update view is unaffected — it shares the
 *     same RPC and the engine serialises on the active profile.
 *
 * Mounted inside `AppInner`, which only renders after `auth:bindProfile`
 * has attached a sidecar. We never tick against an empty profile.
 */
export function useAutoUpdate(): void {
  const { refresh: refreshTasks } = useTasks()
  const inFlight = useRef(false)
  const sidecarLocked = useRef(false)

  // Track sidecar lock state so we don't fire an Update against a child
  // that the OS-level flock won't let us touch anyway.
  useEffect(() => {
    const off = window.zylch.onSidecarStatus((s: SidecarStatusEvent) => {
      sidecarLocked.current = !s.alive && s.code === 'profile_locked'
    })
    return off
  }, [])

  useEffect(() => {
    let cancelled = false
    let timerId: ReturnType<typeof setInterval> | null = null

    const tick = async (): Promise<void> => {
      if (cancelled) return
      if (sidecarLocked.current) {
        console.log('[useAutoUpdate] skip tick — sidecar locked')
        return
      }
      if (inFlight.current) {
        console.log('[useAutoUpdate] skip tick — previous run still in flight')
        return
      }
      // Re-read enable flag every tick so a Settings toggle takes effect
      // without a window restart. We do NOT re-read the interval here:
      // changing setInterval mid-flight risks double-scheduling, and
      // the help text already says interval changes need a restart.
      try {
        const cfg = await window.zylch.settings.get()
        if (cancelled) return
        if (!isEnabled(cfg.values?.AUTO_UPDATE_ENABLED)) {
          console.log('[useAutoUpdate] skip tick — disabled via settings')
          return
        }
      } catch (e) {
        // If we can't read settings, default to OFF for this tick
        // rather than running blind.
        console.warn('[useAutoUpdate] skip tick — settings.get failed', e)
        return
      }
      inFlight.current = true
      try {
        console.log('[useAutoUpdate] tick — running update.run')
        await window.zylch.update.run()
        if (!cancelled) {
          void refreshTasks()
        }
      } catch (e) {
        // Swallow errors: this is a background loop, surfacing them as
        // toast/banners would spam the user. The manual Update button
        // is the path to see the failure explicitly.
        console.warn('[useAutoUpdate] update.run failed', e)
      } finally {
        inFlight.current = false
      }
    }

    void (async (): Promise<void> => {
      try {
        const cfg = await window.zylch.settings.get()
        if (cancelled) return
        if (!isEnabled(cfg.values?.AUTO_UPDATE_ENABLED)) {
          console.log('[useAutoUpdate] disabled at boot — not scheduling')
          return
        }
        const intervalMin = parseIntervalMinutes(cfg.values?.AUTO_UPDATE_INTERVAL_MINUTES)
        const intervalMs = intervalMin * 60 * 1000
        console.log(`[useAutoUpdate] scheduled every ${intervalMin} min`)
        timerId = setInterval(() => void tick(), intervalMs)
      } catch (e) {
        console.warn('[useAutoUpdate] could not load settings — auto-update off', e)
      }
    })()

    return () => {
      cancelled = true
      if (timerId !== null) clearInterval(timerId)
    }
  }, [refreshTasks])
}
