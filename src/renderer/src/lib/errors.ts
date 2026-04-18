/**
 * Centralised error inspection / display helpers.
 *
 * Background: when the sidecar exits because the profile is already in
 * use by another window, the main process decorates the rejected
 * promise with the classified message ("Profile X is already in use by
 * another Zylch window or CLI session.") and pushes a structured
 * `sidecar:status` event to the renderer. App.tsx renders that event
 * as a banner at the top of the window. So when individual catch
 * blocks ALSO render an `alert(...)` or toast for the same error, the
 * user sees two messages — one polished banner and one ugly raw
 * "Error invoking remote method 'rpc:call': ..." dialog.
 *
 * `isProfileLockedError` recognises the lock signature so call sites
 * can suppress the duplicate. `showError` is a one-liner wrapper:
 * suppress on lock, alert otherwise.
 */
export function isProfileLockedError(e: unknown): boolean {
  if (!e) return false
  // Structured error decorated by main/index.ts (`(err as any).code`).
  const code = (e as { code?: unknown }).code
  if (typeof code === 'string' && code === 'profile_locked') return true
  // Fall back to message matching — covers the case where the error
  // crosses the contextBridge as a plain Error and the `.code`
  // property gets stripped.
  const msg = (() => {
    if (e instanceof Error) return e.message || ''
    if (typeof e === 'string') return e
    if (typeof e === 'object' && e && 'message' in e) {
      return String((e as { message?: unknown }).message ?? '')
    }
    return String(e)
  })()
  if (!msg) return false
  return (
    msg.includes('profile_locked') ||
    msg.includes('is already in use by another Zylch') ||
    msg.includes('is already in use by another session')
  )
}

/**
 * Display an error to the user, unless it is the "profile locked"
 * variant — in which case the SidecarStatusBanner already covers it
 * and a second alert would be redundant noise.
 *
 * `prefix` lets callers keep their existing labelling
 * ("Skip failed:", "Update failed:" etc.).
 */
export function showError(e: unknown, prefix?: string): void {
  if (isProfileLockedError(e)) {
    // Banner already explains it; stay silent.
    console.warn('[error] suppressed profile_locked alert', e)
    return
  }
  const msg = errorMessage(e)
  // eslint-disable-next-line no-alert
  alert(prefix ? `${prefix} ${msg}` : msg)
}

/** Pull a printable message off an unknown rejection / throw. */
export function errorMessage(e: unknown): string {
  if (!e) return ''
  if (e instanceof Error) return e.message || String(e)
  if (typeof e === 'string') return e
  if (typeof e === 'object' && 'message' in e) {
    return String((e as { message?: unknown }).message ?? '')
  }
  return String(e)
}
