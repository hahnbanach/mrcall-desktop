export interface ZylchTask {
  id: string
  owner_id: string
  event_type: string
  event_id: string
  contact_email: string
  /**
   * Phone identifier populated for tasks whose trigger channel is
   * WhatsApp (whatsapp-pipeline-parity Fase 3a). Email/phone/calendar
   * tasks leave this NULL. The F8 dedup sweep clusters on
   * `contact_email OR contact_phone` so a cross-channel duplicate
   * collapses regardless of which channel surfaced first.
   */
  contact_phone?: string | null
  contact_name?: string
  /**
   * Short action-oriented title produced by the task detector
   * (TASK_DECISION_TOOL). Names the real subject/person, not the
   * email-sender envelope. NULL on tasks created before this field
   * existed — the UI falls back to contact_name / contact_email.
   */
  title?: string | null
  action_required: boolean
  urgency: 'high' | 'medium' | 'low' | string
  reason: string
  suggested_action: string
  created_at: string
  analyzed_at?: string
  completed_at?: string | null
  close_note?: string | null
  pinned?: boolean
  /**
   * Most recent dated event tied to this task: latest source email
   * date, calendar event start, etc. Falls back to `analyzed_at` →
   * `created_at` so the field is always populated. Engine-provided
   * (ISO 8601 UTC).
   */
  last_signal_at?: string | null
  /**
   * Semantic channel ('email' / 'phone' / 'calendar' / 'whatsapp'),
   * distinct from event_type. NULL on legacy rows that predate the
   * Fase 3.2 column — the renderer treats null as 'email' for the
   * filter so the dropdown stays consistent.
   */
  channel?: 'email' | 'phone' | 'calendar' | 'whatsapp' | string | null
  sources: {
    emails: string[]
    /**
     * WhatsApp message PKs (UUIDs) attached to this task
     * (whatsapp-pipeline-parity Fase 3a). Optional — every task
     * created before Fase 3 ships, and every email/calendar task,
     * omits this field. Cross-channel tasks carry BOTH `emails` and
     * `whatsapp_messages` populated.
     */
    whatsapp_messages?: string[]
    blobs: string[]
    calendar_events: string[]
    /**
     * Channel-native conversation id: RFC 2822 thread cluster for
     * email, ``chat_jid`` for WhatsApp (``<digits>@s.whatsapp.net``
     * or ``<digits>@lid`` privacy-mode pseudonym). The Source panel
     * uses the suffix to pick the right rendering branch.
     */
    thread_id?: string | null
    /**
     * WhatsApp chat_jid pointer for cross-channel tasks
     * (whatsapp-pipeline-parity Fase 4). Stamped on the FIRST WA
     * touchpoint to the task — whether the task was email-derived
     * (gained a WA touchpoint via F7 cross-channel match) or
     * WA-derived. Renderer's Source-panel toggle reads this
     * alongside `thread_id` to pick which channel to render. NULL
     * on tasks with no WA touchpoint.
     */
    whatsapp_chat_jid?: string | null
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
  /**
   * Raw HTML body from the original email, or empty string if the message
   * had no HTML alternative. Rendered inside a fully-sandboxed iframe
   * (sandbox="") so scripts, forms, top-level navigation and plugin
   * content are all disabled. Empty → fall back to `body_plain`.
   */
  body_html: string
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

export interface WhatsAppThread {
  jid: string
  name: string | null
  phone: string | null
  is_group: boolean
  message_count: number
  last_at: string | null
  last_preview: string
  last_from_me: boolean
  /** Matching message text — present only on search results. */
  match_snippet?: string | null
}

export interface WhatsAppMessage {
  id: string
  message_id: string
  chat_jid: string
  sender_jid: string
  sender_name: string | null
  text: string | null
  media_type: string | null
  transcription: string | null
  is_from_me: boolean
  is_group: boolean
  timestamp: string | null
}

/**
 * Streaming event from the engine's task solve loop. Sent over the
 * `tasks.solve.event` JSON-RPC notification; mirrored from the engine
 * shape in `engine/zylch/services/task_executor.py` and the queue
 * envelope in `engine/zylch/rpc/methods.py:tasks_solve`.
 *
 * Every event carries `task_id` so the renderer can route to the right
 * conversation — with multiple solves potentially queued at once, the
 * old "implicit-attribution-to-active-conv" contract no longer holds.
 *
 * Lifecycle:
 *   queued    → emitted if the engine lock is held by another solve;
 *               renderer shows "In coda".
 *   starting  → lock acquired, model work begins.
 *   thinking / tool_use_start / tool_call_pending / tool_result → as before.
 *   done      → clean finish (incl. user-cancelled, with result.cancelled).
 *   error     → executor exception.
 */
type SolveEventBase = { task_id?: string }
export type SolveEvent = SolveEventBase &
  (
    | { type: 'queued' }
    | { type: 'starting' }
    | { type: 'thinking'; text: string }
    | {
        type: 'tool_use_start'
        tool_use_id: string
        name: string
      }
    | {
        type: 'tool_call_pending'
        tool_use_id: string
        name: string
        input: Record<string, unknown>
        preview: string
      }
    | {
        type: 'tool_result'
        tool_use_id: string
        name: string
        output: string
        approved: boolean
      }
    | { type: 'done'; result: { messages?: unknown[]; cancelled?: boolean; task_missing?: boolean } }
    | { type: 'error'; message: string }
  )

export interface ZylchAPI {
  tasks: {
    list: (p?: { include_completed?: boolean; include_skipped?: boolean }) => Promise<ZylchTask[]>
    complete: (task_id: string, note?: string | null) => Promise<{ ok: boolean }>
    reopen: (task_id: string) => Promise<{ ok: boolean }>
    skip: (task_id: string) => Promise<{ ok: boolean }>
    pin: (task_id: string, pinned: boolean) => Promise<{ ok: boolean }>
    reanalyze: (task_id: string) => Promise<{
      ok: boolean
      action: 'kept' | 'closed' | 'updated'
      reason: string
      task_id: string
      usage?: Record<string, unknown>
    }>
    listByThread: (thread_id: string) => Promise<ZylchTask[]>
    /** Manual dedup sweep (Settings → Maintenance). Same worker as the
     *  automatic post-/update path. */
    dedupNow: () => Promise<{
      clusters_examined: number
      clusters_with_dups: number
      tasks_closed: number
      skipped_recently_reopened: number
      skipped_oversize: number
      no_llm: boolean
    }>
    /** Agentic solve — fires SOLVE_SYSTEM_PROMPT with the task's
     *  pre-built context. The live event stream arrives via the
     *  'tasks.solve.event' notification (see SolveEvent below); this
     *  promise resolves only after `done` or `error`. Single solve at
     *  a time engine-side (asyncio.Lock). */
    solve: (
      task_id: string,
      instructions?: string
    ) => Promise<{ ok: boolean; result?: unknown; error?: string }>
    solveApprove: (
      tool_use_id: string,
      payload: { approved: boolean; edited_input?: Record<string, unknown> | null }
    ) => Promise<{ ok: boolean }>
    solveCancel: (task_id?: string) => Promise<{
      ok: boolean
      task_id?: string
      cancelled_pending?: number
      error?: string
    }>
  }
  memory: {
    /** Manual memory reconsolidation (Settings → Maintenance). Walks
     *  user:<owner_id> blobs, groups by canonical Name, calls the
     *  LLM merge service per pair, deletes redundant duplicates. */
    reconsolidateNow: () => Promise<{
      ok: boolean
      error?: string
      groups_examined?: number
      blobs_examined?: number
      blobs_merged?: number
      blobs_kept_distinct?: number
      pair_cap_hit?: boolean
      no_llm?: boolean
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
      approvedOrOpts?:
        | boolean
        | { mode: 'once' | 'session' | 'deny'; edited_input?: Record<string, unknown> }
    ) => Promise<{ ok: boolean }>
  }
  update: {
    run: () => Promise<any>
  }
  agents: {
    /** Runs the 3 personalised-agent trainers serially (memory_message —
     *  channel-aware over email + WhatsApp; task_email — task detection;
     *  emailer — writing style). Progress is streamed via the
     *  ``agents.train.progress`` notification with
     *  ``{pct, step, total, current, message}``. */
    trainAll: () => Promise<{
      ok: boolean
      error?: string
      results: Record<
        string,
        {
          ok: boolean
          error?: string
          threads_analyzed?: number
          whatsapp_chats_analyzed?: number
        }
      >
    }>
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
    /**
     * Gmail-style thread search. ``query`` accepts the operators
     * documented in ``docs/ipc-contract.md`` (``from:``, ``to:``,
     * ``cc:``, ``subject:``, ``body:``, ``has:attachment``,
     * ``is:unread|read|pinned|auto``, ``before:`` / ``after:``,
     * ``older_than:Nd``, ``newer_than:Nd``, ``filename:``). Bare terms
     * match across subject/body/snippet/from. Returns the same
     * ``InboxThread`` shape as ``listInbox`` / ``listSent`` so the
     * thread list renders unchanged.
     */
    search: (params: {
      query: string
      folder?: 'inbox' | 'sent' | 'all'
      limit?: number
      offset?: number
    }) => Promise<{ threads: InboxThread[] }>
    pin: (threadId: string, pinned: boolean) => Promise<{ ok: boolean; affected: number }>
    markRead: (threadId: string) => Promise<{ ok: boolean; affected: number }>
    archive: (threadId: string) => Promise<{
      ok: boolean
      archived: number
      imap: { folder: string; moved: number; attempted: number }
    }>
    deleteLocal: (threadId: string) => Promise<{ ok: boolean; deleted: number }>
  }
  files: {
    select: () => Promise<string[]>
    selectDirectories: () => Promise<string[]>
  }
  profile: {
    /** Resolves to the profile this window's sidecar is bound to.
     *  `id` is the on-disk directory name (Firebase UID — stable, safe
     *  as a key); `email` is the display label from the profile's
     *  `.env`, null when the file is missing or unreadable. */
    current: () => Promise<{ id: string; email: string | null }>
  }
  profiles: {
    /** Each entry is `{id, email}`. Render the email; key by id. */
    list: () => Promise<Array<{ id: string; email: string | null }>>
    create: (
      email: string,
      values: Record<string, string>
    ) => Promise<{ ok: boolean; profile: string }>
  }
  window: {
    /** Opens a fresh auth-pending window. `id` is the picked profile
     *  dir (Firebase UID); the dir's email is used as a SignIn pre-fill
     *  hint. Actual profile binding happens after Firebase signin. */
    openForProfile: (id: string) => Promise<{ ok: boolean }>
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
  account: {
    setFirebaseToken: (args: {
      uid: string
      email: string | null
      idToken: string
      expiresAtMs: number
    }) => Promise<{ ok: boolean }>
    signOut: () => Promise<{ ok: boolean }>
    whoAmI: () => Promise<{
      signed_in: boolean
      uid?: string
      email?: string | null
      expires_at_ms?: number
    }>
    /** Fetch the signed-in user's MrCall credit balance via the
     *  mrcall-agent proxy. Returns the server payload verbatim, OR
     *  `{error: 'auth_expired'}` when the cached Firebase ID token was
     *  rejected (renderer should refresh + retry). */
    balance: () => Promise<
      | {
          balance_credits: number
          balance_micro_usd: number
          balance_usd: number
          granularity_micro_usd?: number
          estimate_messages_remaining?: number
        }
      | { error: 'auth_expired' }
    >
  }
  mrcall: {
    listMyBusinesses: (params?: {
      offset?: number
      limit?: number
    }) => Promise<{ businesses: unknown[]; role: string }>
    searchBusinesses: (params?: {
      emailAddress?: string
      name?: string
      surname?: string
      companyName?: string
      nickname?: string
      businessPhoneNumber?: string
      vatId?: string
      businessId?: string
      address?: string
      countryAlpha2?: string
      subscriptionStatus?: string
      offset?: number
      limit?: number
    }) => Promise<{ businesses: unknown[]; role: string }>
  }
  google: {
    calendar: {
      connect: () => Promise<{ ok: boolean; email: string; scope: string }>
      disconnect: () => Promise<{ ok: boolean }>
      status: () => Promise<{
        connected: boolean
        signed_in?: boolean
        email?: string | null
      }>
      cancel: () => Promise<{ cancelled: boolean }>
    }
  }
  whatsapp: {
    connect: () => Promise<{
      ok: boolean
      phone?: string | null
      display_name?: string | null
      reason?: string
    }>
    disconnect: (
      forgetSession?: boolean
    ) => Promise<{ ok: boolean; forgot: boolean; error?: string }>
    status: () => Promise<{
      connected: boolean
      has_session: boolean
      phone?: string | null
      display_name?: string | null
    }>
    cancel: () => Promise<{ cancelled: boolean }>
    listThreads: (params?: {
      limit?: number
      offset?: number
    }) => Promise<{
      threads: WhatsAppThread[]
      total_messages?: number
      owner_id?: string
      breakdown_by_server?: Record<string, number>
      error?: string
    }>
    listMessages: (params: {
      chat_jid: string
      limit?: number
      offset?: number
    }) => Promise<{ messages: WhatsAppMessage[]; error?: string }>
    searchMessages: (params: {
      query: string
      limit?: number
    }) => Promise<{ threads: WhatsAppThread[]; query?: string; error?: string }>
    sendMessage: (params: {
      chat_jid: string
      text: string
    }) => Promise<{ ok: boolean; message?: WhatsAppMessage; error?: string }>
  }
  shell: {
    openExternal: (url: string) => Promise<{ ok: boolean }>
  }
  signin: {
    googleStart: () => Promise<{
      ok: boolean
      idToken?: string
      email?: string | null
      error?: string
    }>
    googleCancel: () => Promise<{ cancelled: boolean }>
  }
  auth: {
    bindProfile: (
      uid: string
    ) => Promise<{ ok: boolean; found: boolean; reason?: string }>
  }
  onboarding: {
    createProfile: (
      email: string,
      values: Record<string, string>
    ) => Promise<{ ok: true; profile: string } | { ok: false; error: string }>
    createProfileForFirebaseUser: (
      uid: string,
      email: string,
      values: Record<string, string>
    ) => Promise<{ ok: true; profile: string } | { ok: false; error: string }>
    finalize: (profile: string) => Promise<{ ok: boolean }>
  }
  onNotification: (method: string, cb: (params: any) => void) => () => void
  onStderr: (cb: (chunk: string) => void) => () => void
  onSidecarStatus: (cb: (status: SidecarStatusEvent) => void) => () => void
  onOpenProfilePicker: (cb: () => void) => () => void
  // Logs view: scrollback (per-window ring buffer of sidecar stderr,
  // kept in main process) + clear. Live streaming uses the existing
  // onStderr subscription above.
  logs: {
    tail: () => Promise<string[]>
    clear: () => Promise<{ ok: boolean }>
  }
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
