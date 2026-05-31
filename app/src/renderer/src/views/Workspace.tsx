import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { useConversations, type Approval } from '../store/conversations'
import { useTasks } from '../store/tasks'
import { useThread } from '../store/thread'
import { useNarration } from '../hooks/useNarration'
import ChatComposer, { type ChatComposerTaskContext } from '../components/ChatComposer'
import ThreadPanel from '../components/ThreadPanel'
import Icon from '../components/Icon'
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
    markSolveStarted,
    markSolveFinished,
    patchConversation
  } = useConversations()
  const { refresh: refreshTasks } = useTasks()
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

  /**
   * Resolve the two channel-specific thread identifiers ThreadPanel
   * needs (whatsapp-pipeline-parity Fase 4 cross-channel UI).
   *
   * `waChatJid` is the explicit pointer the engine stamps on
   * `task.sources.whatsapp_chat_jid` whenever the task has any WA
   * touchpoint. `openTaskChat` carries it onto `Conversation.waChatJid`.
   *
   * `emailThreadId` is `sourceThreadId` unless `sourceThreadId` is
   * itself a WA chat_jid — that happens for WA-only tasks where the
   * engine reuses `sources.thread_id` to mean "the WA chat" (no
   * separate email cluster exists). In that case we suppress
   * `emailThreadId` so ThreadPanel doesn't try to fetch an email
   * thread that doesn't exist.
   */
  const waChatJid: string | null = active.waChatJid ?? null
  const sourceTidIsWa =
    !!sourceThreadId &&
    (sourceThreadId.endsWith('@s.whatsapp.net') || sourceThreadId.endsWith('@lid'))
  const emailThreadId: string | null = sourceTidIsWa ? null : sourceThreadId

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

  // Solve events: a parallel stream to chat.pending_approval. With
  // multiple solves potentially queued at once (engine serialises
  // execution but accepts the queue), every event carries a `task_id`
  // and we route it to the conversation `'task-' + task_id`. The old
  // "attribute to active.id" contract is gone because more than one
  // conversation can be running/queued simultaneously, and the user
  // can be looking at any of them when an event for another arrives.
  //
  // Narration is per-window (not per-conversation today), so we only
  // mutate it when the event belongs to the conversation the user is
  // currently looking at.
  useEffect(() => {
    const off = window.zylch.onNotification('tasks.solve.event', (event: SolveEvent) => {
      if (!event || typeof event !== 'object') return
      const taskId = event.task_id
      // Defensive: ignore events without task_id (would only happen if
      // an older engine is paired with this renderer — should not in
      // practice since the engine ships in the same bundle).
      if (!taskId) return
      const convId = 'task-' + taskId
      const isActive = convId === active.id
      switch (event.type) {
        case 'queued':
          // Engine acquired the queue slot but hasn't entered the lock
          // yet. Keep busy=true (the conversation is in flight in the
          // user's mental model) but skip narration — the static
          // fallback would say "Sto pensando…" which is misleading
          // when nothing is actually thinking yet. The user-visible
          // "in coda" affordance lives in the conversation row /
          // ChatComposer placeholder.
          setBusy(convId, true)
          break
        case 'starting':
          // Lock acquired, model work begins. Narration kicks in.
          setBusy(convId, true)
          if (isActive) setNarrationSeed('Sto pensando alla tua richiesta.')
          break
        case 'thinking':
          if (event.text && event.text.trim()) {
            appendAssistant(convId, event.text)
            if (isActive) setNarrationSeed('')
          }
          break
        case 'tool_use_start':
          if (isActive) setNarrationSeed(narrationForTool(event.name))
          break
        case 'tool_call_pending':
          setPendingApproval(convId, {
            mode: 'solve',
            toolUseId: event.tool_use_id,
            name: event.name,
            input: event.input || {},
            preview: event.preview || ''
          })
          if (isActive) setNarrationSeed('')
          break
        case 'tool_result':
          if (isActive) setNarrationSeed('')
          break
        case 'done':
          setBusy(convId, false)
          markSolveFinished(convId)
          if (isActive) setNarrationSeed('')
          // Auto-reanalyze decision from the engine. When a mutating
          // solve flips the task to "closed", reflect it here so the
          // composer locks and the user sees the result without
          // navigating back to Tasks. Crucially we also refresh the
          // shared Tasks store — without that the Tasks tab keeps
          // showing the just-closed row until the user manually
          // refreshes (the symptom Mario hit on the Samo Vojnovic
          // task: "in Chat dice chiusa ma in Task la vedo sempre").
          if (event.result?.auto_reanalyzed?.action === 'closed') {
            patchConversation(convId, { taskCompleted: true })
            appendAssistant(
              convId,
              '✓ Task chiusa automaticamente — ' +
                (event.result.auto_reanalyzed.reason || 'la riconciliazione ha rilevato la risoluzione.')
            )
            void refreshTasks()
          } else if (event.result?.auto_reanalyzed?.action === 'updated') {
            appendAssistant(
              convId,
              'ℹ Task aggiornata — ' +
                (event.result.auto_reanalyzed.reason || 'nuovo stato applicato.')
            )
            void refreshTasks()
          }
          break
        case 'error':
          appendAssistant(convId, '⚠ ' + (event.message || 'Solve error'))
          setBusy(convId, false)
          markSolveFinished(convId)
          if (isActive) setNarrationSeed('')
          break
      }
    })
    return off
  }, [
    active.id,
    appendAssistant,
    setPendingApproval,
    setBusy,
    markSolveFinished,
    patchConversation,
    refreshTasks
  ])

  // Solve handler — wired to the lightbulb button next to "Invia". Pipes
  // the user's typed text into `tasks.solve(task_id, instructions=text)`
  // so the engine builds SOLVE_SYSTEM_PROMPT with the task context AND
  // appends the user's instructions as the first user message. Empty
  // text is allowed (acts as "fire the agent with no extra hints",
  // same as the legacy auto-solve that used to fire on Open). Live
  // progress streams through the existing `tasks.solve.event` listener
  // above; this function only kicks off the RPC and echoes the text
  // into the visible history.
  const solve = async (
    text: string,
    _attachmentPaths: string[],
    _ctx?: ChatComposerTaskContext
  ): Promise<void> => {
    if (active.busy) return
    if (!active.taskId) {
      // Defensive — Workspace only renders the Solve button on task
      // conversations, but a stale render or a future caller might
      // slip through. Surface it instead of silently swallowing.
      appendAssistant(active.id, '**Solve unavailable:** this conversation has no task.')
      return
    }
    setDraftInput(active.id, '')
    if (text) appendUser(active.id, text)
    setBusy(active.id, true)
    setNarrationSeed('Sto pensando alla tua richiesta.')
    // Register the in-flight solve so closeConversation can target the
    // right task_id when the user dismisses the tab mid-run.
    markSolveStarted(active.id, active.taskId)
    try {
      const res = await window.zylch.tasks.solve(active.taskId, text || undefined)
      if (!res?.ok) {
        appendAssistant(active.id, '⚠ ' + (res?.error || 'Solve failed without an error message.'))
        setBusy(active.id, false)
        setNarrationSeed('')
        markSolveFinished(active.id)
      }
    } catch (e: unknown) {
      if (!isProfileLockedError(e)) {
        appendAssistant(active.id, '**Solve error:** ' + errorMessage(e))
      }
      setBusy(active.id, false)
      setNarrationSeed('')
      markSolveFinished(active.id)
      throw e
    }
    // Note: we do NOT flip busy=false on success. The `tasks.solve.event`
    // 'done' (or 'error') event handles it — same path the legacy
    // auto-solve relied on. `markSolveFinished` is also called there.
  }

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

  const onApproval = async (
    decision: 'once' | 'session' | 'deny',
    editedInput?: Record<string, unknown>
  ) => {
    const pending = active.pendingApproval
    if (!pending) return
    setPendingApproval(active.id, null)
    try {
      if (pending.mode === 'solve') {
        if (decision === 'deny') {
          // Cancel THIS conversation's solve specifically (engine
          // accepts task_id since the queued-solve refactor — other
          // queued conversations stay alive). Without a task_id arg
          // the engine falls back to the legacy "active executor"
          // path which still works when this conversation is the
          // active one (which it has to be, since `pending` came from
          // its approval card).
          await window.zylch.tasks.solveCancel(active.taskId)
          // Belt-and-suspenders: flip busy immediately so the
          // composer unlocks even if the done event is delayed by
          // the RPC round-trip.
          setBusy(active.id, false)
          setNarrationSeed('')
        } else {
          // tasks.solve has no "session" concept — it's one shot.
          // 'once' → approved, proceed with the tool. `editedInput`
          // carries any changes the user made to the draft (email
          // body, WhatsApp message, recipient) in the approval card;
          // the engine's executor swaps it in for the tool's original
          // input (task_executor.py: decision.edited_input).
          await window.zylch.tasks.solveApprove(pending.toolUseId, {
            approved: true,
            edited_input: editedInput ?? null
          })
        }
      } else {
        // Chat-flow approval. For send tools the card is editable, so
        // forward the edited input (recipient / body the user fixed);
        // the engine swaps it in before the tool runs. A deny carries no
        // payload.
        await window.zylch.chat.approve(pending.toolUseId, {
          mode: decision,
          edited_input: decision === 'deny' ? undefined : editedInput
        })
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
          <div className="flex items-center gap-1 shrink-0">
            {/* Trash: discard this conversation's history. Same effect as
                the × in the sidebar, surfaced here where it's discoverable.
                Re-opening the task from the Tasks tab recomputes a fresh
                solve. Available for any non-general conversation. */}
            {active.id !== 'general' && (
              <button
                onClick={() => {
                  const id = active.id
                  closeConversation(id)
                  setActiveThreadId(null)
                  setActiveTaskId(null)
                }}
                disabled={completing}
                className="p-1.5 rounded text-brand-grey-80 hover:text-brand-danger hover:bg-brand-light-grey disabled:opacity-50"
                title="Trash conversation, will be re-computed if re-opened from Tasks"
                aria-label="Trash conversation"
              >
                <Icon name="trash" size={18} />
              </button>
            )}
            {/* Done / Reopen, now icon-only. Check = mark the task done
                (removes it from open Tasks); reopen ring = bring a closed
                task back under your control. */}
            {active.taskId && (
              <button
                onClick={active.taskCompleted ? reopen : markDone}
                disabled={completing}
                className={
                  'p-1.5 rounded disabled:opacity-50 ' +
                  (active.taskCompleted
                    ? 'text-brand-grey-80 hover:text-brand-black hover:bg-brand-light-grey'
                    : 'text-brand-blue hover:bg-brand-blue/10')
                }
                title={
                  active.taskCompleted
                    ? 'Reopen this task to write or run the agent again'
                    : 'Mark this task as done — removes it from your open Tasks'
                }
                aria-label={active.taskCompleted ? 'Reopen task' : 'Mark task as done'}
              >
                <Icon name={active.taskCompleted ? 'reopen' : 'check'} size={18} />
              </button>
            )}
          </div>
        </header>

        {/* Source panel: email thread preview for task OR thread-only
            conversations. Key by conversation id so React remounts and
            resets internal state when the user switches conversations. */}
        {(emailThreadId || waChatJid) && (
          <ThreadPanel
            key={`source-${active.id}`}
            emailThreadId={emailThreadId}
            whatsappChatJid={waChatJid}
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
              onApproveOnce={(edited) => onApproval('once', edited)}
              onApproveSession={() => onApproval('session')}
              onDecline={() => onApproval('deny')}
            />
          )}
        </div>

        <ChatComposer
          key={active.id}
          onSubmit={send}
          onSolve={active.taskId ? solve : undefined}
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
  onApproveOnce: (editedInput?: Record<string, unknown>) => void
  onApproveSession: () => void
  onDecline: () => void
}) {
  const isSolve = approval.mode === 'solve'
  // Send tools never use "Allow once / Allow for session / Deny"
  // permission semantics, in EITHER flow. For an outgoing message:
  //   - "Allow for session" is dangerous — it would auto-send every
  //     future message in the conversation with no confirmation.
  //   - "Allow once" reads as "grant a permission", not "send THIS
  //     now", which led a user to send an unintended message.
  // So a send card always shows explicit Send / Cancel and never a
  // session grant. Non-send gated tools in chat (run_python,
  // update_memory) keep the permission triad.
  const isSend = SEND_TOOLS.has(approval.name)
  const sendCardUx = isSolve || isSend
  const sendLabel = sendCardUx ? labelForSolve(approval.name) : 'Allow once'
  const denyLabel = sendCardUx ? 'Annulla' : 'Deny'

  // Editable copy of the tool input. The user can fix the draft (email
  // body, WhatsApp/SMS message, recipient) before sending. Re-seeded
  // whenever a new approval arrives (keyed by toolUseId) so a stale edit
  // never leaks into a different tool call. Only string fields are
  // editable; non-string values (rare) stay read-only JSON.
  const [edited, setEdited] = useState<Record<string, unknown>>(approval.input)
  useEffect(() => {
    setEdited(approval.input)
  }, [approval.toolUseId])

  const setField = (k: string, v: string): void => {
    setEdited((prev) => ({ ...prev, [k]: v }))
  }

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
        {Object.entries(edited).map(([k, v]) => {
          const label = (
            <div className="text-xs font-semibold uppercase tracking-wide text-brand-grey-80 mb-0.5">
              {k}
            </div>
          )
          // Editable for send tools in BOTH flows (solve via
          // solveApprove.edited_input, chat via chat.approve.edited_input).
          // Non-string values, and non-send gated tools (run_python,
          // update_memory) in chat, stay read-only.
          if (typeof v !== 'string' || !sendCardUx) {
            return (
              <div key={k}>
                {label}
                <div className="text-sm text-brand-black whitespace-pre-wrap break-words">
                  {typeof v === 'string' ? v : JSON.stringify(v, null, 2)}
                </div>
              </div>
            )
          }
          // Multi-line / long values (email & WhatsApp bodies) get a
          // textarea; short scalars (recipient, subject, phone) get a
          // single-line input.
          const multiline = v.includes('\n') || v.length > 80
          return (
            <div key={k}>
              {label}
              {multiline ? (
                <textarea
                  value={v}
                  onChange={(e) => setField(k, e.target.value)}
                  rows={Math.min(12, Math.max(3, v.split('\n').length + 1))}
                  className="w-full px-2 py-1 text-sm border border-brand-mid-grey rounded focus:outline-none focus:ring-2 focus:ring-brand-orange/40 font-sans"
                />
              ) : (
                <input
                  type="text"
                  value={v}
                  onChange={(e) => setField(k, e.target.value)}
                  className="w-full px-2 py-1 text-sm border border-brand-mid-grey rounded focus:outline-none focus:ring-2 focus:ring-brand-orange/40"
                />
              )}
            </div>
          )
        })}
      </div>
      <div className="flex gap-2 flex-wrap">
        <button
          onClick={() => onApproveOnce(edited)}
          className="px-3 py-1.5 text-sm bg-brand-blue text-white rounded hover:bg-brand-grey-80"
        >
          {sendLabel}
        </button>
        {!sendCardUx && (
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

// Tools that send an outgoing message to a third party. These get the
// explicit Send/Cancel approval card (never the permission triad) in
// BOTH the chat and solve flows. Names differ between the two engines:
// the chat ToolFactory uses `send_whatsapp_message` / `send_draft`,
// the solve TaskExecutor uses `send_whatsapp` / `send_email`.
const SEND_TOOLS = new Set([
  'send_whatsapp_message',
  'send_draft',
  'send_sms',
  'send_email',
  'send_whatsapp'
])

function labelForSolve(toolName: string): string {
  switch (toolName) {
    case 'send_email':
    case 'send_draft':
      return 'Invia email'
    case 'send_whatsapp':
    case 'send_whatsapp_message':
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
