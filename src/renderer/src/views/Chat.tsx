import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'

interface Msg {
  role: 'user' | 'assistant'
  content: string
}

export default function Chat() {
  const [history, setHistory] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [history, busy])

  const send = async () => {
    const msg = input.trim()
    if (!msg || busy) return
    setInput('')
    const newHistory: Msg[] = [...history, { role: 'user', content: msg }]
    setHistory(newHistory)
    setBusy(true)
    try {
      const res = await window.zylch.chat.send(msg, history)
      const content =
        (res && (res.response || res.message || res.content)) ||
        JSON.stringify(res, null, 2)
      setHistory([...newHistory, { role: 'assistant', content }])
    } catch (e: any) {
      setHistory([
        ...newHistory,
        { role: 'assistant', content: '**Error:** ' + (e.message || String(e)) }
      ])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col h-full max-w-3xl mx-auto">
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
        {history.length === 0 && (
          <div className="text-slate-500 text-sm">
            Ask Zylch anything about your tasks, emails, or contacts.
          </div>
        )}
        {history.map((m, i) => (
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
              <div className="prose prose-sm max-w-none">
                <ReactMarkdown>{m.content}</ReactMarkdown>
              </div>
            ) : (
              m.content
            )}
          </div>
        ))}
        {busy && <div className="text-slate-500 text-sm">Zylch is thinking…</div>}
      </div>
      <div className="border-t bg-white p-3 flex gap-2">
        <textarea
          className="flex-1 border rounded px-3 py-2 text-sm resize-none"
          rows={2}
          placeholder="Type a message…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
        />
        <button
          onClick={send}
          disabled={busy || !input.trim()}
          className="px-4 py-2 bg-slate-900 text-white rounded text-sm disabled:bg-slate-400"
        >
          Send
        </button>
      </div>
    </div>
  )
}
