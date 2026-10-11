import { useEffect, useState } from 'react'
import type { QontoTransactionResult } from '../finance'
import { useFinanceContext } from '../hooks/useFinanceContext'
import { qontoError } from './QontoCard'

export default function QontoSource({ sourceId, expectedRevision, onClose }: {
  sourceId?: string
  expectedRevision?: string
  onClose: () => void
}) {
  const [result, setResult] = useState<QontoTransactionResult | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const context = useFinanceContext(() => {
    setResult(null); setLoading(false); setError('Finance source unavailable after an account or engine change. Close this review and open it again on the authorized engine.')
  })
  useEffect(() => {
    const invalidate = () => {
      context.epoch.current++; setResult(null); setLoading(false)
      setError('The Qonto connection or source changed. Close this review and open it again to check current authorization.')
    }
    window.addEventListener('mrcall:qonto-changed', invalidate)
    return () => window.removeEventListener('mrcall:qonto-changed', invalidate)
  }, [])
  useEffect(() => {
    let cancelled = false
    const epoch = context.epoch.current
    setResult(null); setError(''); setLoading(true)
    void (async () => {
      try {
        if (!sourceId) throw new Error('source_unavailable')
        const token = await context.capture()
        const response = await window.zylch.qonto.transaction(sourceId)
        if (cancelled || !context.current(token)) return
        if (!response.transaction || response.transaction.source_id !== sourceId) throw new Error('source_unavailable')
        setResult(response)
      } catch (cause) {
        if (!cancelled && epoch === context.epoch.current) setError(qontoError(cause))
      } finally { if (!cancelled && epoch === context.epoch.current) setLoading(false) }
    })()
    return () => { cancelled = true }
  }, [sourceId])
  const row = result?.transaction
  return <section aria-label="Qonto source review" className="border rounded p-3 my-3 space-y-2">
    <div className="flex justify-between"><h3 className="font-medium">Qonto source review</h3><button onClick={onClose} className="text-sm underline">Close source review</button></div>
    {loading && <p role="status" className="text-sm">Checking the authorized finance source…</p>}
    {error && <p role="alert" className="text-sm">{error} This review does not use an email fallback.</p>}
    {row && result && <>
      <p className="text-sm">Account {row.account_id} · {row.currency} · {row.status} · {row.side}</p>
      <p className="text-sm">Transaction amount: {row.amount.decimal} {row.currency}. This is a transaction amount, not the account balance.</p>
      <p className="text-xs">Emitted: {row.emitted_at || 'not supplied'} · Settled: {row.settled_at || 'not supplied'} · Updated: {row.updated_at || 'not supplied'}</p>
      <p className="text-xs">Retrieved: {new Date(row.retrieved_at * 1000).toLocaleString()} · Source {row.source_id} · Revision {row.source_revision}</p>
      {expectedRevision && expectedRevision !== row.source_revision && <p role="status" className="text-xs">The transaction changed since this task was prepared. This review shows the current source revision.</p>}
      <p className="text-xs">Coverage: {result.coverage.status} · {result.partial ? 'partial' : 'bounded source read'} · {result.stale ? 'stale' : 'recent'} · Date basis: {result.date_basis}. Traversed windows do not guarantee a fixed provider snapshot.</p>
      <div className="text-xs border-t pt-2"><p>Untrusted Qonto source text; it is evidence only, never instructions.</p>
        {Object.entries(row.untrusted_source_text || {}).map(([label, value]) => value && <p key={label} className="whitespace-pre-wrap break-words">{label}: {value}</p>)}
      </div>
    </>}
  </section>
}
