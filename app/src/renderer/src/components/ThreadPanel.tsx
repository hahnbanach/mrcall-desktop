import { useEffect, useMemo, useState } from 'react'
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
  /**
   * Email thread id (RFC 2822 message-id cluster). Populated for any
   * task whose `sources.emails` is non-empty.
   */
  emailThreadId?: string | null
  /**
   * WhatsApp `chat_jid` (`<digits>@s.whatsapp.net` or `<digits>@lid`).
   * Populated for any task whose `sources.whatsapp_messages` is
   * non-empty — the engine stamps `sources.whatsapp_chat_jid` on the
   * first WA touchpoint.
   */
  whatsappChatJid?: string | null
  initialExpanded?: boolean
  /**
   * Called whenever the user toggles the panel. The parent can persist
   * the open/closed state per-conversation.
   */
  onToggle?: (expanded: boolean) => void
}

/**
 * ThreadPanel — collapsible "Source" panel shown at the top of the
 * Workspace view. Renders the conversation source(s) tied to the
 * active task.
 *
 * Three modes, picked automatically from which props are populated:
 *
 * - **Email only** (`emailThreadId` set, `whatsappChatJid` null):
 *   fetches via `emails.listByThread` and renders email articles
 *   newest-first (HTML body in sandboxed iframe, attachments,
 *   "You →" badge). The legacy behaviour.
 *
 * - **WhatsApp only** (`whatsappChatJid` set, `emailThreadId` null):
 *   fetches via `whatsapp.listMessages({ chat_jid })` and renders
 *   chat bubbles aligned right (user) / left (contact).
 *
 * - **Cross-channel** (BOTH set): header carries an Email/WhatsApp
 *   toggle. Body switches between the two views. Default tab is
 *   WhatsApp — the assumption is that the WA touchpoint is more
 *   recent than the email cluster on a cross-channel match
 *   (whatsapp-pipeline-parity Fase 4 typical case: an email task
 *   gained a WA message via F7 cross-channel blob match). Mario can
 *   click Email to swap.
 */
export default function ThreadPanel({
  emailThreadId,
  whatsappChatJid,
  initialExpanded = true,
  onToggle
}: ThreadPanelProps): JSX.Element | null {
  const [expanded, setExpanded] = useState<boolean>(initialExpanded)
  const [emailResult, setEmailResult] = useState<EmailThreadResult | null>(null)
  const [waMessages, setWaMessages] = useState<WhatsAppMessage[] | null>(null)
  const [loadingEmail, setLoadingEmail] = useState<boolean>(false)
  const [loadingWa, setLoadingWa] = useState<boolean>(false)
  const [errorEmail, setErrorEmail] = useState<string | null>(null)
  const [errorWa, setErrorWa] = useState<string | null>(null)
  // Panel body has a fixed height when expanded — the triangle arrow
  // in the header is the only affordance. We tried a drag handle but
  // it got stuck when released over the email iframe (sandbox swallows
  // mouseup), so the feature was removed.
  const BODY_HEIGHT = '45vh'

  const hasEmail = !!emailThreadId
  const hasWa = !!whatsappChatJid
  const crossChannel = hasEmail && hasWa

  // Active tab — only meaningful when cross-channel. Default to
  // WhatsApp because in the typical cross-channel match (email task
  // gains WA touchpoint via F7), the WA event is the more recent one
  // and what the user just clicked to read.
  const [activeTab, setActiveTab] = useState<ThreadSourceType>(
    hasWa ? 'whatsapp' : 'email'
  )

  // When the conversation underneath us changes, snap activeTab back
  // to the right default — preserving the user's manual toggle inside
  // a single conversation but not across switches.
  useEffect(() => {
    setActiveTab(hasWa ? 'whatsapp' : 'email')
  }, [emailThreadId, whatsappChatJid, hasWa])

  // Keep local expanded in sync when the parent swaps to a conversation
  // with a different default (e.g. going from a task to general).
  useEffect(() => {
    setExpanded(initialExpanded)
  }, [initialExpanded, emailThreadId, whatsappChatJid])

  // Fetch email thread when emailThreadId is populated.
  useEffect(() => {
    if (!emailThreadId) {
      setEmailResult(null)
      setErrorEmail(null)
      setLoadingEmail(false)
      return
    }
    let cancelled = false
    setLoadingEmail(true)
    setErrorEmail(null)
    setEmailResult(null)
    window.zylch.emails
      .listByThread(emailThreadId)
      .then((r) => {
        if (cancelled) return
        setEmailResult(r)
      })
      .catch((e: unknown) => {
        if (cancelled) return
        if (isProfileLockedError(e)) {
          setErrorEmail(null)
        } else {
          setErrorEmail(errorMessage(e))
        }
      })
      .finally(() => {
        if (cancelled) return
        setLoadingEmail(false)
      })
    return () => {
      cancelled = true
    }
  }, [emailThreadId])

  // Fetch WA chat when whatsappChatJid is populated.
  useEffect(() => {
    if (!whatsappChatJid) {
      setWaMessages(null)
      setErrorWa(null)
      setLoadingWa(false)
      return
    }
    let cancelled = false
    setLoadingWa(true)
    setErrorWa(null)
    setWaMessages(null)
    window.zylch.whatsapp
      .listMessages({ chat_jid: whatsappChatJid, limit: 200 })
      .then((r) => {
        if (cancelled) return
        if (r.error) {
          setErrorWa(r.error)
          return
        }
        setWaMessages(r.messages ?? [])
      })
      .catch((e: unknown) => {
        if (cancelled) return
        if (isProfileLockedError(e)) {
          setErrorWa(null)
        } else {
          setErrorWa(errorMessage(e))
        }
      })
      .finally(() => {
        if (cancelled) return
        setLoadingWa(false)
      })
    return () => {
      cancelled = true
    }
  }, [whatsappChatJid])

  // Newest-first ordering for both branches.
  const emails: ThreadEmail[] = useMemo(() => {
    const asc = emailResult?.emails ?? []
    return asc.slice().reverse()
  }, [emailResult])
  const waNewestFirst: WhatsAppMessage[] = useMemo(() => {
    const asc = waMessages ?? []
    return asc.slice().reverse()
  }, [waMessages])

  if (!hasEmail && !hasWa) return null

  const emailSubject = emailResult?.emails?.[0]?.subject || '(no subject)'
  const waSubtitle = (() => {
    if (!whatsappChatJid) return ''
    if (whatsappChatJid.endsWith('@s.whatsapp.net')) {
      return '+' + whatsappChatJid.split('@', 1)[0]
    }
    return whatsappChatJid
  })()

  const emailCount = emails.length
  const waCount = waNewestFirst.length

  // Resolve display fields for the active tab.
  const showEmail = activeTab === 'email' || !hasWa
  const showWa = activeTab === 'whatsapp' || !hasEmail
  const loading = showEmail ? loadingEmail : loadingWa
  const error = showEmail ? errorEmail : errorWa
  const headerSubtitle = showEmail ? emailSubject : waSubtitle
  const activeCount = showEmail ? emailCount : waCount

  const handleToggle = (): void => {
    const next = !expanded
    setExpanded(next)
    onToggle?.(next)
  }

  const label = (() => {
    if (loading) return 'Source (loading…)'
    if (error) return 'Source (error)'
    const plural = activeCount === 1 ? '' : 's'
    if (showWa) return `Source — ${activeCount} WhatsApp message${plural}`
    return `Source - ${activeCount} message${plural}`
  })()

  const arrow = expanded ? '▲' : '▼'

  // Render a tab pill — small, low-key, clearly clickable. Highlight
  // active. Only used when cross-channel.
  const TabPill = ({
    label: pillLabel,
    active,
    onClick
  }: {
    label: string
    active: boolean
    onClick: () => void
  }): JSX.Element => (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation()
        onClick()
      }}
      className={
        'text-xs px-2 py-0.5 rounded border transition-colors ' +
        (active
          ? 'bg-brand-blue text-white border-brand-blue'
          : 'bg-white text-brand-grey-80 border-brand-mid-grey hover:bg-brand-light-grey')
      }
    >
      {pillLabel}
    </button>
  )

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
        <span className="flex items-center gap-2 ml-3 min-w-0">
          {crossChannel && expanded && (
            <span className="flex items-center gap-1 shrink-0">
              <TabPill
                label={`Email (${emailCount})`}
                active={activeTab === 'email'}
                onClick={() => setActiveTab('email')}
              />
              <TabPill
                label={`WhatsApp (${waCount})`}
                active={activeTab === 'whatsapp'}
                onClick={() => setActiveTab('whatsapp')}
              />
            </span>
          )}
          {expanded && headerSubtitle && !loading && !error && (
            <span className="text-xs text-brand-grey-80 truncate">{headerSubtitle}</span>
          )}
        </span>
      </button>

      {expanded && (
        <div className="border-t relative" style={{ height: BODY_HEIGHT }}>
          <div className="absolute inset-0 overflow-y-auto">
            {loading && (
              <div className="p-4 text-brand-grey-80 text-sm">Loading thread...</div>
            )}
            {error && (
              <div className="p-4 text-brand-danger text-sm">Failed to load: {error}</div>
            )}
            {!loading && !error && showEmail && emails.length === 0 && (
              <div className="p-4 text-brand-grey-80 text-sm">
                No messages in this thread.
              </div>
            )}
            {!loading && !error && showWa && waNewestFirst.length === 0 && (
              <div className="p-4 text-brand-grey-80 text-sm">
                No WhatsApp messages stored locally for this chat.
              </div>
            )}
            {!loading && !error && showEmail && emails.length > 0 && (
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
            {!loading && !error && showWa && waNewestFirst.length > 0 && (
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
