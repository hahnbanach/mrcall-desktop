/**
 * WhatsApp tab — connection card + threads + reading pane + composer.
 *
 * When the user is not connected we show ConnectWhatsApp full-width so
 * they can scan the QR. Once connected, the engine has stored the
 * history sync into whatsapp_messages and the renderer fetches threads
 * via `whatsapp.list_threads`. Click a thread → `whatsapp.list_messages`
 * fills the right pane.
 *
 * Search: the box atop the thread list calls `whatsapp.search_messages`
 * (message text / transcription / sender + contact name / phone) and
 * swaps the thread list for the matches; Esc / clear restores the list.
 *
 * Send: the composer at the bottom of the reading pane calls
 * `whatsapp.send_message` over the live connection. The returned message
 * is appended optimistically (no full reload).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { WhatsAppMessage, WhatsAppThread } from '../types'
import { errorMessage } from '../lib/errors'
import { formatAbsolute, formatRelative } from '../lib/dates'
import ConnectWhatsApp from './ConnectWhatsApp'

export default function WhatsAppView(): JSX.Element {
  const [connected, setConnected] = useState<boolean | null>(null)
  const [threads, setThreads] = useState<WhatsAppThread[]>([])
  const [threadsLoading, setThreadsLoading] = useState(false)
  const [threadsError, setThreadsError] = useState<string | null>(null)
  // Diagnostic from the engine: total messages stored for this owner_id
  // and the owner_id itself. Surfaced in the empty state so the user
  // can tell "0 messages stored" from "messages stored but all
  // filtered out as broadcast".
  const [debugInfo, setDebugInfo] = useState<{
    totalMessages: number
    ownerId: string | null
    breakdown: Record<string, number> | null
  } | null>(null)
  const [activeJid, setActiveJid] = useState<string | null>(null)
  const [messages, setMessages] = useState<WhatsAppMessage[]>([])
  const [messagesLoading, setMessagesLoading] = useState(false)
  const [messagesError, setMessagesError] = useState<string | null>(null)

  // Search state. `searchResults === null` means "not searching" → show
  // the full thread list; an array (possibly empty) means we're showing
  // matches for `searchInput`.
  const [searchInput, setSearchInput] = useState('')
  const [searchResults, setSearchResults] = useState<WhatsAppThread[] | null>(null)
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)

  // Composer state.
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)

  // Scroll the message pane to the bottom whenever the message list
  // changes (thread open + after sending).
  const messagesScrollRef = useRef<HTMLDivElement>(null)

  // Resolve connected state on mount (cheap status RPC). Threads are
  // rendered ONLY when the WA socket is actually live — having a
  // session DB on disk is not enough. Otherwise the chat list would
  // stay visible after a Disconnect (or before auto-reconnect
  // completes), and anyone glancing at the screen would see the
  // last-known thread/contact list even though we're offline. The
  // SQLite rows are kept on disk; the renderer just refuses to draw
  // them until the socket is back up.
  useEffect(() => {
    let cancelled = false
    let intervalId: ReturnType<typeof setInterval> | null = null

    const poll = async (): Promise<void> => {
      try {
        const r = await window.zylch.whatsapp.status()
        if (cancelled) return
        setConnected(Boolean(r.connected))
        // Once we are live, stop polling — the live socket will keep
        // pushing MessageEv, no further status checks needed. If the
        // socket later drops, the user re-mounts the tab (or hits
        // Refresh on the connect card) and we resume polling.
        if (r.connected && intervalId !== null) {
          clearInterval(intervalId)
          intervalId = null
        }
      } catch {
        if (!cancelled) setConnected(false)
      }
    }

    void poll()
    // Poll every 3 s while we are still off-socket so the auto-reconnect
    // (or a manual click on Reconnect from the card) flips the UI to
    // the live thread list without forcing the user to switch tabs.
    intervalId = setInterval(() => {
      void poll()
    }, 3000)

    return () => {
      cancelled = true
      if (intervalId !== null) clearInterval(intervalId)
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
      setDebugInfo({
        totalMessages: r.total_messages ?? 0,
        ownerId: r.owner_id ?? null,
        breakdown: r.breakdown_by_server ?? null
      })
    } catch (e) {
      setThreadsError(errorMessage(e))
      setThreads([])
      setDebugInfo(null)
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

  // Re-fetch messages for the currently active chat. Used both when
  // the user switches chats AND when a `whatsapp.threads.changed`
  // notification fires for a chat already open (background message
  // arrival while the user has the chat in view).
  const reloadActiveMessages = useCallback(
    (jid: string): (() => void) => {
      let cancelled = false
      setMessagesLoading(true)
      setMessagesError(null)
      window.zylch.whatsapp
        .listMessages({ chat_jid: jid, limit: 200 })
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
    },
    []
  )

  // Load messages whenever the active thread changes.
  useEffect(() => {
    // Switching chats clears any half-typed draft + stale send error.
    setDraft('')
    setSendError(null)
    if (!activeJid) {
      setMessages([])
      return
    }
    const cancel = reloadActiveMessages(activeJid)
    return cancel
  }, [activeJid, reloadActiveMessages])

  // Live thread-list refresh — the engine emits `whatsapp.threads.changed`
  // after every new message (history-sync batch OR live MessageEv).
  // Without this, the list shows the state at first connect and never
  // updates: a chat that received fresh messages keeps its old "Nd ago"
  // preview, which Mario reported as "messages from 4h ago labelled
  // 6d old". Debounce 600 ms — the history sync after a re-connect
  // delivers hundreds of events in a burst; we want ONE refresh after
  // the storm settles, not one per message.
  useEffect(() => {
    if (!connected) return
    let timer: ReturnType<typeof setTimeout> | null = null
    const off = window.zylch.onNotification('whatsapp.threads.changed', () => {
      if (timer !== null) clearTimeout(timer)
      timer = setTimeout(() => {
        timer = null
        void loadThreads()
        if (activeJid) {
          reloadActiveMessages(activeJid)
        }
      }, 600)
    })
    return () => {
      if (timer !== null) clearTimeout(timer)
      off()
    }
  }, [connected, activeJid, reloadActiveMessages])

  // Keep the message pane pinned to the bottom as messages arrive.
  useEffect(() => {
    const el = messagesScrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  const runSearch = async (): Promise<void> => {
    const q = searchInput.trim()
    if (!q) {
      setSearchResults(null)
      setSearchError(null)
      return
    }
    setSearchLoading(true)
    setSearchError(null)
    try {
      const r = await window.zylch.whatsapp.searchMessages({ query: q })
      if (r.error) {
        setSearchError(r.error)
        setSearchResults([])
      } else {
        setSearchResults(r.threads)
      }
    } catch (e) {
      setSearchError(errorMessage(e))
      setSearchResults([])
    } finally {
      setSearchLoading(false)
    }
  }

  const clearSearch = (): void => {
    setSearchInput('')
    setSearchResults(null)
    setSearchError(null)
  }

  const handleSend = async (): Promise<void> => {
    const text = draft.trim()
    if (!text || !activeJid || sending) return
    setSending(true)
    setSendError(null)
    try {
      const r = await window.zylch.whatsapp.sendMessage({ chat_jid: activeJid, text })
      if (!r.ok || !r.message) {
        setSendError(r.error || 'Invio fallito')
        return
      }
      const sent = r.message
      setMessages((prev) => [...prev, sent])
      setDraft('')
      // Reflect the send in the canonical thread list: update the preview,
      // mark outbound, bump to the top by last_at. (Search results are a
      // transient view; leave them untouched.)
      setThreads((prev) => {
        const next = prev.map((t) =>
          t.jid === activeJid
            ? {
                ...t,
                last_preview: text,
                last_from_me: true,
                last_at: sent.timestamp,
                message_count: t.message_count + 1
              }
            : t
        )
        next.sort((a, b) => (b.last_at || '').localeCompare(a.last_at || ''))
        return next
      })
    } catch (e) {
      setSendError(errorMessage(e))
    } finally {
      setSending(false)
    }
  }

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
    // Just the connect card — it carries its own h3 + description so a
    // wrapping h1 here would duplicate the heading text the user sees.
    return (
      <div className="p-6 max-w-3xl mx-auto">
        <ConnectWhatsApp />
      </div>
    )
  }

  const inSearch = searchResults !== null
  const displayThreads = searchResults ?? threads
  const activeThread = displayThreads.find((t) => t.jid === activeJid) || null

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between border-b border-brand-mid-grey/60 px-4 py-2 gap-3">
        <h1 className="text-lg font-semibold">WhatsApp</h1>
        <button
          onClick={() => {
            clearSearch()
            void loadThreads()
          }}
          className="px-3 py-1 text-xs border border-brand-mid-grey rounded hover:bg-brand-light-grey"
        >
          Refresh
        </button>
      </div>
      <div className="flex flex-1 min-h-0">
        {/* Thread list */}
        <aside className="w-[320px] shrink-0 border-r border-brand-mid-grey/60 flex flex-col">
          {/* Search box */}
          <div className="p-2 border-b border-brand-mid-grey/60 shrink-0">
            <div className="relative">
              <input
                type="text"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    void runSearch()
                  } else if (e.key === 'Escape') {
                    e.preventDefault()
                    clearSearch()
                  }
                }}
                placeholder="Cerca chat o messaggi…"
                className="w-full rounded border border-brand-mid-grey pl-3 pr-7 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand-blue"
              />
              {(searchInput || inSearch) && (
                <button
                  type="button"
                  title="Cancella ricerca"
                  onClick={clearSearch}
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 text-brand-grey-80 hover:text-brand-black leading-none text-base"
                >
                  ×
                </button>
              )}
            </div>
            {inSearch && (
              <div className="text-[11px] text-brand-grey-80 mt-1 px-0.5">
                {searchLoading
                  ? 'Ricerca…'
                  : `${displayThreads.length} risultat${
                      displayThreads.length === 1 ? 'o' : 'i'
                    } per «${searchInput.trim()}»`}
              </div>
            )}
          </div>

          <div className="flex-1 overflow-y-auto">
            {inSearch && searchError && (
              <div className="p-3 text-xs text-brand-danger whitespace-pre-wrap">{searchError}</div>
            )}
            {!inSearch && threadsLoading && (
              <div className="p-3 text-xs text-brand-grey-80">Loading threads…</div>
            )}
            {!inSearch && threadsError && (
              <div className="p-3 text-xs text-brand-danger whitespace-pre-wrap">{threadsError}</div>
            )}
            {inSearch && !searchLoading && !searchError && displayThreads.length === 0 && (
              <div className="p-3 text-xs text-brand-grey-80">
                Nessun risultato per «{searchInput.trim()}».
              </div>
            )}
            {!inSearch && !threadsLoading && !threadsError && threads.length === 0 && (
              <div className="p-3 text-xs text-brand-grey-80 space-y-2">
                {debugInfo && debugInfo.totalMessages > 0 ? (
                  <>
                    <p>
                      <strong>{debugInfo.totalMessages}</strong> message
                      {debugInfo.totalMessages === 1 ? '' : 's'} stored locally, but no displayable
                      conversations.
                    </p>
                    {debugInfo.breakdown && Object.keys(debugInfo.breakdown).length > 0 && (
                      <div className="rounded border border-brand-mid-grey/40 bg-white px-2 py-1.5">
                        <div className="text-[10px] uppercase tracking-wide text-brand-grey-80 mb-1">
                          breakdown by JID server
                        </div>
                        <ul className="space-y-0.5 font-mono text-[11px]">
                          {Object.entries(debugInfo.breakdown)
                            .sort((a, b) => b[1] - a[1])
                            .map(([server, count]) => (
                              <li key={server} className="flex justify-between gap-2">
                                <span>{server}</span>
                                <span className="opacity-70">{count}</span>
                              </li>
                            ))}
                        </ul>
                      </div>
                    )}
                    <p className="opacity-80">
                      WhatsApp&apos;s history sync delivers status updates first, then chat messages
                      over the next minutes (sometimes longer). Wait a bit, then click Refresh.
                      Send or receive a chat from your phone and it should appear here within
                      seconds.
                    </p>
                  </>
                ) : (
                  <>
                    <p>
                      No messages stored yet. WhatsApp&apos;s protocol only pushes the full history on
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
                      Or just wait — any new message you send or receive will appear here
                      automatically.
                    </p>
                  </>
                )}
                {debugInfo?.ownerId && (
                  <p className="opacity-50 font-mono text-[10px] break-all">
                    owner_id={debugInfo.ownerId}
                  </p>
                )}
              </div>
            )}
            {displayThreads.map((t) => {
              // Fallback chain: contact display name → resolved phone
              // (from WhatsAppContact.phone_number or stripped JID) →
              // raw JID → "Unknown contact". Last branch covers rows
              // where everything came back null/empty (rare — usually
              // broadcast / system messages we already filter on the
              // engine side).
              const label = t.name || t.phone || t.jid || 'Unknown contact'
              const isActive = t.jid === activeJid
              // In a search view, prefer the matching message snippet so
              // the user sees *why* the chat matched.
              const previewText =
                inSearch && t.match_snippet
                  ? t.match_snippet
                  : t.last_preview
                    ? (t.last_from_me ? 'You: ' : '') + t.last_preview
                    : `${t.message_count} message${t.message_count === 1 ? '' : 's'}`
              return (
                <button
                  key={t.jid}
                  onClick={() => setActiveJid(t.jid)}
                  className={
                    'w-full text-left px-3 py-2 border-b border-brand-mid-grey/40 ' +
                    (isActive ? 'bg-brand-blue/10' : 'bg-white hover:bg-brand-light-grey')
                  }
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <div className="text-sm font-medium text-brand-black truncate">
                      {label}
                      {t.is_group && (
                        <span className="ml-1 text-[10px] uppercase text-brand-grey-80">group</span>
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
                  <div className="text-xs text-brand-grey-80 truncate mt-0.5">{previewText}</div>
                </button>
              )
            })}
          </div>
        </aside>

        {/* Reading pane */}
        <main className="flex-1 min-w-0 flex flex-col bg-brand-light-grey">
          {!activeThread ? (
            <div className="h-full flex items-center justify-center text-sm text-brand-grey-80">
              Select a conversation on the left.
            </div>
          ) : (
            <div className="flex flex-col h-full min-h-0">
              <header className="px-4 py-2 border-b border-brand-mid-grey/60 bg-white shrink-0">
                <div className="text-sm font-semibold">
                  {activeThread.name || activeThread.phone || activeThread.jid}
                </div>
                {activeThread.phone && activeThread.name && (
                  <button
                    type="button"
                    title="Apri in WhatsApp"
                    className="text-xs text-brand-grey-80 hover:underline cursor-pointer bg-transparent border-0 p-0"
                    onClick={() =>
                      void window.zylch.shell.openExternal(
                        `https://wa.me/${(activeThread.phone || '').replace(/\D/g, '')}`
                      )
                    }
                  >
                    {'+' + (activeThread.phone || '').replace(/\D/g, '')}
                  </button>
                )}
              </header>
              <div ref={messagesScrollRef} className="flex-1 overflow-y-auto p-4 space-y-2">
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
                  <div key={m.id} className={'flex ' + (m.is_from_me ? 'justify-end' : 'justify-start')}>
                    <div
                      className={
                        'max-w-[70%] rounded-lg px-3 py-1.5 shadow-sm ' +
                        (m.is_from_me
                          ? 'bg-brand-blue/15 border border-brand-blue/30'
                          : 'bg-white border border-brand-mid-grey/60')
                      }
                    >
                      {!m.is_from_me && activeThread.is_group && m.sender_name && (
                        <div className="text-[11px] font-medium text-brand-blue">{m.sender_name}</div>
                      )}
                      {(m.media_type === 'voice' || m.media_type === 'audio') && m.transcription ? (
                        <div>
                          <div className="text-sm text-brand-black whitespace-pre-wrap">
                            {'\u{1F3A4} ' + m.transcription}
                          </div>
                          <div className="text-[10px] italic text-brand-grey-80">
                            vocale trascritta
                          </div>
                        </div>
                      ) : m.text && m.text !== '[voice]' && m.text !== '[audio]' ? (
                        <div className="text-sm text-brand-black whitespace-pre-wrap">{m.text}</div>
                      ) : m.media_type === 'voice' || m.media_type === 'audio' ? (
                        <div className="text-sm italic text-brand-grey-80">
                          {'\u{1F3A4} [vocale]'}
                        </div>
                      ) : m.media_type ? (
                        <div className="text-sm italic text-brand-grey-80">[{m.media_type}]</div>
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

              {/* Composer */}
              <div className="border-t border-brand-mid-grey/60 bg-white px-3 py-2 shrink-0">
                {sendError && (
                  <div className="text-xs text-brand-danger mb-1 whitespace-pre-wrap">{sendError}</div>
                )}
                <div className="flex items-end gap-2">
                  <textarea
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        void handleSend()
                      }
                    }}
                    rows={2}
                    placeholder="Scrivi un messaggio…  (Invio per inviare, Maiusc+Invio per andare a capo)"
                    className="flex-1 resize-none rounded border border-brand-mid-grey px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-brand-blue"
                  />
                  <button
                    type="button"
                    onClick={() => void handleSend()}
                    disabled={sending || !draft.trim()}
                    className="px-4 py-2 text-sm rounded bg-brand-blue text-white hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {sending ? 'Invio…' : 'Invia'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
