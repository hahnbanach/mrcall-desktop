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

export interface ZylchAPI {
  tasks: {
    list: (p?: { include_completed?: boolean; include_skipped?: boolean }) => Promise<ZylchTask[]>
    complete: (task_id: string) => Promise<{ ok: boolean }>
    skip: (task_id: string) => Promise<{ ok: boolean }>
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
    approve: (tool_use_id: string, approved: boolean) => Promise<{ ok: boolean }>
  }
  update: {
    run: () => Promise<any>
  }
  emails: {
    listByThread: (threadId: string) => Promise<EmailThreadResult>
  }
  files: {
    select: () => Promise<string[]>
  }
  profile: {
    current: () => Promise<string>
  }
  narration: {
    summarize: (lines: string[], context?: string) => Promise<{ text: string }>
    predict: (message: string, context?: string) => Promise<{ text: string }>
  }
  onNotification: (method: string, cb: (params: any) => void) => () => void
  onStderr: (cb: (chunk: string) => void) => () => void
}

declare global {
  interface Window {
    zylch: ZylchAPI
  }
}
