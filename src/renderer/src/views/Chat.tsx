import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { useConversations, type Approval } from '../store/conversations'

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
  const [inputHeight, setInputHeight] = useState(160)

  const startResize = (e: React.MouseEvent): void => {
    const startY = e.clientY
    const startH = inputHeight
    const onMove = (ev: MouseEvent): void => {
      // Dragging UP (negative deltaY in screen coords) makes input TALLER.
      const delta = startY - ev.clientY
      setInputHeight(Math.max(60, Math.min(600, startH + delta)))
    }
    const onUp = (): void => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    document.body.style.userSelect = 'none'
    e.preventDefault()
  }

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

  const send = async () => {
    const text = active.draftInput.trim()
    if (!text || active.busy) return
    setDraftInput(active.id, '')
    appendUser(active.id, text)
    setBusy(active.id, true)
    const historySnapshot = active.history.map((m) => ({ role: m.role, content: m.content }))
    try {
      const res = await window.zylch.chat.send(text, historySnapshot, {
        conversationId: active.id,
        context: active.taskId ? { task_id: active.taskId } : {}
      })
      const content =
        (res && (res.response || res.message || res.content)) || JSON.stringify(res, null, 2)
      appendAssistant(active.id, content)
    } catch (e: any) {
      appendAssistant(active.id, '**Error:** ' + (e.message || String(e)))
    } finally {
      setBusy(active.id, false)
    }
  }

  const onApproval = async (approved: boolean) => {
    const pending = active.pendingApproval
    if (!pending) return
    setPendingApproval(active.id, null)
    try {
      await window.zylch.chat.approve(pending.toolUseId, approved)
    } catch (e: any) {
      appendAssistant(active.id, '**Approval error:** ' + (e.message || String(e)))
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
    } catch (e: any) {
      alert('Complete failed: ' + (e.message || String(e)))
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
          {active.busy && (
            <div className="text-slate-500 text-sm">Zylch sta pensando…</div>
          )}

          {active.pendingApproval && (
            <ApprovalCard
              approval={active.pendingApproval}
              onApprove={() => onApproval(true)}
              onDecline={() => onApproval(false)}
            />
          )}
        </div>

        <div
          className="border-t bg-white flex flex-col"
          style={{ height: inputHeight }}
        >
          <div
            onMouseDown={startResize}
            title="Trascina per ridimensionare"
            className="h-1.5 cursor-ns-resize bg-slate-200 hover:bg-slate-400 shrink-0"
          />
          <div className="flex-1 min-h-0 p-3 flex gap-2">
            <textarea
              className="flex-1 h-full border rounded px-3 py-2 text-sm resize-none"
              placeholder="Scrivi un messaggio…"
              value={active.draftInput}
              disabled={active.busy}
              onChange={(e) => setDraftInput(active.id, e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send()
                }
              }}
            />
            <button
              onClick={send}
              disabled={active.busy || !active.draftInput.trim()}
              className="px-4 py-2 bg-slate-900 text-white rounded text-sm disabled:bg-slate-400 self-end"
            >
              Invia
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function ApprovalCard({
  approval,
  onApprove,
  onDecline
}: {
  approval: Approval
  onApprove: () => void
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
      <div className="flex gap-2">
        <button
          onClick={onApprove}
          className="px-3 py-1.5 text-sm bg-emerald-700 text-white rounded hover:bg-emerald-800"
        >
          Approva e invia
        </button>
        <button
          onClick={onDecline}
          className="px-3 py-1.5 text-sm bg-slate-200 text-slate-800 rounded hover:bg-slate-300"
        >
          Rifiuta
        </button>
      </div>
    </div>
  )
}
