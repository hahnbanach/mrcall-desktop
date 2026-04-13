import { contextBridge, ipcRenderer } from 'electron'

type NotifyCb = (params: unknown) => void
const listeners = new Map<string, Set<NotifyCb>>()

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
    skip: (task_id: string) => call<{ ok: boolean }>('tasks.skip', { task_id })
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
        120000
      ),
    approve: (tool_use_id: string, approved: boolean) =>
      call<{ ok: boolean }>('chat.approve', { tool_use_id, approved })
  },
  sync: {
    run: () => call<any>('sync.run', {}, 600000)
  },
  onNotification: (method: string, cb: NotifyCb): (() => void) => {
    let set = listeners.get(method)
    if (!set) {
      set = new Set()
      listeners.set(method, set)
    }
    set.add(cb)
    return () => set!.delete(cb)
  }
}

contextBridge.exposeInMainWorld('zylch', api)

export type ZylchAPI = typeof api
