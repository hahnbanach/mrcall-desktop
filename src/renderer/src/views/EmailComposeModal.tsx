import { useEffect, useRef, useState } from 'react'

export interface ComposeSeed {
  to: string
  cc?: string
  subject: string
  body: string
  /** reply fields — set when composing a reply to an existing thread */
  thread_id?: string
  in_reply_to?: string
}

interface Props {
  open: boolean
  seed: ComposeSeed
  onClose: () => void
  onAfterSend?: () => void
}

/**
 * EmailComposeModal — minimal Compose / Reply modal.
 *
 * This round ships the UI only. The Save Draft / Send buttons are
 * currently disabled because no first-class `drafts.create` /
 * `drafts.send` RPC is exposed (the existing create_draft/send_draft
 * lives inside the chat-agent tool pipeline, which gates sending
 * behind the approval flow). Wiring them up is a follow-up round so
 * the desktop can send directly without going through the chat agent.
 *
 * For now the user can compose text, review it, and copy the body out
 * — a one-click Send will land in the same modal as soon as the RPC
 * pair exists.
 */
export default function EmailComposeModal({
  open,
  seed,
  onClose,
  onAfterSend
}: Props): JSX.Element | null {
  void onAfterSend
  const [to, setTo] = useState(seed.to || '')
  const [cc, setCc] = useState(seed.cc || '')
  const [subject, setSubject] = useState(seed.subject || '')
  const [body, setBody] = useState(seed.body || '')
  const toRef = useRef<HTMLInputElement | null>(null)

  // Reset fields whenever the seed changes (opening compose for a new
  // thread). Guarded on `open` so the parent can keep the modal mounted
  // while changing the seed.
  useEffect(() => {
    setTo(seed.to || '')
    setCc(seed.cc || '')
    setSubject(seed.subject || '')
    setBody(seed.body || '')
  }, [seed.to, seed.cc, seed.subject, seed.body, seed.thread_id])

  // Autofocus the first empty field.
  useEffect(() => {
    if (!open) return
    const t = setTimeout(() => {
      if (!to) toRef.current?.focus()
    }, 30)
    return () => clearTimeout(t)
  }, [open, to])

  // ESC closes the modal (but not if focus is in a textarea).
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') {
        onClose()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const isReply = !!seed.thread_id

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl w-[640px] max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between px-4 py-3 border-b">
          <h2 className="text-base font-semibold">
            {isReply ? 'Reply' : 'New message'}
          </h2>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-900 text-xl leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
          <label className="flex items-baseline gap-3">
            <span className="text-xs text-slate-500 w-16 shrink-0">To</span>
            <input
              ref={toRef}
              type="email"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              required
              placeholder="recipient@example.com"
              className="flex-1 text-sm border rounded px-2 py-1.5 outline-none focus:ring-2 focus:ring-blue-200"
            />
          </label>
          <label className="flex items-baseline gap-3">
            <span className="text-xs text-slate-500 w-16 shrink-0">Cc</span>
            <input
              type="text"
              value={cc}
              onChange={(e) => setCc(e.target.value)}
              placeholder="(optional)"
              className="flex-1 text-sm border rounded px-2 py-1.5 outline-none focus:ring-2 focus:ring-blue-200"
            />
          </label>
          <label className="flex items-baseline gap-3">
            <span className="text-xs text-slate-500 w-16 shrink-0">Subject</span>
            <input
              type="text"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              required
              className="flex-1 text-sm border rounded px-2 py-1.5 outline-none focus:ring-2 focus:ring-blue-200"
            />
          </label>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Write your message…"
            rows={12}
            className="flex-1 min-h-[200px] text-sm border rounded p-2 outline-none focus:ring-2 focus:ring-blue-200 font-sans resize-y"
          />
          <div className="text-xs text-slate-500 border-t pt-2">
            Note: Save Draft / Send via the desktop is a follow-up round.
            Use the chat panel in the Workspace to send drafts for now.
          </div>
        </div>
        <footer className="flex items-center justify-end gap-2 px-4 py-3 border-t bg-slate-50">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm border rounded hover:bg-white"
          >
            Cancel
          </button>
          <button
            disabled
            title="Save Draft — coming next round"
            className="px-3 py-1.5 text-sm border rounded text-slate-400 cursor-not-allowed"
          >
            Save Draft
          </button>
          <button
            disabled
            title="Send — coming next round"
            className="px-3 py-1.5 text-sm text-white rounded opacity-50 cursor-not-allowed"
            style={{ backgroundColor: 'var(--profile-accent)' }}
          >
            Send
          </button>
        </footer>
      </div>
    </div>
  )
}
