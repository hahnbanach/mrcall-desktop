import { useEffect, useState } from 'react'
import type { EmailThreadResult, ThreadEmail, WhatsAppMessage } from '../types'
import { errorMessage, isProfileLockedError } from '../lib/errors'
import HtmlEmailBody from './HtmlEmailBody'

function formatDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleString('it-IT')
}

export type ThreadSourceType = 'email' | 'whatsapp'

export interface ThreadPanelProps {
  threadId: string | null
  sourceType?: ThreadSourceType
  initialExpanded?: boolean
  /**
   * Called whenever the user toggles the panel. The parent can persist
   * the open/closed state per-conversation.
   */
  onToggle?: (expanded: boolean) => void
}

/**
 * ThreadPanel — collapsible "Source" panel shown at the top of the
 * Workspace view. Fetches the conversation source for `threadId` and
 * renders it newest-first.
 *
 * `sourceType` selects the rendering branch:
 *
 * - `email` (default): fetches via `emails.listByThread` and shows
 *   one `<article>` per email with HTML body in a sandboxed iframe.
 *   The original behaviour, unchanged.
 *
 * - `whatsapp` (added in Fase 4 of whatsapp-pipeline-parity): fetches
 *   via `whatsapp.listMessages({ chat_jid })` and renders WA bubbles
 *   aligned left (contact) / right (user). `chat_jid` is the same
 *   value the engine stores in `task.sources.thread_id` for WA tasks
 *   — either `<digits>@s.whatsapp.net` (real phone) or
 *   `<digits>@lid` (privacy-mode pseudonym).
 */
export default function ThreadPanel({
  threadId,
  sourceType = 'email',
  initialExpanded = true,
  onToggle
}: ThreadPanelProps): JSX.Element | null {
  const [expanded, setExpanded] = useState<boolean>(initialExpanded)
  const [emailResult, setEmailResult] = useState<EmailThreadResult | null>(null)
  const [waMessages, setWaMessages] = useState<WhatsAppMessage[] | null>(null)
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  // Panel body has a fixed height when expanded — the triangle arrow
  // in the header is the only affordance. We tried a drag handle but
  // it got stuck when released over the email iframe (sandbox swallows
  // mouseup), so the feature was removed.
  const BODY_HEIGHT = "45vh"

  // Keep local expanded in sync when the parent swaps to a conversation
  // with a different default (e.g. going from a task to general).
  useEffect(() => {
    setExpanded(initialExpanded)
  }, [initialExpanded, threadId])

  useEffect(() => {
    if (!threadId) {
      setEmailResult(null)
      setWaMessages(null)
      setError(null)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    setEmailResult(null)
    setWaMessages(null)

    const fetchPromise =
      sourceType === 'whatsapp'
        ? window.zylch.whatsapp
            .listMessages({ chat_jid: threadId, limit: 200 })
            .then((r) => {
              if (cancelled) return
              if (r.error) {
                setError(r.error)
                return
              }
              setWaMessages(r.messages ?? [])
            })
        : window.zylch.emails
            .listByThread(threadId)
            .then((r) => {
              if (cancelled) return
              setEmailResult(r)
            })

    fetchPromise
      .catch((e: unknown) => {
        if (cancelled) return
        if (isProfileLockedError(e)) {
          setError(null)
        } else {
          setError(errorMessage(e))
        }
      })
      .finally(() => {
        if (cancelled) return
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [threadId, sourceType])

  if (!threadId) return null

  // Email branch — newest-first, mirrors the legacy behaviour.
  const emailsAsc: ThreadEmail[] = emailResult?.emails ?? []
  const emails: ThreadEmail[] = emailsAsc.slice().reverse()
  const emailSubject = emailsAsc[0]?.subject || '(no subject)'

  // WhatsApp branch — newest-first as well, matching the email side so
  // the most recent message is what the user sees first when the panel
  // opens.
  const waAsc: WhatsAppMessage[] = waMessages ?? []
  const waNewestFirst: WhatsAppMessage[] = waAsc.slice().reverse()

  // Header subtitle: WA shows the chat identifier (resolved phone if
  // the jid is `@s.whatsapp.net`, else the LID), email shows the
  // subject of the most recent message.
  const headerSubtitle = (() => {
    if (sourceType === 'whatsapp') {
      if (threadId.endsWith('@s.whatsapp.net')) {
        return '+' + threadId.split('@', 1)[0]
      }
      return threadId
    }
    return emailSubject
  })()

  const count = sourceType === 'whatsapp' ? waNewestFirst.length : emails.length

  const handleToggle = (): void => {
    const next = !expanded
    setExpanded(next)
    onToggle?.(next)
  }

  const label = (() => {
    if (loading) return 'Source (loading…)'
    if (error) return 'Source (error)'
    const plural = count === 1 ? '' : 's'
    if (sourceType === 'whatsapp') {
      return `Source — ${count} WhatsApp message${plural}`
    }
    return `Source - ${count} message${plural}`
  })()

  const arrow = expanded ? '▲' : '▼'

  return (
    <div className="border-b bg-brand-light-grey">
      <button
        onClick={handleToggle}
        className="w-full flex items-center justify-between px-4 py-2 text-sm text-brand-grey-80 hover:bg-brand-light-grey"
        aria-expanded={expanded}
      >
        <span className="font-medium truncate">
          {arrow} {label}
        </span>
        {expanded && headerSubtitle && !loading && !error && (
          <span className="text-xs text-brand-grey-80 truncate ml-3">{headerSubtitle}</span>
        )}
      </button>

      {expanded && (
        <div
          className="border-t relative"
          style={{ height: BODY_HEIGHT }}
        >
          <div className="absolute inset-0 overflow-y-auto">
          {loading && (
            <div className="p-4 text-brand-grey-80 text-sm">Loading thread...</div>
          )}
          {error && (
            <div className="p-4 text-brand-danger text-sm">Failed to load: {error}</div>
          )}
          {!loading && !error && sourceType === 'email' && emails.length === 0 && (
            <div className="p-4 text-brand-grey-80 text-sm">No messages in this thread.</div>
          )}
          {!loading && !error && sourceType === 'whatsapp' && waNewestFirst.length === 0 && (
            <div className="p-4 text-brand-grey-80 text-sm">
              No WhatsApp messages stored locally for this chat.
            </div>
          )}
          {!loading && !error && sourceType === 'email' && emails.length > 0 && (
            <div className="p-3 space-y-2">
              {emails.map((e) => (
                <article
                  key={e.id}
                  className={
                    'bg-white border rounded-lg p-3 shadow-sm ' +
                    (e.is_user_sent ? 'border-l-4 border-l-brand-blue' : '')
                  }
                >
                  <div className="flex items-start justify-between gap-3 mb-1">
                    <div className="text-sm text-brand-black min-w-0 break-words">
                      {e.is_user_sent && (
                        <span className="inline-block text-xs px-2 py-0.5 mr-2 rounded bg-brand-blue/10 text-brand-blue border border-brand-blue/30">
                          You &rarr;
                        </span>
                      )}
                      {e.is_auto_reply && (
                        <span className="inline-block text-xs px-2 py-0.5 mr-2 rounded bg-brand-light-grey text-brand-grey-80 border border-brand-mid-grey">
                          auto
                        </span>
                      )}
                      <span className="font-medium">
                        {e.from_name ? `${e.from_name} ` : ''}
                        <span className="text-brand-grey-80">&lt;{e.from_email}&gt;</span>
                      </span>
                    </div>
                    <div className="text-xs text-brand-grey-80 whitespace-nowrap">
                      {formatDate(e.date)}
                    </div>
                  </div>
                  <div className="text-xs text-brand-grey-80 mb-2 break-words">
                    <span>To: {e.to_email || '—'}</span>
                    {e.cc_email && <span> &middot; Cc: {e.cc_email}</span>}
                  </div>
                  {e.body_html ? (
                    <HtmlEmailBody html={e.body_html} />
                  ) : (
                    <pre className="text-sm text-brand-black whitespace-pre-wrap break-words font-sans select-text m-0">
                      {e.body_plain}
                    </pre>
                  )}
                  {(e.has_attachments || e.attachment_filenames.length > 0) && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {e.attachment_filenames.length > 0
                        ? e.attachment_filenames.map((name, i) => (
                            <span
                              key={i}
                              className="text-xs px-2 py-0.5 rounded border border-brand-mid-grey bg-brand-light-grey text-brand-grey-80"
                            >
                              &#128206; {name}
                            </span>
                          ))
                        : (
                            <span className="text-xs px-2 py-0.5 rounded border border-brand-mid-grey bg-brand-light-grey text-brand-grey-80">
                              &#128206; attachment
                            </span>
                          )}
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}
          {!loading && !error && sourceType === 'whatsapp' && waNewestFirst.length > 0 && (
            <div className="p-3 space-y-2">
              {waNewestFirst.map((m) => (
                <article
                  key={m.id}
                  className={
                    'max-w-[80%] border rounded-lg p-2.5 shadow-sm ' +
                    (m.is_from_me
                      ? 'ml-auto bg-brand-blue/10 border-brand-blue/30'
                      : 'mr-auto bg-white')
                  }
                >
                  <div className="flex items-baseline justify-between gap-3 mb-1">
                    <div className="text-xs text-brand-grey-80 min-w-0 break-words">
                      {m.is_from_me ? (
                        <span className="font-medium text-brand-blue">You</span>
                      ) : (
                        <span className="font-medium">
                          {m.sender_name || m.sender_jid}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-brand-grey-80 whitespace-nowrap">
                      {m.timestamp ? formatDate(m.timestamp) : ''}
                    </div>
                  </div>
                  {m.text ? (
                    <pre className="text-sm text-brand-black whitespace-pre-wrap break-words font-sans select-text m-0">
                      {m.text}
                    </pre>
                  ) : (
                    <span className="text-xs italic text-brand-grey-80">
                      {m.media_type ? `[${m.media_type}]` : '[no text]'}
                    </span>
                  )}
                </article>
              ))}
            </div>
          )}
          </div>
        </div>
      )}
    </div>
  )
}
