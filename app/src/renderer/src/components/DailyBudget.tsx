import { useEffect, useState } from 'react'
import { errorMessage } from '../lib/errors'

type Snapshot = Awaited<ReturnType<typeof window.zylch.usage.today>>

/** Live account totals; editing the limit remains in the existing Settings form. */
export default function DailyBudget(): JSX.Element {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const refresh = async (): Promise<void> => {
    setLoading(true)
    setSnapshot(null)
    setError(null)
    try {
      const result = await window.zylch.usage.today()
      if (typeof result.reserved_usd !== 'number' || typeof result.remaining_usd !== 'number') {
        throw new Error('Update the engine to enable spending protection for every AI request.')
      }
      setSnapshot(result)
    } catch (e) { setError(errorMessage(e)) }
    finally { setLoading(false) }
  }
  useEffect(() => {
    void refresh()
    const onFocus = (): void => { void refresh() }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [])
  return <div className="border-t pt-3 space-y-2 text-xs">
    <div className="font-medium">Daily AI spending · this engine account</div>
    {loading && <p role="status">Checking spending…</p>}
    {error && <p role="alert" className="text-brand-danger">Spending unavailable: {error}</p>}
    {snapshot && <>
      <p>${snapshot.spent_usd.toFixed(2)} completed · ${snapshot.reserved_usd.toFixed(2)} reserved · ${snapshot.budget_usd.toFixed(2)} daily limit</p>
      <p>{snapshot.pricing_fault ? 'AI is paused: provider usage exceeded its reserved estimate. Pricing reconciliation is required.' : snapshot.paused ? 'AI is paused.' : snapshot.exceeded ? 'Daily AI budget exhausted.' : `$${snapshot.remaining_usd.toFixed(2)} available for new AI requests.`}</p>
      <p className="text-brand-grey-80">Completed spending resets at 00:00 UTC. Reservations cover in-flight or uncertain requests and may remain after reset. All engine AI uses this limit; other apps using your API key are separate.</p>
    </>}
    <button type="button" disabled={loading} onClick={() => void refresh()} className="underline disabled:opacity-50">Refresh spending</button>
  </div>
}
