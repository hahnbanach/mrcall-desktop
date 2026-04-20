import { useEffect, useState } from 'react'
import type { EmailThreadResult, ThreadEmail } from '../types'
import { errorMessage, isProfileLockedError } from '../lib/errors'
import HtmlEmailBody from './HtmlEmailBody'

function formatDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleString('it-IT')
}

export type ThreadSourceType = 'email' // future: 'whatsapp' | ...

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
 * Workspace view. Fetches the email thread for `threadId` via
 * `emails.listByThread` and renders it in reverse-chronological order
 * (newest first), mirroring what the old Email tab used to show.
 *
 * sourceType is a forward hook: for now only 'email' is implemented,
 * but the rendering switch is isolated here so a future WhatsApp
 * source can slot in without changing Workspace.tsx.
 */
export default function ThreadPanel({
  threadId,
  sourceType = 'email',
  initialExpanded = true,
  onToggle
}: ThreadPanelProps): JSX.Element | null {
  const [expanded, setExpanded] = useState<boolean>(initialExpanded)
  const [result, setResult] = useState<EmailThreadResult | null>(null)
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
    if (!threadId || sourceType !== 'email') {
      setResult(null)
      setError(null)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    setResult(null)
    window.zylch.emails
      .listByThread(threadId)
      .then((r) => {
        if (cancelled) return
        setResult(r)
      })
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

  const emailsAsc: ThreadEmail[] = result?.emails ?? []
  const emails: ThreadEmail[] = emailsAsc.slice().reverse()
  const subject = emailsAsc[0]?.subject || '(no subject)'
  const count = emails.length

  const handleToggle = (): void => {
    const next = !expanded
    setExpanded(next)
    onToggle?.(next)
  }

  const label = (() => {
    if (loading) return 'Source (loading...)'
    if (error) return 'Source (error)'
    if (sourceType === 'email') {
      return expanded
        ? `Source - ${count} ${count === 1 ? 'message' : 'messages'}`
        : `Source - ${count} ${count === 1 ? 'message' : 'messages'}`
    }
    return 'Source'
  })()

  const arrow = expanded ? '\u25B2' : '\u25BC'

  return (
    <div className="border-b bg-slate-50">
      <button
        onClick={handleToggle}
        className="w-full flex items-center justify-between px-4 py-2 text-sm text-slate-700 hover:bg-slate-100"
        aria-expanded={expanded}
      >
        <span className="font-medium truncate">
          {arrow} {label}
        </span>
        {expanded && subject && !loading && !error && (
          <span className="text-xs text-slate-500 truncate ml-3">{subject}</span>
        )}
      </button>

      {expanded && (
        <div
          className="border-t relative"
          style={{ height: BODY_HEIGHT }}
        >
          <div className="absolute inset-0 overflow-y-auto">
          {loading && (
            <div className="p-4 text-slate-500 text-sm">Loading thread...</div>
          )}
          {error && (
            <div className="p-4 text-red-700 text-sm">Failed to load: {error}</div>
          )}
          {!loading && !error && emails.length === 0 && (
            <div className="p-4 text-slate-500 text-sm">No messages in this thread.</div>
          )}
          {!loading && !error && emails.length > 0 && sourceType === 'email' && (
            <div className="p-3 space-y-2">
              {emails.map((e) => (
                <article
                  key={e.id}
                  className={
                    'bg-white border rounded-lg p-3 shadow-sm ' +
                    (e.is_user_sent ? 'border-l-4 border-l-green-500' : '')
                  }
                >
                  <div className="flex items-start justify-between gap-3 mb-1">
                    <div className="text-sm text-slate-900 min-w-0 break-words">
                      {e.is_user_sent && (
                        <span className="inline-block text-xs px-2 py-0.5 mr-2 rounded bg-green-100 text-green-800 border border-green-300">
                          You &rarr;
                        </span>
                      )}
                      {e.is_auto_reply && (
                        <span className="inline-block text-xs px-2 py-0.5 mr-2 rounded bg-slate-100 text-slate-600 border border-slate-300">
                          auto
                        </span>
                      )}
                      <span className="font-medium">
                        {e.from_name ? `${e.from_name} ` : ''}
                        <span className="text-slate-500">&lt;{e.from_email}&gt;</span>
                      </span>
                    </div>
                    <div className="text-xs text-slate-500 whitespace-nowrap">
                      {formatDate(e.date)}
                    </div>
                  </div>
                  <div className="text-xs text-slate-500 mb-2 break-words">
                    <span>To: {e.to_email || '\u2014'}</span>
                    {e.cc_email && <span> &middot; Cc: {e.cc_email}</span>}
                  </div>
                  {e.body_html ? (
                    <HtmlEmailBody html={e.body_html} />
                  ) : (
                    <pre className="text-sm text-slate-900 whitespace-pre-wrap break-words font-sans select-text m-0">
                      {e.body_plain}
                    </pre>
                  )}
                  {(e.has_attachments || e.attachment_filenames.length > 0) && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {e.attachment_filenames.length > 0
                        ? e.attachment_filenames.map((name, i) => (
                            <span
                              key={i}
                              className="text-xs px-2 py-0.5 rounded border border-slate-300 bg-slate-50 text-slate-700"
                            >
                              &#128206; {name}
                            </span>
                          ))
                        : (
                            <span className="text-xs px-2 py-0.5 rounded border border-slate-300 bg-slate-50 text-slate-700">
                              &#128206; attachment
                            </span>
                          )}
                    </div>
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
