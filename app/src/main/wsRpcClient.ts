import { EventEmitter } from 'events'
import WebSocket from 'ws'
import type { RpcClient } from './rpcClient'

type Pending = {
  resolve: (v: unknown) => void
  reject: (e: Error) => void
  timer: NodeJS.Timeout
  method: string
}

// Custom WS close code the engine uses when the Firebase session expired
// mid-connection (see engine/zylch/rpc/server_ws.py WS_CLOSE_AUTH_EXPIRED).
// On this code we MUST obtain a fresh token before reconnecting — a plain
// reconnect with the stale token would just be rejected again.
const WS_CLOSE_AUTH_EXPIRED = 4401

// Reconnect backoff: start small, cap so a long outage doesn't busy-loop
// nor wait minutes to recover once the network returns.
const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 15000

// Proactive server-session refresh. The engine enforces the Firebase
// token's own `exp` and closes 4401 when it lapses; refreshing well
// inside the ~1h token lifetime keeps the socket alive without a
// reconnect. 30 min matches the plan's recommended cadence.
const AUTH_REFRESH_INTERVAL_MS = 30 * 60 * 1000

type GetToken = () => Promise<string | null>
// Optional getter for the long-lived Firebase refresh token. Returns null
// when none has been pushed yet (older app builds, or before first signin).
type GetRefreshToken = () => Promise<string | null>

/**
 * WebSocketRpcClient — the cross-machine transport. Speaks the SAME
 * JSON-RPC 2.0 dialogue as `StdioRpcClient`, but over a WebSocket to an
 * engine running `zylch -p <uid> serve --ws HOST:PORT` on another machine
 * (or locally for the Phase-2 smoke test).
 *
 * Auth: the WebSocket upgrade carries `Authorization: Bearer <jwt>`. The
 * engine verifies it (RS256) and gates `token.sub == profile OWNER_ID`,
 * rejecting the upgrade with HTTP 401 (no/invalid token) or 403 (valid
 * token, wrong owner). The verified handshake token becomes the engine's
 * in-memory session — so `account.set_firebase_token` is NOT needed over
 * WS (unlike stdio).
 *
 * Liveness model: the WS engine never emits `engine.ready` (that is
 * stdio-only). "Ready" == the socket reached OPEN. We synthesise the
 * renderer's expected ready signal as a `'status' {alive:true,
 * ready:true}` event the instant the socket opens, and a `'status'
 * {alive:false}` on every drop. Reconnects re-emit ready so the boot
 * splash / banner recover automatically; because notification
 * subscriptions live in the renderer (via `onNotification`), they survive
 * reconnects transparently as long as the main→renderer forward keeps
 * running.
 */
export class WebSocketRpcClient extends EventEmitter implements RpcClient {
  private ws: WebSocket | null = null
  private pending = new Map<number, Pending>()
  // RPCs issued before the socket is OPEN are queued here and flushed on
  // 'open' — mirroring stdio, where an early request waits in the pipe
  // until the engine answers rather than failing fast. The per-call
  // timeout (in call()) still bounds each queued request.
  private sendQueue: { id: number; payload: string }[] = []
  private nextId = 1
  private connected = false
  // Set by stop() — a deliberate, permanent teardown. Suppresses all
  // further reconnect attempts and flips the loop into the `'exit'`
  // terminal state.
  private stopped = false
  private intentionalRestart = false
  private reconnectAttempts = 0
  private reconnectTimer: NodeJS.Timeout | null = null
  private authRefreshTimer: NodeJS.Timeout | null = null
  private connectStartedAtMs = 0
  // Last structured failure, surfaced by classifyError() and as the
  // message on the `'status' {alive:false}` events the renderer renders.
  private lastFailure: { code: string; message: string; hint?: string } = {
    code: 'ws_connecting',
    message: 'Connecting to remote engine…'
  }

  constructor(
    private url: string,
    private getToken: GetToken,
    private profile: string,
    // Optional: lets the proactive `auth.refresh` include the Firebase
    // refresh token so the engine can refresh the ID token server-side for
    // headless operation. Omitted by callers that don't have one (e.g. the
    // Settings "Test connection" probe may pass a snapshot without it).
    private getRefreshToken?: GetRefreshToken
  ) {
    super()
  }

  // The configured remote URL is a BASE (e.g. wss://desktop.mrcall.ai, or
  // ws://127.0.0.1:5174 over an SSH tunnel). We always append `/ws/<uid>`
  // so a Caddy reverse-proxy can route each profile to its own engine
  // socket — the app stores ONE base URL but each window reaches its own
  // backend. A direct engine ignores the path, so this is backward-
  // compatible with a plain base URL (tunnel / local).
  private connectUrl(): string {
    return `${this.url.replace(/\/+$/, '')}/ws/${encodeURIComponent(this.profile)}`
  }

  isAlive(): boolean {
    return this.connected && this.ws !== null && this.ws.readyState === WebSocket.OPEN
  }

  markIntentionalRestart(): void {
    this.intentionalRestart = true
  }

  isIntentionalRestart(): boolean {
    return this.intentionalRestart
  }

  // WS has no child stderr stream; the Logs view's file tailer
  // (<profileDir>/zylch.log on the SERVER) is not reachable from the
  // client either. Return empty so callers that join this for an error
  // message degrade gracefully.
  lastStderrLines(): string[] {
    return []
  }

  classifyError(): { code: string; message: string; hint?: string } {
    if (this.intentionalRestart) {
      return { code: 'restarting', message: 'Reconnecting to remote engine…' }
    }
    return this.lastFailure
  }

  start(): void {
    this.stopped = false
    void this.connect()
  }

  private emitStatusUp(bootMs: number): void {
    this.emit('status', {
      alive: true,
      profile: this.profile,
      ready: true,
      bootMs,
      remoteUrl: this.url
    })
  }

  private emitStatusDown(code: string, message: string, hint?: string): void {
    this.lastFailure = { code, message, hint }
    this.emit('status', {
      alive: false,
      profile: this.profile,
      exitCode: null,
      code,
      message,
      ...(hint ? { hint } : {})
    })
  }

  private async connect(): Promise<void> {
    if (this.stopped) return
    if (this.ws) {
      // Defensive: never leak a half-open socket across a reconnect.
      // `terminate()` on a still-CONNECTING socket makes `ws` emit an
      // ASYNC 'error' ("WebSocket was closed before the connection was
      // established"). After removeAllListeners() there is no 'error'
      // listener, so Node would rethrow it as an UNCAUGHT exception (the
      // crash popup). Attach a no-op error sink before terminating so the
      // late error is absorbed.
      const old = this.ws
      this.ws = null
      try {
        old.removeAllListeners()
        old.on('error', () => {})
        old.terminate()
      } catch {}
    }

    let token: string | null
    try {
      token = await this.getToken()
    } catch (e) {
      token = null
      console.warn('[ws] getToken threw', e)
    }
    if (this.stopped) return

    if (!token) {
      // No Firebase token yet (signin not complete, or the renderer
      // hasn't pushed one). Surface a clear "not signed in" status
      // instead of opening a doomed socket, then retry with backoff so
      // we connect automatically once a token appears.
      this.connected = false
      this.emitStatusDown(
        'not_signed_in',
        'Not signed in — sign in to reach the remote engine.'
      )
      this.scheduleReconnect()
      return
    }

    this.connectStartedAtMs = Date.now()
    const target = this.connectUrl()
    console.log(`[ws] connecting url=${target} profile=${this.profile}`)
    let ws: WebSocket
    try {
      ws = new WebSocket(target, {
        headers: { Authorization: `Bearer ${token}` },
        // Frame ceiling mirrors the engine's 16 MiB max_size (chat.send
        // with embedded email bodies can be large).
        maxPayload: 16 * 1024 * 1024
      })
    } catch (e) {
      // Synchronous construction failure (e.g. malformed URL).
      const msg = e instanceof Error ? e.message : String(e)
      this.connected = false
      this.emitStatusDown('ws_bad_url', `Invalid remote engine URL: ${msg}`)
      this.scheduleReconnect()
      return
    }
    this.ws = ws

    ws.on('open', () => {
      if (this.stopped) {
        try {
          ws.close()
        } catch {}
        return
      }
      this.connected = true
      this.reconnectAttempts = 0
      this.intentionalRestart = false
      const bootMs = Date.now() - this.connectStartedAtMs
      console.log(`[ws] open url=${this.url} (connect ${bootMs} ms)`)
      this.emitStatusUp(bootMs)
      this.startAuthRefresh()
      // Flush any RPCs that arrived before we finished connecting.
      this.flushQueue()
    })

    ws.on('message', (data: WebSocket.RawData, isBinary: boolean) => {
      // The engine sends exactly one JSON object per TEXT frame. Binary
      // frames aren't part of the Phase-2 contract; decode defensively.
      const text = isBinary ? data.toString() : data.toString('utf8')
      this.onMessage(text)
    })

    ws.on('close', (code: number, reasonBuf: Buffer) => {
      const reason = reasonBuf?.toString('utf8') || ''
      console.warn(`[ws] close code=${code} reason=${reason} url=${this.url}`)
      this.connected = false
      this.stopAuthRefresh()
      // Reject everything in flight so callers fail fast and the renderer
      // can retry once the socket comes back.
      this.failAllPending(`websocket closed (code=${code})`)

      if (this.stopped) {
        // Deliberate teardown — terminal. Mirror the stdio `'exit'`
        // contract so index.ts can log it; no reconnect.
        this.emit('exit', {
          code,
          signal: null,
          classified: { code: 'ws_closed', message: `WebSocket closed (code=${code})` }
        })
        return
      }

      if (code === WS_CLOSE_AUTH_EXPIRED) {
        // Token expired server-side. getToken() (wired to the renderer's
        // Firebase refresh) yields a fresh JWT on the next connect().
        this.emitStatusDown(
          'auth_expired',
          'Session expired — refreshing and reconnecting…'
        )
        // Reconnect promptly (don't punish the user with full backoff for
        // an expected expiry), but still go through connect() so a fresh
        // token is fetched.
        this.reconnectAttempts = 0
        this.scheduleReconnect()
        return
      }

      // Any other drop: surface a disconnected status and reconnect with
      // capped backoff.
      this.emitStatusDown(
        'ws_disconnected',
        reason
          ? `Disconnected from remote engine (code=${code}): ${reason}`
          : `Disconnected from remote engine (code=${code}).`,
        'Reconnecting automatically…'
      )
      this.scheduleReconnect()
    })

    ws.on('unexpected-response', (_req, res) => {
      // The HTTP upgrade was rejected before the socket opened — this is
      // how the engine signals auth failures: 401 (no/invalid token) or
      // 403 (valid token, wrong owner). `ws` also emits 'error' after
      // this, but the status code only lives here, so classify now.
      const statusCode = res.statusCode
      let code = 'ws_upgrade_rejected'
      let message = `Remote engine rejected the connection (HTTP ${statusCode}).`
      let hint: string | undefined
      if (statusCode === 401) {
        code = 'ws_unauthorized'
        message = 'Remote engine rejected the token (401 Unauthorized).'
        hint = 'Sign in again or check the backend URL.'
      } else if (statusCode === 403) {
        code = 'ws_forbidden'
        message =
          'Signed-in account does not own the remote profile (403 Forbidden).'
        hint = 'The remote engine is bound to a different MrCall account.'
      }
      this.connected = false
      this.emitStatusDown(code, message, hint)
      // 'close' won't fire for a rejected upgrade; drive reconnect here —
      // EXCEPT 403 (signed-in account doesn't own this profile / backend
      // bound to another account): retrying can't fix that without the
      // user switching account or backend URL, so we stop the loop and
      // leave the banner up. 401 may self-heal next connect (fresh JWT).
      if (statusCode !== 403) {
        this.scheduleReconnect()
      }
      try {
        res.destroy()
      } catch {}
    })

    ws.on('error', (err: Error) => {
      // Connection refused / DNS / TLS errors land here. If we already
      // classified via 'unexpected-response', keep that richer message.
      console.warn(`[ws] error url=${this.url}: ${err.message}`)
      if (!this.connected && this.lastFailure.code !== 'ws_unauthorized' && this.lastFailure.code !== 'ws_forbidden') {
        this.emitStatusDown('ws_error', `Cannot reach remote engine: ${err.message}`)
      }
      // 'close' fires after 'error' for an open socket; for a failed
      // connect it may not, so the unexpected-response / connect paths
      // own reconnect scheduling. Avoid double-scheduling here.
    })
  }

  private onMessage(text: string): void {
    let msg: any
    try {
      msg = JSON.parse(text)
    } catch {
      console.error('[ws] non-JSON frame:', text.slice(0, 200))
      return
    }
    if (typeof msg.id === 'number' && (msg.result !== undefined || msg.error !== undefined)) {
      const p = this.pending.get(msg.id)
      if (!p) {
        console.warn(`[ws] response for unknown id=${msg.id}`)
        return
      }
      this.pending.delete(msg.id)
      clearTimeout(p.timer)
      if (msg.error) {
        p.reject(new Error(msg.error.message || 'rpc error'))
      } else {
        p.resolve(msg.result)
      }
      return
    }
    if (msg.method) {
      // id-less message → server notification. Same shape + event name as
      // the stdio client, so the renderer's onNotification handlers are
      // transport-agnostic. The WS engine never emits `engine.ready`, so
      // we don't special-case it here.
      this.emit('notification', { method: msg.method, params: msg.params })
    }
  }

  private failAllPending(reason: string): void {
    this.sendQueue = []
    for (const [, p] of this.pending) {
      clearTimeout(p.timer)
      p.reject(new Error(reason))
    }
    this.pending.clear()
  }

  private scheduleReconnect(): void {
    if (this.stopped) return
    if (this.reconnectTimer) return
    const delay = Math.min(
      RECONNECT_MAX_MS,
      RECONNECT_BASE_MS * Math.pow(2, this.reconnectAttempts)
    )
    this.reconnectAttempts++
    console.log(`[ws] reconnect in ${delay} ms (attempt ${this.reconnectAttempts})`)
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      void this.connect()
    }, delay)
  }

  private startAuthRefresh(): void {
    this.stopAuthRefresh()
    this.authRefreshTimer = setInterval(async () => {
      if (!this.isAlive()) return
      let token: string | null = null
      try {
        token = await this.getToken()
      } catch (e) {
        console.warn('[ws] auth refresh getToken threw', e)
      }
      if (!token) {
        console.warn('[ws] auth refresh skipped — no token')
        return
      }
      let refreshToken: string | null = null
      if (this.getRefreshToken) {
        try {
          refreshToken = await this.getRefreshToken()
        } catch (e) {
          console.warn('[ws] auth refresh getRefreshToken threw', e)
        }
      }
      try {
        await this.call(
          'auth.refresh',
          // Include the refresh token only when present, so the engine can
          // store it and refresh the ID token server-side for headless
          // operation. Older engines ignore the extra field.
          refreshToken
            ? { id_token: token, refresh_token: refreshToken }
            : { id_token: token },
          15000
        )
        console.log('[ws] auth.refresh ok')
      } catch (e) {
        // Non-fatal: if the token already lapsed the engine closes 4401
        // and the reconnect path fetches a fresh one.
        console.warn('[ws] auth.refresh failed', e)
      }
    }, AUTH_REFRESH_INTERVAL_MS)
  }

  private stopAuthRefresh(): void {
    if (this.authRefreshTimer) {
      clearInterval(this.authRefreshTimer)
      this.authRefreshTimer = null
    }
  }

  call<T = unknown>(method: string, params: unknown = {}, timeoutMs = 60000): Promise<T> {
    const id = this.nextId++
    const payload = JSON.stringify({ jsonrpc: '2.0', id, method, params })
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        this.sendQueue = this.sendQueue.filter((q) => q.id !== id)
        reject(new Error(`rpc timeout: ${method}`))
      }, timeoutMs)
      this.pending.set(id, {
        resolve: resolve as (v: unknown) => void,
        reject,
        timer,
        method
      })
      if (this.isAlive() && this.ws) {
        this.sendNow(id, payload)
      } else {
        // Not connected yet (initial connect / reconnect in flight). Queue
        // instead of failing fast, so a view that mounts before the WS
        // finishes its token handshake doesn't get a spurious "not
        // connected" — the request waits exactly as it would in the stdio
        // pipe. The timeout above still bounds it; flushed on 'open'.
        this.sendQueue.push({ id, payload })
      }
    })
  }

  private sendNow(id: number, payload: string): void {
    try {
      this.ws!.send(payload, (err) => {
        if (!err) return
        const p = this.pending.get(id)
        if (p) {
          clearTimeout(p.timer)
          this.pending.delete(id)
          p.reject(err)
        }
      })
    } catch (e) {
      const p = this.pending.get(id)
      if (p) {
        clearTimeout(p.timer)
        this.pending.delete(id)
        p.reject(e instanceof Error ? e : new Error(String(e)))
      }
    }
  }

  private flushQueue(): void {
    const queued = this.sendQueue
    this.sendQueue = []
    for (const { id, payload } of queued) {
      if (this.pending.has(id)) this.sendNow(id, payload)
    }
  }

  stop(): void {
    console.log(`[ws] stopping url=${this.url}`)
    this.stopped = true
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.stopAuthRefresh()
    this.failAllPending('client stopped')
    if (this.ws) {
      try {
        this.ws.close(1000, 'client shutdown')
      } catch {}
      // Hard backstop in case the server doesn't ACK the close.
      const sock = this.ws
      setTimeout(() => {
        try {
          if (sock.readyState !== WebSocket.CLOSED) sock.terminate()
        } catch {}
      }, 2000)
    }
    this.connected = false
  }
}
