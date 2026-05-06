/**
 * Human-friendly relative time strings for the desktop UI.
 *
 * Returns short forms keyed off "now":
 *   - <60s          → "just now"
 *   - <60m          → "Nm ago"
 *   - <24h          → "Nh ago"
 *   - <7d           → "Nd ago"
 *   - <365d         → "MMM d"  (e.g. "Mar 14")
 *   - else          → "MMM d, YYYY"
 *
 * Future timestamps render mirrored ("in 5m", "in 3d") — calendar-event
 * sources can sit in the future legitimately.
 *
 * `null` / undefined / unparseable input → empty string. The renderer
 * is expected to hide the row when the result is empty.
 */
export function formatRelative(input: string | null | undefined, now: Date = new Date()): string {
  if (!input) return ''
  const parsed = new Date(input)
  if (Number.isNaN(parsed.getTime())) return ''
  const deltaMs = parsed.getTime() - now.getTime()
  const future = deltaMs > 0
  const abs = Math.abs(deltaMs)

  const m = 60 * 1000
  const h = 60 * m
  const d = 24 * h
  const w = 7 * d
  const y = 365 * d

  const fmt = (n: number, unit: string): string =>
    future ? `in ${n}${unit}` : `${n}${unit} ago`

  if (abs < 45 * 1000) return future ? 'soon' : 'just now'
  if (abs < h) return fmt(Math.round(abs / m), 'm')
  if (abs < d) return fmt(Math.round(abs / h), 'h')
  if (abs < w) return fmt(Math.round(abs / d), 'd')
  if (abs < y) {
    return parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  }
  return parsed.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })
}

/**
 * Absolute, locale-formatted timestamp suitable for a `title=` tooltip.
 * Returns empty string for unparseable input so callers can `title || undefined`.
 */
export function formatAbsolute(input: string | null | undefined): string {
  if (!input) return ''
  const parsed = new Date(input)
  if (Number.isNaN(parsed.getTime())) return ''
  return parsed.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}
