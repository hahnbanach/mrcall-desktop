import { contextBridge, ipcRenderer } from 'electron'

type NotifyCb = (params: unknown) => void
const listeners = new Map<string, Set<NotifyCb>>()

type StderrCb = (chunk: string) => void
const stderrListeners = new Set<StderrCb>()

ipcRenderer.on('sidecar:stderr', (_e, chunk: string) => {
  for (const cb of stderrListeners) {
    try {
      cb(chunk)
    } catch (e) {
      console.error('[preload] stderr handler error', e)
    }
  }
})

ipcRenderer.on('rpc:notification', (_e, msg: { method: string; params: unknown }) => {
  const set = listeners.get(msg.method)
  if (!set) return
  for (const cb of set) {
    try {
      cb(msg.params)
    } catch (e) {
      console.error('[preload] notification handler error', e)
    }
  }
})

const call = <T = unknown>(method: string, params: unknown = {}, timeout?: number): Promise<T> =>
  ipcRenderer.invoke('rpc:call', method, params, timeout) as Promise<T>

const api = {
  tasks: {
    list: (params: { include_completed?: boolean; include_skipped?: boolean } = {}) =>
      call<any[]>('tasks.list', params),
    complete: (task_id: string) => call<{ ok: boolean }>('tasks.complete', { task_id }),
    skip: (task_id: string) => call<{ ok: boolean }>('tasks.skip', { task_id }),
    reanalyze: (task_id: string) =>
      call<{
        ok: boolean
        action: 'kept' | 'closed' | 'updated'
        reason: string
        task_id: string
        usage?: Record<string, unknown>
      }>('tasks.reanalyze', { task_id }, 120000)
  },
  chat: {
    send: (
      message: string,
      conversation_history: unknown[] = [],
      opts: { conversationId?: string; context?: Record<string, unknown> } = {}
    ) =>
      call<any>(
        'chat.send',
        {
          message,
          conversation_history,
          conversation_id: opts.conversationId ?? 'general',
          context: opts.context ?? {}
        },
        600000
      ),
    approve: (tool_use_id: string, approved: boolean) =>
      call<{ ok: boolean }>('chat.approve', { tool_use_id, approved })
  },
  update: {
    run: () => call<any>('update.run', {}, 600000)
  },
  narration: {
    summarize: (lines: string[], context: string = '') =>
      call<{ text: string }>('narration.summarize', { lines, context }, 15000)
  },
  onNotification: (method: string, cb: NotifyCb): (() => void) => {
    let set = listeners.get(method)
    if (!set) {
      set = new Set()
      listeners.set(method, set)
    }
    set.add(cb)
    return () => set!.delete(cb)
  },
  onStderr: (cb: StderrCb): (() => void) => {
    stderrListeners.add(cb)
    return () => {
      stderrListeners.delete(cb)
    }
  }
}

contextBridge.exposeInMainWorld('zylch', api)

export type ZylchAPI = typeof api
