import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import type { EmailThreadResult, ThreadEmail } from '../types'
import { useThread } from '../store/thread'
import { useConversations, type Approval } from '../store/conversations'
import ChatComposer, { type ChatComposerTaskContext } from '../components/ChatComposer'
import { useNarration } from '../hooks/useNarration'
import { errorMessage, isProfileLockedError } from '../lib/errors'

function formatDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleString('it-IT')
}

export default function Emails() {
  const { activeThreadId, activeTaskId } = useThread()
  const {
    state: convState,
    appendUser,
    appendAssistant,
    setBusy,
    setPendingApproval
  } = useConversations()
  const [result, setResult] = useState<EmailThreadResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [narrationSeed, setNarrationSeed] = useState<string>('')

  // Find the conversation that goes with the active task (if any).
  // The Dashboard "Open" button calls openTaskChat(task) before routing
  // here, so the conversation `task-${taskId}` should already exist.
  const conversationId = activeTaskId ? `task-${activeTaskId}` : 'general'
  const conversation =
    convState.conversations.find((c) => c.id === conversationId) ||
    convState.conversations.find((c) => c.id === 'general')!
  const sourceEmailId = conversation.sourceEmailId

  const narration = useNarration(!!conversation.busy, '', narrationSeed)

  useEffect(() => {
    if (!activeThreadId) {
      setResult(null)
      setError(null)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    setResult(null)
    window.zylch.emails
      .listByThread(activeThreadId)
      .then((r) => {
        if (cancelled) return
        setResult(r)
      })
      .catch((e: unknown) => {
        if (cancelled) return
        // Profile lock: top banner already explains; no inline duplicate.
        if (isProfileLockedError(e)) {
          setError(null)
        } else {
          setError(errorMessage(e))
        }
      })
      .finally(() => {
        if (cancelled) return
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [activeThreadId])

  // Subscribe once to pending_approval notifications so destructive tools
  // initiated from this view also surface their approval gate. Uses the
  // shared conversations store so a Solve in another tab still sees its
  // own approvals correctly.
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
    return () => {
      off()
    }
  }, [setPendingApproval])

  const sendChat = async (
    text: string,
    attachmentPaths: string[],
    _ctx?: ChatComposerTaskContext
  ): Promise<void> => {
    if (!text || conversation.busy) return
    appendUser(conversation.id, text)
    setNarrationSeed('Sto pensando alla tua richiesta.')
    setBusy(conversation.id, true)
    const historySnapshot = conversation.history.map((m) => ({
      role: m.role,
      content: m.content
    }))
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
      if (activeTaskId) chatContext.task_id = activeTaskId
      if (sourceEmailId) chatContext.email_id = sourceEmailId
      if (attachmentPaths.length > 0) chatContext.attachment_paths = attachmentPaths
      const res = await window.zylch.chat.send(text, historySnapshot, {
        conversationId: conversation.id,
        context: chatContext
      })
      const content =
        (res && (res.response || res.message || res.content)) || JSON.stringify(res, null, 2)
      appendAssistant(conversation.id, content)
    } catch (e: unknown) {
      if (!isProfileLockedError(e)) {
        appendAssistant(conversation.id, '**Error:** ' + errorMessage(e))
      }
      throw e
    } finally {
      setBusy(conversation.id, false)
      setNarrationSeed('')
    }
  }

  const onApproval = async (approved: boolean): Promise<void> => {
    const pending = conversation.pendingApproval
    if (!pending) return
    setPendingApproval(conversation.id, null)
    try {
      await window.zylch.chat.approve(pending.toolUseId, approved)
    } catch (e: unknown) {
      if (!isProfileLockedError(e)) {
        appendAssistant(conversation.id, '**Approval error:** ' + errorMessage(e))
      }
    }
  }

  if (!activeThreadId) {
    return (
      <div className="p-8 text-slate-500">
        No thread selected. Click Open on a task.
      </div>
    )
  }

  if (loading) {
    return <div className="p-8 text-slate-500">Loading thread…</div>
  }

  if (error) {
    return (
      <div className="p-8 text-red-700">Failed to load: {error}</div>
    )
  }

  const emailsAsc: ThreadEmail[] = result?.emails ?? []
  if (emailsAsc.length === 0) {
    return (
      <div className="p-8 text-slate-500">
        No messages in this thread.
      </div>
    )
  }

  // Backend returns emails ASC (chronological); render in reverse so the
  // newest message is at the top of the Email tab. Do NOT change the
  // backend order: other call sites (LLM thread context) depend on ASC.
  const emails: ThreadEmail[] = emailsAsc.slice().reverse()
  const subject = emailsAsc[0]?.subject || '(no subject)'

  return (
    <div className="flex flex-col h-full">
      {/* Email list — scrollable region; capped so the composer always
          fits, regardless of how many messages the thread has. */}
      <div className="flex-1 overflow-y-auto">
        <div className="p-6 max-w-4xl mx-auto">
          <header className="mb-4">
            <h1 className="text-2xl font-semibold text-slate-900 break-words">
              {subject}
            </h1>
            <div className="text-sm text-slate-500 mt-1">
              {emails.length} {emails.length === 1 ? 'message' : 'messages'}
            </div>
          </header>
          <div className="space-y-3">
            {emails.map((e) => (
              <article
                key={e.id}
                className={
                  'bg-white border rounded-lg p-4 shadow-sm ' +
                  (e.is_user_sent ? 'border-l-4 border-l-green-500' : '')
                }
              >
                <div className="flex items-start justify-between gap-3 mb-1">
                  <div className="text-sm text-slate-900 min-w-0 break-words">
                    {e.is_user_sent && (
                      <span className="inline-block text-xs px-2 py-0.5 mr-2 rounded bg-green-100 text-green-800 border border-green-300">
                        You →
                      </span>
                    )}
                    {e.is_auto_reply && (
                      <span className="inline-block text-xs px-2 py-0.5 mr-2 rounded bg-slate-100 text-slate-600 border border-slate-300">
                        auto
                      </span>
                    )}
                    <span className="font-medium">
                      {e.from_name ? `${e.from_name} ` : ''}
                      <span className="text-slate-500">&lt;{e.from_email}&gt;</span>
                    </span>
                  </div>
                  <div className="text-xs text-slate-500 whitespace-nowrap">
                    {formatDate(e.date)}
                  </div>
                </div>
                <div className="text-xs text-slate-500 mb-3 break-words">
                  <span>To: {e.to_email || '—'}</span>
                  {e.cc_email && <span> · Cc: {e.cc_email}</span>}
                </div>
                <pre className="text-sm text-slate-900 whitespace-pre-wrap break-words font-sans select-text m-0">
                  {e.body_plain}
                </pre>
                {(e.has_attachments || e.attachment_filenames.length > 0) && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {e.attachment_filenames.length > 0
                      ? e.attachment_filenames.map((name, i) => (
                          <span
                            key={i}
                            className="text-xs px-2 py-0.5 rounded border border-slate-300 bg-slate-50 text-slate-700"
                          >
                            📎 {name}
                          </span>
                        ))
                      : (
                        <span className="text-xs px-2 py-0.5 rounded border border-slate-300 bg-slate-50 text-slate-700">
                          📎 attachment
                        </span>
                      )}
                  </div>
                )}
              </article>
            ))}
          </div>
        </div>
      </div>

      {/* Mini chat thread + composer pinned at the bottom. Capped at a
          fraction of the viewport so the email list above stays usable
          even after a long back-and-forth. */}
      <div className="border-t bg-slate-50 flex flex-col max-h-[55vh]">
        {(conversation.history.length > 0 ||
          conversation.busy ||
          conversation.pendingApproval) && (
          <div className="overflow-y-auto p-3 space-y-2 max-h-64">
            {conversation.history.map((m, i) => (
              <div
                key={i}
                className={
                  'p-2 rounded text-sm whitespace-pre-wrap ' +
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
            {conversation.busy && !conversation.pendingApproval && (
              <div className="text-slate-500 italic text-xs whitespace-pre-wrap">
                {narration || 'Sto pensando alla tua richiesta.'}
              </div>
            )}
            {conversation.pendingApproval && (
              <ApprovalCard
                approval={conversation.pendingApproval}
                onApprove={() => onApproval(true)}
                onDecline={() => onApproval(false)}
              />
            )}
          </div>
        )}
        <ChatComposer
          key={conversation.id}
          onSubmit={sendChat}
          disabled={!!conversation.busy}
          placeholder={
            activeTaskId
              ? 'Chiedi qualcosa su questa task…'
              : 'Apri una task per iniziare…'
          }
          taskContext={{ taskId: activeTaskId ?? undefined, emailId: sourceEmailId }}
          narration={narration}
        />
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
    <div className="border border-amber-400 bg-amber-50 rounded-lg p-3 mr-12 text-sm">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs px-2 py-0.5 bg-amber-200 text-amber-900 rounded font-mono">
          {approval.name}
        </span>
        <span className="text-amber-900 font-medium">Conferma richiesta</span>
      </div>
      {approval.preview && (
        <div className="text-slate-800 mb-2 whitespace-pre-wrap">
          {approval.preview}
        </div>
      )}
      <div className="flex gap-2">
        <button
          onClick={onApprove}
          className="px-3 py-1 text-sm bg-emerald-700 text-white rounded hover:bg-emerald-800"
        >
          Approva e invia
        </button>
        <button
          onClick={onDecline}
          className="px-3 py-1 text-sm bg-slate-200 text-slate-800 rounded hover:bg-slate-300"
        >
          Rifiuta
        </button>
      </div>
    </div>
  )
}
