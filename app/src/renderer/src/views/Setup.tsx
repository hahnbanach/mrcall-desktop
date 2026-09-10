import { useCallback, useEffect, useRef, useState } from 'react'
import { preparationSummary } from '../lib/setupReadiness'

const VENDOR = 'wss://desktop.mrcall.ai'
type API = Window['zylch']
type Handoff = Awaited<ReturnType<API['workspace']['status']>>
type Snapshot = {
  config: Awaited<ReturnType<API['settings']['getBackendLocation']>>
  handoff: Handoff
  identity: Awaited<ReturnType<API['account']['whoAmI']>> | null
  settings: Record<string, string> | null
  memory: Awaited<ReturnType<API['memory']['status']>> | null
  preparation: Awaited<ReturnType<API['setup']['state']>> | null
}
export default function Setup({ onNavigate, active = true, refreshSession = async () => { const { ensureEngineSession } = await import('../firebase/authUtils'); await ensureEngineSession() } }: {
  onNavigate: (view: 'settings' | 'update') => void
  active?: boolean
  refreshSession?: () => Promise<void>
}): JSX.Element {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [copied, setCopied] = useState(false)
  const generation = useRef(0)
  const refresh = useCallback(async () => {
    const id = ++generation.current
    setBusy(true)
    setError('')
    setSnapshot(null)
    try {
      const [config, handoff] = await Promise.all([
        window.zylch.settings.getBackendLocation(), window.zylch.workspace.status()
      ])
      const values = await Promise.allSettled([
        window.zylch.account.whoAmI(), window.zylch.settings.get(),
        window.zylch.memory.status(), window.zylch.setup.state()
      ] as const)
      if (id !== generation.current) return
      const [identity, settings, memory, preparation] = values
      setSnapshot({ config, handoff,
        identity: identity.status === 'fulfilled' ? identity.value : null,
        settings: settings.status === 'fulfilled' ? settings.value.values : null,
        memory: memory.status === 'fulfilled' ? memory.value : null,
        preparation: preparation.status === 'fulfilled' ? preparation.value : null })
      if (values.some(value => value.status === 'rejected')) setError('Some engine checks could not finish. Check the connection in Settings, then retry.')
    } catch {
      if (id === generation.current) setError('Could not check setup. Open Settings to check the engine connection, then retry.')
    } finally { if (id === generation.current) setBusy(false) }
  }, [])
  useEffect(() => {
    if (active) void refresh()
    return () => { generation.current++ }
  }, [active, refresh])
  useEffect(() => window.zylch.onSidecarStatus(status => {
    generation.current++
    setSnapshot(null)
    if (status.alive && status.ready) void refresh()
    else { setBusy(false); setError('The engine is reconnecting or unavailable. Configuration remains available in Settings.') }
  }), [refresh])
  const remote = snapshot?.config.location === 'remote'
  const connected = !!(remote && snapshot?.identity?.signed_in && snapshot.handoff.available && snapshot.identity.uid === snapshot.handoff.uid)
  const settings = snapshot?.settings
  const mailbox = !!(settings?.IMAP_HOST && settings.EMAIL_PASSWORD)
  const provider = settings?.LLM_PROVIDER
  const billing = provider === 'mrcall' || (provider === 'anthropic' && !!settings?.ANTHROPIC_API_KEY) || (provider === 'openai' && !!settings?.OPENAI_API_KEY)
  const configured = mailbox && billing && !!snapshot?.memory?.available
  const preparation = preparationSummary(snapshot?.preparation ?? null)
  const ready = connected && configured && preparation.complete
  const connect = async () => {
    const id = ++generation.current
    setBusy(true); setError(''); setNotice('Checking the remote engine…'); setSnapshot(null)
    try {
      const target = snapshot?.config.location === 'remote' ? snapshot.config.url || VENDOR : VENDOR
      if (target.replace(/\/+$/, '') === VENDOR) {
        const status = await window.zylch.provision.status()
        if (!status.ok) throw new Error(status.message)
        if (status.state === 'preparing') {
          if (id === generation.current) setNotice('Your engine is being prepared. Wait a moment, then select Connect remote engine again.')
          return
        }
        if (status.state !== 'active') {
          const result = await window.zylch.provision.start()
          if (!result.ok && result.code !== 'already_provisioned') throw new Error(result.message)
          const current = await window.zylch.provision.status()
          if (!current.ok) throw new Error(current.message)
          if (current.state !== 'active') {
            if (id === generation.current) setNotice('Your engine is being prepared. Wait a moment, then select Connect remote engine again.')
            return
          }
        }
      }
      await refreshSession()
      const currentHandoff = await window.zylch.workspace.status()
      const proof = await window.zylch.settings.testBackendConnection(target)
      if (!proof.ok) throw new Error(proof.message)
      if (!proof.signedIn || !proof.uid || !currentHandoff.available || proof.uid !== currentHandoff.uid) throw new Error('The remote engine identity could not be verified for this profile. Sign in again and retry.')
      if (id !== generation.current) return
      const saved = await window.zylch.settings.setBackendLocation('remote', target)
      if (!saved.ok) throw new Error('The connection could not be saved. Retry from Settings.')
      setNotice('Remote engine selected. Checking its configuration and data…')
      await refreshSession()
      await window.zylch.sidecar.restart()
      await refresh()
    } catch (e) { if (id === generation.current) setError(e instanceof Error ? e.message : 'Connection failed. Retry or check Settings.') }
    finally { if (id === generation.current) setBusy(false) }
  }
  const copyCommand = async () => {
    if (!ready || !snapshot?.handoff.available) return
    try {
      await navigator.clipboard.writeText(snapshot.handoff.command)
      setCopied(true)
    } catch { setError('Copy failed. Select and copy the command manually.') }
  }
  const primary = !snapshot ? 'Check setup' : !connected ? 'Connect remote engine' : !configured ? 'Configure account' : !preparation.complete ? 'Prepare data' : 'Copy workspace command'
  const act = () => { if (ready) void copyCommand(); else if (!snapshot) void refresh(); else if (!connected) void connect(); else onNavigate(!configured ? 'settings' : 'update') }
  const cards = [
    { title: 'Configure your account', done: configured, text: settings ? `${settings.EMAIL_ADDRESS || 'Mailbox not selected'} · ${mailbox ? 'Mail connection configured' : 'Mail connection needed'} · ${billing ? 'Engine AI billing configured' : 'Engine AI billing needed'} · ${snapshot?.memory?.available ? 'Company memory connected' : 'Company memory needs attention'}` : 'Connect your mailbox, choose how to pay for engine AI, and create or join company memory.', action: 'Open settings', run: () => onNavigate('settings') },
    { title: 'Connect the remote engine', done: connected, text: connected ? `Connected as ${snapshot?.identity?.email || 'your profile'}. The engine runs independently of this computer.` : 'Activate your hosted engine, verify its identity, and select it. Company activation may require MrCall support. Local mode remains available in Settings.', action: connected ? 'Check connection' : 'Connect remote engine', run: () => void connect() },
    { title: 'Prepare your mailbox', done: connected && preparation.complete, text: preparation.text + ' Review suggested answers before sending.', action: 'Prepare data', run: () => onNavigate('update') },
    { title: 'Create your operator workspace', done: false, text: 'On this same computer, use cs-kernel to create a workspace. Then open Codex or Claude Code there. Your agent subscription is separate from MrCall engine credits.', action: '', run: () => {} }
  ]
  return <div className="max-w-4xl mx-auto p-6 md:p-10 space-y-6">
    <header className="rounded-2xl bg-brand-black text-white p-6 md:p-8">
      <p className="text-xs uppercase tracking-widest opacity-70">MrCall · Operator setup</p>
      <h1 className="text-3xl font-semibold mt-3">Your company, ready for your agent.</h1>
      <p className="mt-3 text-sm opacity-80 max-w-xl">Configure the engine here. Work with your company’s mail and memory from Codex or Claude Code in your workspace.</p>
      <div className="mt-5 flex flex-wrap items-center gap-3"><button disabled={busy} onClick={act} className="bg-white text-brand-black rounded-lg px-4 py-2 font-medium disabled:opacity-50">{busy ? 'Checking…' : primary}</button><button onClick={() => onNavigate('settings')} className="text-sm underline">Settings</button><span className="text-xs opacity-70">{ready ? 'Engine checks complete · workspace verification comes next' : 'Complete each step at your own pace'}</span></div>
    </header>
    {error && <div role="alert" className="rounded-lg border border-brand-danger/30 bg-brand-danger/10 p-4 text-sm"><p>{error}</p><button disabled={busy} onClick={() => void refresh()} className="underline mt-2">Retry checks</button></div>}
    {notice && <p role="status" className="text-sm bg-white border rounded-lg p-4">{notice}</p>}
    <div className="space-y-3">{cards.map((card, i) => <section key={card.title} className="bg-white border border-brand-mid-grey rounded-xl p-5 flex gap-4">
      <span className={'rounded-full w-8 h-8 shrink-0 flex items-center justify-center text-sm font-semibold ' + (card.done ? 'bg-green-100 text-green-800' : 'bg-brand-light-grey')}>{card.done ? '✓' : i + 1}</span>
      <div className="min-w-0 flex-1"><h2 className="font-semibold">{card.title}</h2><p className="text-sm text-brand-grey-80 mt-2 leading-relaxed">{card.text}</p>
        {card.action && <button onClick={card.run} disabled={busy && i === 1} className="mt-3 text-sm underline disabled:opacity-50">{card.action}</button>}
        {i === 3 && <div className="mt-3 space-y-3">
          {ready && snapshot?.handoff.available ? <><p className="text-xs text-brand-grey-80">Install a cs-kernel version that supports desktop setup before running this command.</p><code className="block rounded-lg bg-brand-light-grey p-3 text-xs break-all select-all">{snapshot.handoff.command}</code><button className="text-sm underline" onClick={() => void copyCommand()}>{copied ? 'Copied' : 'Copy command'}</button><p className="text-xs text-brand-grey-80">After creation and login, run <code>cs setup</code> inside the workspace. It verifies prerequisites; installed agent software alone does not prove agent sign-in.</p></> : <p className="text-sm">{snapshot?.handoff.available === false ? snapshot.handoff.reason : 'Verify this remote engine, its configuration, and mailbox processing to unlock the handoff.'}</p>}
        </div>}
      </div>
    </section>)}</div>
  </div>
}
