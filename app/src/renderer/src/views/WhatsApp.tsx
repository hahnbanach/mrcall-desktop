/**
 * WhatsApp tab — connection card + threads + reading pane.
 *
 * When the user is not connected we show ConnectWhatsApp full-width so
 * they can scan the QR. Once connected, the engine has stored the
 * history sync into whatsapp_messages and the renderer fetches threads
 * via `whatsapp.list_threads`. Click a thread → `whatsapp.list_messages`
 * fills the right pane.
 *
 * Send-message UI is deliberately not here yet — read-only view first.
 */
import { useEffect, useState } from 'react'
import type { WhatsAppMessage, WhatsAppThread } from '../types'
import { errorMessage } from '../lib/errors'
import { formatAbsolute, formatRelative } from '../lib/dates'
import ConnectWhatsApp from './ConnectWhatsApp'

export default function WhatsAppView(): JSX.Element {
  const [connected, setConnected] = useState<boolean | null>(null)
  const [threads, setThreads] = useState<WhatsAppThread[]>([])
  const [threadsLoading, setThreadsLoading] = useState(false)
  const [threadsError, setThreadsError] = useState<string | null>(null)
  const [activeJid, setActiveJid] = useState<string | null>(null)
  const [messages, setMessages] = useState<WhatsAppMessage[]>([])
  const [messagesLoading, setMessagesLoading] = useState(false)
  const [messagesError, setMessagesError] = useState<string | null>(null)

  // Resolve connected state on mount (cheap status RPC). Threads are
  // loaded only once we know the engine has a chance of returning data.
  useEffect(() => {
    let cancelled = false
    window.zylch.whatsapp
      .status()
      .then((r) => {
        if (cancelled) return
        setConnected(r.connected || r.has_session)
      })
      .catch(() => {
        if (!cancelled) setConnected(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const loadThreads = async (): Promise<void> => {
    setThreadsLoading(true)
    setThreadsError(null)
    try {
      const r = await window.zylch.whatsapp.listThreads()
      if (r.error) {
        setThreadsError(r.error)
        setThreads([])
      } else {
        setThreads(r.threads)
      }
    } catch (e) {
      setThreadsError(errorMessage(e))
      setThreads([])
    } finally {
      setThreadsLoading(false)
    }
  }

  // Load threads once we think the user has data (connected OR has a
  // local session DB even if currently offline). list_threads reads
  // SQLite, doesn't require a live socket.
  useEffect(() => {
    if (connected) {
      void loadThreads()
    }
  }, [connected])

  // Load messages whenever the active thread changes.
  useEffect(() => {
    if (!activeJid) {
      setMessages([])
      return
    }
    let cancelled = false
    setMessagesLoading(true)
    setMessagesError(null)
    window.zylch.whatsapp
      .listMessages({ chat_jid: activeJid, limit: 200 })
      .then((r) => {
        if (cancelled) return
        if (r.error) {
          setMessagesError(r.error)
          setMessages([])
        } else {
          setMessages(r.messages)
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setMessagesError(errorMessage(e))
          setMessages([])
        }
      })
      .finally(() => {
        if (!cancelled) setMessagesLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [activeJid])

  // Pre-connect or no-session: full-width connect card.
  if (connected === null) {
    return (
      <div className="p-6 max-w-3xl mx-auto">
        <h1 className="text-2xl font-semibold mb-2">WhatsApp</h1>
        <div className="text-sm text-brand-grey-80">Loading…</div>
      </div>
    )
  }
  if (!connected) {
    return (
      <div className="p-6 max-w-3xl mx-auto">
        <h1 className="text-2xl font-semibold mb-2">WhatsApp</h1>
        <p className="text-sm text-brand-grey-80 mb-6">
          Local WhatsApp connection via the Linked Devices flow. Messages and contacts stay on
          this machine — nothing routes through a third-party server.
        </p>
        <ConnectWhatsApp />
      </div>
    )
  }

  const activeThread = threads.find((t) => t.jid === activeJid) || null

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between border-b border-brand-mid-grey/60 px-4 py-2 gap-3">
        <h1 className="text-lg font-semibold">WhatsApp</h1>
        <button
          onClick={() => void loadThreads()}
          className="px-3 py-1 text-xs border border-brand-mid-grey rounded hover:bg-brand-light-grey"
        >
          Refresh
        </button>
      </div>
      <div className="flex flex-1 min-h-0">
        {/* Thread list */}
        <aside className="w-[320px] shrink-0 border-r border-brand-mid-grey/60 overflow-y-auto">
          {threadsLoading && (
            <div className="p-3 text-xs text-brand-grey-80">Loading threads…</div>
          )}
          {threadsError && (
            <div className="p-3 text-xs text-brand-danger whitespace-pre-wrap">
              {threadsError}
            </div>
          )}
          {!threadsLoading && !threadsError && threads.length === 0 && (
            <div className="p-3 text-xs text-brand-grey-80 space-y-2">
              <p>
                No conversations yet. WhatsApp&apos;s protocol only pushes the full history on
                the <strong>first</strong> link — for already-paired devices it sends only new
                live messages going forward.
              </p>
              <p>To pull historical chats, re-link with a fresh QR scan:</p>
              <button
                onClick={async () => {
                  try {
                    await window.zylch.whatsapp.disconnect(true)
                    setConnected(false)
                  } catch (e) {
                    setThreadsError(errorMessage(e))
                  }
                }}
                className="px-2 py-1 text-xs border border-brand-mid-grey rounded hover:bg-brand-light-grey"
              >
                Forget device and re-link
              </button>
              <p className="opacity-80">
                Or just wait — any new message you send or receive will appear here automatically.
              </p>
            </div>
          )}
          {threads.map((t) => {
            // Fallback chain: contact display name → resolved phone
            // (from WhatsAppContact.phone_number or stripped JID) →
            // raw JID → "Unknown contact". Last branch covers rows
            // where everything came back null/empty (rare — usually
            // broadcast / system messages we already filter on the
            // engine side).
            const label = t.name || t.phone || t.jid || 'Unknown contact'
            const isActive = t.jid === activeJid
            const previewText = t.last_preview
              ? (t.last_from_me ? 'You: ' : '') + t.last_preview
              : `${t.message_count} message${t.message_count === 1 ? '' : 's'}`
            return (
              <button
                key={t.jid}
                onClick={() => setActiveJid(t.jid)}
                className={
                  'w-full text-left px-3 py-2 border-b border-brand-mid-grey/40 ' +
                  (isActive
                    ? 'bg-brand-blue/10'
                    : 'bg-white hover:bg-brand-light-grey')
                }
              >
                <div className="flex items-baseline justify-between gap-2">
                  <div className="text-sm font-medium text-brand-black truncate">
                    {label}
                    {t.is_group && (
                      <span className="ml-1 text-[10px] uppercase text-brand-grey-80">
                        group
                      </span>
                    )}
                  </div>
                  {t.last_at && (
                    <div
                      className="text-[11px] text-brand-grey-80 shrink-0"
                      title={formatAbsolute(t.last_at)}
                    >
                      {formatRelative(t.last_at)}
                    </div>
                  )}
                </div>
                <div className="text-xs text-brand-grey-80 truncate mt-0.5">
                  {previewText}
                </div>
              </button>
            )
          })}
        </aside>

        {/* Reading pane */}
        <main className="flex-1 min-w-0 overflow-y-auto bg-brand-light-grey">
          {!activeThread ? (
            <div className="h-full flex items-center justify-center text-sm text-brand-grey-80">
              Select a conversation on the left.
            </div>
          ) : (
            <div className="flex flex-col h-full">
              <header className="px-4 py-2 border-b border-brand-mid-grey/60 bg-white">
                <div className="text-sm font-semibold">
                  {activeThread.name || activeThread.phone || activeThread.jid}
                </div>
                {activeThread.phone && activeThread.name && (
                  <div className="text-xs text-brand-grey-80">+{activeThread.phone}</div>
                )}
              </header>
              <div className="flex-1 overflow-y-auto p-4 space-y-2">
                {messagesLoading && (
                  <div className="text-xs text-brand-grey-80">Loading messages…</div>
                )}
                {messagesError && (
                  <div className="text-xs text-brand-danger whitespace-pre-wrap">
                    {messagesError}
                  </div>
                )}
                {!messagesLoading && !messagesError && messages.length === 0 && (
                  <div className="text-xs text-brand-grey-80">No messages in this thread.</div>
                )}
                {messages.map((m) => (
                  <div
                    key={m.id}
                    className={
                      'flex ' + (m.is_from_me ? 'justify-end' : 'justify-start')
                    }
                  >
                    <div
                      className={
                        'max-w-[70%] rounded-lg px-3 py-1.5 shadow-sm ' +
                        (m.is_from_me
                          ? 'bg-brand-blue/15 border border-brand-blue/30'
                          : 'bg-white border border-brand-mid-grey/60')
                      }
                    >
                      {!m.is_from_me && activeThread.is_group && m.sender_name && (
                        <div className="text-[11px] font-medium text-brand-blue">
                          {m.sender_name}
                        </div>
                      )}
                      {m.text ? (
                        <div className="text-sm text-brand-black whitespace-pre-wrap">
                          {m.text}
                        </div>
                      ) : m.media_type ? (
                        <div className="text-sm italic text-brand-grey-80">
                          [{m.media_type}]
                        </div>
                      ) : (
                        <div className="text-sm italic text-brand-grey-80">[empty]</div>
                      )}
                      <div
                        className="text-[10px] text-brand-grey-80 mt-0.5"
                        title={formatAbsolute(m.timestamp)}
                      >
                        {formatRelative(m.timestamp)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
