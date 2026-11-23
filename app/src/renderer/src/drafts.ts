export interface MailboxDraft {
  id: string
  mailbox_id: string
  mailbox_address?: string
  status: 'draft'
  to?: string | string[]
  to_addresses?: string[]
  cc?: string | string[]
  cc_addresses?: string[]
  bcc?: string | string[]
  bcc_addresses?: string[]
  subject: string
  body: string
  body_format?: string
  body_editable?: boolean
  in_reply_to?: string | null
  references?: string[]
  thread_id?: string
  date?: string
  attachments?: Array<{ filename?: string; name?: string; size?: number }>
  has_attachments?: boolean
}

export interface MailboxDraftPatch {
  draft_id: string
  to?: string
  cc?: string
  bcc?: string
  subject?: string
  body?: string
}

export interface MailboxDraftResult {
  ok: boolean
  draft?: MailboxDraft
  cause?: string
}

export interface MailboxDraftOutcome {
  ok: boolean
  state: string
  request_key: string
  operation_id?: string
  draft_id: string
  message_id?: string
  effect_certainty?: string
  cause?: string
}

export interface MailboxDraftAPI {
  list: (params?: { mailbox_id?: string }) => Promise<MailboxDraft[]>
  get: (draftId: string) => Promise<MailboxDraftResult>
  update: (params: MailboxDraftPatch) => Promise<MailboxDraftResult>
  send: (draftId: string, requestKey: string) => Promise<MailboxDraftOutcome>
  trash: (draftId: string, requestKey: string) => Promise<MailboxDraftOutcome>
}
