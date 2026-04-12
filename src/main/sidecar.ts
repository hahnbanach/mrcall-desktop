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
 */
export class SidecarClient extends EventEmitter {
  private proc: ChildProcessWithoutNullStreams | null = null
  private pending = new Map<number, Pending>()
  private nextId = 1
  private buf = ''
  private dead = false

  constructor(private opts: SidecarOptions) {
    super()
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
      // zylch logs to stderr; just mirror for debugging
      process.stderr.write(`[sidecar.stderr] ${chunk}`)
    })
    this.proc.on('exit', (code, signal) => {
      console.error(`[sidecar] exit code=${code} signal=${signal}`)
      this.dead = true
      for (const [, p] of this.pending) {
        clearTimeout(p.timer)
        p.reject(new Error(`sidecar exited (code=${code})`))
      }
      this.pending.clear()
      this.emit('exit', { code, signal })
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
      return Promise.reject(new Error('sidecar not running'))
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
