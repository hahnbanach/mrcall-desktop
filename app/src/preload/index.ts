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
    complete: (task_id: string, note?: string | null) =>
      call<{ ok: boolean }>('tasks.complete', { task_id, note: note ?? null }),
    reopen: (task_id: string) => call<{ ok: boolean }>('tasks.reopen', { task_id }),
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
      }>('tasks.reanalyze', { task_id }, 120000),
    // Returns the open tasks whose sources reference emails in the given
    // thread. Used by the Inbox "Open" button: we always navigate to the
    // Tasks view and filter to these ids, even when the list is empty or
    // has exactly one element. No direct-open shortcut.
    listByThread: (thread_id: string) =>
      call<any[]>('tasks.list_by_thread', { thread_id }, 15000)
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
    // 12h ceiling — a first sync on a busy inbox can legitimately take
    // 1–4h (IMAP pull + memory extraction + task detection over every
    // thread). The old 10-minute timeout was giving users a bogus
    // "rpc timeout: update.run" error on new profiles.
    run: () => call<any>('update.run', {}, 12 * 3600 * 1000)
  },
  emails: {
    listByThread: (threadId: string) =>
      call<any>('emails.list_by_thread', { thread_id: threadId }, 60000),
    listInbox: (params: { limit?: number; offset?: number } = {}) =>
      call<{ threads: any[] }>(
        'emails.list_inbox',
        { limit: params.limit ?? 50, offset: params.offset ?? 0 },
        30000
      ),
    listSent: (params: { limit?: number; offset?: number } = {}) =>
      call<{ threads: any[] }>(
        'emails.list_sent',
        { limit: params.limit ?? 50, offset: params.offset ?? 0 },
        30000
      ),
    pin: (threadId: string, pinned: boolean) =>
      call<{ ok: boolean; affected: number }>(
        'emails.pin',
        { thread_id: threadId, pinned },
        15000
      ),
    markRead: (threadId: string) =>
      call<{ ok: boolean; affected: number }>(
        'emails.mark_read',
        { thread_id: threadId },
        15000
      ),
    archive: (threadId: string) =>
      // IMAP MOVE can take a few seconds (network + folder lookup) so
      // we give this a comfortable 60s ceiling — the renderer shows a
      // spinner in the archive button until it resolves.
      call<{
        ok: boolean
        archived: number
        imap: { folder: string; moved: number; attempted: number }
      }>('emails.archive', { thread_id: threadId }, 60000),
    deleteLocal: (threadId: string) =>
      // Local-only soft delete: instant, no network. Method name
      // `deleteLocal` on this side to keep the "never touches IMAP"
      // promise visible at every call site.
      call<{ ok: boolean; deleted: number }>(
        'emails.delete',
        { thread_id: threadId },
        15000
      )
  },
  files: {
    select: (): Promise<string[]> =>
      ipcRenderer.invoke('dialog:selectFiles') as Promise<string[]>,
    selectDirectories: (): Promise<string[]> =>
      ipcRenderer.invoke('dialog:selectDirectories') as Promise<string[]>
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
  onboarding: {
    // True iff ~/.zylch/profiles is empty (no subdirectories). The
    // onboarding window is opened by the main process before the
    // renderer loads, but we also check at mount so the renderer can
    // route correctly when opened with ?onboarding=1 query.
    isFirstRun: (): Promise<boolean> =>
      ipcRenderer.invoke('onboarding:isFirstRun') as Promise<boolean>,
    // Creates a profile directly on disk — NO sidecar involved. Used
    // exclusively from the first-run wizard. Returns ok=false with an
    // `error` string on validation / filesystem errors (the renderer
    // surfaces it inline).
    createProfile: (
      email: string,
      values: Record<string, string>
    ): Promise<{ ok: true; profile: string } | { ok: false; error: string }> =>
      ipcRenderer.invoke('onboarding:createProfile', email, values) as Promise<
        { ok: true; profile: string } | { ok: false; error: string }
      >,
    // After a successful createProfile, the renderer calls finalize to
    // spawn a real profile-bound window and close the onboarding one.
    finalize: (email: string): Promise<{ ok: boolean }> =>
      ipcRenderer.invoke('onboarding:finalize', email) as Promise<{ ok: boolean }>
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
