import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  ReactNode,
  createElement
} from 'react'
import type { ZylchTask } from '../types'
import { errorMessage, isProfileLockedError } from '../lib/errors'

// Shared tasks store so the Update view can invalidate the Dashboard's
// list after `update.run` finishes. Without this, Dashboard only loads
// tasks on mount and stays stale after Update.

type Ctx = {
  tasks: ZylchTask[]
  loading: boolean
  error: string | null
  /** Fetch fresh tasks from the sidecar. No caching; always hits RPC. */
  refresh: () => Promise<void>
  /** Optimistic in-place update — used by Dashboard item actions. */
  setTasks: React.Dispatch<React.SetStateAction<ZylchTask[]>>
}

const TasksContext = createContext<Ctx | null>(null)

export function TasksProvider({ children }: { children: ReactNode }): JSX.Element {
  const [tasks, setTasks] = useState<ZylchTask[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Guard against races where a stale fetch resolves after a newer one
  // (e.g. user clicks Refresh twice in quick succession). We only apply
  // the result of the most recently started fetch.
  const reqIdRef = useRef(0)

  const refresh = useCallback(async () => {
    const myId = ++reqIdRef.current
    setLoading(true)
    setError(null)
    try {
      const r = await window.zylch.tasks.list()
      if (myId !== reqIdRef.current) return // stale
      setTasks(r)
    } catch (e: unknown) {
      if (myId !== reqIdRef.current) return // stale
      if (isProfileLockedError(e)) {
        setError(null)
      } else {
        setError(errorMessage(e))
      }
    } finally {
      if (myId === reqIdRef.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const value: Ctx = { tasks, loading, error, refresh, setTasks }
  return createElement(TasksContext.Provider, { value }, children)
}

export function useTasks(): Ctx {
  const ctx = useContext(TasksContext)
  if (!ctx) throw new Error('useTasks must be used within TasksProvider')
  return ctx
}
