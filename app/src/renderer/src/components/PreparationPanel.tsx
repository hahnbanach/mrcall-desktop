import { useEffect, useRef, useState } from 'react'
import type { PreparationStatus } from '../types'
import { errorMessage } from '../lib/errors'

export default function PreparationPanel({ disabled, hasData, onBusy, onFinished, onAvailability }: {
  disabled: boolean
  hasData: boolean
  onBusy: (busy: boolean) => void
  onFinished: () => void
  onAvailability: (supported: boolean, paused: boolean) => void
}): JSX.Element {
  const [state, setState] = useState<PreparationStatus | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [working, setWorking] = useState(false)
  const [pausing, setPausing] = useState(false)
  const localBusy = useRef(false)
  const generation = useRef(0)
  const request = useRef(0)
  const callbacks = useRef({ onBusy, onFinished, onAvailability })
  callbacks.current = { onBusy, onFinished, onAvailability }

  const refresh = async (): Promise<void> => {
    const epoch = generation.current
    const id = ++request.current
    try {
      const result = await window.zylch.preparation.status()
      if (epoch !== generation.current || id !== request.current) return
      setState(result)
      setStatusError(null)
      callbacks.current.onAvailability(true, result.paused)
      callbacks.current.onBusy(localBusy.current || result.running)
    } catch (cause) {
      if (epoch !== generation.current || id !== request.current) return
      setState(null)
      callbacks.current.onAvailability(false, true)
      const message = errorMessage(cause)
      setStatusError(message.includes('not found') || message.includes('-32601')
        ? 'This engine needs an update to support bounded preparation. Update the engine before starting analysis.'
        : 'Preparation status is unavailable. Check the engine connection, then refresh. Analysis stays disabled until status is known.')
    }
  }

  useEffect(() => {
    void refresh()
    const timer = setInterval(() => void refresh(), 5000)
    const focus = (): void => { void refresh() }
    window.addEventListener('focus', focus)
    const off = window.zylch.onSidecarStatus((status) => {
      generation.current++
      request.current++
      setState(null)
      setNotice(null)
      setError(null)
      setStatusError(null)
      setWorking(false)
      localBusy.current = false
      setPausing(false)
      callbacks.current.onBusy(false)
      callbacks.current.onAvailability(false, true)
      if (status.alive && status.ready) void refresh()
    })
    return () => {
      generation.current++
      clearInterval(timer)
      window.removeEventListener('focus', focus)
      off()
    }
  }, [])

  const analyze = async (): Promise<void> => {
    if (!state || state.running || working || disabled || !hasData) return
    const epoch = generation.current
    setWorking(true)
    localBusy.current = true
    callbacks.current.onBusy(true)
    setNotice(null)
    setError(null)
    try {
      const result = await window.zylch.preparation.resume()
      if (epoch !== generation.current) return
      request.current++
      setState(result)
      setNotice(result.stop_reason)
      if (!result.success) setError(result.errors.map((item) => item.detail).join('\n') || 'Analysis stopped. Review the engine spending status before resuming.')
      callbacks.current.onFinished()
    } catch (cause) {
      if (epoch !== generation.current) return
      setError(`${errorMessage(cause)} Check status before trying again: the engine may still be working.`)
    } finally {
      if (epoch === generation.current) {
        setWorking(false)
        localBusy.current = false
        await refresh()
      }
    }
  }

  const pause = async (): Promise<void> => {
    const epoch = generation.current
    setPausing(true)
    try {
      const result = await window.zylch.preparation.pause()
      if (epoch !== generation.current) return
      request.current++
      setState(result)
      setNotice('Pause saved. Requests already sent may finish and still count toward today’s budget.')
      callbacks.current.onAvailability(true, true)
    } catch (cause) {
      if (epoch === generation.current) setError(`Pause could not be confirmed: ${errorMessage(cause)}`)
    } finally {
      if (epoch === generation.current) setPausing(false)
    }
  }

  const active = working || !!state?.running
  return <section aria-labelledby="preparation-heading">
    <h2 id="preparation-heading" className="text-2xl font-semibold mb-2">Analyze one batch</h2>
    <p className="text-sm text-brand-grey-80 mb-4">
      Turn downloaded messages into shared memory and action items. This uses paid AI and stays within your daily allowance.
      A batch does up to {state?.next_run_limit ?? 25} processing steps. Memory, task detection, and initial assistant training each use steps.
    </p>
    {state && <>
      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 my-4 text-sm">
        <div><dt className="text-brand-grey-80">Steps waiting</dt><dd className="font-semibold">{state.pending}</dd></div>
        <div><dt className="text-brand-grey-80">Completed this batch</dt><dd className="font-semibold">{state.completed}</dd></div>
        <div><dt className="text-brand-grey-80">Failed this batch</dt><dd className="font-semibold">{state.failed}</dd></div>
        <div><dt className="text-brand-grey-80">Batch progress</dt><dd className="font-semibold">{state.attempted} / {state.limit} steps</dd></div>
      </dl>
      <p role="status" className="text-sm mb-3">{active ? 'Analysis is running.' : state.paused ? 'Automatic analysis is paused.' : 'Ready for a bounded batch.'} {state.stop_reason}</p>
      {(state.suspended > 0 || state.retry_waiting > 0) && <p className="text-sm text-brand-orange mb-3">
        {state.suspended} items stopped after three failures. {state.retry_waiting} items are waiting before another attempt.
        Failed items stay pending; the engine continues with eligible messages.
      </p>}
    </>}
    <div className="flex flex-wrap gap-3">
      <button onClick={() => void analyze()} disabled={!state || active || disabled || !hasData}
        className="px-4 py-2 bg-brand-black text-white rounded disabled:bg-brand-mid-grey">
        {active ? 'Analyzing…' : 'Analyze next batch'}
      </button>
      <button onClick={() => void pause()} disabled={!state || pausing || (state.paused && !active)}
        className="px-4 py-2 border rounded disabled:opacity-50">{pausing ? 'Saving pause…' : 'Pause analysis'}</button>
      <button onClick={() => void refresh()} className="px-4 py-2 border rounded">Refresh status</button>
    </div>
    {!hasData && <p className="text-sm mt-2">Sync messages first. Analysis will train missing assistant guidance automatically.</p>}
    <p className="text-xs text-brand-grey-80 mt-3">Each click starts one batch. It does not turn recurring analysis on. Adjust the daily allowance and batch size in Settings.</p>
    {notice && <p role="status" className="p-3 mt-3 border rounded text-sm">{notice}</p>}
    {statusError && <p role="alert" className="p-3 mt-3 border rounded text-sm">{statusError}</p>}
    {error && <p role="alert" className="p-3 mt-3 border border-brand-danger/30 text-brand-danger rounded text-sm whitespace-pre-wrap">{error}</p>}
  </section>
}
