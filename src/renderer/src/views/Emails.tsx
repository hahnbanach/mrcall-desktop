import { useEffect, useState } from 'react'
import type { EmailThreadResult, ThreadEmail } from '../types'
import { useThread } from '../store/thread'

function formatDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleString('it-IT')
}

export default function Emails() {
  const { activeThreadId } = useThread()
  const [result, setResult] = useState<EmailThreadResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
        const msg = e instanceof Error ? e.message : String(e)
        setError(msg)
      })
      .finally(() => {
        if (cancelled) return
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [activeThreadId])

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

  const emails: ThreadEmail[] = result?.emails ?? []
  if (emails.length === 0) {
    return (
      <div className="p-8 text-slate-500">
        No messages in this thread.
      </div>
    )
  }

  const subject = emails[0]?.subject || '(no subject)'

  return (
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
  )
}
