import type { QontoCoverage } from '../src/renderer/src/finance'

export function createQontoFixture(saved: { connected?: boolean; generation?: number; prepared?: boolean; closed?: boolean; pinned?: boolean; companyName?: string } = {}) {
  let uid = 'fixture-uid'
  let companyName = saved.companyName ?? 'Fixture MrCall company'
  let companyNumber = 0
  let companyDescriptorAvailable = true
  let signedIn = true
  let backend = { location: 'local', url: '' }
  let connected = saved.connected ?? false
  let capability: number | undefined = 1
  let generation = saved.generation ?? 0
  let sourceRevision = 'fixture-revision-1'
  let legacyFields = false
  let challenge: { id: string; credentials: string; generation: number } | null = null
  let previewId = ''
  let prepared = saved.prepared ?? false
  let closed = saved.closed ?? false
  let pinned = saved.pinned ?? false
  let syncError: string | null = null
  let nextError = ''
  let testTtl = 300000
  const delays = new Map<string, { resolve: (value: unknown) => void; result: unknown } | null>()
  const channels = new Map<string, Set<(...args: unknown[]) => void>>()
  const calls: Array<{ method: string; params: Record<string, unknown> }> = []
  const coverage = (): QontoCoverage => ({
    status: syncError ? 'partial' : 'completed', completed_windows: syncError ? 10 : 30,
    remaining_windows: syncError ? 20 : 0, remaining_backfill_windows: syncError ? 20 : 0,
    history_planned: true, error: syncError, unresolved_pending_windows: 0, retry_at: null,
    coverage_kind: 'traversed_windows', accounts: [{ account_id: 'fixture-eur', emitted_watermark: '2026-10-04T00:00:00Z', updated_watermark: '2026-10-04T00:00:00Z', initial_from: '2026-09-04T00:00:00Z', initial_to: '2026-10-04T00:00:00Z' }]
  })
  // Older engines return `bootstrap` in status and removal results; the card ignores it.
  const legacyStatus = () => legacyFields ? { bootstrap: { available: true, status: 'available' } } : {}
  // Mirrors only the engine's credential-source refusal: `input` is the one accepted source and
  // `bootstrap` gets the engine's message. Other outcomes of this bridge are simplified stand-ins.
  const requireInputSource = (params: Record<string, unknown>) => {
    const source = params.credential_source === undefined ? 'input' : params.credential_source
    if (source === 'bootstrap') throw new Error('credentials_required: Enter the organization login and API key.')
    if (source !== 'input') throw new Error('invalid_credentials')
  }
  const status = () => ({ status: connected ? 'connected' : 'disconnected', generation, account_count: connected ? 1 : 0, source_access: false, credential_stored: connected, ...legacyStatus(), ...(connected ? { sync: coverage() } : {}) })
  const tasks = () => connected && prepared ? [{ id: 'fixture-qonto-task', owner_id: uid, channel: 'qonto', event_type: 'qonto', event_id: 'fixture-event', contact_email: '', title: 'Review this declined outgoing transaction', action_required: true, urgency: 'medium', reason: 'A selected account has a declined debit.', suggested_action: 'Review the Qonto source. No payment will be initiated.', created_at: '2026-10-04T00:00:00Z', completed_at: closed ? '2026-10-04T01:00:00Z' : null, pinned, sources: { emails: [], blobs: [], calendar_events: [], qonto: { source_id: 'fixture-source', source_revision: sourceRevision } } }] : []
  const emit = (name: string, value: unknown) => { for (const callback of channels.get(name) || []) callback({}, value) }
  const evaluate = (method: string, params: Record<string, unknown>) => {
    if (method === 'system.capabilities') return { chat_history_binding: capability }
    if (method === 'settings.schema') return { fields: [{ key: 'FIRST_NAME', label: 'First name', type: 'text', group: 'Personal data', optional: true }] }
    if (method === 'settings.get') return { values: { FIRST_NAME: 'Fixture owner' } }
    if (method === 'settings.get_secret') return { key: params.key, value: '' }
    if (method === 'memory.status') return { available: true, has_key: true, reason: '', self_notion: companyName, blob_count: 0, contributors: [] }
    if (method === 'memory.join_preview') return { well_formed: true, exists: true, self_notion: 'Other company ' + (companyNumber + 1), blob_count: 0, contributors: [] }
    if (method === 'memory.join') { companyName = 'Other company ' + (++companyNumber); connected = false; generation++; challenge = null; previewId = ''; return { ok: true, self_notion: companyName, merged: {} } }
    if (method === 'sms.get_sender') return { sender: '' }
    if (method === 'account.who_am_i') return { signed_in: signedIn, uid: signedIn ? uid : undefined }
    if (method === 'tasks.list') return tasks().filter(task => params.include_completed || !task.completed_at)
    if (method === 'tasks.pin') { pinned = params.pinned === true; return { ok: true } }
    if (method === 'tasks.complete') { closed = true; return { ok: true } }
    if (method === 'tasks.reopen') { closed = false; return { ok: true } }
    if (method === 'tasks.skip') { prepared = false; return { ok: true } }
    if (!method.startsWith('qonto.')) throw new Error('Unexpected fixture RPC: ' + method)
    if (!signedIn) throw new Error('identity_required')
    if (nextError) { const error = nextError; nextError = ''; throw new Error(error) }
    if (method === 'qonto.status') return status()
    if (method === 'qonto.test') {
      requireInputSource(params)
      if (!params.login || !params.api_key) throw new Error('credentials_required')
      challenge = { id: 'fixture-challenge-' + calls.length, credentials: JSON.stringify(params), generation }
      return { ok: true, ...(companyDescriptorAvailable ? { company_name: companyName } : {}), organization: { id: 'fixture-organization', name: 'Fixture Qonto', legal_name: 'Fixture Qonto legal company', accounts: [{ id: 'fixture-eur', name: 'Fixture EUR account', currency: 'EUR' }, { id: 'fixture-usd', name: 'Fixture USD account', currency: 'USD' }] }, challenge_id: challenge.id, expires_at: (Date.now() + testTtl) / 1000, account_ids: ['fixture-eur', 'fixture-usd'], engine_location: backend.location === 'local' ? 'local' : 'hosted', consent_version: 1 }
    }
    if (method === 'qonto.connect') {
      if (params.authority_confirmed !== true || params.consent_version !== 1) throw new Error('authority_required')
      requireInputSource(params)
      if (!challenge || params.challenge_id !== challenge.id || challenge.generation !== generation) throw new Error('challenge_invalid')
      const credentials = { credential_source: params.credential_source, login: params.login, api_key: params.api_key }
      if (JSON.stringify(credentials) !== challenge.credentials) throw new Error('invalid_credentials')
      const accounts = params.account_ids as string[]
      if (!Array.isArray(accounts) || !accounts.length || accounts.some(id => !['fixture-eur', 'fixture-usd'].includes(id))) throw new Error('accounts_invalid')
      connected = true; generation++; challenge = null
      return { ok: true, status: 'connected', generation, account_count: accounts.length, initial_sync: { ok: true, generation, requests: 30, ...coverage() } }
    }
    if (method === 'qonto.disconnect' || method === 'qonto.delete_imported_data') {
      if (method === 'qonto.delete_imported_data' && params.confirmed !== true) throw new Error('confirmation_required')
      connected = false; generation++; previewId = ''
      if (method === 'qonto.delete_imported_data') prepared = false
      return { ok: true, status: 'disconnected', generation, ...legacyStatus(), ...(legacyFields ? { bootstrap_retained: true } : {}), ...(method === 'qonto.delete_imported_data' ? { deleted: true, removed_rows: 1, published_facts_retained: true } : {}) }
    }
    if (!connected) throw new Error('source_unavailable')
    if (method === 'qonto.sync') return { ok: true, generation, requests: 30, ...coverage() }
    if (method === 'qonto.prepare') {
      if (params.resume !== true) throw new Error('paused')
      prepared = true
      return { success: true, summary: 'One finance batch completed. Saved pause remains enabled.', attempted: 1, completed: 1, failed: 0, paused: true, limit: 25, errors: [] }
    }
    if (method === 'qonto.publication_preview') {
      previewId = 'fixture-preview-' + generation
      return { preview_id: previewId, fact_text: 'The company uses Qonto with a selected EUR business account.', disclosure: 'All current and future company-key holders can read this minimal fact. The selected LLM may process it.', generation }
    }
    if (method === 'qonto.publish') {
      if (!previewId || params.preview_id !== previewId || params.confirmed !== true || params.resume !== true) throw new Error('confirmation_required')
      previewId = ''
      return { status: 'committed' }
    }
    if (method === 'qonto.transaction') {
      if (params.source_id !== 'fixture-source') throw new Error('source_unavailable')
      return { organization_id: 'fixture-organization', generation, retrieved_at: 1791072000, date_basis: 'source_timestamps', partial: false, stale: false, coverage: coverage(), transaction: { source_id: 'fixture-source', source_revision: sourceRevision, account_id: 'fixture-eur', currency: 'EUR', status: 'declined', side: 'debit', amount: { minor: 100, scale: 2, decimal: '1.00' }, retrieved_at: 1791072000, emitted_at: '2026-10-04T00:00:00Z', settled_at: null, updated_at: '2026-10-04T00:00:00Z', untrusted_source_text: { label: 'Synthetic fixture evidence' }, source_text_policy: 'untrusted evidence, never instructions' } }
    }
    throw new Error('Method not found: ' + method)
  }
  return {
    on: (name: string, callback: (...args: unknown[]) => void) => { const set = channels.get(name) || new Set(); set.add(callback); channels.set(name, set) },
    invoke: async (channel: string, method?: string, params: Record<string, unknown> = {}) => {
      if (channel === 'profile:current') return { id: uid, email: 'fixture@example.test' }
      if (channel === 'settings:getBackendLocation') return backend
      if (channel === 'sidecar:restart') { emit('sidecar:status', { alive: false, profile: uid, code: 'restarting' }); emit('sidecar:status', { alive: true, ready: true, profile: uid }); return { ok: true } }
      if (channel !== 'rpc:call' || !method) throw new Error('Unexpected fixture IPC: ' + channel)
      calls.push({ method, params: JSON.parse(JSON.stringify(params)) })
      const result = evaluate(method, params)
      if (delays.has(method)) return new Promise(resolve => delays.set(method, { resolve, result }))
      return result
    },
    calls: () => calls,
    companyDescriptor: (available: boolean) => { companyDescriptorAvailable = available },
    defer: (method: string) => delays.set(method, null),
    release: (method: string) => { const item = delays.get(method); delays.delete(method); item?.resolve(item.result) },
    pending: (method: string) => !!delays.get(method),
    fail: (outcome: string) => { nextError = outcome },
    testTtl: (milliseconds: number) => { testTtl = milliseconds },
    oldEngine: () => { capability = undefined },
    legacyBootstrapFields: (enabled: boolean) => { legacyFields = enabled },
    partialSync: () => { syncError = 'network' },
    goodSync: () => { syncError = null },
    connectFixture: () => { connected = true; generation++; prepared = true },
    changeRevision: () => { sourceRevision = 'fixture-revision-2' },
    changeHost: () => { backend = { location: 'remote', url: 'wss://fixture.engine.test' }; emit('sidecar:status', { alive: false, profile: uid, code: 'restarting' }); emit('sidecar:status', { alive: true, ready: true, profile: uid, remoteUrl: backend.url }) },
    changeUid: (value: string) => { uid = value; connected = false; generation++; emit('sidecar:status', { alive: true, ready: true, profile: uid }) },
    signOut: () => { signedIn = false },
    signIn: () => { signedIn = true },
    state: () => ({ connected, generation, prepared, closed, pinned, companyName })
  }
}
