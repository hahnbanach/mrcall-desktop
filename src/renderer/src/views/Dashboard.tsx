import { useEffect, useState } from 'react'
import type { ZylchTask } from '../types'
import { useConversations } from '../store/conversations'

interface Props {
  onOpenChat?: () => void
}

const URGENCY_ORDER = ['high', 'medium', 'low']
const URGENCY_STYLES: Record<string, string> = {
  high: 'bg-red-100 text-red-800 border-red-300',
  medium: 'bg-amber-100 text-amber-800 border-amber-300',
  low: 'bg-slate-100 text-slate-700 border-slate-300'
}

export default function Dashboard({ onOpenChat }: Props = {}) {
  const { openTaskChat } = useConversations()
  const [tasks, setTasks] = useState<ZylchTask[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await window.zylch.tasks.list()
      setTasks(r)
    } catch (e: any) {
      setError(e.message || String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const onSkip = async (id: string) => {
    try {
      await window.zylch.tasks.skip(id)
      setTasks((t) => t.filter((x) => x.id !== id))
    } catch (e: any) {
      alert('Skip failed: ' + e.message)
    }
  }
  const onClose = async (id: string) => {
    try {
      await window.zylch.tasks.complete(id)
      setTasks((t) => t.filter((x) => x.id !== id))
    } catch (e: any) {
      alert('Close failed: ' + e.message)
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

  if (loading) return <div className="p-8 text-slate-500">Loading tasks…</div>
  if (error)
    return (
      <div className="p-8">
        <div className="text-red-700">Error: {error}</div>
        <button
          onClick={load}
          className="mt-3 px-3 py-1.5 bg-slate-900 text-white rounded text-sm"
        >
          Retry
        </button>
      </div>
    )

  const grouped: Record<string, ZylchTask[]> = {}
  for (const t of tasks) {
    const k = (t.urgency || 'low').toLowerCase()
    ;(grouped[k] ||= []).push(t)
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-semibold">Tasks ({tasks.length})</h1>
        <button
          onClick={load}
          className="px-3 py-1.5 text-sm border rounded hover:bg-slate-100"
        >
          Refresh
        </button>
      </div>
      {tasks.length === 0 && (
        <div className="text-slate-500">No tasks. All clear.</div>
      )}
      {URGENCY_ORDER.map((u) => {
        const list = grouped[u]
        if (!list || list.length === 0) return null
        return (
          <section key={u} className="mb-6">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-600 mb-2">
              {u} ({list.length})
            </h2>
            <div className="space-y-3">
              {list.map((t) => (
                <article
                  key={t.id}
                  className="bg-white border rounded-lg p-4 shadow-sm"
                >
                  <div className="flex items-start justify-between gap-3 mb-2">
                    <div>
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
                    <div className="text-sm text-slate-700 whitespace-pre-wrap border-l-2 border-slate-200 pl-3 mb-3">
                      {t.reason}
                    </div>
                  )}
                  <div className="flex gap-2">
                    <button
                      onClick={() => onSkip(t.id)}
                      className="px-3 py-1.5 text-sm border rounded hover:bg-slate-100"
                    >
                      Skip
                    </button>
                    <button
                      onClick={() => onClose(t.id)}
                      className="px-3 py-1.5 text-sm bg-slate-900 text-white rounded hover:bg-slate-700"
                    >
                      Close
                    </button>
                    <button
                      onClick={() => {
                        openTaskChat(t)
                        onOpenChat?.()
                      }}
                      className="px-3 py-1.5 text-sm border rounded hover:bg-slate-100"
                    >
                      Solve
                    </button>
                  </div>
                </article>
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}
