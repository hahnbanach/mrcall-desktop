import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { useConversations, type Approval } from '../store/conversations'
import { useThread } from '../store/thread'
import { useNarration } from '../hooks/useNarration'
import ChatComposer, { type ChatComposerTaskContext } from '../components/ChatComposer'
import ThreadPanel from '../components/ThreadPanel'
import { errorMessage, isProfileLockedError, showError } from '../lib/errors'
import type { SolveEvent } from '../types'

interface Props {
  onGoToTasks?: () => void
}

/**
 * Workspace — unified conversation view (ex-Chat).
 *
 * Left sidebar: task conversations + "general".
 * Right pane:
 *   - Top: collapsible "Source" panel. Expanded by default when the
 *     active conversation has a taskId + threadId; absent for "general".
 *     For now we only render email threads; sourceType is plumbed
 *     through ThreadPanel so a WhatsApp source can slot in later.
 *   - Below: chat history + composer (same behaviour as the old Chat tab).
 *
 * Panel expanded/collapsed state is persisted per-conversation in a
 * local Map so toggling once on a task conversation sticks for that
 * task while you move around.
 */
export default function Workspace({ onGoToTasks }: Props = {}) {
  const {
    state,
    setActive,
    closeConversation,
    appendUser,
    appendAssistant,
    setDraftInput,
    setPendingApproval,
    setBusy,
    patchConversation
  } = useConversations()
  const { activeThreadId, activeTaskId, setActiveThreadId, setActiveTaskId } = useThread()

  const active = state.conversations.find((c) => c.id === state.activeId)!
  const scrollRef = useRef<HTMLDivElement>(null)
  const [completing, setCompleting] = useState(false)
  const [narrationSeed, setNarrationSeed] = useState<string>('')
  const [lastUserText, setLastUserText] = useState<string>('')

  // Per-conversation Source panel expansion state. Key: conversation.id.
  // If a conversation isn't in the map, fall back to the default rule
  // (expanded when taskId + threadId present, collapsed otherwise).
  const [panelExpanded, setPanelExpanded] = useState<Record<string, boolean>>({})

  // Thread ID to render in the Source panel. Priority:
  //   1. A thread-only conversation carries its thread id via the
  //      `thread-<threadId>` prefix contract (set by `openThreadChat`
  //      in Email view).
  //   2. Otherwise the conversation itself carries `threadId` — set
  //      by openTaskChat from `task.sources.thread_id`. This is the
  //      path that fixes the sidebar-switch staleness: every task
  //      conv knows its own thread, so changing conversation in the
  //      sidebar updates the Source panel without going through the
  //      global thread store.
  //   3. Fallback only: if a task conv was opened by a path that
  //      didn't set Conversation.threadId (legacy persisted convs
  //      from pre-fix) and the user navigated here via Tasks → Open,
  //      activeThreadId in the thread store may still match. Read it
  //      only when activeTaskId matches the active conv's taskId.
  const sourceThreadId = (() => {
    if (active.id.startsWith('thread-')) return active.id.slice('thread-'.length)
    if (active.threadId) return active.threadId
    if (!active.taskId) return null
    if (activeTaskId === active.taskId) return activeThreadId
    return null
  })()

  // Keep the global thread-store in sync when the user switches
  // conversation inside the sidebar. The Source panel reads its
  // thread id from `active.threadId` directly so this isn't strictly
  // required for the panel — but other views (e.g. Email's open-from-
  // thread shortcut) still consult the thread store, so we keep both
  // in lockstep with whatever conv is on screen.
  useEffect(() => {
    if (!active.taskId) {
      // "general" — clear task context; leave threadId alone so a
      // quick round-trip back to the task doesn't re-fetch.
      if (activeTaskId !== null) setActiveTaskId(null)
      return
    }
    if (activeTaskId !== active.taskId) {
      setActiveTaskId(active.taskId)
    }
    // Mirror the conversation's own threadId into the store. Setting
    // null when the conv has no threadId is the right behaviour —
    // anything else would surface a stale thread from a previous
    // selection.
    const next = active.threadId ?? null
    if (next !== activeThreadId) {
      setActiveThreadId(next)
    }
  }, [
    active.id,
    active.taskId,
    active.threadId,
    activeTaskId,
    activeThreadId,
    setActiveTaskId,
    setActiveThreadId
  ])

  // Build context for narration: prefer the last user message in history.
  const narrationContext = (() => {
    if (lastUserText) return lastUserText
    for (let i = active.history.length - 1; i >= 0; i -= 1) {
      const m = active.history[i]
      if (m.role === 'user' && m.content) return m.content
    }
    return ''
  })()
  const narration = useNarration(!!active.busy, narrationContext, narrationSeed)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [active.history, active.busy, active.pendingApproval])

  // Subscribe once per mount to pending_approval notifications; route by conversation_id.
  useEffect(() => {
    const off = window.zylch.onNotification('chat.pending_approval', (params: any) => {
      if (!params || typeof params !== 'object') return
      const convId: string = params.conversation_id || 'general'
      const approval: Approval = {
        mode: 'chat',
        toolUseId: params.tool_use_id,
        name: params.name,
        input: params.input || {},
        preview: params.preview || ''
      }
      setPendingApproval(convId, approval)
    })
    const offCtx = window.zylch.onNotification('chat.context', () => {
      // no-op for v1
    })
    return () => {
      off()
      offCtx()
    }
  }, [setPendingApproval])

  // Solve events: a parallel stream to chat.pending_approval. tasks.solve
  // runs on the *currently active* task conversation, so we route every
  // event to active.id. Engine guarantees one solve at a time
  // (asyncio.Lock), so there is no convId disambiguation problem here.
  useEffect(() => {
    const off = window.zylch.onNotification('tasks.solve.event', (event: SolveEvent) => {
      if (!event || typeof event !== 'object') return
      const convId = active.id
      switch (event.type) {
        case 'thinking':
          if (event.text && event.text.trim()) {
            appendAssistant(convId, event.text)
            // Reset narration so the static fallback ("Sto pensando…")
            // doesn't shout over the model's own text bubble.
            setNarrationSeed('')
          }
          break
        case 'tool_use_start':
          // Replace the narration with the current activity.
          // Italian phrasing because USER_LANGUAGE is Italian-first;
          // we re-evaluate localisation if/when we ship in another
          // language.
          setNarrationSeed(narrationForTool(event.name))
          break
        case 'tool_call_pending':
          setPendingApproval(convId, {
            mode: 'solve',
            toolUseId: event.tool_use_id,
            name: event.name,
            input: event.input || {},
            preview: event.preview || ''
          })
          // Hide the narration — the approval card is now the
          // user's full attention.
          setNarrationSeed('')
          break
        case 'tool_result':
          // Intentionally not rendered as a chat bubble — the model's
          // next `thinking` block is what the user reads, and dumping
          // search_memory output would defeat the brief-output rule.
          // We do however reset the narration: the tool finished and
          // we're back to "the model is thinking".
          setNarrationSeed('')
          break
        case 'done':
          setBusy(convId, false)
          setNarrationSeed('')
          break
        case 'error':
          appendAssistant(convId, '⚠ ' + (event.message || 'Solve error'))
          setBusy(convId, false)
          setNarrationSeed('')
          break
      }
    })
    return off
  }, [active.id, appendAssistant, setPendingApproval, setBusy])

  const send = async (
    text: string,
    attachmentPaths: string[],
    _ctx?: ChatComposerTaskContext
  ): Promise<void> => {
    if (!text || active.busy) return
    // Clear the per-conversation seed/template; subsequent re-mounts of
    // the composer (e.g. after switching tabs) should start empty.
    setDraftInput(active.id, '')
    appendUser(active.id, text)
    setLastUserText(text)
    setNarrationSeed('Sto pensando alla tua richiesta.')
    setBusy(active.id, true)
    const historySnapshot = active.history.map((m) => ({ role: m.role, content: m.content }))
    window.zylch.narration
      .predict(text, '')
      .then((r) => {
        const t = (r && typeof r.text === 'string' ? r.text.trim() : '') || ''
        if (t) setNarrationSeed(t)
      })
      .catch(() => {
        /* fallback seed already set */
      })
    try {
      const chatContext: Record<string, unknown> = {}
      if (active.taskId) chatContext.task_id = active.taskId
      if (active.sourceEmailId) chatContext.email_id = active.sourceEmailId
      if (attachmentPaths.length > 0) chatContext.attachment_paths = attachmentPaths
      const res = await window.zylch.chat.send(text, historySnapshot, {
        conversationId: active.id,
        context: chatContext
      })
      const content =
        (res && (res.response || res.message || res.content)) || JSON.stringify(res, null, 2)
      appendAssistant(active.id, content)
    } catch (e: unknown) {
      // Profile-locked: the SidecarStatusBanner is already shouting
      // about it; appending an "Error: …" assistant bubble would be
      // duplicate noise.
      if (!isProfileLockedError(e)) {
        appendAssistant(active.id, '**Error:** ' + errorMessage(e))
      }
      throw e
    } finally {
      setBusy(active.id, false)
      setNarrationSeed('')
    }
  }

  const onApproval = async (decision: 'once' | 'session' | 'deny') => {
    const pending = active.pendingApproval
    if (!pending) return
    setPendingApproval(active.id, null)
    try {
      if (pending.mode === 'solve') {
        if (decision === 'deny') {
          // Cancel the whole solve, don't just decline this tool.
          // Without this the engine would feed "User declined" back
          // to the model, which then proposes alternatives — defeats
          // the user's intent ("Annulla" means stop, let me write).
          // solveCancel resolves the pending future with
          // CancelledError; the engine's run() catches it and emits
          // a `done` event, the listener flips busy → false.
          await window.zylch.tasks.solveCancel()
          // Belt-and-suspenders: flip busy immediately so the
          // composer unlocks even if the done event is delayed by
          // the RPC round-trip.
          setBusy(active.id, false)
          setNarrationSeed('')
        } else {
          // tasks.solve has no "session" concept — it's one shot.
          // 'once' → approved, proceed with the tool.
          await window.zylch.tasks.solveApprove(pending.toolUseId, {
            approved: true
          })
        }
      } else {
        await window.zylch.chat.approve(pending.toolUseId, { mode: decision })
      }
    } catch (e: unknown) {
      if (!isProfileLockedError(e)) {
        appendAssistant(active.id, '**Approval error:** ' + errorMessage(e))
      }
    }
  }

  const markDone = async () => {
    if (!active.taskId) return
    setCompleting(true)
    try {
      await window.zylch.tasks.complete(active.taskId)
      const id = active.id
      closeConversation(id)
      // Also clear thread-store state: the panel would otherwise still
      // point at a closed task when the user returns.
      setActiveThreadId(null)
      setActiveTaskId(null)
      onGoToTasks?.()
    } catch (e: unknown) {
      showError(e, 'Complete failed:')
    } finally {
      setCompleting(false)
    }
  }

  const reopen = async () => {
    if (!active.taskId) return
    setCompleting(true)
    try {
      await window.zylch.tasks.reopen(active.taskId)
      // Flip read-only off so composer unlocks immediately. We do NOT
      // fire a fresh solve here: Reopen means the user wants control
      // back, not necessarily a new agent run. To trigger the agent
      // they just write something (chat.send) or close+open from
      // Tasks tab.
      patchConversation(active.id, { taskCompleted: false })
    } catch (e: unknown) {
      showError(e, 'Reopen failed:')
    } finally {
      setCompleting(false)
    }
  }

  // Decide panel expansion for the current conversation. User overrides
  // stored in `panelExpanded` win; otherwise use the default rule:
  // expanded whenever we have a thread to show.
  const defaultExpanded = !!sourceThreadId
  const isPanelExpanded = active.id in panelExpanded
    ? panelExpanded[active.id]
    : defaultExpanded

  return (
    <div className="flex h-full">
      <aside className="w-[220px] border-r bg-brand-light-grey flex flex-col">
        <div className="p-3 text-xs font-semibold uppercase tracking-wide text-brand-grey-80">
          Conversazioni
        </div>
        <div className="flex-1 overflow-y-auto">
          {state.conversations.map((c) => {
            const isActive = c.id === state.activeId
            const closable = c.id !== 'general'
            return (
              <div
                key={c.id}
                onClick={() => setActive(c.id)}
                className={
                  'group px-3 py-2 cursor-pointer border-l-2 flex items-center justify-between ' +
                  (isActive
                    ? 'bg-white border-brand-black'
                    : 'border-transparent hover:bg-brand-light-grey')
                }
              >
                <span className="text-sm truncate">{c.title}</span>
                {closable && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      closeConversation(c.id)
                    }}
                    className="ml-2 text-brand-mid-grey hover:text-brand-black opacity-0 group-hover:opacity-100"
                    title="Chiudi"
                  >
                    ×
                  </button>
                )}
              </div>
            )
          })}
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="flex items-center justify-between px-4 py-2 border-b bg-white">
          <div className="font-semibold truncate">{active.title}</div>
          {active.taskId && (
            <button
              onClick={active.taskCompleted ? reopen : markDone}
              disabled={completing}
              className="px-3 py-1.5 text-sm bg-brand-blue text-white rounded hover:bg-brand-grey-80 disabled:bg-brand-mid-grey"
            >
              {completing
                ? 'Attendere…'
                : active.taskCompleted
                  ? 'Riapri'
                  : 'Marca come fatta'}
            </button>
          )}
        </header>

        {/* Source panel: email thread preview for task OR thread-only
            conversations. Key by conversation id so React remounts and
            resets internal state when the user switches conversations. */}
        {sourceThreadId && (
          <ThreadPanel
            key={`source-${active.id}`}
            threadId={sourceThreadId}
            sourceType="email"
            initialExpanded={isPanelExpanded}
            onToggle={(expanded) =>
              setPanelExpanded((m) => ({ ...m, [active.id]: expanded }))
            }
          />
        )}

        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
          {active.history.length === 0 && !active.pendingApproval && !active.busy && (
            <div className="text-brand-grey-80 text-sm">
              {active.taskId
                ? active.taskCompleted
                  ? 'Task chiusa. Riapri per scrivere o lanciare l’agente.'
                  : 'Chiedi un follow-up o usa il bottone Marca come fatta.'
                : 'Ask MrCall Desktop anything about your tasks, emails, or contacts.'}
            </div>
          )}
          {active.history.map((m, i) => (
            <div
              key={i}
              className={
                'p-3 rounded-lg whitespace-pre-wrap ' +
                (m.role === 'user'
                  ? 'bg-brand-black text-white ml-12'
                  : 'bg-white border mr-12')
              }
            >
              {m.role === 'assistant' ? (
                <div className="prose prose-sm max-w-none whitespace-pre-wrap">
                  <ReactMarkdown>{m.content}</ReactMarkdown>
                </div>
              ) : (
                m.content
              )}
            </div>
          ))}
          {active.busy && !active.pendingApproval && (
            <div className="text-brand-grey-80 italic text-sm whitespace-pre-wrap">
              {narration || 'Sto pensando alla tua richiesta.'}
            </div>
          )}

          {active.pendingApproval && (
            <ApprovalCard
              approval={active.pendingApproval}
              onApproveOnce={() => onApproval('once')}
              onApproveSession={() => onApproval('session')}
              onDecline={() => onApproval('deny')}
            />
          )}
        </div>

        <ChatComposer
          key={active.id}
          onSubmit={send}
          disabled={!!active.busy || !!active.taskCompleted}
          placeholder={
            active.taskCompleted
              ? 'Task chiusa — riaprila per scrivere.'
              : 'Scrivi un messaggio…'
          }
          taskContext={{ taskId: active.taskId, emailId: active.sourceEmailId }}
          initialText={active.draftInput}
        />
      </div>
    </div>
  )
}

function ApprovalCard({
  approval,
  onApproveOnce,
  onApproveSession,
  onDecline
}: {
  approval: Approval
  onApproveOnce: () => void
  onApproveSession: () => void
  onDecline: () => void
}) {
  const isSolve = approval.mode === 'solve'
  // Solve is a one-shot agentic run: there are no future invocations
  // of this tool inside the same solve, so "Allow for session" is
  // meaningless. Chat flow keeps the three-button shape it had.
  const sendLabel = isSolve ? labelForSolve(approval.name) : 'Allow once'
  const denyLabel = isSolve ? 'Annulla' : 'Deny'
  return (
    <div className="border border-brand-orange bg-brand-orange/10 rounded-lg p-4 mr-12">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs px-2 py-0.5 bg-brand-orange/30 text-brand-orange rounded font-mono">
          {approval.name}
        </span>
        <span className="text-sm text-brand-orange font-medium">
          {isSolve ? 'Conferma per procedere' : 'Conferma richiesta'}
        </span>
      </div>
      {approval.preview && (
        <div className="text-sm text-brand-black mb-3 whitespace-pre-wrap">
          {approval.preview}
        </div>
      )}
      <div className="bg-white border border-brand-orange/30 rounded p-3 mb-3 space-y-2">
        {Object.entries(approval.input).map(([k, v]) => (
          <div key={k}>
            <div className="text-xs font-semibold uppercase tracking-wide text-brand-grey-80">
              {k}
            </div>
            <div className="text-sm text-brand-black whitespace-pre-wrap break-words">
              {typeof v === 'string' ? v : JSON.stringify(v, null, 2)}
            </div>
          </div>
        ))}
      </div>
      <div className="flex gap-2 flex-wrap">
        <button
          onClick={onApproveOnce}
          className="px-3 py-1.5 text-sm bg-brand-blue text-white rounded hover:bg-brand-grey-80"
        >
          {sendLabel}
        </button>
        {!isSolve && (
          <button
            onClick={onApproveSession}
            className="px-3 py-1.5 text-sm bg-brand-grey-80 text-white rounded hover:bg-brand-grey-80"
            title="Auto-approve this tool for the rest of this conversation"
          >
            Allow for session
          </button>
        )}
        <button
          onClick={onDecline}
          className="px-3 py-1.5 text-sm bg-brand-mid-grey text-brand-black rounded hover:bg-brand-mid-grey"
        >
          {denyLabel}
        </button>
      </div>
    </div>
  )
}

function labelForSolve(toolName: string): string {
  switch (toolName) {
    case 'send_email':
      return 'Invia email'
    case 'send_whatsapp':
      return 'Invia WhatsApp'
    case 'send_sms':
      return 'Invia SMS'
    case 'run_python':
      return 'Esegui'
    case 'update_memory':
      return 'Aggiorna memoria'
    default:
      return 'Conferma'
  }
}

/**
 * Narration line shown while a solve tool is running. The italian
 * phrasing matches USER_LANGUAGE=it; revisit when we ship in another
 * language. The fallback covers any tool we haven't enumerated —
 * still beats the static "Sto pensando alla tua richiesta."
 */
function narrationForTool(toolName: string): string {
  switch (toolName) {
    case 'search_memory':
      return 'Sto cercando nella memoria…'
    case 'search_emails':
      return 'Sto cercando nelle email…'
    case 'read_document':
      return 'Sto leggendo il documento…'
    case 'download_attachment':
      return 'Sto scaricando l’allegato…'
    case 'web_search':
      return 'Sto cercando sul web…'
    case 'run_python':
      return 'Sto eseguendo il codice…'
    case 'update_memory':
      return 'Sto aggiornando la memoria…'
    case 'send_email':
      return 'Sto inviando l’email…'
    case 'send_whatsapp':
      return 'Sto inviando il WhatsApp…'
    case 'send_sms':
      return 'Sto inviando l’SMS…'
    default:
      return `Sto eseguendo ${toolName}…`
  }
}
