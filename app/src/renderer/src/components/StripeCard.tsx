import { useEffect, useRef, useState } from 'react'
import type { StripeStatus, StripeTestResult } from '../stripe'
import { useFinanceContext, type FinanceContextToken } from '../hooks/useFinanceContext'
import { auth } from '../firebase/config'
import { ensureEngineSession, isAuthSessionActive } from '../firebase/authUtils'

export function stripeError(cause: unknown): string {
  const raw = cause instanceof Error ? cause.message : String(cause)
  if (/method not found|unknown method|not implemented|update_required/i.test(raw)) return 'Update the selected engine to use the Stripe connection.'
  if (/startup_timeout/i.test(raw)) return 'The selected engine did not respond in time. Retry the connection check.'
  if (/identity_required|session_expired/i.test(raw)) return 'Sign in to the selected engine profile again, then retry the connection check.'
  if (/revoked|invalid_credentials|auth|permission/i.test(raw)) return 'Stripe rejected the key or required read permissions. Check the restricted key and Test again.'
  if (/challenge|generation|company_changed|context_changed|binding_changed/i.test(raw)) return 'The tested connection expired or its context changed. Test and confirm again.'
  if (/rate_limit/i.test(raw)) return 'Stripe is limiting requests. Wait before testing again.'
  return 'Stripe request failed. Check the selected engine and restricted key, then try again.'
}

export default function StripeCard() {
  const [status, setStatus] = useState<StripeStatus | null>(null)
  const [ready, setReady] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [key, setKey] = useState('')
  const [tested, setTested] = useState<StripeTestResult | null>(null)
  const [authority, setAuthority] = useState(false)
  const [company, setCompany] = useState('')
  const [host, setHost] = useState('')
  const secret = useRef<string | null>(null)
  const loaded = useRef<FinanceContextToken | null>(null)
  const loadedCompany = useRef<string | null>(null)
  const generation = useRef<number | null>(null)
  const sequence = useRef(0)
  const version = useRef(0)
  const refreshRef = useRef<() => Promise<void>>(async () => {})
  const clear = () => { secret.current = null; setKey(''); setTested(null); setAuthority(false) }
  const reset = () => {
    sequence.current++; version.current++; clear(); loaded.current = null; loadedCompany.current = null
    generation.current = null; setStatus(null); setReady(false); setLoading(false); setBusy(false); setCompany(''); setHost('')
    setNotice('The account, engine or company changed. Test again before connecting.')
    if (auth.currentUser && !context.companyChanging.current) void refreshRef.current()
  }
  const context = useFinanceContext(reset)
  const companyLabel = (memory: { available: boolean; self_notion?: string | null }) => memory.available ? memory.self_notion || 'Current company memory (name not set)' : 'Company memory unavailable'
  const refresh = async () => {
    const request = ++sequence.current
    const epoch = context.epoch.current
    const uid = auth.currentUser?.uid
    let settled = false
    const current = () => !settled && request === sequence.current && epoch === context.epoch.current && uid === auth.currentUser?.uid && isAuthSessionActive() && !context.companyChanging.current
    setReady(false); setLoading(true)
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
      const result = await Promise.race([
        (async () => {
          if (!current() || !await ensureEngineSession()) throw new Error('identity_required')
          if (!current()) throw new Error('context_changed')
          const token = await context.capture()
          if (!current() || !context.current(token)) throw new Error('context_changed')
          const [snapshot, memory] = await Promise.all([window.zylch.stripe.status(), window.zylch.memory.status()])
          return { token, snapshot, memory }
        })(),
        new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error('startup_timeout')), 12000) })
      ])
      if (!current() || !context.current(result.token)) return
      const { token, snapshot, memory } = result
      const name = companyLabel(memory)
      if (loadedCompany.current !== null && loadedCompany.current !== name) { context.invalidate(); return }
      if (generation.current !== null && generation.current !== snapshot.generation) { version.current++; clear() }
      generation.current = snapshot.generation; loaded.current = token; loadedCompany.current = name
      setStatus(snapshot); setReady(memory.available); setCompany(name)
      setHost(token.transport === 'local' ? 'Local engine on this computer' : token.transport.slice(7))
      if (!memory.available) { clear(); setNotice('Company memory is unavailable. Restore company memory, then retry the connection check.') }
      else setNotice('')
    } catch (cause) {
      if (request !== sequence.current || epoch !== context.epoch.current || uid !== auth.currentUser?.uid) return
      clear(); setReady(false); setStatus(null); setCompany('Unavailable'); setHost('Unavailable'); setNotice(stripeError(cause))
    } finally {
      settled = true
      clearTimeout(timer)
      if (request === sequence.current) setLoading(false)
    }
  }
  refreshRef.current = refresh
  useEffect(() => {
    void refresh()
    const focus = () => { void refreshRef.current() }
    window.addEventListener('focus', focus)
    return () => { sequence.current++; secret.current = null; window.removeEventListener('focus', focus) }
  }, [])
  useEffect(() => {
    if (!tested) return
    const timer = setTimeout(() => { version.current++; clear(); setNotice('The Stripe test expired. Test again before saving.') }, Math.max(0, tested.expires_at * 1000 - Date.now()))
    return () => clearTimeout(timer)
  }, [tested])
  const admit = async () => {
    const token = await context.capture()
    if (!loaded.current || loaded.current.transport !== token.transport || loaded.current.uid !== token.uid) { reset(); throw new Error('context_changed') }
    const [memory, snapshot] = await Promise.all([window.zylch.memory.status(), window.zylch.stripe.status()])
    if (!context.current(token)) throw new Error('context_changed')
    if (!memory.available || companyLabel(memory) !== loadedCompany.current) { context.invalidate(); throw new Error('company_changed') }
    if (snapshot.generation !== generation.current) { clear(); await refresh(); setNotice(stripeError(new Error('generation_changed'))); throw new Error('generation_changed') }
    return token
  }
  const run = async (action: (token: FinanceContextToken, form: number) => Promise<void>) => {
    if (!ready || busy) return
    const epoch = context.epoch.current
    const form = version.current
    setBusy(true); setNotice('')
    try { const token = await admit(); if (context.current(token) && form === version.current) await action(token, form) }
    catch (cause) { if (epoch === context.epoch.current && form === version.current) { clear(); setNotice(stripeError(cause)) } }
    finally { if (epoch === context.epoch.current) setBusy(false) }
  }
  const test = () => run(async (token, form) => {
    const apiKey = key
    clear()
    if (!/^rk_(test|live)_[A-Za-z0-9]+$/.test(apiKey)) throw new Error('invalid_credentials')
    const result = await window.zylch.stripe.test({ api_key: apiKey })
    if (!context.current(token) || form !== version.current) return
    if (!result.account?.id || !['test', 'live'].includes(result.mode) || !Array.isArray(result.capabilities) || !result.challenge_id || !Number.isFinite(result.expires_at) || result.expires_at * 1000 <= Date.now() || !Object.prototype.hasOwnProperty.call(result, 'company_name') || (result.company_name !== null && typeof result.company_name !== 'string')) throw new Error('update_required')
    const memory = await window.zylch.memory.status()
    if (!context.current(token) || form !== version.current) return
    if (!memory.available || companyLabel(memory) !== loadedCompany.current) { context.invalidate(); return }
    secret.current = apiKey; setTested(result); setNotice('Test passed. Confirm the account, environment and company before saving.')
  })
  const save = () => run(async (token, form) => {
    if (!tested || !secret.current || !authority || tested.expires_at * 1000 <= Date.now()) throw new Error('challenge_invalid')
    const params = { api_key: secret.current, challenge_id: tested.challenge_id, authority_confirmed: true as const }
    clear()
    const result = await window.zylch.stripe.connect(params)
    if (!context.current(token) || form !== version.current) return
    if (result.status !== 'connected') throw new Error('not_connected')
    setNotice('Stripe connected.'); await refresh()
  })
  const disconnect = () => run(async (token, form) => {
    clear()
    await window.zylch.stripe.disconnect()
    if (!context.current(token) || form !== version.current) return
    setNotice('Stripe disconnected. Provider key revocation is a separate action in Stripe.'); await refresh()
  })
  const enabled = ready && !busy
  const style = 'px-3 py-1.5 text-sm border rounded disabled:opacity-50'
  return <section aria-label="Stripe connection" className="bg-white border rounded-lg p-4 space-y-3">
    <h3 className="font-semibold">Stripe</h3>
    <p className="text-xs text-brand-grey-80">Read customers, payments, invoices and subscriptions with a restricted account key. MrCall cannot change Stripe records. A restricted key may still allow writes in other integrations.</p>
    <p className="text-xs text-brand-grey-80">Requested operator lookups disclose selected records to the invoking agent, its configured model and transcript. No automatic company-memory publication occurs. Disconnect cannot retract previously disclosed results.</p>
    <p className="text-sm">MrCall company: {tested ? tested.company_name || 'Current company memory (name not set)' : loading ? 'Checking…' : company || 'Unavailable'} · Host: {loading ? 'Checking…' : host || 'Unavailable'}</p>
    {status && <p className="text-sm">Connection: {status.status}{status.account ? ` · ${status.account.name || status.account.id} · ${status.account.id} · ${status.mode} environment` : ''}</p>}
    {status?.error && <p role="alert">{stripeError(new Error(status.error))}</p>}
    <label className="block text-sm">Stripe restricted API key<input aria-label="Stripe restricted API key" type="password" autoComplete="new-password" value={key} disabled={!ready || busy} onChange={event => { version.current++; clear(); setKey(event.target.value); setNotice('') }} className="block border rounded px-2 py-1 w-full" /></label>
    <p className="text-xs">Use rk_test_ or rk_live_ with account identity and supported resource read permissions. Saved keys are never read back.</p>
    <button className={style} disabled={!enabled || !/^rk_(test|live)_[A-Za-z0-9]+$/.test(key)} onClick={test}>Test Stripe</button>
    {tested && <div className="border rounded p-3 space-y-2">
      <p className="text-sm">Stripe account: {tested.account.name || 'Unnamed account'} · {tested.account.id} · {tested.mode} environment</p>
      <p className="text-xs">Available reads: {tested.capabilities.join(', ') || 'none'}. Credentials are hidden and held only until this tested Save expires.</p>
      <label className="flex gap-2 text-sm"><input aria-label="Confirm Stripe authority" type="checkbox" checked={authority} disabled={!enabled} onChange={event => setAuthority(event.target.checked)} />I am authorized to connect this Stripe account and environment to the MrCall company and engine displayed above.</label>
      <button className={style} disabled={!enabled || !authority} onClick={save}>Save Stripe</button>
    </div>}
    {status?.status === 'connected' && <p className="text-xs">Available reads: {status.capabilities.join(', ') || 'none'}. Enter and Test a new restricted key to replace this connection.</p>}
    <div className="flex gap-2"><button className={style} disabled={busy} onClick={() => void refresh()}>Refresh Stripe status</button><button className={style} disabled={!enabled || !status || status.status === 'disconnected'} onClick={disconnect}>Disconnect Stripe</button></div>
    {(notice || busy || loading) && <p role="status" className="text-sm">{busy ? 'Working…' : loading ? 'Checking the selected engine connection…' : notice}</p>}
  </section>
}
