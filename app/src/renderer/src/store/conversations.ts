import {
  createContext,
  useContext,
  useEffect,
  useReducer,
  useCallback,
  useState,
  useRef,
  ReactNode,
  createElement
} from 'react'
import type { ZylchTask } from '../types'

// Where we stash conversations between renderer reloads (Cmd+R,
// Electron restart, crash). Key is per-profile so two windows bound
// to different profiles don't stomp on each other.
const STORAGE_KEY_PREFIX = 'zylch:conversations:'

function loadPersisted(profile: string): State | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_PREFIX + profile)
    if (!raw) return null
    const parsed = JSON.parse(raw) as State
    if (!parsed || !Array.isArray(parsed.conversations)) return null
    // Reset ephemeral fields on restore: a dangling in-flight RPC can't
    // be resumed, and a stale approval prompt would fire against a tool
    // call the sidecar has already forgotten.
    // Also wipe any pre-fix draftInput on task-conversations with empty
    // history — those persist the old "Aiutami a gestire questa task…"
    // template from before the agent-first refactor. Free-chat (no
    // taskId) conversations keep their draft so an in-flight draft
    // survives a reload.
    const conversations = parsed.conversations.map((c) => {
      const isStaleTaskDraft = !!c.taskId && (c.history?.length ?? 0) === 0
      return {
        ...c,
        busy: false,
        pendingApproval: null,
        draftInput: isStaleTaskDraft ? '' : c.draftInput
      }
    })
    const activeId = conversations.some((c) => c.id === parsed.activeId)
      ? parsed.activeId
      : 'general'
    return { conversations, activeId }
  } catch {
    return null
  }
}

function savePersisted(profile: string, state: State): void {
  try {
    localStorage.setItem(STORAGE_KEY_PREFIX + profile, JSON.stringify(state))
  } catch {
    /* quota exceeded or storage unavailable — degrade silently */
  }
}

export type Msg = { role: 'user' | 'assistant'; content: string }

export type Approval = {
  /**
   * Which RPC surface produced this approval prompt — drives which
   * engine method the renderer calls back on:
   *   - 'chat'  → chat.approve (existing free-chat flow)
   *   - 'solve' → tasks.solve.approve (Open-from-Tasks agentic flow)
   * The card visual differs slightly: 'solve' has no "session"
   * variant (a solve is one-shot — no future invocations to
   * pre-authorise).
   */
  mode: 'chat' | 'solve'
  toolUseId: string
  name: string
  input: Record<string, unknown>
  preview: string
}

export type Conversation = {
  id: string
  title: string
  taskId?: string
  // Set when this conversation was opened directly from a thread (Email
  // view "Open" button). For task-backed conversations the thread id
  // lives in the thread store and is resolved via activeThreadId —
  // this field is only populated for thread-only conversations whose
  // id follows the `thread-<threadId>` convention.
  threadId?: string
  sourceEmailId?: string
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
  openThreadChat: (threadId: string, subject: string, sourceEmailId?: string) => void
  closeConversation: (id: string) => void
  setActive: (id: string) => void
  appendUser: (id: string, text: string) => void
  appendAssistant: (id: string, text: string) => void
  setDraftInput: (id: string, text: string) => void
  setPendingApproval: (id: string, approval: Approval | null) => void
  setBusy: (id: string, busy: boolean) => void
  /** Whether `id` is currently driving an in-flight tasks.solve.
   *  Used by Workspace.tsx to disable the composer while the agent
   *  is mid-run, and by closeConversation to fire solveCancel. */
  isSolveBusy: (id: string) => boolean
}

const ConversationsContext = createContext<Ctx | null>(null)

// Tracks the conversation id whose tasks.solve call is in flight.
// Module-level Map (not React state) because the solve runs as a
// fire-and-forget Promise outside the reducer — the listener in
// Workspace.tsx is what feeds the conversation; this map is just
// the cancel handle used by closeConversation.
const solvesInFlight = new Set<string>()

export function ConversationsProvider({ children }: { children: ReactNode }) {
  // Resolve the profile key for localStorage on mount and remember it.
  // zylch.profile.current() is a fire-and-forget at render time; before
  // it resolves we fall back to a neutral "unknown" key so no data is
  // lost if the user starts typing before the IPC returns.
  const [profileKey, setProfileKey] = useState<string>('unknown')
  useEffect(() => {
    let cancelled = false
    window.zylch.profile
      .current()
      .then((p) => {
        // Persist by stable id (Firebase UID for new profiles, email
        // for legacy) so the localStorage bucket survives email
        // changes — the user's email-as-display lives only in the UI.
        if (!cancelled && p && p.id) setProfileKey(p.id)
      })
      .catch(() => {
        /* leave key as 'unknown' */
      })
    return () => {
      cancelled = true
    }
  }, [])

  const [state, dispatch] = useReducer(reducer, initialState, (init) => {
    // Try the 'unknown' bucket first (set at the very first render);
    // once profileKey resolves we re-hydrate via the effect below.
    const persisted = loadPersisted('unknown')
    return persisted ?? init
  })

  // When the real profile key becomes available, re-hydrate from its
  // own bucket (if present). This happens once, before any meaningful
  // user interaction.
  useEffect(() => {
    if (profileKey === 'unknown') return
    const persisted = loadPersisted(profileKey)
    if (persisted) {
      // Replace the whole state atomically — OPEN_TASK_CHAT is already
      // an upsert, so replay each conversation and leave the active id.
      // We dispatch SET_ACTIVE after re-opening to make sure the target
      // survives even if 'general' was the last active.
      for (const c of persisted.conversations) {
        if (c.id === 'general') continue
        dispatch({ type: 'OPEN_TASK_CHAT', conv: c })
      }
      dispatch({ type: 'SET_ACTIVE', id: persisted.activeId })
    }
  }, [profileKey])

  // Persist on every state change, keyed by the active profile. Writes
  // are cheap (JSON.stringify of a few KB) and happen on the UI thread;
  // at this scale the overhead is invisible.
  useEffect(() => {
    savePersisted(profileKey, state)
  }, [profileKey, state])

  // Mirror state into a ref so the stable-identity callbacks below can
  // read it without re-creating themselves on every render. Without
  // this, openTaskChat would change identity on every state update and
  // any consumer hook calling it inside its own effect would loop.
  const stateRef = useRef(state)
  useEffect(() => {
    stateRef.current = state
  }, [state])

  const openTaskChat = useCallback((task: ZylchTask) => {
    const id = 'task-' + task.id
    const title = task.contact_name || task.contact_email || task.id.slice(0, 8)
    // Source email id from task.sources.emails[0] if present — kept on
    // the conversation so free-text follow-ups (post-solve) can pass
    // it to chat.send.
    const sourceEmailId =
      task.sources && Array.isArray(task.sources.emails) && task.sources.emails.length > 0
        ? task.sources.emails[0]
        : undefined
    // Persist the source thread id ON the conversation so the Source
    // panel renders the right thread when the user switches between
    // conversations in the sidebar. Without this, only the global
    // thread-store's `activeThreadId` carries it — and that store is
    // not refreshed on sidebar-driven conversation switches, leading
    // to a stale thread being shown over the new conversation.
    // Engine guarantees `sources.thread_id` is populated for task
    // rows (see engine/zylch/storage/database._backfill_task_thread_id).
    const sourceThreadId =
      task.sources && typeof task.sources.thread_id === 'string'
        ? task.sources.thread_id
        : undefined

    // If we're re-opening a task conversation that already has
    // history (user clicked Open twice, or this was restored from
    // localStorage after a reload), don't fire a fresh solve —
    // single solve at a time engine-side, and the previous one
    // already produced an answer worth keeping. The user can ask
    // follow-ups via the composer (chat.send) without re-paying for
    // the agent loop.
    const existing = stateRef.current.conversations.find((c) => c.id === id)
    const shouldStartSolve =
      !existing || (existing.history.length === 0 && !existing.pendingApproval)

    dispatch({
      type: 'OPEN_TASK_CHAT',
      conv: {
        id,
        title,
        taskId: task.id,
        threadId: sourceThreadId,
        sourceEmailId,
        history: existing?.history ?? [],
        draftInput: '',
        pendingApproval: existing?.pendingApproval ?? null,
        // Busy stays true until tasks.solve resolves OR the listener
        // sees `done` / `error`. Whichever fires first flips it back.
        busy: shouldStartSolve
      }
    })

    if (!shouldStartSolve) return
    if (solvesInFlight.has(id)) return

    solvesInFlight.add(id)
    window.zylch.tasks
      .solve(task.id)
      .then((res) => {
        if (!res?.ok) {
          // Push an assistant bubble with the engine's error so the
          // user sees what went wrong (most likely: no Anthropic key
          // AND no Firebase signin — make_llm_client refuses).
          dispatch({
            type: 'APPEND_ASSISTANT',
            id,
            text: '⚠ ' + (res?.error || 'Solve failed without an error message.')
          })
        }
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : String(e)
        dispatch({
          type: 'APPEND_ASSISTANT',
          id,
          text: '⚠ Solve RPC failed: ' + msg
        })
      })
      .finally(() => {
        solvesInFlight.delete(id)
        dispatch({ type: 'SET_BUSY', id, busy: false })
      })
  }, [])

  // Open a thread-only conversation (no task attached). Used by Email
  // view's "Open" button. Conversation id is `thread-<threadId>` —
  // Workspace relies on this prefix contract to resolve the Source
  // panel when no activeThreadId is set from the thread store.
  const openThreadChat = useCallback(
    (threadId: string, subject: string, sourceEmailId?: string) => {
      const id = 'thread-' + threadId
      const title = subject || threadId.slice(0, 20)
      dispatch({
        type: 'OPEN_TASK_CHAT',
        conv: {
          id,
          title,
          taskId: undefined,
          threadId,
          sourceEmailId,
          history: [],
          draftInput: '',
          pendingApproval: null,
          busy: false
        }
      })
    },
    []
  )

  const closeConversation = useCallback((id: string) => {
    // If a solve is in flight on this conversation, ask the engine to
    // abort. Best-effort — the engine's _solve_lock releases on its
    // own at timeout, so even if the cancel RPC fails the system
    // recovers; we just save the user the wait.
    if (solvesInFlight.has(id)) {
      void window.zylch.tasks.solveCancel().catch(() => {
        /* engine may be down or the lock may have already cleared */
      })
    }
    dispatch({ type: 'CLOSE', id })
  }, [])

  const isSolveBusy = useCallback((id: string): boolean => {
    return solvesInFlight.has(id)
  }, [])
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
    openThreadChat,
    closeConversation,
    setActive,
    appendUser,
    appendAssistant,
    setDraftInput,
    setPendingApproval,
    setBusy,
    isSolveBusy
  }
  return createElement(ConversationsContext.Provider, { value }, children)
}

export function useConversations(): Ctx {
  const ctx = useContext(ConversationsContext)
  if (!ctx) throw new Error('useConversations must be used within ConversationsProvider')
  return ctx
}
