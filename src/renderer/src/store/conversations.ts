import {
  createContext,
  useContext,
  useReducer,
  useCallback,
  ReactNode,
  createElement
} from 'react'
import type { ZylchTask } from '../types'

export type Msg = { role: 'user' | 'assistant'; content: string }

export type Approval = {
  toolUseId: string
  name: string
  input: Record<string, unknown>
  preview: string
}

export type Conversation = {
  id: string
  title: string
  taskId?: string
  history: Msg[]
  draftInput: string
  pendingApproval: Approval | null
  busy: boolean
}

type State = {
  conversations: Conversation[]
  activeId: string
}

type Action =
  | { type: 'OPEN_TASK_CHAT'; conv: Conversation }
  | { type: 'CLOSE'; id: string }
  | { type: 'SET_ACTIVE'; id: string }
  | { type: 'APPEND_USER'; id: string; text: string }
  | { type: 'APPEND_ASSISTANT'; id: string; text: string }
  | { type: 'SET_DRAFT'; id: string; text: string }
  | { type: 'SET_PENDING'; id: string; approval: Approval | null }
  | { type: 'SET_BUSY'; id: string; busy: boolean }

const GENERAL: Conversation = {
  id: 'general',
  title: 'Chat generale',
  taskId: undefined,
  history: [],
  draftInput: '',
  pendingApproval: null,
  busy: false
}

const initialState: State = {
  conversations: [GENERAL],
  activeId: 'general'
}

const patch = (state: State, id: string, p: Partial<Conversation>): State => ({
  ...state,
  conversations: state.conversations.map((c) => (c.id === id ? { ...c, ...p } : c))
})

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'OPEN_TASK_CHAT': {
      const exists = state.conversations.find((c) => c.id === action.conv.id)
      const conversations = exists
        ? state.conversations.map((c) => (c.id === action.conv.id ? action.conv : c))
        : [...state.conversations, action.conv]
      return { ...state, conversations, activeId: action.conv.id }
    }
    case 'CLOSE': {
      if (action.id === 'general') return state
      const conversations = state.conversations.filter((c) => c.id !== action.id)
      const activeId = state.activeId === action.id ? 'general' : state.activeId
      return { conversations, activeId }
    }
    case 'SET_ACTIVE':
      return { ...state, activeId: action.id }
    case 'APPEND_USER': {
      const c = state.conversations.find((x) => x.id === action.id)
      if (!c) return state
      return patch(state, action.id, {
        history: [...c.history, { role: 'user', content: action.text }]
      })
    }
    case 'APPEND_ASSISTANT': {
      const c = state.conversations.find((x) => x.id === action.id)
      if (!c) return state
      return patch(state, action.id, {
        history: [...c.history, { role: 'assistant', content: action.text }]
      })
    }
    case 'SET_DRAFT':
      return patch(state, action.id, { draftInput: action.text })
    case 'SET_PENDING':
      return patch(state, action.id, { pendingApproval: action.approval })
    case 'SET_BUSY':
      return patch(state, action.id, { busy: action.busy })
  }
}

type Ctx = {
  state: State
  openTaskChat: (task: ZylchTask) => void
  closeConversation: (id: string) => void
  setActive: (id: string) => void
  appendUser: (id: string, text: string) => void
  appendAssistant: (id: string, text: string) => void
  setDraftInput: (id: string, text: string) => void
  setPendingApproval: (id: string, approval: Approval | null) => void
  setBusy: (id: string, busy: boolean) => void
}

const ConversationsContext = createContext<Ctx | null>(null)

function buildTemplate(t: ZylchTask): string {
  const name = t.contact_name || '—'
  const email = t.contact_email || '—'
  const urgency = t.urgency || '—'
  const action = t.suggested_action || '—'
  const reason = t.reason || '—'
  return [
    'Aiutami a gestire questa task.',
    '',
    `\u{1F4CB} ${name} <${email}>`,
    `Urgenza: ${urgency}`,
    '',
    'Cosa fare:',
    action,
    '',
    'Contesto:',
    reason
  ].join('\n')
}

export function ConversationsProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState)

  const openTaskChat = useCallback((task: ZylchTask) => {
    const id = 'task-' + task.id
    const title = task.contact_name || task.contact_email || task.id.slice(0, 8)
    dispatch({
      type: 'OPEN_TASK_CHAT',
      conv: {
        id,
        title,
        taskId: task.id,
        history: [],
        draftInput: buildTemplate(task),
        pendingApproval: null,
        busy: false
      }
    })
  }, [])

  const closeConversation = useCallback(
    (id: string) => dispatch({ type: 'CLOSE', id }),
    []
  )
  const setActive = useCallback((id: string) => dispatch({ type: 'SET_ACTIVE', id }), [])
  const appendUser = useCallback(
    (id: string, text: string) => dispatch({ type: 'APPEND_USER', id, text }),
    []
  )
  const appendAssistant = useCallback(
    (id: string, text: string) => dispatch({ type: 'APPEND_ASSISTANT', id, text }),
    []
  )
  const setDraftInput = useCallback(
    (id: string, text: string) => dispatch({ type: 'SET_DRAFT', id, text }),
    []
  )
  const setPendingApproval = useCallback(
    (id: string, approval: Approval | null) =>
      dispatch({ type: 'SET_PENDING', id, approval }),
    []
  )
  const setBusy = useCallback(
    (id: string, busy: boolean) => dispatch({ type: 'SET_BUSY', id, busy }),
    []
  )

  const value: Ctx = {
    state,
    openTaskChat,
    closeConversation,
    setActive,
    appendUser,
    appendAssistant,
    setDraftInput,
    setPendingApproval,
    setBusy
  }
  return createElement(ConversationsContext.Provider, { value }, children)
}

export function useConversations(): Ctx {
  const ctx = useContext(ConversationsContext)
  if (!ctx) throw new Error('useConversations must be used within ConversationsProvider')
  return ctx
}
