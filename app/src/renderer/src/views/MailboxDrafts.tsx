import { useCallback, useEffect, useRef, useState } from 'react'
import type { MailboxDraft, MailboxDraftPatch } from '../drafts'
import { errorMessage } from '../lib/errors'
import HtmlEmailBody from '../components/HtmlEmailBody'

type Action = 'send' | 'trash'
type Pending = { kind: Action; requestKey: string; draftId: string; mailboxId?: string; sentConfirmed?: boolean }
type Editor = { to: string; cc: string; bcc: string; subject: string; body: string }

function addresses(value: string | string[] | undefined): string {
  return Array.isArray(value) ? value.join(', ') : value || ''
}

function fields(draft: MailboxDraft): Editor {
  return {
    to: addresses(draft.to ?? draft.to_addresses),
    cc: addresses(draft.cc ?? draft.cc_addresses),
    bcc: addresses(draft.bcc ?? draft.bcc_addresses),
    subject: draft.subject || '', body: draft.body || ''
  }
}

function message(error: unknown): string {
  const value = errorMessage(error)
  return value.includes('imap_authentication') || value.includes('mailbox_credentials')
    ? 'Check this mailbox’s email connection settings, then refresh drafts.'
    : value
}

function pendingPrefix(profileId: string): string {
  return `mrcall:mailbox-draft-action:${encodeURIComponent(profileId)}:`
}

function pendingKey(profileId: string, id: string): string {
  return pendingPrefix(profileId) + id
}

function savedOperations(profileId: string, mailboxId?: string): Pending[] {
  const result: Pending[] = []
  for (let index = 0; index < localStorage.length; index++) {
    const key = localStorage.key(index)
    if (!key?.startsWith(pendingPrefix(profileId))) continue
    try {
      const value = JSON.parse(localStorage.getItem(key) || '') as Pending
      if ((value.kind === 'send' || value.kind === 'trash') && typeof value.requestKey === 'string'
        && typeof value.draftId === 'string' && key === pendingKey(profileId, value.draftId)
        && (!mailboxId || value.mailboxId === mailboxId)) result.push(value)
    } catch {
      // Malformed browser state grants no mailbox operation.
    }
  }
  return result
}

export default function MailboxDrafts({ mailboxId, profileId, active, onCountChange }: {
  mailboxId?: string
  profileId: string
  active: boolean
  onCountChange: (count: number | undefined) => void
}): JSX.Element {
  const [rows, setRows] = useState<MailboxDraft[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<MailboxDraft | null>(null)
  const [opening, setOpening] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editor, setEditor] = useState<Editor | null>(null)
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState<Pending | null>(null)
  const [recoveries, setRecoveries] = useState<Pending[]>(() => savedOperations(profileId, mailboxId))
  const [notice, setNotice] = useState<string | null>(null)
  const request = useRef(0)
  const opened = useRef(0)
  const actionLock = useRef(false)

  const refresh = useCallback(async () => {
    const current = ++request.current
    setLoading(true)
    setError(null)
    setRecoveries(savedOperations(profileId, mailboxId))
    try {
      const next = await window.zylch.drafts.list(mailboxId ? { mailbox_id: mailboxId } : {})
      if (current !== request.current) return
      if (!Array.isArray(next)) throw new Error('The mailbox draft list is unavailable. Refresh to try again.')
      setRows(next)
      onCountChange(next.length)
      return next
    } catch (cause) {
      if (current === request.current) {
        setError(message(cause))
        onCountChange(undefined)
      }
    } finally {
      if (current === request.current) setLoading(false)
    }
  }, [mailboxId, profileId, onCountChange])

  useEffect(() => {
    if (!active) return
    void refresh()
    const timer = window.setInterval(() => void refresh(), 30000)
    const onFocus = (): void => { void refresh() }
    window.addEventListener('focus', onFocus)
    const off = window.zylch.onSidecarStatus((status) => {
      if (status.alive && status.ready) void refresh()
    })
    return () => {
      request.current++
      opened.current++
      window.clearInterval(timer)
      window.removeEventListener('focus', onFocus)
      off()
    }
  }, [active, refresh])

  const open = async (id: string): Promise<void> => {
    const current = ++opened.current
    setSelectedId(id)
    setDraft(null)
    setEditor(null)
    setEditing(false)
    setError(null)
    setNotice(null)
    setOpening(true)
    try {
      const saved = localStorage.getItem(pendingKey(profileId, id))
      setPending(saved ? JSON.parse(saved) as Pending : null)
      const result = await window.zylch.drafts.get(id)
      if (current !== opened.current) return
      if (!result.ok || !result.draft) throw new Error(result.cause || 'This draft is no longer in the mailbox.')
      if (result.draft.id !== id) throw new Error('The mailbox returned a different draft. Refresh to try again.')
      setDraft(result.draft)
    } catch (cause) {
      if (current === opened.current) setError(message(cause))
    } finally {
      if (current === opened.current) setOpening(false)
    }
  }

  const back = (): void => {
    opened.current++
    setSelectedId(null)
    setDraft(null)
    setEditor(null)
    setEditing(false)
    setError(null)
    setNotice(null)
    setPending(null)
    void refresh()
  }

  const save = async (): Promise<void> => {
    if (!draft || !editor || actionLock.current) return
    actionLock.current = true
    setBusy(true)
    setError(null)
    try {
      const original = fields(draft)
      const patch: MailboxDraftPatch = { draft_id: draft.id }
      for (const key of ['to', 'cc', 'bcc', 'subject', 'body'] as const) {
        if (editor[key] !== original[key]) patch[key] = editor[key]
      }
      if (Object.keys(patch).length > 1) {
        const result = await window.zylch.drafts.update(patch)
        if (!result.ok || !result.draft) throw new Error(result.cause || 'The draft could not be saved.')
        if (!result.draft.id || result.draft.mailbox_id && draft.mailbox_id
          && result.draft.mailbox_id !== draft.mailbox_id) throw new Error('The mailbox returned a different mailbox. Refresh to try again.')
        setDraft(result.draft)
        setSelectedId(result.draft.id)
      }
      setEditing(false)
      setEditor(null)
      setNotice('Saved in your mailbox.')
      await refresh()
    } catch (cause) {
      setError(message(cause))
    } finally {
      actionLock.current = false
      setBusy(false)
    }
  }

  const perform = async (kind: Action): Promise<void> => {
    if (!selectedId || actionLock.current || editing || pending && pending.kind !== kind) return
    actionLock.current = true
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      let current = draft
      if (!pending) {
        const listed = await refresh()
        if (!listed) return
        if (!listed.some(row => row.id === selectedId)) {
          setSelectedId(null)
          setDraft(null)
          throw new Error('This draft changed or left the mailbox. Select its current entry before trying again.')
        }
        const observed = await window.zylch.drafts.get(selectedId)
        if (!observed.ok || !observed.draft || observed.draft.id !== selectedId) {
          throw new Error(observed.cause || 'This draft is no longer in the mailbox. Refresh drafts.')
        }
        current = observed.draft
        setDraft(current)
        if (kind === 'send' && (current.has_attachments || current.attachments?.length)) {
          throw new Error('This draft has attachments. Send it from your mail app.')
        }
      }
      const operation = pending || { kind, requestKey: crypto.randomUUID(), draftId: selectedId,
        mailboxId: current?.mailbox_id || mailboxId }
      localStorage.setItem(pendingKey(profileId, operation.draftId), JSON.stringify(operation))
      setRecoveries(savedOperations(profileId, mailboxId))
      setPending(operation)
      const result = kind === 'send' && pending && !pending.sentConfirmed
        ? await window.zylch.drafts.sendStatus(operation.draftId, operation.requestKey)
        : await window.zylch.drafts[kind](operation.draftId, operation.requestKey)
      if (!result.ok) {
        if (result.effect_certainty === 'not-dispatched') {
          localStorage.removeItem(pendingKey(profileId, operation.draftId))
          setRecoveries(savedOperations(profileId, mailboxId))
          setPending(null)
          setError(message(result.cause || 'The mailbox operation did not start. Refresh the draft and try again.'))
          return
        }
        if (kind === 'send' && result.state === 'sent' && result.effect_certainty === 'verified') {
          const confirmed = { ...operation, sentConfirmed: true }
          localStorage.setItem(pendingKey(profileId, operation.draftId), JSON.stringify(confirmed))
          setPending(confirmed)
          setRecoveries(savedOperations(profileId, mailboxId))
          setNotice('Sent mail is confirmed. Remove the original draft to finish.')
        } else {
          setNotice(kind === 'send'
            ? 'Sending is not confirmed. Check again to retrieve the result of the same send.'
            : 'Moving to Trash is not confirmed. Check again to retrieve the same operation.')
        }
        if (result.cause) setError(message(result.cause))
        return
      }
      localStorage.removeItem(pendingKey(profileId, operation.draftId))
      setRecoveries(savedOperations(profileId, mailboxId))
      setPending(null)
      setSelectedId(null)
      setDraft(null)
      setNotice(kind === 'send' ? 'Sent. Confirmed in Sent mail.' : 'Moved to Trash.')
      await refresh()
    } catch (cause) {
      setError(message(cause))
    } finally {
      actionLock.current = false
      setBusy(false)
    }
  }

  const hasAttachments = !!draft && (draft.has_attachments || !!draft.attachments?.length)
  const html = draft?.body_format === 'html'
  const richBody = html || draft?.body_editable === false
  const inputClass = 'w-full border border-brand-mid-grey rounded px-3 py-2 text-sm focus:outline-none focus:border-brand-blue'

  return (
    <div className="flex flex-col h-full min-h-0" aria-label="Mailbox drafts">
      <div className="flex items-center gap-2 px-4 py-3 border-b">
        {selectedId && <button onClick={back} disabled={busy || editing} className="text-sm border rounded px-3 py-1.5 disabled:opacity-50">Back to drafts</button>}
        <span className="text-sm text-brand-grey-80 flex-1">Drafts in your mailbox</span>
        <button onClick={() => selectedId ? void open(selectedId) : void refresh()} disabled={busy || editing || opening || loading}
          className="text-sm border rounded px-3 py-1.5 disabled:opacity-50">Refresh drafts</button>
      </div>
      {error && <div role="alert" className="p-4 text-sm text-brand-danger">{error}</div>}
      {notice && <div role="status" className="px-4 py-3 text-sm text-brand-grey-80">{notice}</div>}
      {selectedId ? (
        <div className="flex-1 overflow-y-auto p-4">
          {opening && <p className="text-sm text-brand-grey-80">Opening mailbox draft…</p>}
          {draft && !opening && (editing && editor ? (
            <div className="space-y-3">
              {(['to', 'cc', 'bcc', 'subject'] as const).map((field) => (
                <label key={field} className="block text-sm capitalize">{field === 'cc' ? 'Cc' : field === 'bcc' ? 'Bcc' : field}
                  <input aria-label={`Draft ${field}`} className={inputClass} value={editor[field]} disabled={busy}
                    onChange={(event) => setEditor({ ...editor, [field]: event.target.value })} />
                </label>
              ))}
              {richBody ? <><p className="text-sm text-brand-grey-80">Edit rich-text content in Gmail.</p>{html
                ? <HtmlEmailBody html={draft.body} /> : <pre className="whitespace-pre-wrap font-sans text-sm">{draft.body}</pre>}</> : (
                <label className="block text-sm">Message
                  <textarea aria-label="Draft message" className={`${inputClass} min-h-[240px]`} value={editor.body} disabled={busy}
                    onChange={(event) => setEditor({ ...editor, body: event.target.value })} />
                </label>
              )}
              <div className="flex gap-2">
                <button onClick={() => void save()} disabled={busy} className="bg-brand-blue text-white rounded px-3 py-2 text-sm disabled:opacity-50">{busy ? 'Saving…' : 'Save draft'}</button>
                <button onClick={() => { setEditor(null); setEditing(false); setError(null) }} disabled={busy}
                  className="border rounded px-3 py-2 text-sm disabled:opacity-50">Cancel editing</button>
              </div>
            </div>
          ) : (
            <article>
              <h2 className="font-semibold text-lg mb-2">{draft.subject || '(no subject)'}</h2>
              <dl className="text-sm text-brand-grey-80 mb-4 space-y-1">
                <div><dt className="inline font-medium">To: </dt><dd className="inline">{fields(draft).to || '—'}</dd></div>
                {fields(draft).cc && <div><dt className="inline font-medium">Cc: </dt><dd className="inline">{fields(draft).cc}</dd></div>}
                {fields(draft).bcc && <div><dt className="inline font-medium">Bcc: </dt><dd className="inline">{fields(draft).bcc}</dd></div>}
                {draft.mailbox_address && <div><dt className="inline font-medium">Mailbox: </dt><dd className="inline">{draft.mailbox_address}</dd></div>}
              </dl>
              {html ? <HtmlEmailBody html={draft.body} /> : <pre className="whitespace-pre-wrap break-words font-sans text-sm">{draft.body}</pre>}
              {hasAttachments && <p className="mt-4 text-sm text-brand-grey-80">This draft has attachments. Edit or send it in Gmail.</p>}
              <div className="mt-4 flex gap-2">
                <button onClick={() => { setEditor(fields(draft)); setEditing(true); setNotice(null) }} disabled={busy || !!pending || hasAttachments}
                  className="border rounded px-3 py-2 text-sm disabled:opacity-50">Edit draft</button>
              </div>
            </article>
          ))}
          {!opening && !editing && (draft || pending) && (
            <div className="mt-4 flex gap-2">
              <button onClick={() => void perform('send')} disabled={busy || pending?.kind === 'trash' || hasAttachments}
                className="bg-brand-blue text-white rounded px-3 py-2 text-sm disabled:opacity-50">{busy && pending?.kind === 'send' ? 'Checking send…' : pending?.kind === 'send' ? pending.sentConfirmed ? 'Remove sent draft' : 'Check send' : 'Send draft'}</button>
              <button onClick={() => void perform('trash')} disabled={busy || pending?.kind === 'send'}
                className="border border-brand-danger/30 text-brand-danger rounded px-3 py-2 text-sm disabled:opacity-50">{busy && pending?.kind === 'trash' ? 'Checking Trash…' : pending?.kind === 'trash' ? 'Check Trash' : 'Move to Trash'}</button>
            </div>
          )}
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto">
          {recoveries.length > 0 && <section aria-label="Pending mailbox operations" className="p-4 border-b">
            <p className="text-sm mb-2">Retrieve the result of an operation that is still unconfirmed.</p>
            {recoveries.map((operation) => <button key={operation.draftId}
              onClick={() => void open(operation.draftId)} className="block text-sm border rounded px-3 py-2 mb-2">
              {operation.kind === 'send' ? 'Review pending send' : 'Review pending Trash'}
            </button>)}
          </section>}
          {loading && !rows.length && <p className="p-4 text-sm text-brand-grey-80">Loading drafts…</p>}
          {!loading && !error && !rows.length && <p className="p-4 text-sm text-brand-grey-80">No drafts in your mailbox.</p>}
          <ul>{rows.map((row) => (
            <li key={row.id}>
              <button onClick={() => void open(row.id)} data-draft-id={row.id} className="w-full text-left border-b px-4 py-3 hover:bg-brand-light-grey">
                <div className="text-sm text-brand-grey-80 truncate">{fields(row).to || '(no recipient)'}</div>
                <div className="text-sm font-medium truncate">{row.subject || '(no subject)'}</div>
              </button>
            </li>
          ))}</ul>
        </div>
      )}
    </div>
  )
}
