import { useEffect, useRef, useState } from 'react'
import { errorMessage } from '../lib/errors'

type Snapshot = Awaited<ReturnType<typeof window.zylch.usage.today>>
const roleNames: Record<string, string> = {
  MODEL_MEMORY_EXTRACT: 'Read messages', MODEL_MEMORY_MERGE: 'Update memory',
  MODEL_TASK_DETECTION: 'Find tasks', MODEL_REANALYZE: 'Review tasks', MODEL_DEDUP: 'Merge duplicate tasks'
}

export default function DailyBudget(): JSX.Element {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [checking, setChecking] = useState(false)
  const [cursor, setCursor] = useState<string | undefined>()
  const generation = useRef(0)
  const request = useRef(0)
  const refresh = async (): Promise<void> => {
    const epoch = generation.current
    const id = ++request.current
    setLoading(true); setSnapshot(null); setError(null)
    try {
      const result = await window.zylch.usage.today()
      if (epoch !== generation.current || id !== request.current) return
      if (typeof result.reserved_usd !== 'number' || typeof result.remaining_usd !== 'number' || !result.model_policy) {
        throw new Error('Update the engine to enable the current spending controls and model policy.')
      }
      setSnapshot(result)
    } catch (e) { if (epoch === generation.current && id === request.current) setError(errorMessage(e)) }
    finally { if (epoch === generation.current && id === request.current) setLoading(false) }
  }
  useEffect(() => {
    void refresh()
    const onFocus = (): void => { void refresh() }
    window.addEventListener('focus', onFocus)
    const off = window.zylch.onSidecarStatus(status => {
      generation.current++; request.current++
      setSnapshot(null); setNotice(null); setError(null); setCursor(undefined); setChecking(false)
      if (status.alive && status.ready) void refresh()
      else setLoading(false)
    })
    return () => { generation.current++; window.removeEventListener('focus', onFocus); off() }
  }, [])
  const reconcile = async (): Promise<void> => {
    const epoch = generation.current
    setChecking(true); setNotice(null)
    try {
      const result = await window.zylch.usage.reconcile(cursor)
      if (epoch !== generation.current) return
      setCursor(result.next_cursor || undefined)
      setNotice(`${result.recovered} confirmed receipts recovered; ${result.unresolved} remain uncertain in this page. ${result.next_cursor ? 'Continue to check the next page.' : result.message}`)
      await refresh()
    } catch (cause) { if (epoch === generation.current) setNotice(errorMessage(cause)) }
    finally { if (epoch === generation.current) setChecking(false) }
  }
  return <div className="border-t pt-3 space-y-2 text-xs">
    <div className="font-medium">Daily AI spending · this engine account</div>
    {loading && <p role="status">Checking spending…</p>}
    {error && <p role="alert" className="text-brand-danger">Spending unavailable: {error}</p>}
    {snapshot && <>
      <p>${snapshot.spent_usd.toFixed(2)} completed · ${snapshot.reserved_usd.toFixed(2)} reserved · ${snapshot.budget_usd.toFixed(2)} daily limit</p>
      <p>{snapshot.billing_supported === false ? snapshot.billing_reason || 'Configure the selected provider before starting AI.' : snapshot.pricing_fault ? 'AI is paused: provider usage exceeded its reserved estimate. Pricing reconciliation is required.' : snapshot.paused ? 'AI is paused. Check your daily limit and reserved requests.' : `$${snapshot.remaining_usd.toFixed(2)} available for new AI requests.`}</p>
      <p className="text-brand-grey-80">Completed spending resets at 00:00 UTC. In-flight or uncertain requests remain reserved after reset. This limit covers this engine account; other apps using your API key are separate. Direct-provider totals are usage-based estimates; MrCall totals include credit rounding and markup.</p>
      {snapshot.model_policy && <div className="space-y-1">
        <p className="font-medium">Saved models · {snapshot.model_policy.provider} · {snapshot.model_policy.preset}</p>
        <p>Conversation: {snapshot.model_policy.model}</p>
        {Object.entries(snapshot.model_policy.roles).map(([role, model]) => <p key={role}>{roleNames[role] || role}: {model}</p>)}
        <p className="text-brand-grey-80">{snapshot.model_policy.quality_status} After changing models or billing, start a new run or conversation.</p>
      </div>}
      {snapshot.reserved_usd > 0 && <button type="button" disabled={checking} onClick={() => void reconcile()} className="underline disabled:opacity-50">{checking ? 'Checking receipts…' : cursor ? 'Check next receipts' : 'Check MrCall receipts'}</button>}
    </>}
    {notice && <p role="status">{notice}</p>}
    <button type="button" disabled={loading} onClick={() => void refresh()} className="underline disabled:opacity-50">Refresh spending</button>
  </div>
}
