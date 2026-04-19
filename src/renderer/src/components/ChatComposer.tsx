import { useEffect, useRef, useState } from 'react'

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
  // User-resizable composer height. The top edge acts as a drag handle:
  // grab and move up to grow the box, down to shrink. Clamped so the
  // message list above always keeps some room.
  const DEFAULT_HEIGHT = 200
  const MIN_HEIGHT = 120
  const [height, setHeight] = useState<number>(DEFAULT_HEIGHT)
  const dragRef = useRef<{ startY: number; startH: number } | null>(null)

  useEffect(() => {
    const onMove = (e: MouseEvent): void => {
      if (!dragRef.current) return
      const { startY, startH } = dragRef.current
      // Dragging UP makes the composer taller.
      const next = startH + (startY - e.clientY)
      // Upper bound: never eat more than 70% of the viewport.
      const maxH = Math.round(window.innerHeight * 0.7)
      setHeight(Math.max(MIN_HEIGHT, Math.min(maxH, next)))
    }
    const onUp = (): void => {
      if (!dragRef.current) return
      dragRef.current = null
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])

  const startDrag = (e: React.MouseEvent): void => {
    e.preventDefault()
    dragRef.current = { startY: e.clientY, startH: height }
    document.body.style.cursor = 'ns-resize'
    document.body.style.userSelect = 'none'
  }

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
    // Clear the input up-front so the user isn't staring at a duplicate of
    // what they just sent while the LLM takes its 30s to answer. If the
    // submit fails we restore both the text and the attachments so they
    // can retry without losing anything.
    setText('')
    setPendingAttachments([])
    setBusy(true)
    try {
      await onSubmit(trimmed, attachmentsSnapshot, taskContext)
    } catch (e) {
      setText(trimmed)
      setPendingAttachments(attachmentsSnapshot)
      console.error('[ChatComposer] onSubmit failed', e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="border-t bg-white flex flex-col relative"
      style={{ height }}
    >
      {/* Drag handle — the whole top border is grabbable. 5px hit area
          with a subtle visible bar; cursor flips to ns-resize on hover. */}
      <div
        onMouseDown={startDrag}
        title="Drag to resize"
        className="absolute -top-[3px] left-0 right-0 h-[6px] cursor-ns-resize group z-10"
      >
        <div className="mx-auto mt-[2px] h-[2px] w-10 rounded bg-slate-300 group-hover:bg-slate-500 transition-colors" />
      </div>
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
      <div className="p-3 flex gap-2 items-end flex-1 min-h-0">
        <textarea
          className="flex-1 h-full border rounded px-3 py-2 text-sm resize-none"
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
