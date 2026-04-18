import { spawn, ChildProcessWithoutNullStreams } from 'child_process'
import { EventEmitter } from 'events'

type Pending = {
  resolve: (v: unknown) => void
  reject: (e: Error) => void
  timer: NodeJS.Timeout
  method: string
}

export interface SidecarOptions {
  cwd: string
  binary: string
  profile: string
}

/**
 * SidecarClient — owns the `zylch rpc` child process.
 * - Line-buffers stdout, parses JSON-RPC 2.0.
 * - Dispatches responses by `id` to pending promises.
 * - Emits 'notification' events for server-initiated messages.
 * - Keeps the last N lines of stderr in a ring so callers can build a
 *   helpful error after the child dies (Bug 2: "sidecar not running" was
 *   shown to the renderer with no context — now we attach the captured
 *   reason via `lastError` and `lastStderrLines`).
 */
export class SidecarClient extends EventEmitter {
  private proc: ChildProcessWithoutNullStreams | null = null
  private pending = new Map<number, Pending>()
  private nextId = 1
  private buf = ''
  private dead = false
  private stderrRing: string[] = []
  private static readonly STDERR_RING_MAX = 50
  // Set when the process exits with a non-zero status, or when we manage
  // to extract a meaningful reason from the stderr ring.
  lastError: string | null = null
  lastExitCode: number | null = null
  lastExitSignal: NodeJS.Signals | null = null
  // Marker set by the main process via `markIntentionalRestart()` right
  // before calling `stop()` as part of a Settings-driven restart. The exit
  // handler reads this so it can classify the death as a benign
  // "restarting" event instead of a crash, which prevents the
  // SidecarStatusBanner from flashing red/amber for the ~1s gap between
  // SIGTERM and the new child becoming alive.
  private intentionalRestart = false

  constructor(private opts: SidecarOptions) {
    super()
  }

  isAlive(): boolean {
    return !this.dead && this.proc !== null
  }

  /** Caller marks the upcoming stop() as part of a deliberate restart. */
  markIntentionalRestart(): void {
    this.intentionalRestart = true
  }

  isIntentionalRestart(): boolean {
    return this.intentionalRestart
  }

  lastStderrLines(): string[] {
    return [...this.stderrRing]
  }

  /**
   * Best-effort classification of the captured stderr. Returns a small
   * structured object the renderer can present as a banner.
   */
  classifyError(): { code: string; message: string; hint?: string } {
    // If this death was triggered by an intentional restart (Settings →
    // Save), report it as such so the renderer suppresses the red/amber
    // crash banner and shows a small "Restarting…" indicator instead.
    if (this.intentionalRestart) {
      return {
        code: 'restarting',
        message: 'Restarting sidecar…'
      }
    }
    const text = this.stderrRing.join('\n')
    const lockMatch = text.match(/Profile '([^']+)' is already in use by another session/)
    if (lockMatch) {
      return {
        code: 'profile_locked',
        message: `Profile ${lockMatch[1]} is already in use by another Zylch window or CLI session.`,
        hint: 'Close the other Zylch window (or stop the running zylch CLI) and try again.'
      }
    }
    const tail = this.stderrRing
      .filter((l) => l.trim().length > 0)
      .slice(-3)
      .join(' | ')
      .trim()
    if (this.lastExitCode !== null && this.lastExitCode !== 0) {
      return {
        code: 'sidecar_crashed',
        message: tail
          ? `Sidecar exited (code=${this.lastExitCode}): ${tail}`
          : `Sidecar exited unexpectedly (code=${this.lastExitCode}).`
      }
    }
    if (this.dead) {
      return {
        code: 'sidecar_not_running',
        message: tail || 'Sidecar is not running.'
      }
    }
    return { code: 'sidecar_not_running', message: 'Sidecar is not running.' }
  }

  start(): void {
    const args = ['-p', this.opts.profile, 'rpc']
    console.log(`[sidecar] spawn ${this.opts.binary} ${args.join(' ')} cwd=${this.opts.cwd}`)
    this.proc = spawn(this.opts.binary, args, {
      cwd: this.opts.cwd,
      env: { ...process.env },
      stdio: ['pipe', 'pipe', 'pipe']
    })

    this.proc.stdout.setEncoding('utf8')
    this.proc.stdout.on('data', (chunk: string) => this.onStdout(chunk))
    this.proc.stderr.setEncoding('utf8')
    this.proc.stderr.on('data', (chunk: string) => {
      // zylch logs to stderr; mirror for debugging AND forward to renderer
      process.stderr.write(`[sidecar.stderr] ${chunk}`)
      // Append each non-empty line to the ring buffer so we can build a
      // helpful error after the child dies. Keep at most STDERR_RING_MAX
      // lines.
      for (const line of chunk.split('\n')) {
        if (!line) continue
        this.stderrRing.push(line)
        if (this.stderrRing.length > SidecarClient.STDERR_RING_MAX) {
          this.stderrRing.splice(0, this.stderrRing.length - SidecarClient.STDERR_RING_MAX)
        }
      }
      this.emit('stderr', chunk)
    })
    this.proc.on('exit', (code, signal) => {
      console.error(`[sidecar] exit code=${code} signal=${signal}`)
      this.dead = true
      this.lastExitCode = code
      this.lastExitSignal = signal
      const cls = this.classifyError()
      this.lastError = cls.message
      for (const [, p] of this.pending) {
        clearTimeout(p.timer)
        p.reject(new Error(`sidecar exited (code=${code}): ${cls.message}`))
      }
      this.pending.clear()
      this.emit('exit', { code, signal, classified: cls })
    })
    this.proc.on('error', (err) => {
      console.error('[sidecar] error', err)
      this.emit('error', err)
    })
  }

  private onStdout(chunk: string): void {
    this.buf += chunk
    let idx: number
    while ((idx = this.buf.indexOf('\n')) >= 0) {
      const line = this.buf.slice(0, idx).trim()
      this.buf = this.buf.slice(idx + 1)
      if (!line) continue
      let msg: any
      try {
        msg = JSON.parse(line)
      } catch (e) {
        console.error('[sidecar] non-JSON line:', line.slice(0, 200))
        continue
      }
      if (typeof msg.id === 'number' && (msg.result !== undefined || msg.error !== undefined)) {
        const p = this.pending.get(msg.id)
        if (!p) {
          console.warn(`[sidecar] response for unknown id=${msg.id}`)
          continue
        }
        this.pending.delete(msg.id)
        clearTimeout(p.timer)
        if (msg.error) {
          p.reject(new Error(msg.error.message || 'rpc error'))
        } else {
          p.resolve(msg.result)
        }
      } else if (msg.method) {
        // notification
        this.emit('notification', { method: msg.method, params: msg.params })
      }
    }
  }

  call<T = unknown>(method: string, params: unknown = {}, timeoutMs = 60000): Promise<T> {
    if (this.dead || !this.proc) {
      // Build the most informative message we can: the captured reason
      // (if any) wins; fall back to the generic string. The renderer
      // pattern-matches on substrings to render a friendlier banner.
      const cls = this.classifyError()
      return Promise.reject(new Error(cls.message || 'sidecar not running'))
    }
    const id = this.nextId++
    const req = { jsonrpc: '2.0', id, method, params }
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`rpc timeout: ${method}`))
      }, timeoutMs)
      this.pending.set(id, {
        resolve: resolve as (v: unknown) => void,
        reject,
        timer,
        method
      })
      this.proc!.stdin.write(JSON.stringify(req) + '\n', (err) => {
        if (err) {
          clearTimeout(timer)
          this.pending.delete(id)
          reject(err)
        }
      })
    })
  }

  stop(): void {
    if (this.proc && !this.dead) {
      console.log('[sidecar] stopping')
      try {
        this.proc.stdin.end()
      } catch {}
      this.proc.kill('SIGTERM')
      setTimeout(() => {
        if (this.proc && !this.dead) {
          try {
            this.proc.kill('SIGKILL')
          } catch {}
        }
      }, 2000)
    }
  }
}
