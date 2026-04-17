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
  sources: { emails: string[]; blobs: string[]; calendar_events: string[] }
}

export interface ZylchAPI {
  tasks: {
    list: (p?: { include_completed?: boolean; include_skipped?: boolean }) => Promise<ZylchTask[]>
    complete: (task_id: string) => Promise<{ ok: boolean }>
    skip: (task_id: string) => Promise<{ ok: boolean }>
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
  onNotification: (method: string, cb: (params: any) => void) => () => void
}

declare global {
  interface Window {
    zylch: ZylchAPI
  }
}
