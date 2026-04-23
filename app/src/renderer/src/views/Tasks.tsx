import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ZylchTask } from '../types'
import { useConversations } from '../store/conversations'
import { useTasks } from '../store/tasks'
import { useThread } from '../store/thread'
import { showError } from '../lib/errors'

type StatusFilter = 'open' | 'closed'

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
  high: 'bg-red-100 text-red-800 border-red-300',
  medium: 'bg-amber-100 text-amber-800 border-amber-300',
  low: 'bg-slate-100 text-slate-700 border-slate-300'
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
  const onClose = async (id: string) => {
    try {
      await window.zylch.tasks.complete(id)
      mutateVisible((t) => t.filter((x) => x.id !== id))
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

  const q = search.trim().toLowerCase()
  const searchFiltered = useMemo(() => {
    if (!q) return statusFiltered
    return statusFiltered.filter((t) => {
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
  }, [statusFiltered, q])

  // Loading / error states. In thread-filter mode we swap to the
  // thread-specific loading/error so the banner remains visible above.
  const isThreadMode = taskThreadFilter != null
  const activeLoading = isThreadMode ? threadLoading : loading
  const activeError = isThreadMode ? threadError : error
  if (activeLoading)
    return <div className="p-8 text-slate-500">Loading tasks…</div>
  if (activeError)
    return (
      <div className="p-8">
        <div className="text-red-700">Error: {activeError}</div>
        <button
          onClick={load}
          className="mt-3 px-3 py-1.5 bg-slate-900 text-white rounded text-sm"
        >
          Retry
        </button>
      </div>
    )

  // Client-side safety sort: pinned tasks first, preserving the existing
  // backend order as a stable tie-breaker. This protects optimistic updates
  // from showing pinned tasks out of place between request and refetch.
  const sortedTasks = [...searchFiltered].sort(
    (a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0)
  )

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
          'bg-white border rounded-lg p-4 shadow-sm ' +
          (t.pinned ? 'border-l-4 border-l-amber-400 ' : '') +
          (isClosedView ? 'text-slate-500 opacity-80' : '')
        }
      >
        <div className="flex items-start justify-between gap-3 mb-2">
          <div className="flex items-center gap-2">
            {t.pinned && (
              <span
                className="text-amber-600"
                title="Pinned"
                aria-label="Pinned"
              >
                📌
              </span>
            )}
            <div className="text-sm text-slate-500">
              {t.contact_name
                ? `${t.contact_name} <${t.contact_email}>`
                : t.contact_email}
            </div>
          </div>
          <span
            className={
              'text-xs px-2 py-0.5 border rounded ' +
              (URGENCY_STYLES[u] || URGENCY_STYLES.low)
            }
          >
            {u}
          </span>
        </div>
        <div className="text-slate-900 whitespace-pre-wrap mb-2">
          {t.suggested_action}
        </div>
        <button
          onClick={() => toggle(t.id)}
          className="text-xs text-slate-500 hover:text-slate-800 mb-2"
        >
          {expanded.has(t.id) ? 'Hide reason' : 'Show reason'}
        </button>
        {expanded.has(t.id) && (
          <div
            className={
              'text-sm whitespace-pre-wrap border-l-2 border-slate-200 pl-3 mb-3 ' +
              (isClosedView ? 'text-slate-500 line-through' : 'text-slate-700')
            }
          >
            {t.reason}
          </div>
        )}
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => onPin(t)}
            disabled={pinning.has(t.id)}
            title={t.pinned ? 'Unpin task' : 'Pin task to top'}
            className={
              'px-3 py-1.5 text-sm border rounded disabled:opacity-50 disabled:cursor-not-allowed ' +
              (t.pinned
                ? 'bg-amber-100 text-amber-800 border-amber-300 hover:bg-amber-200'
                : 'hover:bg-slate-100 text-slate-600')
            }
          >
            {t.pinned ? '📌 Pinned' : '📌 Pin'}
          </button>
          {!isClosedView && (
            <button
              onClick={() => onSkip(t.id)}
              className="px-3 py-1.5 text-sm border rounded hover:bg-slate-100"
            >
              Skip
            </button>
          )}
          {isClosedView ? (
            <button
              onClick={() => onReopen(t.id)}
              className="px-3 py-1.5 text-sm border rounded hover:bg-slate-100"
              title="Reopen this task"
            >
              ↺ Reopen
            </button>
          ) : (
            <button
              onClick={() => onClose(t.id)}
              className="px-3 py-1.5 text-sm bg-slate-900 text-white rounded hover:bg-slate-700"
            >
              Close
            </button>
          )}
          <button
            onClick={() => onUpdate(t.id)}
            disabled={updating.has(t.id)}
            className="px-3 py-1.5 text-sm border rounded hover:bg-slate-100 disabled:opacity-50 disabled:cursor-not-allowed"
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
            className="px-3 py-1.5 text-sm bg-emerald-700 text-white rounded hover:bg-emerald-800"
            title={threadId ? 'Open in workspace' : 'Open in workspace (no thread)'}
          >
            Open
          </button>
        </div>
        {keptNotice[t.id] && (
          <div className="mt-2 text-xs text-slate-600 bg-slate-50 border border-slate-200 rounded px-2 py-1.5">
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
          className="px-3 py-1.5 text-sm border rounded hover:bg-slate-100"
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
          className="flex items-center justify-between gap-3 mb-4 px-3 py-2 bg-[color:var(--profile-accent-soft)] border border-[color:var(--profile-accent)] rounded"
        >
          <div className="min-w-0 text-sm">
            <span className="font-medium">Tasks for thread:</span>{' '}
            <span className="truncate inline-block max-w-[60ch] align-bottom">
              {taskThreadFilter.subject || '(no subject)'}
            </span>
          </div>
          <button
            onClick={() => setTaskThreadFilter(null)}
            className="px-2 py-1 text-xs border rounded bg-white hover:bg-slate-100"
            title="Show all tasks"
          >
            ✕ Clear filter
          </button>
        </div>
      )}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        {!isThreadMode && (
          <div
            className="inline-flex rounded-full border border-slate-300 overflow-hidden"
            role="group"
            aria-label="Filter by status"
          >
            <button
              type="button"
              onClick={() => setStatusFilter('open')}
              className={
                'px-3 py-1 text-sm ' +
                (statusFilter === 'open'
                  ? 'bg-emerald-700 text-white border-emerald-700'
                  : 'bg-white text-slate-600 hover:bg-slate-100')
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
                'px-3 py-1 text-sm border-l border-slate-300 ' +
                (statusFilter === 'closed'
                  ? 'bg-emerald-700 text-white border-emerald-700'
                  : 'bg-white text-slate-600 hover:bg-slate-100')
              }
              aria-pressed={statusFilter === 'closed'}
            >
              Closed
            </button>
          </div>
        )}
        <div className="flex items-center gap-1.5 border border-slate-300 rounded px-2 py-1 bg-white">
          <span aria-hidden="true" className="text-slate-400 text-sm">
            🔍
          </span>
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
        <div className="text-slate-500">
          {isThreadMode
            ? 'No tasks for this thread.'
            : isClosedView
              ? 'No closed tasks.'
              : 'No tasks. All clear.'}
        </div>
      )}
      {pinnedTasks.length > 0 && (
        <section className="mb-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-amber-700 mb-2">
            📌 Pinned ({pinnedTasks.length})
          </h2>
          <div className="space-y-3">{pinnedTasks.map(renderTask)}</div>
        </section>
      )}
      {URGENCY_ORDER.map((u) => {
        const list = grouped[u]
        if (!list || list.length === 0) return null
        return (
          <section key={u} className="mb-6">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-600 mb-2">
              {u} ({list.length})
            </h2>
            <div className="space-y-3">{list.map(renderTask)}</div>
          </section>
        )
      })}
    </div>
  )
}
