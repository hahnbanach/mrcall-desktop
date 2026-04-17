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
  setActiveThreadId: (id: string | null) => void
}

const ThreadContext = createContext<Ctx | null>(null)

export function ThreadProvider({ children }: { children: ReactNode }) {
  const [activeThreadId, setActiveThreadIdRaw] = useState<string | null>(null)
  const setActiveThreadId = useCallback(
    (id: string | null) => setActiveThreadIdRaw(id),
    []
  )
  const value: Ctx = { activeThreadId, setActiveThreadId }
  return createElement(ThreadContext.Provider, { value }, children)
}

export function useThread(): Ctx {
  const ctx = useContext(ThreadContext)
  if (!ctx) throw new Error('useThread must be used within ThreadProvider')
  return ctx
}
