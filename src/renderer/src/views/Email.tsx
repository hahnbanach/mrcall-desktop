import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { InboxThread, ThreadEmail } from '../types'
import { errorMessage, isProfileLockedError } from '../lib/errors'
import { useConversations } from '../store/conversations'
import { useThread } from '../store/thread'
import HtmlEmailBody from '../components/HtmlEmailBody'
// EmailComposeModal intentionally not imported: the "Open" flow
// replaces the old "Compose from Email" entrypoint. A future blank
// compose icon will re-add this.
// import EmailComposeModal, { ComposeSeed } from './EmailComposeModal'

type Folder = 'inbox' | 'drafts' | 'sent'

function formatShortDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const now = new Date()
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  if (sameDay) return d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
  const sameYear = d.getFullYear() === now.getFullYear()
  if (sameYear)
    return d.toLocaleDateString('it-IT', { day: '2-digit', month: 'short' })
  return d.toLocaleDateString('it-IT', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit'
  })
}

function formatFullDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleString('it-IT')
}

interface EmailProps {
  /**
   * Navigate to the Workspace view. Called by the "Open" button after the
   * conversations store + thread store have been updated so the active
   * conversation is the thread-only one.
   */
  onOpenWorkspace?: (threadId: string) => void
}

/**
 * Email view — Superhuman-style 1-or-2 column layout.
 *
 * Toolbar (top of thread list):
 *   - ☰ (burger) when nothing is selected → opens folder dropdown.
 *   - ← (back)   when a thread is selected → clears selection.
 *   - Folder name (Inbox / Drafts / Sent) rendered next to the icon.
 *
 * No thread selected:  thread list takes the full width; reading pane unmounted.
 * Thread selected:     thread list fixed at 380px, reading pane fills the rest.
 *
 * Keyboard (when focus is not in INPUT/TEXTAREA):
 *   J / ArrowDown  — next thread
 *   K / ArrowUp    — prev thread
 *   Enter          — scroll selected into view
 *   C              — Open the selected thread in Workspace
 */
export default function Email({ onOpenWorkspace }: EmailProps = {}): JSX.Element {
  const [folder, setFolder] = useState<Folder>('inbox')
  const [threads, setThreads] = useState<InboxThread[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [pinning, setPinning] = useState<Set<string>>(new Set())
  const [draftsCount, setDraftsCount] = useState<number>(0)
  const [folderMenuOpen, setFolderMenuOpen] = useState(false)

  const { openThreadChat } = useConversations()
  const { setActiveThreadId, setActiveTaskId } = useThread()

  const listRef = useRef<HTMLDivElement | null>(null)

  // ─── data ─────────────────────────────────────────────────────────
  const PAGE_SIZE = 50

  const loadFolder = useCallback(
    async (target: Folder, append = false) => {
      setLoading(true)
      setError(null)
      try {
        if (target === 'inbox') {
          const r = await window.zylch.emails.listInbox({
            limit: PAGE_SIZE,
            offset: append ? threads.length : 0
          })
          setThreads((prev) => (append ? [...prev, ...r.threads] : r.threads))
          setHasMore(r.threads.length === PAGE_SIZE)
        } else if (target === 'sent') {
          const r = await window.zylch.emails.listSent({
            limit: PAGE_SIZE,
            offset: append ? threads.length : 0
          })
          setThreads((prev) => (append ? [...prev, ...r.threads] : r.threads))
          setHasMore(r.threads.length === PAGE_SIZE)
        } else {
          // Drafts use the existing chat-side endpoint — no dedicated RPC
          // is exposed for the desktop today. We just surface the count,
          // and the user edits drafts via the chat flow. The middle column
          // shows a stub; clicking a draft in the future could reuse the
          // compose modal pre-populated.
          setThreads([])
          setHasMore(false)
        }
      } catch (e: unknown) {
        if (!isProfileLockedError(e)) setError(errorMessage(e))
      } finally {
        setLoading(false)
      }
    },
    [threads.length]
  )

  // Initial load + folder change.
  useEffect(() => {
    setSelectedId(null)
    setThreads([])
    void loadFolder(folder, false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [folder])

  // Drafts badge: refresh on mount + every 30s. Uses the existing
  // tasks.list RPC? No — there's no public list_drafts RPC yet. Rather
  // than add one in this round, we derive a best-effort count from the
  // chat pipeline's narration output. To stay within the "no new deps,
  // no new RPC beyond spec" constraint, we just leave this at 0 until
  // a future round wires up drafts.list. Keeps the UI element visible.
  useEffect(() => {
    setDraftsCount(0)
  }, [])

  // ─── selection ────────────────────────────────────────────────────
  const selectedIndex = useMemo(() => {
    if (!selectedId) return -1
    return threads.findIndex((t) => t.thread_id === selectedId)
  }, [threads, selectedId])

  const selected = selectedIndex >= 0 ? threads[selectedIndex] : null

  const selectByIndex = useCallback(
    (idx: number) => {
      if (idx < 0 || idx >= threads.length) return
      const t = threads[idx]
      setSelectedId(t.thread_id)
      // Optimistically clear unread on open; fire-and-forget mark_read.
      if (t.unread) {
        setThreads((prev) =>
          prev.map((x) => (x.thread_id === t.thread_id ? { ...x, unread: false } : x))
        )
      }
      window.zylch.emails.markRead(t.thread_id).catch(() => {
        /* fire-and-forget */
      })
      // Scroll selected card into view in the list column.
      requestAnimationFrame(() => {
        const node = listRef.current?.querySelector<HTMLElement>(
          `[data-thread-id="${CSS.escape(t.thread_id)}"]`
        )
        node?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
      })
    },
    [threads]
  )

  // ─── open selected thread in Workspace ───────────────────────────
  // Shared by: the sidebar "Open" button, the reading-pane "Open" button,
  // and the `C` keyboard shortcut. No-op if nothing is selected.
  const openSelected = useCallback(() => {
    if (!selected) return
    openThreadChat(selected.thread_id, selected.subject || '', selected.last_email_id)
    setActiveThreadId(selected.thread_id)
    setActiveTaskId(null)
    onOpenWorkspace?.(selected.thread_id)
  }, [selected, openThreadChat, setActiveThreadId, setActiveTaskId, onOpenWorkspace])

  // ─── pin ───────────────────────────────────────────────────────────
  const onPin = useCallback(
    async (thread: InboxThread, evt?: React.MouseEvent) => {
      evt?.stopPropagation()
      const next = !thread.pinned
      setPinning((s) => new Set(s).add(thread.thread_id))
      // Optimistic update.
      setThreads((prev) =>
        prev.map((t) => (t.thread_id === thread.thread_id ? { ...t, pinned: next } : t))
      )
      try {
        await window.zylch.emails.pin(thread.thread_id, next)
        // Re-fetch to get authoritative ordering.
        await loadFolder(folder, false)
      } catch (e: unknown) {
        // Roll back.
        setThreads((prev) =>
          prev.map((t) =>
            t.thread_id === thread.thread_id ? { ...t, pinned: thread.pinned } : t
          )
        )
        if (!isProfileLockedError(e)) setError(errorMessage(e))
      } finally {
        setPinning((s) => {
          const n = new Set(s)
          n.delete(thread.thread_id)
          return n
        })
      }
    },
    [folder, loadFolder]
  )

  // ─── keyboard shortcuts ───────────────────────────────────────────
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      const active = document.activeElement
      const tag = active?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || (active as HTMLElement)?.isContentEditable) {
        return
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return
      switch (e.key) {
        case 'j':
        case 'J':
        case 'ArrowDown':
          e.preventDefault()
          selectByIndex(Math.min(threads.length - 1, (selectedIndex < 0 ? 0 : selectedIndex + 1)))
          break
        case 'k':
        case 'K':
        case 'ArrowUp':
          e.preventDefault()
          selectByIndex(Math.max(0, selectedIndex - 1))
          break
        case 'Enter':
          if (selectedIndex >= 0) selectByIndex(selectedIndex)
          break
        case 'c':
        case 'C':
          // Mapped to "Open" for now — opens the selected thread in
          // Workspace. No-op if no thread is selected. Reply (`R`) was
          // removed: the user handles replies from the Workspace chat.
          if (selected) {
            e.preventDefault()
            openSelected()
          }
          break
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [threads, selectedIndex, selected, selectByIndex, openSelected])

  // ─── rendering ────────────────────────────────────────────────────
  const folders: Array<{ id: Folder; label: string; badge?: number }> = [
    { id: 'inbox', label: 'Inbox' },
    { id: 'drafts', label: 'Drafts', badge: draftsCount },
    { id: 'sent', label: 'Sent' }
  ]

  const currentFolderLabel =
    folders.find((f) => f.id === folder)?.label ?? 'Inbox'

  return (
    <div className="flex flex-col md:flex-row h-full">
      {/* Thread list column: full width when no selection, 380px when a
          thread is open. */}
      <section
        className={
          'flex flex-col bg-white border-r ' +
          (selected ? 'w-[380px] shrink-0' : 'flex-1 min-w-0')
        }
      >
        {/* Toolbar: burger (no selection) or back arrow (selection) +
            current folder name. */}
        <div className="relative flex items-center gap-2 px-3 py-2 border-b bg-white shrink-0">
          {selected ? (
            <button
              onClick={() => setSelectedId(null)}
              title="Back to list"
              aria-label="Back"
              className="w-8 h-8 flex items-center justify-center rounded hover:bg-slate-100 text-slate-700 text-lg leading-none"
            >
              {'\u2190'}
            </button>
          ) : (
            <button
              onClick={() => setFolderMenuOpen((v) => !v)}
              title="Switch folder"
              aria-label="Switch folder"
              aria-haspopup="menu"
              aria-expanded={folderMenuOpen}
              className="w-8 h-8 flex items-center justify-center rounded hover:bg-slate-100 text-slate-700 text-lg leading-none"
            >
              {'\u2630'}
            </button>
          )}
          <div className="text-sm font-bold text-slate-900">
            {currentFolderLabel}
          </div>
          {folderMenuOpen && !selected && (
            <>
              {/* Click-outside backdrop. */}
              <div
                className="fixed inset-0 z-10"
                onClick={() => setFolderMenuOpen(false)}
              />
              <div
                role="menu"
                className="absolute left-2 top-full mt-1 bg-white border rounded shadow-lg z-20 py-1 min-w-[180px]"
              >
                {folders.map((f) => {
                  const active = folder === f.id
                  return (
                    <button
                      key={f.id}
                      role="menuitem"
                      onClick={() => {
                        setFolder(f.id)
                        setFolderMenuOpen(false)
                      }}
                      className={
                        'w-full flex items-center justify-between px-3 py-1.5 text-sm text-left ' +
                        (active
                          ? 'text-white'
                          : 'text-slate-700 hover:bg-slate-100')
                      }
                      style={
                        active ? { backgroundColor: 'var(--profile-accent)' } : undefined
                      }
                    >
                      <span>{f.label}</span>
                      {f.badge != null && f.badge > 0 && (
                        <span
                          className={
                            'text-xs rounded-full px-2 py-0.5 ' +
                            (active
                              ? 'bg-white/25 text-white'
                              : 'bg-slate-200 text-slate-700')
                          }
                        >
                          {f.badge}
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>
            </>
          )}
        </div>

        <div ref={listRef} className="flex-1 overflow-y-auto">
          {loading && threads.length === 0 && (
            <div className="p-4 text-sm text-slate-500">Loading…</div>
          )}
          {error && (
            <div className="p-4 text-sm text-red-700">Failed: {error}</div>
          )}
          {!loading && !error && threads.length === 0 && folder !== 'drafts' && (
            <div className="p-4 text-sm text-slate-500">No threads.</div>
          )}
          {folder === 'drafts' && (
            <div className="p-4 text-sm text-slate-500">
              Drafts live in the chat flow for now. Open a thread to
              reply via Workspace chat.
            </div>
          )}
          <ul className="flex flex-col">
            {threads.map((t) => {
              const isSel = t.thread_id === selectedId
              const who = t.from_name?.trim() || t.from_email || '(no sender)'
              return (
                <li
                  key={t.thread_id}
                  data-thread-id={t.thread_id}
                  onClick={() => {
                    const idx = threads.findIndex((x) => x.thread_id === t.thread_id)
                    selectByIndex(idx)
                  }}
                  className={
                    'group relative px-3 py-2 border-b cursor-pointer select-none ' +
                    (isSel
                      ? 'bg-[color:var(--profile-accent-soft)] '
                      : 'hover:bg-slate-50 ') +
                    (t.pinned ? 'border-l-4 ' : 'border-l-4 border-l-transparent ')
                  }
                  style={
                    t.pinned
                      ? { borderLeftColor: 'var(--profile-accent)' }
                      : undefined
                  }
                >
                  <div className="flex items-center justify-between gap-2 mb-0.5">
                    <div
                      className={
                        'text-sm truncate min-w-0 ' +
                        (t.unread ? 'font-semibold text-slate-900' : 'text-slate-700')
                      }
                    >
                      {t.pinned && (
                        <span className="mr-1" title="Pinned">
                          📌
                        </span>
                      )}
                      {who}
                    </div>
                    <div className="text-xs text-slate-500 whitespace-nowrap shrink-0">
                      {formatShortDate(t.date)}
                    </div>
                  </div>
                  <div
                    className={
                      'text-sm truncate ' +
                      (t.unread ? 'font-medium text-slate-800' : 'text-slate-700')
                    }
                  >
                    {t.subject || '(no subject)'}
                    {t.message_count > 1 && (
                      <span className="text-xs text-slate-400 ml-1">
                        ({t.message_count})
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-slate-500 truncate">{t.snippet}</div>
                  {/* Pin button (visible on hover) */}
                  <button
                    onClick={(e) => onPin(t, e)}
                    disabled={pinning.has(t.thread_id)}
                    title={t.pinned ? 'Unpin thread' : 'Pin thread'}
                    className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 focus:opacity-100 text-sm px-1 py-0.5 rounded bg-white/80 border border-slate-200 hover:bg-white disabled:opacity-50"
                  >
                    📌
                  </button>
                </li>
              )
            })}
          </ul>
          {hasMore && (
            <div className="p-3 text-center">
              <button
                onClick={() => void loadFolder(folder, true)}
                disabled={loading}
                className="px-3 py-1.5 text-sm border rounded hover:bg-slate-50 disabled:opacity-50"
              >
                {loading ? 'Loading…' : 'Load more'}
              </button>
            </div>
          )}
        </div>
      </section>

      {/* Reading pane: only mounted when a thread is selected. */}
      {selected && (
        <section className="flex-1 min-w-0 flex flex-col bg-white h-full">
          <ThreadReadingPane
            thread={selected}
            onOpen={openSelected}
            onPin={() => onPin(selected)}
            pinning={pinning.has(selected.thread_id)}
          />
        </section>
      )}
    </div>
  )
}

/**
 * Reading pane — fetches the full thread via emails.list_by_thread and
 * renders it newest-first (mirroring the Workspace ThreadPanel style).
 */
function ThreadReadingPane({
  thread,
  onOpen,
  onPin,
  pinning
}: {
  thread: InboxThread
  onOpen: () => void
  onPin: () => void
  pinning: boolean
}): JSX.Element {
  const [emails, setEmails] = useState<ThreadEmail[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setEmails([])
    window.zylch.emails
      .listByThread(thread.thread_id)
      .then((r) => {
        if (cancelled) return
        // Newest first.
        setEmails(r.emails.slice().reverse())
      })
      .catch((e: unknown) => {
        if (cancelled) return
        if (!isProfileLockedError(e)) setError(errorMessage(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [thread.thread_id])

  return (
    <>
      <header className="border-b px-4 py-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold truncate">
            {thread.subject || '(no subject)'}
          </h2>
          <div className="text-xs text-slate-500">
            {emails.length || thread.message_count} messages
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={onOpen}
            title="Open thread in Workspace"
            className="px-3 py-1.5 text-sm text-white rounded"
            style={{ backgroundColor: 'var(--profile-accent)' }}
          >
            ✉ Open
          </button>
          <button
            disabled
            title="Reply (use Workspace chat)"
            className="px-3 py-1.5 text-sm border rounded text-slate-400 cursor-not-allowed"
          >
            Reply
          </button>
          <button
            disabled
            title="Forward (coming soon)"
            className="px-3 py-1.5 text-sm border rounded text-slate-400 cursor-not-allowed"
          >
            Forward
          </button>
          <button
            onClick={onPin}
            disabled={pinning}
            title={thread.pinned ? 'Unpin' : 'Pin'}
            className={
              'px-2 py-1.5 text-sm border rounded hover:bg-slate-50 disabled:opacity-50 ' +
              (thread.pinned ? 'bg-amber-50 border-amber-300' : '')
            }
          >
            📌
          </button>
          <button
            disabled
            title="Archive (coming soon)"
            className="px-3 py-1.5 text-sm border rounded text-slate-400 cursor-not-allowed"
          >
            Archive
          </button>
        </div>
      </header>
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {loading && <div className="text-sm text-slate-500">Loading thread…</div>}
        {error && <div className="text-sm text-red-700">Failed: {error}</div>}
        {!loading && !error && emails.length === 0 && (
          <div className="text-sm text-slate-500">No messages.</div>
        )}
        {emails.map((e) => (
          <article
            key={e.id}
            className={
              'border rounded-lg p-3 shadow-sm bg-white ' +
              (e.is_user_sent ? 'border-l-4 border-l-emerald-500' : '')
            }
          >
            <div className="flex items-start justify-between gap-3 mb-1">
              <div className="text-sm text-slate-900 min-w-0 break-words">
                {e.is_user_sent && (
                  <span className="inline-block text-xs px-2 py-0.5 mr-2 rounded bg-emerald-100 text-emerald-800 border border-emerald-300">
                    You →
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
                {formatFullDate(e.date)}
              </div>
            </div>
            <div className="text-xs text-slate-500 mb-2 break-words">
              <span>To: {e.to_email || '—'}</span>
              {e.cc_email && <span> · Cc: {e.cc_email}</span>}
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
                        📎 {name}
                      </span>
                    ))
                  : (
                      <span className="text-xs px-2 py-0.5 rounded border border-slate-300 bg-slate-50 text-slate-700">
                        📎 attachment
                      </span>
                    )}
              </div>
            )}
          </article>
        ))}
      </div>
    </>
  )
}
