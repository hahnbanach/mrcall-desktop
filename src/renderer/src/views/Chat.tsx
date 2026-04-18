import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { useConversations, type Approval } from '../store/conversations'
import { useNarration } from '../hooks/useNarration'
import ChatComposer, { type ChatComposerTaskContext } from '../components/ChatComposer'
import { errorMessage, isProfileLockedError, showError } from '../lib/errors'

interface Props {
  onGoToDashboard?: () => void
}

export default function Chat({ onGoToDashboard }: Props = {}) {
  const {
    state,
    setActive,
    closeConversation,
    appendUser,
    appendAssistant,
    setDraftInput,
    setPendingApproval,
    setBusy
  } = useConversations()

  const active = state.conversations.find((c) => c.id === state.activeId)!
  const scrollRef = useRef<HTMLDivElement>(null)
  const [completing, setCompleting] = useState(false)
  const [narrationSeed, setNarrationSeed] = useState<string>('')
  const [lastUserText, setLastUserText] = useState<string>('')

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

  const onApproval = async (mode: 'once' | 'session' | 'deny') => {
    const pending = active.pendingApproval
    if (!pending) return
    setPendingApproval(active.id, null)
    try {
      await window.zylch.chat.approve(pending.toolUseId, { mode })
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
      onGoToDashboard?.()
    } catch (e: unknown) {
      showError(e, 'Complete failed:')
    } finally {
      setCompleting(false)
    }
  }

  return (
    <div className="flex h-full">
      <aside className="w-[220px] border-r bg-slate-50 flex flex-col">
        <div className="p-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
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
                    ? 'bg-white border-slate-900'
                    : 'border-transparent hover:bg-slate-100')
                }
              >
                <span className="text-sm truncate">{c.title}</span>
                {closable && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      closeConversation(c.id)
                    }}
                    className="ml-2 text-slate-400 hover:text-slate-900 opacity-0 group-hover:opacity-100"
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
              onClick={markDone}
              disabled={completing}
              className="px-3 py-1.5 text-sm bg-emerald-700 text-white rounded hover:bg-emerald-800 disabled:bg-slate-400"
            >
              {completing ? 'Attendere…' : 'Marca come fatta'}
            </button>
          )}
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
          {active.history.length === 0 && !active.pendingApproval && (
            <div className="text-slate-500 text-sm">
              {active.taskId
                ? 'Rivedi il messaggio, modificalo se vuoi, poi invialo.'
                : 'Ask Zylch anything about your tasks, emails, or contacts.'}
            </div>
          )}
          {active.history.map((m, i) => (
            <div
              key={i}
              className={
                'p-3 rounded-lg whitespace-pre-wrap ' +
                (m.role === 'user'
                  ? 'bg-slate-900 text-white ml-12'
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
            <div className="text-slate-500 italic text-sm whitespace-pre-wrap">
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
          disabled={!!active.busy}
          placeholder="Scrivi un messaggio…"
          taskContext={{ taskId: active.taskId, emailId: active.sourceEmailId }}
          narration={narration}
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
  return (
    <div className="border border-amber-400 bg-amber-50 rounded-lg p-4 mr-12">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs px-2 py-0.5 bg-amber-200 text-amber-900 rounded font-mono">
          {approval.name}
        </span>
        <span className="text-sm text-amber-900 font-medium">
          Conferma richiesta
        </span>
      </div>
      {approval.preview && (
        <div className="text-sm text-slate-800 mb-3 whitespace-pre-wrap">
          {approval.preview}
        </div>
      )}
      <div className="bg-white border border-amber-200 rounded p-3 mb-3 space-y-2">
        {Object.entries(approval.input).map(([k, v]) => (
          <div key={k}>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              {k}
            </div>
            <div className="text-sm text-slate-900 whitespace-pre-wrap break-words">
              {typeof v === 'string' ? v : JSON.stringify(v, null, 2)}
            </div>
          </div>
        ))}
      </div>
      <div className="flex gap-2 flex-wrap">
        <button
          onClick={onApproveOnce}
          className="px-3 py-1.5 text-sm bg-emerald-700 text-white rounded hover:bg-emerald-800"
        >
          Allow once
        </button>
        <button
          onClick={onApproveSession}
          className="px-3 py-1.5 text-sm bg-emerald-900 text-white rounded hover:bg-emerald-950"
          title="Auto-approve this tool for the rest of this conversation"
        >
          Allow for session
        </button>
        <button
          onClick={onDecline}
          className="px-3 py-1.5 text-sm bg-slate-200 text-slate-800 rounded hover:bg-slate-300"
        >
          Deny
        </button>
      </div>
    </div>
  )
}
