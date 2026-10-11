/** Bounded, role-scoped business discovery. No billing selection is made here. */
export interface Business {
  businessId: string
  companyName?: string
  nickname?: string
  name?: string
  surname?: string
  emailAddress?: string
  businessPhoneNumber?: string
  totalHits?: number
}
interface BusinessApi {
  listMyBusinesses(params: { limit: number }): Promise<{ businesses: unknown[] }>
  searchBusinesses(params: Record<string, string | number>): Promise<{ businesses: unknown[] }>
}
export interface BusinessResults { businesses: Business[]; partial: boolean; truncated: boolean }
export class BusinessSearchError extends Error {
  constructor(readonly code: 'authentication' | 'timeout' | 'failed' | 'malformed' | 'cancelled') {
    super(code)
  }
}
const LIMIT = 25
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
export function businessQueries(query: string): Record<string, string>[] {
  const q = query.trim()
  if (!q) return []
  if (UUID.test(q)) return [{ businessId: q }]
  const like = '%' + q.replace(/^%+|%+$/g, '') + '%'
  if (q.includes('@')) return [{ emailAddress: like }]
  return ['companyName', 'nickname', 'name', 'surname'].map(key => ({ [key]: like }))
}
export function checkedBusinesses(value: unknown): Business[] {
  if (!Array.isArray(value)) throw new BusinessSearchError('malformed')
  return value.map(item => {
    if (!item || typeof item.businessId !== 'string' || !item.businessId.trim()) {
      throw new BusinessSearchError('malformed')
    }
    const business: Business = { businessId: item.businessId }
    for (const key of ['companyName', 'nickname', 'name', 'surname', 'emailAddress', 'businessPhoneNumber'] as const) {
      if (typeof item[key] === 'string') business[key] = item[key]
    }
    if (Number.isFinite(item.totalHits) && item.totalHits >= 0) business.totalHits = item.totalHits
    return business
  })
}
export function businessSearchError(error: unknown): BusinessSearchError {
  if (error instanceof BusinessSearchError) return error
  const e = error as { code?: number; message?: string } | null
  const message = typeof e?.message === 'string' ? e.message : ''
  if (e?.code === -32010 || /not signed in|auth.*expired|unauthorized/i.test(message)) return new BusinessSearchError('authentication')
  if (/timed? out|timeout/i.test(message)) return new BusinessSearchError('timeout')
  return new BusinessSearchError('failed')
}
export function businessSearchMessage(error: unknown): string {
  switch (businessSearchError(error).code) {
    case 'authentication': return 'Sign in to MrCall again to search for a business.'
    case 'timeout': return 'Business search timed out. Check the connection and retry.'
    case 'malformed': return 'Business search returned an invalid response. Retry the search.'
    default: return 'Business search failed. Check the connection and retry.'
  }
}
/** Selected IDs are opaque; only discovery text uses format-based routing. */
type BusinessLookupQuery = string | { businessId: string }
export function createBusinessLookup(api: BusinessApi) {
  // Raw RPCs already have a 30-second deadline. A timed-out UI must not start
  // another batch while they are still running; obsolete queued work is skipped.
  let tail: Promise<unknown> = Promise.resolve()
  return (query: BusinessLookupQuery, signal: AbortSignal): Promise<BusinessResults> => {
    const task = tail.catch(() => {}).then(async () => {
      if (signal.aborted) throw new BusinessSearchError('cancelled')
      const filters = typeof query === 'string' ? businessQueries(query) : [{ businessId: query.businessId }]
      const calls = filters.length
        ? filters.map(filter => () => api.searchBusinesses({ ...filter, limit: LIMIT }))
        : [() => api.listMyBusinesses({ limit: LIMIT })]
      const responses = await Promise.allSettled(calls.map(async call => checkedBusinesses((await call()).businesses)))
      if (signal.aborted) throw new BusinessSearchError('cancelled')
      const found = new Map<string, Business>()
      const errors: BusinessSearchError[] = []
      let truncated = false
      for (const response of responses) {
        if (response.status === 'rejected') { errors.push(businessSearchError(response.reason)); continue }
        const rows = response.value
        truncated ||= rows.length >= LIMIT || rows.some(row => (row.totalHits ?? 0) > rows.length)
        rows.forEach(row => { if (!found.has(row.businessId)) found.set(row.businessId, row) })
      }
      const authError = errors.find(error => error.code === 'authentication')
      if (authError) throw authError
      if (errors.length && !found.size) throw errors[0]
      return { businesses: [...found.values()], partial: errors.length > 0, truncated }
    })
    tail = task.catch(() => {})
    return task
  }
}
export function boundedBusinessLookup(
  lookup: ReturnType<typeof createBusinessLookup>, query: BusinessLookupQuery, controller: AbortController, timeoutMs: number
): Promise<BusinessResults> {
  return new Promise((resolve, reject) => {
    const cleanup = (): void => { clearTimeout(timer); controller.signal.removeEventListener('abort', abort) }
    const abort = (): void => { cleanup(); reject(new BusinessSearchError('cancelled')) }
    const timer = setTimeout(() => {
      cleanup()
      reject(new BusinessSearchError('timeout'))
      controller.abort()
    }, timeoutMs)
    controller.signal.addEventListener('abort', abort, { once: true })
    if (controller.signal.aborted) { abort(); return }
    lookup(query, controller.signal).then(result => { cleanup(); resolve(result) }, error => { cleanup(); reject(error) })
  })
}
