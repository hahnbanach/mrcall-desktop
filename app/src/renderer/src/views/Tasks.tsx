import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ZylchTask } from '../types'
import { useConversations } from '../store/conversations'
import { useTasks } from '../store/tasks'
import { useThread } from '../store/thread'
import { showError } from '../lib/errors'
import { formatAbsolute, formatRelative } from '../lib/dates'
import Icon from '../components/Icon'

type StatusFilter = 'open' | 'closed'
type SortMode = 'urgency' | 'date'
type ChannelFilter = 'all' | 'email' | 'phone' | 'calendar' | 'whatsapp'

// Persistence key for the channel filter — kept in localStorage so a
// user who only cares about phone tasks doesn't have to flip the
// dropdown on every reload.
const CHANNEL_FILTER_KEY = 'mrcall.tasks.channelFilter'

interface Props {
  /**
   * Called when the user clicks "Open" on a task. The parent must
   * switch the view to the Workspace. Upstream (App.tsx) also sets
   * `activeThreadId` + `activeTaskId` on the thread store so the
   * Source panel in Workspace can load the email thread.
   */
  onOpenWorkspace?: (threadId: string | null, taskId: string) => void
}

const URGENCY_ORDER = ['high', 'medium', 'low']
const URGENCY_STYLES: Record<string, string> = {
  high: 'bg-brand-danger/10 text-brand-danger border-brand-danger/30',
  medium: 'bg-brand-orange/10 text-brand-orange border-brand-orange/30',
  low: 'bg-brand-light-grey text-brand-grey-80 border-brand-mid-grey'
}

export default function Tasks({ onOpenWorkspace }: Props = {}) {
  const { openTaskChat, setActive, state: convState } = useConversations()
  // Tasks live in a shared store so Update.tsx can invalidate us after
  // a pipeline run. `refresh()` always hits the sidecar — there is no
  // memoization on this path.
  const { tasks, loading, error, refresh, setTasks } = useTasks()
  // ── Thread filter (Inbox "Open" flow) ───────────────────────────────
  // When the user clicks "Open" on an Email inbox thread, the Email view
  // sets `taskThreadFilter` on the thread store and navigates us here.
  // In that mode we bypass the shared tasks store and hit
  // `tasks.list_by_thread` directly — a thread can have 0 tasks and we
  // must show an "empty for this thread" state rather than falling back
  // to the full list.
  const { taskThreadFilter, setTaskThreadFilter } = useThread()
  const [threadTasks, setThreadTasks] = useState<ZylchTask[]>([])
  const [threadLoading, setThreadLoading] = useState(false)
  const [threadError, setThreadError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('open')
  const [sortMode, setSortMode] = useState<SortMode>('urgency')
  const [channelFilter, setChannelFilter] = useState<ChannelFilter>(() => {
    try {
      const v = localStorage.getItem(CHANNEL_FILTER_KEY)
      if (v === 'email' || v === 'phone' || v === 'calendar' || v === 'whatsapp') return v
    } catch {
      /* localStorage unavailable */
    }
    return 'all'
  })
  useEffect(() => {
    try {
      localStorage.setItem(CHANNEL_FILTER_KEY, channelFilter)
    } catch {
      /* ignore */
    }
  }, [channelFilter])
  const [search, setSearch] = useState('')

  const loadThreadTasks = useCallback(async (threadId: string) => {
    setThreadLoading(true)
    setThreadError(null)
    try {
      const r = await window.zylch.tasks.listByThread(threadId)
      setThreadTasks(r)
    } catch (e: unknown) {
      setThreadError(e instanceof Error ? e.message : String(e))
      setThreadTasks([])
    } finally {
      setThreadLoading(false)
    }
  }, [])

  // Re-fetch whenever the filter changes (incl. when the user resets it).
  useEffect(() => {
    if (taskThreadFilter) {
      void loadThreadTasks(taskThreadFilter.threadId)
    } else {
      setThreadTasks([])
      setThreadError(null)
    }
  }, [taskThreadFilter, loadThreadTasks])

  // `load` re-fetches with the current toggle so callers (Refresh button,
  // post-action refresh) don't have to remember which slice is shown. In
  // thread-filter mode it re-hits `tasks.list_by_thread` instead.
  const load = (): Promise<void> => {
    if (taskThreadFilter) return loadThreadTasks(taskThreadFilter.threadId)
    return refresh(statusFilter === 'closed' ? { include_completed: true } : undefined)
  }
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [updating, setUpdating] = useState<Set<string>>(new Set())
  const [pinning, setPinning] = useState<Set<string>>(new Set())
  const [keptNotice, setKeptNotice] = useState<Record<string, string>>({})
  // ── Close-with-note composer ────────────────────────────────────────
  // When the user clicks Close on an open task we swap the action row
  // for an inline composer (textarea + Save / Cancel). Empty textarea →
  // close without a note. Only one task can be in composer mode at a
  // time; opening another resets the draft.
  const [closingId, setClosingId] = useState<string | null>(null)
  const [noteDraft, setNoteDraft] = useState('')

  // Re-fetch whenever the user flips the Open/Closed toggle. The mount
  // fetch in TasksProvider already covers the initial Open load. Skipped
  // in thread-filter mode: the status toggle is hidden there.
  useEffect(() => {
    if (taskThreadFilter) return
    void refresh(statusFilter === 'closed' ? { include_completed: true } : undefined)
  }, [statusFilter, refresh, taskThreadFilter])

  // Helper: apply an in-place mutation to whichever list is active.
  // In thread-filter mode we operate on the local `threadTasks` array;
  // otherwise on the shared tasks store (same behaviour as before).
  const mutateVisible = (
    fn: (prev: ZylchTask[]) => ZylchTask[]
  ): void => {
    if (taskThreadFilter) setThreadTasks((t) => fn(t))
    else setTasks((t) => fn(t))
  }

  const onPin = async (task: ZylchTask) => {
    const next = !task.pinned
    // Optimistic update
    mutateVisible((t) => t.map((x) => (x.id === task.id ? { ...x, pinned: next } : x)))
    setPinning((s) => new Set(s).add(task.id))
    try {
      await window.zylch.tasks.pin(task.id, next)
      // Refetch to get authoritative ordering from the backend
      await load()
    } catch (e: unknown) {
      // Roll back the optimistic flip on failure
      mutateVisible((t) =>
        t.map((x) => (x.id === task.id ? { ...x, pinned: task.pinned } : x))
      )
      showError(e, 'Pin failed:')
    } finally {
      setPinning((s) => {
        const n = new Set(s)
        n.delete(task.id)
        return n
      })
    }
  }
  const onSkip = async (id: string) => {
    try {
      await window.zylch.tasks.skip(id)
      mutateVisible((t) => t.filter((x) => x.id !== id))
    } catch (e: unknown) {
      showError(e, 'Skip failed:')
    }
  }
  const beginClose = (id: string) => {
    setClosingId(id)
    setNoteDraft('')
  }
  const cancelClose = () => {
    setClosingId(null)
    setNoteDraft('')
  }
  const commitClose = async (id: string) => {
    const note = noteDraft.trim() || null
    try {
      await window.zylch.tasks.complete(id, note)
      mutateVisible((t) => t.filter((x) => x.id !== id))
      setClosingId(null)
      setNoteDraft('')
    } catch (e: unknown) {
      showError(e, 'Close failed:')
    }
  }
  const onReopen = async (id: string) => {
    try {
      await window.zylch.tasks.reopen(id)
      // Drop from the current (closed) view — it's now open.
      mutateVisible((t) => t.filter((x) => x.id !== id))
    } catch (e: unknown) {
      showError(e, 'Reopen failed:')
    }
  }
  const onUpdate = async (id: string) => {
    setUpdating((s) => new Set(s).add(id))
    setKeptNotice((n) => {
      if (!(id in n)) return n
      const m = { ...n }
      delete m[id]
      return m
    })
    try {
      const r = await window.zylch.tasks.reanalyze(id)
      if (r.action === 'closed') {
        mutateVisible((t) => t.filter((x) => x.id !== id))
      } else if (r.action === 'updated') {
        await load()
      } else {
        setKeptNotice((n) => ({ ...n, [id]: r.reason }))
        setTimeout(() => {
          setKeptNotice((n) => {
            if (!(id in n)) return n
            const m = { ...n }
            delete m[id]
            return m
          })
        }, 6000)
      }
    } catch (e: unknown) {
      showError(e, 'Update failed:')
    } finally {
      setUpdating((s) => {
        const n = new Set(s)
        n.delete(id)
        return n
      })
    }
  }
  const toggle = (id: string) => {
    setExpanded((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  }

  // Step 1: pick the slice the toggle wants. The backend returns mixed
  // open+closed when `include_completed` is true, so we filter here to
  // show ONLY closed in the Closed view (and only open in the Open view,
  // which is the default backend behaviour but we double-guard).
  // In thread-filter mode we bypass this — `tasks.list_by_thread` already
  // returns the exact set (open only), so we use `threadTasks` verbatim.
  // NB: hooks must run on every render — they live above the loading/error
  // early returns to obey the Rules of Hooks.
  const statusFiltered = useMemo(() => {
    if (taskThreadFilter) return threadTasks
    if (statusFilter === 'closed') return tasks.filter((t) => t.completed_at != null)
    return tasks.filter((t) => t.completed_at == null)
  }, [tasks, statusFilter, taskThreadFilter, threadTasks])

  // Channel filter (Fase 3.2): operates between status and search so
  // the search count reflects what the user is actually looking at.
  // 'all' is a no-op; 'email' includes legacy null-channel rows so
  // pre-3.2 tasks don't disappear when the user picks Email.
  const channelFiltered = useMemo(() => {
    if (channelFilter === 'all') return statusFiltered
    if (channelFilter === 'email') {
      return statusFiltered.filter(
        (t) => !t.channel || t.channel === 'email'
      )
    }
    return statusFiltered.filter((t) => t.channel === channelFilter)
  }, [statusFiltered, channelFilter])

  // Channel counts feed badges in the dropdown so the user can see
  // how many phone vs email tasks exist without scrubbing through.
  const channelCounts = useMemo(() => {
    const out = { all: statusFiltered.length, email: 0, phone: 0, calendar: 0, whatsapp: 0 }
    for (const t of statusFiltered) {
      const c = t.channel || 'email'
      if (c === 'email' || c === 'phone' || c === 'calendar' || c === 'whatsapp') {
        out[c] += 1
      } else {
        out.email += 1
      }
    }
    return out
  }, [statusFiltered])

  const q = search.trim().toLowerCase()
  const searchFiltered = useMemo(() => {
    if (!q) return channelFiltered
    return channelFiltered.filter((t) => {
      const hay = [
        t.contact_name || '',
        t.contact_email || '',
        t.reason || '',
        t.suggested_action || ''
      ]
        .join(' ')
        .toLowerCase()
      return hay.includes(q)
    })
  }, [channelFiltered, q])

  // Loading / error states. In thread-filter mode we swap to the
  // thread-specific loading/error so the banner remains visible above.
  const isThreadMode = taskThreadFilter != null
  const activeLoading = isThreadMode ? threadLoading : loading
  const activeError = isThreadMode ? threadError : error
  if (activeLoading)
    return <div className="p-8 text-brand-grey-80">Loading tasks…</div>
  if (activeError)
    return (
      <div className="p-8">
        <div className="text-brand-danger">Error: {activeError}</div>
        <button
          onClick={load}
          className="mt-3 px-3 py-1.5 bg-brand-black text-white rounded text-sm hover:bg-brand-grey-80 transition-colors"
        >
          Retry
        </button>
      </div>
    )

  // Client-side sort. Always pinned-first; within each pin bucket we
  // either preserve the engine's urgency order ('urgency' mode) or sort
  // by `last_signal_at` descending ('date' mode — newest signal first).
  // Pinned-first is stable across mode changes so optimistic updates
  // don't reshuffle.
  const sortedTasks = [...searchFiltered].sort((a, b) => {
    const pa = a.pinned ? 0 : 1
    const pb = b.pinned ? 0 : 1
    if (pa !== pb) return pa - pb
    if (sortMode === 'date') {
      const ta = a.last_signal_at ? new Date(a.last_signal_at).getTime() : 0
      const tb = b.last_signal_at ? new Date(b.last_signal_at).getTime() : 0
      return tb - ta
    }
    return 0 // urgency mode: trust engine's ordering (already grouped below)
  })

  const pinnedTasks = sortedTasks.filter((t) => t.pinned)
  const unpinnedTasks = sortedTasks.filter((t) => !t.pinned)
  // Thread-filter mode fetches OPEN tasks only, so the closed styling
  // never applies there regardless of the toggle's in-memory state.
  const isClosedView = !isThreadMode && statusFilter === 'closed'

  const grouped: Record<string, ZylchTask[]> = {}
  for (const t of unpinnedTasks) {
    const k = (t.urgency || 'low').toLowerCase()
    ;(grouped[k] ||= []).push(t)
  }

  const renderTask = (t: ZylchTask) => {
    const u = (t.urgency || 'low').toLowerCase()
    const threadId = t.sources?.thread_id || null
    return (
      <article
        key={t.id}
        className={
          'bg-white border border-brand-mid-grey/40 rounded-2xl p-4 shadow-sm ' +
          (t.pinned ? 'border-l-4 border-l-brand-orange ' : '') +
          (isClosedView ? 'text-brand-grey-80 opacity-80' : '')
        }
      >
        <div className="flex items-start justify-between gap-3 mb-2">
          <div className="flex items-center gap-2">
            {t.pinned && (
              <Icon
                name="pin"
                size={14}
                className="text-brand-orange shrink-0"
                aria-label="Pinned"
              />
            )}
            <div className="text-sm text-brand-grey-80">
              {t.contact_name
                ? `${t.contact_name} <${t.contact_email}>`
                : t.contact_email}
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {t.last_signal_at && (
              <span
                className="text-xs text-brand-grey-80"
                title={formatAbsolute(t.last_signal_at)}
              >
                {formatRelative(t.last_signal_at)}
              </span>
            )}
            <span
              className={
                'text-xs px-2 py-0.5 border rounded ' +
                (URGENCY_STYLES[u] || URGENCY_STYLES.low)
              }
            >
              {u}
            </span>
          </div>
        </div>
        <div className="text-brand-black whitespace-pre-wrap mb-2">
          {t.suggested_action}
        </div>
        <button
          onClick={() => toggle(t.id)}
          className="text-xs text-brand-grey-80 hover:text-brand-black mb-2"
        >
          {expanded.has(t.id) ? 'Hide reason' : 'Show reason'}
        </button>
        {expanded.has(t.id) && (
          <div
            className={
              'text-sm whitespace-pre-wrap border-l-2 border-brand-mid-grey pl-3 mb-3 ' +
              (isClosedView ? 'text-brand-grey-80 line-through' : 'text-brand-grey-80')
            }
          >
            {t.reason}
          </div>
        )}
        {isClosedView && t.close_note && (
          <div className="mb-3 text-sm bg-brand-light-grey border-l-2 border-brand-blue pl-3 py-1.5 pr-2 rounded-r">
            <span className="text-xs uppercase tracking-wide text-brand-grey-80">
              Closing note
            </span>
            <div className="text-brand-black whitespace-pre-wrap">{t.close_note}</div>
          </div>
        )}
        {closingId === t.id ? (
          <div className="space-y-2">
            <textarea
              value={noteDraft}
              onChange={(e) => setNoteDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  e.preventDefault()
                  cancelClose()
                } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault()
                  void commitClose(t.id)
                }
              }}
              autoFocus
              placeholder="Optional closing note — e.g. 'Already paid via bank transfer'"
              className="w-full text-sm border border-brand-mid-grey rounded p-2 resize-y min-h-[60px] outline-none focus:border-brand-blue"
              rows={2}
            />
            <div className="flex gap-2 flex-wrap">
              <button
                onClick={() => void commitClose(t.id)}
                className="px-3 py-1.5 text-sm bg-brand-black text-white rounded hover:bg-brand-grey-80 transition-colors"
                title={
                  noteDraft.trim()
                    ? 'Close task with this note (⌘↵)'
                    : 'Close task without a note (⌘↵)'
                }
              >
                {noteDraft.trim() ? 'Save & close' : 'Close (no note)'}
              </button>
              <button
                onClick={cancelClose}
                className="px-3 py-1.5 text-sm border border-brand-mid-grey rounded hover:bg-brand-light-grey transition-colors"
                title="Cancel (Esc)"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => onPin(t)}
            disabled={pinning.has(t.id)}
            title={t.pinned ? 'Unpin task' : 'Pin task to top'}
            className={
              'px-3 py-1.5 text-sm border rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-1.5 ' +
              (t.pinned
                ? 'bg-brand-orange/10 text-brand-orange border-brand-orange/30 hover:bg-brand-orange/20'
                : 'border-brand-mid-grey hover:bg-brand-light-grey text-brand-grey-80')
            }
          >
            <Icon name="pin" size={14} />
            {t.pinned ? 'Pinned' : 'Pin'}
          </button>
          {!isClosedView && (
            <button
              onClick={() => onSkip(t.id)}
              className="px-3 py-1.5 text-sm border border-brand-mid-grey rounded hover:bg-brand-light-grey transition-colors"
            >
              Skip
            </button>
          )}
          {isClosedView ? (
            <button
              onClick={() => onReopen(t.id)}
              className="px-3 py-1.5 text-sm border border-brand-mid-grey rounded hover:bg-brand-light-grey transition-colors inline-flex items-center gap-1.5"
              title="Reopen this task"
            >
              <Icon name="reopen" size={14} />
              Reopen
            </button>
          ) : (
            <button
              onClick={() => beginClose(t.id)}
              className="px-3 py-1.5 text-sm bg-brand-black text-white rounded hover:bg-brand-grey-80 transition-colors"
              title="Close task (with optional note)"
            >
              Close
            </button>
          )}
          <button
            onClick={() => onUpdate(t.id)}
            disabled={updating.has(t.id)}
            className="px-3 py-1.5 text-sm border border-brand-mid-grey rounded hover:bg-brand-light-grey transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {updating.has(t.id) ? 'Analyzing…' : 'Update'}
          </button>
          <button
            onClick={() => {
              // Task conversation is `task-<id>` — openTaskChat creates
              // it if missing (and seeds the first draft message).
              // Don't overwrite an existing conversation: a prior Open
              // may already have back-and-forth we must preserve.
              const convId = `task-${t.id}`
              const exists = convState.conversations.some((c) => c.id === convId)
              if (!exists) {
                openTaskChat(t)
              } else {
                setActive(convId)
              }
              onOpenWorkspace?.(threadId, t.id)
            }}
            className="px-3 py-1.5 text-sm bg-brand-blue text-white rounded hover:bg-brand-grey-80 transition-colors"
            title={threadId ? 'Open in workspace' : 'Open in workspace (no thread)'}
          >
            Open
          </button>
        </div>
        )}
        {keptNotice[t.id] && (
          <div className="mt-2 text-xs text-brand-grey-80 bg-brand-light-grey border border-brand-mid-grey rounded px-2 py-1.5">
            Task kept — {keptNotice[t.id]}
          </div>
        )}
      </article>
    )
  }

  const visibleCount = sortedTasks.length
  const matchSuffix = q ? ` (${visibleCount} matches)` : ''

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-semibold">
          Tasks ({visibleCount}){matchSuffix}
        </h1>
        <button
          onClick={() => void load()}
          className="px-3 py-1.5 text-sm border border-brand-mid-grey rounded hover:bg-brand-light-grey transition-colors"
        >
          Refresh
        </button>
      </div>
      {/* Thread-filter banner: appears only when the user came here from
          the Email view's "Open" button. Shows the thread subject and a
          reset control so the user can jump back to the full task list.
          In this mode the Open/Closed toggle is hidden (the RPC returns
          open tasks only — the toggle has no meaning here). */}
      {isThreadMode && taskThreadFilter && (
        <div
          role="status"
          className="flex items-center justify-between gap-3 mb-4 px-3 py-2 bg-brand-light-grey border-l-4 border-brand-blue rounded"
        >
          <div className="min-w-0 text-sm">
            <span className="font-medium">Tasks for thread:</span>{' '}
            <span className="truncate inline-block max-w-[60ch] align-bottom">
              {taskThreadFilter.subject || '(no subject)'}
            </span>
          </div>
          <button
            onClick={() => setTaskThreadFilter(null)}
            className="px-2 py-1 text-xs border border-brand-mid-grey rounded bg-white hover:bg-brand-light-grey transition-colors inline-flex items-center gap-1"
            title="Show all tasks"
          >
            <Icon name="close" size={12} />
            Clear filter
          </button>
        </div>
      )}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        {!isThreadMode && (
          <div
            className="inline-flex rounded-full border border-brand-mid-grey overflow-hidden"
            role="group"
            aria-label="Filter by status"
          >
            <button
              type="button"
              onClick={() => setStatusFilter('open')}
              className={
                'px-3 py-1 text-sm transition-colors ' +
                (statusFilter === 'open'
                  ? 'bg-brand-blue text-white'
                  : 'bg-white text-brand-grey-80 hover:bg-brand-light-grey')
              }
              aria-pressed={statusFilter === 'open'}
            >
              Open
            </button>
            <button
              type="button"
              onClick={() => setStatusFilter('closed')}
              title="Show closed tasks"
              className={
                'px-3 py-1 text-sm border-l border-brand-mid-grey transition-colors ' +
                (statusFilter === 'closed'
                  ? 'bg-brand-blue text-white'
                  : 'bg-white text-brand-grey-80 hover:bg-brand-light-grey')
              }
              aria-pressed={statusFilter === 'closed'}
            >
              Closed
            </button>
          </div>
        )}
        <div className="flex items-center gap-1.5 border border-brand-mid-grey rounded px-2 py-1 bg-white">
          <span className="text-xs text-brand-grey-80 shrink-0">Sort</span>
          <select
            value={sortMode}
            onChange={(e) => setSortMode(e.target.value as SortMode)}
            className="text-sm bg-transparent outline-none"
            aria-label="Sort tasks by"
          >
            <option value="urgency">Urgency</option>
            <option value="date">Date</option>
          </select>
        </div>
        {!isThreadMode && (
          <div className="flex items-center gap-1.5 border border-brand-mid-grey rounded px-2 py-1 bg-white">
            <span className="text-xs text-brand-grey-80 shrink-0">Channel</span>
            <select
              value={channelFilter}
              onChange={(e) => setChannelFilter(e.target.value as ChannelFilter)}
              className="text-sm bg-transparent outline-none"
              aria-label="Filter tasks by channel"
            >
              <option value="all">All ({channelCounts.all})</option>
              <option value="email">Email ({channelCounts.email})</option>
              <option value="phone">Phone ({channelCounts.phone})</option>
              <option value="calendar">Calendar ({channelCounts.calendar})</option>
              <option value="whatsapp">WhatsApp ({channelCounts.whatsapp})</option>
            </select>
          </div>
        )}
        <div className="flex items-center gap-1.5 border border-brand-mid-grey rounded px-2 py-1 bg-white">
          <Icon name="search" size={14} className="text-brand-mid-grey shrink-0" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search…"
            aria-label="Search tasks"
            className="text-sm outline-none bg-transparent w-48"
          />
        </div>
      </div>
      {sortedTasks.length === 0 && (
        <div className="text-brand-grey-80">
          {isThreadMode
            ? 'No tasks for this thread.'
            : isClosedView
              ? 'No closed tasks.'
              : 'No tasks. All clear.'}
        </div>
      )}
      {pinnedTasks.length > 0 && (
        <section className="mb-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-brand-orange mb-2 inline-flex items-center gap-2">
            <Icon name="pin" size={14} />
            Pinned ({pinnedTasks.length})
          </h2>
          <div className="space-y-3">{pinnedTasks.map(renderTask)}</div>
        </section>
      )}
      {sortMode === 'date' ? (
        unpinnedTasks.length > 0 && (
          <section className="mb-6">
            <div className="space-y-3">{unpinnedTasks.map(renderTask)}</div>
          </section>
        )
      ) : (
        URGENCY_ORDER.map((u) => {
          const list = grouped[u]
          if (!list || list.length === 0) return null
          return (
            <section key={u} className="mb-6">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-brand-grey-80 mb-2">
                {u} ({list.length})
              </h2>
              <div className="space-y-3">{list.map(renderTask)}</div>
            </section>
          )
        })
      )}
    </div>
  )
}
