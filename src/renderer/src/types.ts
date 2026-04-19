export interface ZylchTask {
  id: string
  owner_id: string
  event_type: string
  event_id: string
  contact_email: string
  contact_name?: string
  action_required: boolean
  urgency: 'high' | 'medium' | 'low' | string
  reason: string
  suggested_action: string
  created_at: string
  analyzed_at?: string
  completed_at?: string | null
  pinned?: boolean
  sources: {
    emails: string[]
    blobs: string[]
    calendar_events: string[]
    thread_id?: string | null
  }
}

export interface ThreadEmail {
  id: string
  from_email: string
  from_name: string
  to_email: string
  cc_email: string
  date: string
  subject: string
  body_plain: string
  is_auto_reply: boolean
  is_user_sent: boolean
  has_attachments: boolean
  attachment_filenames: string[]
}

export interface EmailThreadResult {
  emails: ThreadEmail[]
}

export interface InboxThread {
  thread_id: string
  subject: string
  from_email: string
  from_name: string
  to_email: string
  date: string
  snippet: string
  unread: boolean
  has_attachments: boolean
  pinned: boolean
  message_count: number
  last_email_id: string
}

export interface ZylchAPI {
  tasks: {
    list: (p?: { include_completed?: boolean; include_skipped?: boolean }) => Promise<ZylchTask[]>
    complete: (task_id: string) => Promise<{ ok: boolean }>
    skip: (task_id: string) => Promise<{ ok: boolean }>
    pin: (task_id: string, pinned: boolean) => Promise<{ ok: boolean }>
    reanalyze: (task_id: string) => Promise<{
      ok: boolean
      action: 'kept' | 'closed' | 'updated'
      reason: string
      task_id: string
      usage?: Record<string, unknown>
    }>
  }
  chat: {
    send: (
      message: string,
      conversation_history?: unknown[],
      opts?: { conversationId?: string; context?: Record<string, unknown> }
    ) => Promise<any>
    approve: (
      tool_use_id: string,
      approvedOrOpts?: boolean | { mode: 'once' | 'session' | 'deny' }
    ) => Promise<{ ok: boolean }>
  }
  update: {
    run: () => Promise<any>
  }
  emails: {
    listByThread: (threadId: string) => Promise<EmailThreadResult>
    listInbox: (params?: {
      limit?: number
      offset?: number
    }) => Promise<{ threads: InboxThread[] }>
    listSent: (params?: {
      limit?: number
      offset?: number
    }) => Promise<{ threads: InboxThread[] }>
    pin: (threadId: string, pinned: boolean) => Promise<{ ok: boolean; affected: number }>
    markRead: (threadId: string) => Promise<{ ok: boolean; affected: number }>
  }
  files: {
    select: () => Promise<string[]>
    selectDirectories: () => Promise<string[]>
  }
  profile: {
    current: () => Promise<string>
  }
  profiles: {
    list: () => Promise<string[]>
    create: (
      email: string,
      values: Record<string, string>
    ) => Promise<{ ok: boolean; profile: string }>
  }
  window: {
    openForProfile: (email: string) => Promise<{ ok: boolean }>
  }
  narration: {
    summarize: (lines: string[], context?: string) => Promise<{ text: string }>
    predict: (message: string, context?: string) => Promise<{ text: string }>
  }
  settings: {
    schema: () => Promise<{
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
    }>
    get: () => Promise<{ values: Record<string, string> }>
    update: (
      updates: Record<string, string>
    ) => Promise<{ ok: boolean; applied: string[]; skipped_unchanged: string[] }>
  }
  sidecar: {
    restart: () => Promise<{ ok: boolean }>
  }
  onNotification: (method: string, cb: (params: any) => void) => () => void
  onStderr: (cb: (chunk: string) => void) => () => void
  onSidecarStatus: (cb: (status: SidecarStatusEvent) => void) => () => void
  onOpenProfilePicker: (cb: () => void) => () => void
}

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

declare global {
  interface Window {
    zylch: ZylchAPI
  }
}
