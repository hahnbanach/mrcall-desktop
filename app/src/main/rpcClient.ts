import { EventEmitter } from 'events'

/**
 * RpcClient — the transport abstraction the main process talks to.
 *
 * Today's local-stdio path (`StdioRpcClient`, the old `SidecarClient`) and
 * the new cross-machine path (`WebSocketRpcClient`) both implement this so
 * `index.ts` is transport-agnostic: it wires the same events and calls the
 * same methods regardless of where the engine actually runs.
 *
 * Events (EventEmitter):
 *  - `'notification'` `{ method, params }` — every server-initiated
 *    JSON-RPC notification EXCEPT `engine.ready`. The renderer's
 *    `onNotification(method, cb)` subscriptions consume these verbatim.
 *  - `'status'` `RpcStatusEvent` — liveness/health, shaped exactly like
 *    the `sidecar:status` payload the renderer already renders (boot
 *    splash + SidecarStatusBanner). The client OWNS the synthesis of this
 *    event: stdio derives `ready` from the engine's `engine.ready`
 *    notification; ws derives it from the socket reaching OPEN (the WS
 *    engine never emits `engine.ready`).
 *  - `'stderr'` `chunk: string` — raw child stderr (stdio only; ws never
 *    emits this). Feeds the per-window Logs ring buffer.
 *  - `'exit'` `{ code, signal, classified }` — the underlying transport
 *    died PERMANENTLY (stdio: child process exited; ws: only emitted on a
 *    `stop()`-initiated teardown). Distinct from a transient ws drop,
 *    which surfaces as a `'status' {alive:false}` and auto-reconnects.
 *
 * Keeping the `'notification'` event name + payload identical to the old
 * `SidecarClient` means renderer-facing wiring needs no change.
 */
export type RpcStatusEvent =
  | {
      alive: true
      profile: string
      // True once the engine can serve RPCs. Stdio: set when
      // `engine.ready` arrives. WS: set when the socket reaches OPEN
      // (and the handshake auth passed).
      ready?: boolean
      // Boot/connect duration in ms (only on the ready:true event).
      bootMs?: number
      // Present for the ws transport: the remote endpoint, surfaced by
      // the renderer's IdentityBanner so a remote session is obvious.
      remoteUrl?: string
    }
  | {
      alive: false
      profile: string
      exitCode: number | null
      code: string
      message: string
      hint?: string
    }

export interface ExitInfo {
  code: number | null
  signal: NodeJS.Signals | null
  classified?: { code: string; message: string; hint?: string }
}

/**
 * The surface `index.ts` consumes. Both transports are drop-in for this.
 */
export interface RpcClient extends EventEmitter {
  /** Begin the transport (spawn the child / open the socket). */
  start(): void
  /** Issue a JSON-RPC request and resolve/reject on the response. */
  call<T = unknown>(method: string, params?: unknown, timeoutMs?: number): Promise<T>
  /** Tear down the transport permanently (no auto-reconnect after this). */
  stop(): void
  /** True while the transport can currently serve a `call()`. */
  isAlive(): boolean
  /** Mark the next `stop()` as a deliberate restart (suppresses the crash banner). */
  markIntentionalRestart(): void
  isIntentionalRestart(): boolean
  /** Best-effort structured reason for the most recent failure. */
  classifyError(): { code: string; message: string; hint?: string }
  /** Last N stderr lines (stdio only; ws returns []). */
  lastStderrLines(): string[]
}
