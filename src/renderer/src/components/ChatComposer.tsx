import { useState } from 'react'

export interface ChatComposerTaskContext {
  taskId?: string
  emailId?: string
}

export interface ChatComposerProps {
  onSubmit: (
    text: string,
    attachmentPaths: string[],
    taskContext?: ChatComposerTaskContext
  ) => Promise<void> | void
  disabled?: boolean
  placeholder?: string
  taskContext?: ChatComposerTaskContext
  narration?: string
  initialText?: string
  showAttachments?: boolean
}

/**
 * ChatComposer — reusable text + attachments composer.
 *
 * Internal state for `text`, `pendingAttachments`, and `busy` (local
 * loading). Calls `onSubmit(text, attachmentPaths, taskContext)` on
 * Enter (no Shift) or button click; awaits the returned Promise to
 * gate the busy spinner. On a successful send (no throw) the text and
 * attachments are cleared.
 *
 * The textarea is intentionally larger than the original Chat input
 * (~5 rows minimum, vertically resizable, capped at ~16rem) so users
 * can compose multi-paragraph messages comfortably.
 */
export default function ChatComposer({
  onSubmit,
  disabled = false,
  placeholder = 'Scrivi un messaggio…',
  taskContext,
  narration,
  initialText = '',
  showAttachments = true
}: ChatComposerProps) {
  const [text, setText] = useState<string>(initialText)
  const [pendingAttachments, setPendingAttachments] = useState<string[]>([])
  const [busy, setBusy] = useState<boolean>(false)

  const isDisabled = disabled || busy

  const basename = (p: string): string => {
    const parts = p.split(/[\\/]/)
    return parts[parts.length - 1] || p
  }

  const pickAttachments = async (): Promise<void> => {
    try {
      const paths = await window.zylch.files.select()
      if (paths && paths.length > 0) {
        setPendingAttachments((prev) => {
          const seen = new Set(prev)
          const merged = [...prev]
          for (const p of paths) {
            if (!seen.has(p)) {
              seen.add(p)
              merged.push(p)
            }
          }
          return merged
        })
      }
    } catch (e) {
      console.error('[ChatComposer] file picker failed', e)
    }
  }

  const removeAttachment = (path: string): void => {
    setPendingAttachments((prev) => prev.filter((p) => p !== path))
  }

  const send = async (): Promise<void> => {
    const trimmed = text.trim()
    if (!trimmed || isDisabled) return
    const attachmentsSnapshot = pendingAttachments.slice()
    setBusy(true)
    try {
      await onSubmit(trimmed, attachmentsSnapshot, taskContext)
      // Clear input only after successful send.
      setText('')
      setPendingAttachments([])
    } catch (e) {
      console.error('[ChatComposer] onSubmit failed', e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="border-t bg-white flex flex-col">
      {narration && busy && (
        <div className="px-3 pt-2 text-slate-500 italic text-sm whitespace-pre-wrap">
          {narration}
        </div>
      )}
      {showAttachments && pendingAttachments.length > 0 && (
        <div className="px-3 pt-2 flex flex-wrap gap-2">
          {pendingAttachments.map((path) => (
            <span
              key={path}
              title={path}
              className="inline-flex items-center gap-1 px-2 py-1 text-xs border border-slate-300 rounded bg-slate-100 text-slate-800"
            >
              <span className="truncate max-w-[240px]">{basename(path)}</span>
              <button
                onClick={() => removeAttachment(path)}
                disabled={isDisabled}
                className="text-slate-500 hover:text-slate-900"
                title="Rimuovi allegato"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="p-3 flex gap-2 items-end">
        <textarea
          className="flex-1 border rounded px-3 py-2 text-sm resize-y min-h-[120px] max-h-64"
          placeholder={placeholder}
          value={text}
          disabled={isDisabled}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
        />
        {showAttachments && (
          <button
            onClick={pickAttachments}
            disabled={isDisabled}
            title="Allega file"
            className="px-3 py-2 bg-slate-200 text-slate-800 rounded text-sm hover:bg-slate-300 disabled:bg-slate-100 disabled:text-slate-400"
          >
            📎
          </button>
        )}
        <button
          onClick={send}
          disabled={isDisabled || !text.trim()}
          className="px-4 py-2 bg-slate-900 text-white rounded text-sm disabled:bg-slate-400"
        >
          {busy ? '…' : 'Invia'}
        </button>
      </div>
    </div>
  )
}
