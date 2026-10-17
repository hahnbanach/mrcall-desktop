import { useEffect, useRef, useState } from 'react'
import type { QontoCredentials, QontoPublicationPreview, QontoStatus, QontoTestResult } from '../finance'
import { useFinanceContext, type FinanceContextToken } from '../hooks/useFinanceContext'
import { auth } from '../firebase/config'

const OUTCOMES: Record<string, string> = {
  login_required: 'Enter the Qonto organization API login together with the key.',
  credentials_required: 'Enter your Qonto organization API login and key, then Test.',
  invalid_credentials: 'The Qonto login or key format is invalid.',
  auth: 'Qonto rejected these credentials. Check the API login and key, then Test again.',
  network: 'Qonto could not be reached. Check the network and try again.',
  tls: 'The secure connection to Qonto could not be verified. Check the engine network configuration.',
  rate_limited: 'Qonto is limiting requests. Wait until the retry time before syncing again.',
  accounts_invalid: 'Choose at least one account from the tested company, then Test again.',
  authority_required: 'Confirm that you are authorized to connect this company.',
  challenge_expired: 'The Qonto test expired. Test again before saving.',
  challenge_invalid: 'The Qonto test is no longer valid. Test again before saving.',
  binding_changed: 'The company or account binding changed. Test and confirm the connection again.',
  company_changed: 'Company memory changed. Test and confirm the Qonto binding again.',
  identity_required: 'Sign in to the selected engine profile before using Qonto.',
  session_expired: 'Your engine session expired. Sign in again.',
  generation_changed: 'The Qonto connection changed. Refresh its status and Test again.',
  not_connected: 'Connect Qonto before using this action.',
  source_unavailable: 'The private Qonto source is unavailable. Connect and authorize it on this engine before reviewing.',
  sync_limit: 'This bounded sync reached its work limit. Sync again to continue the remaining history windows.',
  invalid_response: 'Qonto returned data the engine could not validate. Refresh status and try again; incomplete coverage is retained.',
  busy: 'A Qonto operation is already running. Wait, then refresh its status.',
  paused: 'Preparation is paused. Use the explicit one-batch action to run a batch without changing the saved pause.',
  context_changed: 'The account or engine changed. Reload Qonto status and Test again.'
}
export function qontoError(cause: unknown): string {
  const raw = cause instanceof Error ? cause.message : String(cause)
  if (/method not found|unknown method|not implemented|update_required/i.test(raw)) return 'Your engine needs an update for this Qonto action.'
  const outcome = Object.keys(OUTCOMES).find(code => new RegExp(`\\b${code}\\b`).test(raw))
  return outcome ? OUTCOMES[outcome] : 'Qonto request failed. Refresh the connection status and check the engine configuration before trying again.'
}

export default function QontoCard() {
  const [status, setStatus] = useState<QontoStatus | null>(null)
  const [ready, setReady] = useState(false)
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState('')
  const [login, setLogin] = useState('')
  const [key, setKey] = useState('')
  const [tested, setTested] = useState<QontoTestResult | null>(null)
  const [accounts, setAccounts] = useState<string[]>([])
  const [authority, setAuthority] = useState(false)
  const [company, setCompany] = useState('')
  const [host, setHost] = useState('')
  const [preview, setPreview] = useState<QontoPublicationPreview | null>(null)
  const [publicationConsent, setPublicationConsent] = useState(false)
  const [deleteConsent, setDeleteConsent] = useState(false)
  const credentialRef = useRef<QontoCredentials | null>(null)
  const loadedContext = useRef<FinanceContextToken | null>(null)
  const loadedCompany = useRef<string | null>(null)
  const request = useRef(0)
  const formVersion = useRef(0)
  const refreshRef = useRef<() => Promise<void>>(async () => {})
  const clearTest = () => {
    credentialRef.current = null
    setTested(null); setAccounts([]); setAuthority(false)
  }
  const reset = () => {
    request.current++; formVersion.current++
    clearTest(); setLogin(''); setKey(''); setStatus(null); setReady(false)
    setPreview(null); setPublicationConsent(false); setDeleteConsent(false)
    setBusy(''); setCompany(''); setHost(''); loadedContext.current = null; loadedCompany.current = null
    setNotice('The account, engine or company changed. Test again before connecting.')
    if (auth.currentUser && !context.companyChanging.current) void refreshRef.current()
  }
  const context = useFinanceContext(reset)
  const refresh = async () => {
    const sequence = ++request.current
    try {
      const token = await context.capture()
      const caps = await window.zylch.system.capabilities().catch(() => null)
      if (!context.current(token) || sequence !== request.current) return
      if (caps?.chat_history_binding !== 1) throw new Error('update_required')
      const [snapshot, memory] = await Promise.all([window.zylch.qonto.status(), window.zylch.memory.status()])
      if (!context.current(token) || sequence !== request.current) return
      if (loadedContext.current && (loadedContext.current.transport !== token.transport || loadedContext.current.uid !== token.uid)) {
        clearTest(); setLogin(''); setKey(''); setPreview(null); setPublicationConsent(false)
      }
      const name = memory.available ? memory.self_notion || 'Current company memory (name not set)' : 'Company memory unavailable'
      if (loadedCompany.current !== null && loadedCompany.current !== name) { context.invalidate(); return }
      loadedContext.current = token; loadedCompany.current = name
      setStatus(snapshot); setReady(memory.available)
      setCompany(name)
      setHost(token.transport === 'local' ? 'Local engine on this computer' : token.transport.slice(7))
    } catch (cause) {
      if (sequence !== request.current) return
      setReady(false); setNotice(qontoError(cause))
    }
  }
  refreshRef.current = refresh
  useEffect(() => {
    void refresh()
    const focus = () => { void refreshRef.current() }
    window.addEventListener('focus', focus)
    return () => { request.current++; credentialRef.current = null; window.removeEventListener('focus', focus) }
  }, [])
  useEffect(() => {
    if (!tested) return
    const timer = setTimeout(() => { clearTest(); setNotice('The Qonto test expired. Test again before saving.') }, Math.max(0, tested.expires_at * 1000 - Date.now()))
    return () => clearTimeout(timer)
  }, [tested])
  const edit = (change: () => void) => {
    formVersion.current++; clearTest(); setPreview(null); setPublicationConsent(false); setNotice('')
    change()
  }
  const admit = async () => {
    const token = await context.capture()
    const loaded = loadedContext.current
    if (!loaded || loaded.transport !== token.transport || loaded.uid !== token.uid) {
      reset(); throw new Error('context_changed')
    }
    const memory = await window.zylch.memory.status()
    if (!context.current(token)) throw new Error('context_changed')
    const name = memory.available ? memory.self_notion || 'Current company memory (name not set)' : 'Company memory unavailable'
    if (!memory.available || name !== loadedCompany.current) { context.invalidate(); throw new Error('company_changed') }
    return token
  }
  const run = async (label: string, action: (token: FinanceContextToken) => Promise<void>) => {
    if (!ready || busy) return
    const epoch = context.epoch.current
    const version = formVersion.current
    setBusy(label); setNotice('')
    try {
      const token = await admit()
      if (context.current(token)) await action(token)
    } catch (cause) {
      if (epoch === context.epoch.current && version === formVersion.current) {
        credentialRef.current = null; setLogin(''); setKey(''); setTested(null)
        setPreview(null); setPublicationConsent(false); setNotice(qontoError(cause))
      }
    } finally { if (epoch === context.epoch.current) setBusy('') }
  }
  const test = () => run('Testing Qonto…', async token => {
    const version = formVersion.current
    const credentials: QontoCredentials = { credential_source: 'input', login, api_key: key }
    clearTest()
    try {
      const result = await window.zylch.qonto.test(credentials)
      if (!context.current(token) || version !== formVersion.current) return
      if (!Object.prototype.hasOwnProperty.call(result, 'company_name') || (result.company_name !== null && typeof result.company_name !== 'string')) throw new Error('update_required')
      const memory = await window.zylch.memory.status()
      if (!context.current(token) || version !== formVersion.current) return
      const name = memory.available ? memory.self_notion || 'Current company memory (name not set)' : 'Company memory unavailable'
      if (!memory.available || name !== loadedCompany.current) { context.invalidate(); throw new Error('company_changed') }
      if (!result.ok || !result.challenge_id || result.expires_at * 1000 <= Date.now() || !result.organization?.accounts?.length) throw new Error('challenge_invalid')
      credentialRef.current = credentials
      setTested(result); setAccounts(result.account_ids); setNotice('Test passed. Check the company and accounts, then confirm your authority before saving.')
    } finally { if (context.current(token) && version === formVersion.current) { setLogin(''); setKey('') } }
  })
  const save = () => run('Saving Qonto…', async token => {
    if (!tested || !credentialRef.current || !authority || !accounts.length || accounts.some(id => !tested.account_ids.includes(id))) throw new Error('authority_required')
    if (tested.expires_at * 1000 <= Date.now()) throw new Error('challenge_expired')
    const params = { ...credentialRef.current, challenge_id: tested.challenge_id, account_ids: accounts, authority_confirmed: true, consent_version: tested.consent_version }
    credentialRef.current = null; setLogin(''); setKey(''); setTested(null)
    const result = await window.zylch.qonto.connect(params)
    if (!context.current(token)) return
    if (!result.ok || result.status !== 'connected') throw new Error('not_connected')
    window.dispatchEvent(new Event('mrcall:qonto-changed'))
    setNotice(result.initial_sync.status === 'completed' ? 'Qonto connected. Initial history windows were traversed.' : 'Qonto connected. Initial sync is partial; review coverage and sync again to continue.')
    await refresh()
  })
  const sync = () => run('Syncing Qonto…', async token => {
    setPreview(null); setPublicationConsent(false)
    const result = await window.zylch.qonto.sync()
    if (!context.current(token)) return
    window.dispatchEvent(new Event('mrcall:qonto-changed'))
    setNotice(result.error ? qontoError(new Error(result.error)) : `Sync ${result.status}. ${result.remaining_windows} windows remain.`)
    await refresh()
  })
  const prepare = () => run('Preparing finance batch…', async token => {
    const result = await window.zylch.qonto.prepare(true)
    if (!context.current(token)) return
    window.dispatchEvent(new Event('mrcall:qonto-changed'))
    setNotice(result.errors?.length ? result.errors.map(error => error.detail).join(' · ') : result.summary || `One finance batch completed: ${result.completed ?? 0} items. ${result.stop_reason || ''}`)
  })
  const previewFact = () => run('Loading publication preview…', async token => {
    setPreview(null); setPublicationConsent(false)
    const result = await window.zylch.qonto.publicationPreview()
    if (!context.current(token)) return
    if (!result.preview_id || !result.fact_text || !result.disclosure) throw new Error('invalid_response')
    setPreview(result)
  })
  const publish = () => run('Publishing confirmed fact…', async token => {
    if (!preview || !publicationConsent) return
    const result = await window.zylch.qonto.publish(preview.preview_id, true, true)
    if (!context.current(token)) return
    setPreview(null); setPublicationConsent(false)
    setNotice(`Publication ${result.status}${result.reason ? ': ' + result.reason : '.'}`)
  })
  const disconnect = () => run('Disconnecting Qonto…', async token => {
    clearTest(); setPreview(null); setPublicationConsent(false); setLogin(''); setKey('')
    await window.zylch.qonto.disconnect()
    if (!context.current(token)) return
    window.dispatchEvent(new Event('mrcall:qonto-changed'))
    setNotice('Qonto disconnected.')
    await refresh()
  })
  const deleteData = () => run('Deleting imported finance data…', async token => {
    if (!deleteConsent) return
    const result = await window.zylch.qonto.deleteImportedData(true)
    if (!context.current(token)) return
    setDeleteConsent(false); clearTest(); setPreview(null); setPublicationConsent(false)
    window.dispatchEvent(new Event('mrcall:qonto-changed'))
    setNotice(result.deleted ? 'Imported finance data deleted. Historical company facts remain shared; remove them through the ordinary memory tools if needed.' : 'Deletion was not confirmed by the engine.')
    await refresh()
  })
  const connected = status?.status === 'connected'
  const enabled = ready && !busy
  const style = 'px-3 py-1.5 text-sm border rounded disabled:opacity-50'
  return <section aria-label="Qonto connection" className="bg-white border rounded-lg p-4 space-y-3">
    <h3 className="font-semibold">Qonto</h3>
    <p className="text-xs text-brand-grey-80">MrCall reads selected accounts only; it cannot make payments or change Qonto records. The Qonto API key itself can allow writes by other integrations.</p>
    <p className="text-xs text-brand-grey-80">Raw finance records stay private in this profile on the selected engine host. Only records needed for a requested answer go to your configured LLM. Company memory receives no raw balances, account numbers or transaction narratives automatically.</p>
    <p className="text-sm">MrCall company: {tested ? tested.company_name || 'Current company memory (name not set)' : company || 'Checking…'} · Host: {host || 'Checking…'}</p>
    {status && <p className="text-sm">Connection: {status.status} · Selected accounts: {status.account_count}</p>}
    {status?.error && <p role="alert">{qontoError(new Error(status.error))}</p>}
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <label className="text-sm">Qonto API login<input aria-label="Qonto API login" type="password" autoComplete="off" value={login} disabled={!ready || (!!busy && busy !== 'Testing Qonto…')} onChange={event => edit(() => setLogin(event.target.value))} className="block border rounded px-2 py-1 w-full" /></label>
        <label className="text-sm">Qonto API key<input aria-label="Qonto API key" type="password" autoComplete="new-password" value={key} disabled={!ready || (!!busy && busy !== 'Testing Qonto…')} onChange={event => edit(() => setKey(event.target.value))} className="block border rounded px-2 py-1 w-full" /></label>
      </div>
      <button className={style} disabled={!enabled || !login || !key} onClick={test}>Test Qonto</button>
      {tested && <div className="border rounded p-3 space-y-2">
        <p className="text-sm font-medium">Qonto legal company: {tested.organization.legal_name} · {tested.organization.id}</p>
        <p className="text-xs">Confirmed engine location: {tested.engine_location}. Credentials are hidden and held only for this tested Save; editing credentials requires a new Test.</p>
        {tested.organization.accounts.map(account => <label key={account.id} className="flex gap-2 text-sm"><input type="checkbox" aria-label={`Select Qonto account ${account.id}`} checked={accounts.includes(account.id)} disabled={!enabled} onChange={event => { setAccounts(previous => event.target.checked ? [...previous, account.id] : previous.filter(id => id !== account.id)); setAuthority(false) }} />{account.name} · {account.currency} · {account.id}</label>)}
        <label className="flex gap-2 text-sm"><input aria-label="Confirm Qonto authority" type="checkbox" checked={authority} disabled={!enabled} onChange={event => setAuthority(event.target.checked)} />I am authorized to connect this Qonto company and these accounts to the MrCall company and host displayed above.</label>
        <button className={style} disabled={!enabled || !authority || !accounts.length} onClick={save}>Save Qonto and sync</button>
      </div>}
    </div>
    {status?.sync && <div className="text-xs border-t pt-2 space-y-1">
      <p>Sync coverage: {status.sync.status} · {status.sync.completed_windows} traversed windows · {status.sync.remaining_backfill_windows} initial-history windows remain · {status.sync.unresolved_pending_windows} pending windows need review.</p>
      <p>Traversed pages do not guarantee a fixed provider snapshot. Partial or stale coverage cannot establish complete cash flow.</p>
      {status.last_sync_at && <p>Last sync attempt: {new Date(status.last_sync_at * 1000).toLocaleString()}</p>}
      {status.sync.accounts.map(account => <p key={account.account_id}>Account {account.account_id}: emitted history through {account.emitted_watermark || 'not traversed'}; updates through {account.updated_watermark || 'not traversed'}.</p>)}
      {status.sync.error && <p role="alert">{qontoError(new Error(status.sync.error))}</p>}
      {status.sync.retry_at && <p>Retry after {new Date(status.sync.retry_at * 1000).toLocaleString()}.</p>}
    </div>}
    <div className="flex flex-wrap gap-2">
      <button className={style} disabled={!!busy} onClick={() => void refresh()}>Refresh Qonto status</button>
      <button className={style} disabled={!enabled || !connected} onClick={sync}>Sync Qonto now</button>
      <button className={style} disabled={!enabled || !connected} onClick={prepare}>Prepare one finance batch</button>
      <button className={style} disabled={!enabled || !connected} onClick={previewFact}>Preview company fact</button>
      <button className={style} disabled={!enabled || !connected} onClick={disconnect}>Disconnect Qonto</button>
    </div>
    <p className="text-xs">Preparation is an explicit bounded batch and does not enable automatic processing or change saved pause. Publication may use your configured LLM and is subject to the saved budget.</p>
    {preview && <div className="border rounded p-3 space-y-2">
      <p className="text-sm font-medium">Exact company fact: {preview.fact_text}</p><p className="text-xs">{preview.disclosure}</p>
      <p className="text-xs">Visible to all current and future company-key holders; the configured LLM may process this fact.</p>
      <label className="flex gap-2 text-sm"><input aria-label="Confirm Qonto publication" type="checkbox" checked={publicationConsent} disabled={!enabled} onChange={event => setPublicationConsent(event.target.checked)} />I confirm sharing exactly this previewed company fact.</label>
      <button className={style} disabled={!enabled || !publicationConsent} onClick={publish}>Publish confirmed fact</button>
    </div>}
    <div className="border-t pt-3 space-y-2">
      <p className="text-xs">Disconnect hides retained imported records. Delete imported data also removes private source rows and generated source-only task evidence. Published company facts remain historical shared knowledge. Neither action regenerates the Qonto key; provider key regeneration is a separate Qonto action that may affect other integrations.</p>
      <label className="flex gap-2 text-sm"><input aria-label="Confirm deletion of Qonto imported data" type="checkbox" checked={deleteConsent} disabled={!enabled} onChange={event => setDeleteConsent(event.target.checked)} />Delete imported finance data on this engine; keep historical shared facts.</label>
      <button className={style} disabled={!enabled || !deleteConsent} onClick={deleteData}>Delete imported Qonto data</button>
    </div>
    {(notice || busy) && <p role="status" className="text-sm text-brand-grey-80">{busy || notice}</p>}
  </section>
}
