import {
  createContext,
  useContext,
  useState,
  ReactNode,
  createElement,
  useCallback
} from 'react'

type Ctx = {
  activeThreadId: string | null
  activeTaskId: string | null
  /**
   * When set, the Tasks view shows ONLY the tasks for this thread (via
   * `tasks.list_by_thread`) with a banner naming the thread and a reset
   * button. Set by the Email view's "Open" button; cleared by the banner's
   * reset button or any other navigation that wants the unfiltered list.
   */
  taskThreadFilter: { threadId: string; subject: string } | null
  setActiveThreadId: (id: string | null) => void
  setActiveTaskId: (id: string | null) => void
  setTaskThreadFilter: (
    value: { threadId: string; subject: string } | null
  ) => void
}

const ThreadContext = createContext<Ctx | null>(null)

export function ThreadProvider({ children }: { children: ReactNode }) {
  const [activeThreadId, setActiveThreadIdRaw] = useState<string | null>(null)
  const [activeTaskId, setActiveTaskIdRaw] = useState<string | null>(null)
  const [taskThreadFilter, setTaskThreadFilterRaw] = useState<
    { threadId: string; subject: string } | null
  >(null)
  const setActiveThreadId = useCallback(
    (id: string | null) => setActiveThreadIdRaw(id),
    []
  )
  const setActiveTaskId = useCallback(
    (id: string | null) => setActiveTaskIdRaw(id),
    []
  )
  const setTaskThreadFilter = useCallback(
    (value: { threadId: string; subject: string } | null) =>
      setTaskThreadFilterRaw(value),
    []
  )
  const value: Ctx = {
    activeThreadId,
    activeTaskId,
    taskThreadFilter,
    setActiveThreadId,
    setActiveTaskId,
    setTaskThreadFilter
  }
  return createElement(ThreadContext.Provider, { value }, children)
}

export function useThread(): Ctx {
  const ctx = useContext(ThreadContext)
  if (!ctx) throw new Error('useThread must be used within ThreadProvider')
  return ctx
}
