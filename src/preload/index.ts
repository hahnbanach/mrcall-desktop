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

// Structured sidecar liveness/health events pushed by main when the
// child process spawns or dies. The renderer renders a banner from this.
export type SidecarStatusEvent =
  | { alive: true; profile: string }
  | {
      alive: false
      profile: string
      exitCode: number | null
      code: string
      message: string
      hint?: string
    }
type StatusCb = (status: SidecarStatusEvent) => void
const statusListeners = new Set<StatusCb>()
ipcRenderer.on('sidecar:status', (_e, status: SidecarStatusEvent) => {
  for (const cb of statusListeners) {
    try {
      cb(status)
    } catch (e) {
      console.error('[preload] status handler error', e)
    }
  }
})

type MenuCb = () => void
const openProfilePickerListeners = new Set<MenuCb>()
ipcRenderer.on('menu:openProfilePicker', () => {
  for (const cb of openProfilePickerListeners) {
    try {
      cb()
    } catch (e) {
      console.error('[preload] openProfilePicker handler error', e)
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
    pin: (task_id: string, pinned: boolean) =>
      call<{ ok: boolean }>('tasks.pin', { task_id, pinned }, 30000),
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
    approve: (
      tool_use_id: string,
      approvedOrOpts: boolean | { mode: 'once' | 'session' | 'deny' } = true
    ) => {
      // Back-compat: `approve(id, true/false)` still works. Preferred
      // form is `approve(id, { mode: 'once' | 'session' | 'deny' })`.
      const payload: Record<string, unknown> = { tool_use_id }
      if (typeof approvedOrOpts === 'boolean') {
        payload.approved = approvedOrOpts
      } else {
        payload.mode = approvedOrOpts.mode
      }
      return call<{ ok: boolean }>('chat.approve', payload)
    }
  },
  update: {
    run: () => call<any>('update.run', {}, 600000)
  },
  emails: {
    listByThread: (threadId: string) =>
      call<any>('emails.list_by_thread', { thread_id: threadId }, 60000)
  },
  files: {
    select: (): Promise<string[]> =>
      ipcRenderer.invoke('dialog:selectFiles') as Promise<string[]>
  },
  profile: {
    current: (): Promise<string> => ipcRenderer.invoke('profile:current') as Promise<string>
  },
  profiles: {
    list: (): Promise<string[]> => ipcRenderer.invoke('profiles:list') as Promise<string[]>,
    create: (email: string, values: Record<string, string>) =>
      call<{ ok: boolean; profile: string }>('profiles.create', { email, values }, 30000)
  },
  window: {
    openForProfile: (email: string): Promise<{ ok: boolean }> =>
      ipcRenderer.invoke('window:openForProfile', email) as Promise<{ ok: boolean }>
  },
  narration: {
    summarize: (lines: string[], context: string = '') =>
      call<{ text: string }>('narration.summarize', { lines, context }, 15000),
    predict: (message: string, context: string = '') =>
      call<{ text: string }>('narration.predict', { message, context }, 15000)
  },
  settings: {
    schema: () =>
      call<{
        fields: Array<{
          key: string
          label: string
          type: 'text' | 'password' | 'number' | 'select' | 'textarea'
          group: string
          optional?: boolean
          options?: string[]
          help?: string
          secret?: boolean
        }>
      }>('settings.schema', {}, 30000),
    get: () => call<{ values: Record<string, string> }>('settings.get', {}, 30000),
    update: (updates: Record<string, string>) =>
      call<{ ok: boolean; applied: string[]; skipped_unchanged: string[] }>(
        'settings.update',
        { updates },
        30000
      )
  },
  sidecar: {
    restart: (): Promise<{ ok: boolean }> =>
      ipcRenderer.invoke('sidecar:restart') as Promise<{ ok: boolean }>
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
  },
  onSidecarStatus: (cb: StatusCb): (() => void) => {
    statusListeners.add(cb)
    return () => {
      statusListeners.delete(cb)
    }
  },
  onOpenProfilePicker: (cb: MenuCb): (() => void) => {
    openProfilePickerListeners.add(cb)
    return () => {
      openProfilePickerListeners.delete(cb)
    }
  }
}

contextBridge.exposeInMainWorld('zylch', api)

export type ZylchAPI = typeof api
