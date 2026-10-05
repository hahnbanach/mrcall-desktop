/** Local consistency checks; Firebase verification remains authoritative. */
export interface CachedToken {
  uid: string; email: string | null; idToken: string; expiresAtMs: number; refreshToken?: string
}
export class WindowAuthSessions {
  private tokens = new Map<number, CachedToken>()
  private pending = new Map<number, { controller: AbortController; profile: string; promise: Promise<CachedToken | null> }>()
  constructor(private now = Date.now, private timeoutMs = 5000) {}
  accept(id: number, value: CachedToken, profile?: string): CachedToken | null {
    try {
      if (!value || typeof value.uid !== 'string' || !value.uid || typeof value.idToken !== 'string' ||
          (profile && profile !== value.uid)) return null
      const parts = value.idToken.split('.')
      if (parts.length !== 3) return null
      const claims = JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf8'))
      if (claims.sub !== value.uid || !Number.isFinite(claims.exp) || !Number.isFinite(value.expiresAtMs)) return null
      const expiresAtMs = Math.min(value.expiresAtMs, claims.exp * 1000)
      if (expiresAtMs <= this.now()) return null
      const token: CachedToken = { uid: value.uid, email: typeof value.email === 'string' ? value.email : null,
        idToken: value.idToken, expiresAtMs,
        ...(typeof value.refreshToken === 'string' && value.refreshToken ? { refreshToken: value.refreshToken } : {}) }
      this.tokens.set(id, token)
      return token
    } catch { return null }
  }
  get(id: number): CachedToken | undefined {
    const token = this.tokens.get(id)
    return token && token.expiresAtMs > this.now() + 30_000 ? token : undefined
  }
  delete(id: number): void {
    this.tokens.delete(id)
    const pending = this.pending.get(id)
    this.pending.delete(id)
    pending?.controller.abort()
  }
  clear(): void {
    for (const id of new Set([...this.tokens.keys(), ...this.pending.keys()])) this.delete(id)
  }
  async fresh(id: number, profile: string, request: (signal: AbortSignal) => Promise<boolean>): Promise<CachedToken | null> {
    const cached = this.get(id)
    if (cached?.uid === profile) return cached
    const existing = this.pending.get(id)
    if (existing) return existing.profile === profile ? existing.promise : null
    const controller = new AbortController()
    const pending = { controller, profile, promise: Promise.resolve(null as CachedToken | null) }
    this.pending.set(id, pending)
    pending.promise = (async () => {
      const timer = setTimeout(() => controller.abort(), this.timeoutMs)
      try {
        const cancelled = new Promise<boolean>((resolve) => {
          controller.signal.addEventListener('abort', () => resolve(false), { once: true })
        })
        const ok = await Promise.race([request(controller.signal), cancelled])
        if (!ok || controller.signal.aborted || this.pending.get(id) !== pending) return null
        const token = this.get(id)
        return token?.uid === profile ? token : null
      } catch { return null }
      finally {
        clearTimeout(timer)
        controller.abort()
        if (this.pending.get(id) === pending) this.pending.delete(id)
      }
    })()
    return pending.promise
  }
}
export class TokenRefreshRequests {
  private sequence = 0
  private pending = new Map<number, { windowId: number; finish: (ok: boolean) => void }>()
  request(windowId: number, uid: string, signal: AbortSignal,
    send: (payload: { requestId: number; uid: string }) => void): Promise<boolean> {
    if (signal.aborted) return Promise.resolve(false)
    const requestId = ++this.sequence
    return new Promise((resolve) => {
      const abort = (): void => finish(false)
      const finish = (ok: boolean): void => {
        this.pending.delete(requestId)
        signal.removeEventListener('abort', abort)
        resolve(ok)
      }
      this.pending.set(requestId, { windowId, finish })
      signal.addEventListener('abort', abort, { once: true })
      try { send({ requestId, uid }) } catch { finish(false) }
    })
  }
  respond(windowId: number, payload: { requestId?: unknown; ok?: unknown }): void {
    if (!payload || typeof payload.requestId !== 'number') return
    const pending = this.pending.get(payload.requestId)
    if (pending?.windowId === windowId) pending.finish(payload.ok === true)
  }
}
export async function retireAuthTransport(transport: {
  isAlive(): boolean; call(method: string, params: unknown, timeout: number): Promise<unknown>;
  markIntentionalRestart(): void; stop(): void
} | undefined, timeoutMs = 1000): Promise<void> {
  if (!transport) return
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    if (transport.isAlive()) await Promise.race([transport.call('account.sign_out', {}, timeoutMs),
      new Promise<void>((resolve) => { timer = setTimeout(resolve, timeoutMs) })])
  } catch { /* Offline logout still clears authentication. */ }
  finally {
    if (timer) clearTimeout(timer)
    transport.markIntentionalRestart()
    transport.stop()
  }
}
