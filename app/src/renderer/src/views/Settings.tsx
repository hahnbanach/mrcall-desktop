import * as React from 'react'
import { useEffect, useMemo, useState } from 'react'
import { errorMessage, isProfileLockedError } from '../lib/errors'
import Icon from '../components/Icon'
import ConnectGoogleCalendar from './ConnectGoogleCalendar'
import ConnectWhatsApp from './ConnectWhatsApp'
import { performSignOut } from '../App'
import { auth } from '../firebase/config'
import { ensureEngineSession } from '../firebase/authUtils'

type FieldType = 'text' | 'password' | 'number' | 'select' | 'textarea'

interface FieldDescriptor {
  key: string
  label: string
  type: FieldType
  group: string
  optional?: boolean
  options?: string[]
  help?: string
  secret?: boolean
  /** Render a native folder picker next to the text input. */
  picker?: 'directory' | 'directories'
  /** Hint shown when the value is unset: placeholder for text/number
   *  inputs, and the implicit first choice for selects. */
  default?: string
}

const SECRET_PLACEHOLDER = '<set>'

export default function Settings(): JSX.Element {
  const [fields, setFields] = useState<FieldDescriptor[]>([])
  const [loaded, setLoaded] = useState<Record<string, string>>({})
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState<{
    kind: 'idle' | 'success' | 'error' | 'progress'
    text: string
  }>({ kind: 'idle', text: '' })
  const [error, setError] = useState<string | null>(null)

  // Load schema + values once on mount.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [schema, current] = await Promise.all([
          window.zylch.settings.schema(),
          window.zylch.settings.get()
        ])
        if (cancelled) return
        setFields(schema.fields || [])
        setLoaded(current.values || {})
      } catch (e: unknown) {
        if (!cancelled) {
          if (isProfileLockedError(e)) {
            setError(null)
          } else {
            setError(errorMessage(e))
          }
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // Group fields for rendering.
  const grouped = useMemo(() => {
    const out = new Map<string, FieldDescriptor[]>()
    for (const f of fields) {
      const arr = out.get(f.group) || []
      arr.push(f)
      out.set(f.group, arr)
    }
    return Array.from(out.entries())
  }, [fields])

  // Compute the set of changes that will actually go to the wire.
  const changes = useMemo(() => {
    const out: Record<string, string> = {}
    for (const f of fields) {
      if (!(f.key in edits)) continue
      const newV = edits[f.key]
      const oldV = loaded[f.key] ?? ''
      // Secrets: skip if user left the placeholder unchanged.
      if (f.secret && newV === SECRET_PLACEHOLDER) continue
      if (newV === oldV) continue
      out[f.key] = newV
    }
    return out
  }, [edits, loaded, fields])

  const hasChanges = Object.keys(changes).length > 0

  const handleChange = (key: string, value: string) => {
    setEdits((prev) => ({ ...prev, [key]: value }))
  }

  const handleSave = async () => {
    if (!hasChanges) return
    setSaving(true)
    setError(null)
    setStatus({ kind: 'progress', text: 'Saving…' })
    try {
      const res = await window.zylch.settings.update(changes)
      if (!res.ok) {
        throw new Error('settings.update returned ok=false')
      }
      setStatus({ kind: 'progress', text: 'Restarting sidecar…' })
      let restarted = false
      try {
        const r = await window.zylch.sidecar.restart()
        restarted = r.ok
      } catch {
        restarted = false
      }
      // Reload values from the (possibly new) sidecar.
      try {
        const current = await window.zylch.settings.get()
        setLoaded(current.values || {})
        setEdits({})
      } catch {
        // Non-fatal — the user can refresh.
      }
      setStatus({
        kind: 'success',
        text: restarted
          ? `Saved ${res.applied.length} field(s). Sidecar restarted.`
          : `Saved ${res.applied.length} field(s). Restart MrCall Desktop to apply.`
      })
    } catch (e: unknown) {
      if (isProfileLockedError(e)) {
        setError(null)
      } else {
        setError(errorMessage(e))
      }
      setStatus({ kind: 'error', text: 'Save failed' })
    } finally {
      setSaving(false)
    }
  }

  const handleDiscard = () => {
    setEdits({})
    setStatus({ kind: 'idle', text: '' })
    setError(null)
  }

  if (loading) {
    return (
      <div className="p-6 max-w-3xl mx-auto">
        <h1 className="text-2xl font-semibold mb-4">Settings</h1>
        <div className="text-brand-grey-80">Loading…</div>
      </div>
    )
  }

  return (
    <div className="p-6 max-w-3xl mx-auto pb-24">
      <h1 className="text-2xl font-semibold mb-2">Settings</h1>
      <p className="text-sm text-brand-grey-80 mb-6">
        Edit the active profile&apos;s configuration. Secrets are masked — type a new value to
        replace, leave as <code className="text-xs bg-brand-light-grey px-1">{SECRET_PLACEHOLDER}</code> to
        keep the stored value.
      </p>

      {error && (
        <div className="mb-4 p-3 bg-brand-danger/10 border border-brand-danger/30 text-brand-danger rounded whitespace-pre-wrap">
          {error}
        </div>
      )}

      <section className="mb-6">
        <h2 className="text-sm font-semibold uppercase text-brand-grey-80 mb-3 border-b pb-1">
          Account
        </h2>
        <AccountCard />
      </section>

      <section className="mb-6">
        <h2 className="text-sm font-semibold uppercase text-brand-grey-80 mb-3 border-b pb-1">
          Backend location
        </h2>
        <BackendLocationCard />
      </section>

      <section className="mb-6">
        <h2 className="text-sm font-semibold uppercase text-brand-grey-80 mb-3 border-b pb-1">
          Integrations
        </h2>
        <div className="space-y-3">
          <ConnectGoogleCalendar />
          <ConnectWhatsApp />
        </div>
      </section>

      <section className="mb-6">
        <h2 className="text-sm font-semibold uppercase text-brand-grey-80 mb-3 border-b pb-1">
          SMS
        </h2>
        <SMSSenderCard />
      </section>

      <section className="mb-6">
        <h2 className="text-sm font-semibold uppercase text-brand-grey-80 mb-3 border-b pb-1">
          Maintenance
        </h2>
        <MaintenanceCard />
      </section>

      {grouped.map(([group, items]) => (
        <section key={group} className="mb-6">
          <h2 className="text-sm font-semibold uppercase text-brand-grey-80 mb-3 border-b pb-1">
            {group}
          </h2>
          <div className="space-y-4">
            {group === 'LLM' && (
              <LLMProviderCard
                // The engine resolves transport from key presence: an
                // ANTHROPIC_API_KEY in .env means BYOK, absence means
                // MrCall credits. We mirror that here — picking the
                // BYOK side reveals the key field in the schema below;
                // picking credits clears it.
                hasAnthropicKey={
                  ('ANTHROPIC_API_KEY' in edits
                    ? !!edits.ANTHROPIC_API_KEY
                    : !!loaded.ANTHROPIC_API_KEY)
                }
                onClearKey={() => handleChange('ANTHROPIC_API_KEY', '')}
              />
            )}
            {items.map((f) => (
              <FieldRow
                key={f.key}
                field={f}
                value={f.key in edits ? edits[f.key] : (loaded[f.key] ?? '')}
                onChange={(v) => handleChange(f.key, v)}
                isDirty={f.key in edits && edits[f.key] !== (loaded[f.key] ?? '')}
              />
            ))}
          </div>
        </section>
      ))}

      <div className="fixed bottom-0 left-0 right-0 border-t bg-white/95 backdrop-blur px-6 py-3 flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={!hasChanges || saving}
          className="px-4 py-2 bg-brand-black text-white rounded disabled:bg-brand-mid-grey"
        >
          {saving ? 'Saving…' : `Save${hasChanges ? ` (${Object.keys(changes).length})` : ''}`}
        </button>
        <button
          onClick={handleDiscard}
          disabled={!hasChanges || saving}
          className="px-4 py-2 border rounded text-brand-grey-80 disabled:text-brand-mid-grey"
        >
          Discard changes
        </button>
        {status.kind !== 'idle' && (
          <span
            className={
              'text-sm ' +
              (status.kind === 'success'
                ? 'text-brand-blue'
                : status.kind === 'error'
                  ? 'text-brand-danger'
                  : 'text-brand-grey-80')
            }
          >
            {status.text}
          </span>
        )}
      </div>
    </div>
  )
}

// ─── LLM mode card (BYOK vs MrCall credits) ──────────────────────────
//
// The engine has one provider (Anthropic) over two transports: direct
// (BYOK Anthropic key) and proxy (MrCall credits, billed via the
// Firebase session). The runtime decides based on whether
// ANTHROPIC_API_KEY is set in `.env`. This card mirrors that — it does
// not write a separate "provider" setting. Picking BYOK reveals the
// key field in the schema-driven section below; picking credits
// clears the key (with optional sign-in check).

interface BalancePayload {
  balance_credits: number
  balance_micro_usd: number
  balance_usd: number
  granularity_micro_usd?: number
  estimate_messages_remaining?: number
}

// Renderer doesn't know the active business_id (the engine resolves it
// from the Firebase JWT server-side). Bare /plan lets the dashboard
// pick up the business from the user's auth state.
const TOPUP_URL = 'https://dashboard.mrcall.ai/plan'

// ─── Backend location card (Local stdio vs Remote WebSocket) ─────────
//
// Cross-machine transport, Phase 2. Mirrors the LLMProviderCard radio
// pattern. The choice is PER-INSTALLATION (this machine), persisted
// machine-global in ~/.zylch/backend-config.json — NOT in the profile
// .env. Local (default) spawns the on-device sidecar exactly as today;
// Remote connects to `zylch -p <uid> serve --ws HOST:PORT` running on
// another machine, authenticating with the window's Firebase token.
//
// Applying a change requires re-establishing the transport, so this card
// owns its own Apply button that writes the config and then restarts the
// window's client (`sidecar.restart()` re-reads the config and builds the
// matching transport).
// SMS sender (SMS_FROM) — the alphanumeric "from" shown to recipients when
// the assistant sends an SMS. It's a per-business StarChat variable (same one
// the dashboard configures + the post-call SMS uses), so this card reads/writes
// it through the engine RPC -> mrcall-agent -> StarChat, NOT the profile .env.
function SMSSenderCard(): JSX.Element {
  const [saved, setSaved] = useState('')
  const [sender, setSender] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ kind: 'idle' | 'ok' | 'err'; text: string }>({
    kind: 'idle',
    text: ''
  })

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const r = await window.zylch.sms.getSender()
        if (cancelled) return
        if ('error' in r) {
          setMsg({ kind: 'err', text: 'Sign-in expired — sign in again.' })
        } else {
          setSaved(r.sender ?? '')
          setSender(r.sender ?? '')
        }
      } catch (e) {
        if (!cancelled) setMsg({ kind: 'err', text: errorMessage(e) })
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const isDirty = sender !== saved
  const isValid = sender.trim().length >= 1 && sender.length <= 11

  const handleSave = async (): Promise<void> => {
    if (!isDirty || !isValid) return
    setSaving(true)
    setMsg({ kind: 'idle', text: '' })
    try {
      const r = await window.zylch.sms.setSender(sender.trim())
      if ('error' in r) {
        setMsg({ kind: 'err', text: 'Sign-in expired — sign in again.' })
        return
      }
      setSaved(r.sender)
      setSender(r.sender)
      setMsg({ kind: 'ok', text: 'SMS sender saved.' })
    } catch (e) {
      setMsg({ kind: 'err', text: errorMessage(e) })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-white border border-brand-mid-grey rounded-lg p-4 space-y-3">
      <div>
        <div className="text-sm font-semibold text-brand-black">SMS sender</div>
        <p className="text-xs text-brand-grey-80 mt-0.5">
          The name shown as the sender when you send an SMS (max 11 characters).
          One-way: recipients can&apos;t reply. Leave it set and the assistant can
          text contacts from chat.
        </p>
      </div>
      {loading ? (
        <div className="text-xs text-brand-grey-80">Loading…</div>
      ) : (
        <>
          <label className="block">
            <span className="flex items-center justify-between text-xs font-medium text-brand-grey-80 mb-1">
              <span>Sender ID</span>
              <span className="font-mono text-[10px] text-brand-mid-grey">{sender.length}/11</span>
            </span>
            <input
              type="text"
              value={sender}
              maxLength={11}
              onChange={(e) => {
                setSender(e.target.value.slice(0, 11))
                setMsg({ kind: 'idle', text: '' })
              }}
              placeholder="e.g. MrCall"
              className={
                'w-full px-3 py-2 border rounded text-sm focus:outline-none focus:ring-2 ' +
                (isDirty && !isValid
                  ? 'border-brand-danger bg-brand-danger/5 focus:ring-brand-danger/50'
                  : 'border-brand-mid-grey focus:ring-brand-mid-grey')
              }
            />
          </label>
          {msg.kind !== 'idle' && (
            <div
              className={
                'text-xs ' + (msg.kind === 'ok' ? 'text-brand-blue' : 'text-brand-danger')
              }
            >
              {msg.text}
            </div>
          )}
          <div className="flex items-center gap-3 pt-1">
            <button
              onClick={() => void handleSave()}
              disabled={!isDirty || !isValid || saving}
              className="px-3 py-1.5 text-xs bg-brand-black text-white rounded disabled:bg-brand-mid-grey"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
            {isDirty && (
              <button
                onClick={() => {
                  setSender(saved)
                  setMsg({ kind: 'idle', text: '' })
                }}
                disabled={saving}
                className="px-3 py-1.5 text-xs border rounded text-brand-grey-80 hover:bg-brand-light-grey disabled:opacity-50"
              >
                Discard
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function BackendLocationCard(): JSX.Element {
  const signedIn = !!auth.currentUser
  const [loading, setLoading] = useState(true)
  // The persisted state (what's actually live after the last apply).
  const [savedLocation, setSavedLocation] = useState<'local' | 'remote'>('local')
  const [savedUrl, setSavedUrl] = useState('')
  // The in-progress edits.
  const [location, setLocation] = useState<'local' | 'remote'>('local')
  const [url, setUrl] = useState('')
  const [applying, setApplying] = useState(false)
  const [applyMsg, setApplyMsg] = useState<{ kind: 'idle' | 'ok' | 'err'; text: string }>({
    kind: 'idle',
    text: ''
  })
  const [testMsg, setTestMsg] = useState<{ kind: 'idle' | 'ok' | 'err' | 'busy'; text: string }>(
    { kind: 'idle', text: '' }
  )

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const cfg = await window.zylch.settings.getBackendLocation()
        if (cancelled) return
        setSavedLocation(cfg.location)
        setSavedUrl(cfg.url ?? '')
        setLocation(cfg.location)
        setUrl(cfg.url ?? '')
      } catch {
        /* fall back to local defaults already in state */
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const urlValid = location === 'local' || /^wss?:\/\/.+/i.test(url.trim())
  const dirty = location !== savedLocation || (location === 'remote' && url.trim() !== savedUrl)

  const handleTest = async (): Promise<void> => {
    const u = url.trim()
    if (!/^wss?:\/\/.+/i.test(u)) {
      setTestMsg({ kind: 'err', text: 'Enter a ws:// or wss:// URL first.' })
      return
    }
    setTestMsg({ kind: 'busy', text: 'Testing…' })
    try {
      const r = await window.zylch.settings.testBackendConnection(u)
      if (r.ok) {
        setTestMsg({
          kind: 'ok',
          text: r.signedIn
            ? `Connected as ${r.email || r.uid || 'unknown'}.`
            : 'Connected, but the engine reports no active session.'
        })
      } else {
        setTestMsg({ kind: 'err', text: `${r.message} (${r.code})` })
      }
    } catch (e) {
      setTestMsg({ kind: 'err', text: errorMessage(e) })
    }
  }

  const handleApply = async (): Promise<void> => {
    setApplying(true)
    setApplyMsg({ kind: 'idle', text: '' })
    try {
      const r = await window.zylch.settings.setBackendLocation(
        location,
        location === 'remote' ? url.trim() : undefined
      )
      if (!r.ok) {
        setApplyMsg({ kind: 'err', text: 'Failed to save backend location.' })
        return
      }
      setSavedLocation(location)
      setSavedUrl(location === 'remote' ? url.trim() : '')
      // Re-establish the transport: restart() re-reads backend-config.json
      // and builds the matching client (stdio ↔ ws).
      setApplyMsg({ kind: 'idle', text: 'Reconnecting…' })
      try {
        await window.zylch.sidecar.restart()
      } catch {
        /* the restart banner / next RPC will surface failures */
      }
      setApplyMsg({
        kind: 'ok',
        text:
          location === 'remote'
            ? 'Saved. Reconnecting to the remote engine…'
            : 'Saved. Restarting the local engine…'
      })
    } catch (e) {
      setApplyMsg({ kind: 'err', text: errorMessage(e) })
    } finally {
      setApplying(false)
    }
  }

  if (loading) {
    return (
      <div className="bg-white border border-brand-mid-grey rounded-lg p-4">
        <div className="text-xs text-brand-grey-80">Loading…</div>
      </div>
    )
  }

  return (
    <div className="bg-white border border-brand-mid-grey rounded-lg p-4 space-y-3">
      <div className="text-xs font-medium text-brand-grey-80">Where does the engine run?</div>

      <label className="flex items-start gap-2 cursor-pointer">
        <input
          type="radio"
          name="backend-location"
          checked={location === 'local'}
          onChange={() => setLocation('local')}
          className="mt-0.5"
        />
        <span className="text-sm text-brand-black">
          <strong>Local</strong> <span className="text-brand-grey-80">(default)</span>
          <div className="text-xs text-brand-grey-80 mt-0.5">
            The engine runs on this machine. Your data never leaves the device.
          </div>
        </span>
      </label>

      <label className="flex items-start gap-2 cursor-pointer">
        <input
          type="radio"
          name="backend-location"
          checked={location === 'remote'}
          onChange={() => setLocation('remote')}
          className="mt-0.5"
        />
        <span className="text-sm text-brand-black flex-1">
          <strong>Remote</strong>{' '}
          <span className="text-brand-grey-80 font-mono text-[11px]">(wss://…)</span>
          <div className="text-xs text-brand-grey-80 mt-0.5">
            Connect to an engine running on another machine
            (<code className="text-[11px]">zylch -p &lt;uid&gt; serve --ws HOST:PORT</code>).
            Authenticated with your signed-in MrCall account.
          </div>
        </span>
      </label>

      {location === 'remote' && (
        <div className="mt-2 border-t pt-3 space-y-2">
          <label className="block text-xs font-medium text-brand-grey-80">
            Backend URL
            <input
              type="text"
              value={url}
              onChange={(e) => {
                setUrl(e.target.value)
                setTestMsg({ kind: 'idle', text: '' })
              }}
              placeholder="wss://desktop.mrcall.ai  (or ws://127.0.0.1:5174 for a local test)"
              spellCheck={false}
              autoCapitalize="off"
              autoCorrect="off"
              className={
                'mt-1 w-full px-3 py-2 border rounded text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-mid-grey ' +
                (url.trim() && !urlValid
                  ? 'border-brand-danger bg-brand-danger/5'
                  : 'border-brand-mid-grey')
              }
            />
          </label>
          {url.trim() && !urlValid && (
            <div className="text-xs text-brand-danger">URL must start with ws:// or wss://</div>
          )}
          {!signedIn && (
            <div className="text-xs text-brand-danger">
              Sign in first — the remote engine authenticates with your MrCall account.
            </div>
          )}
          <div className="flex items-center gap-3 text-xs">
            <button
              type="button"
              onClick={() => void handleTest()}
              disabled={!urlValid || !signedIn || testMsg.kind === 'busy'}
              className="px-3 py-1.5 border rounded text-brand-grey-80 hover:bg-brand-light-grey disabled:opacity-50"
            >
              {testMsg.kind === 'busy' ? 'Testing…' : 'Test connection'}
            </button>
            {testMsg.kind !== 'idle' && (
              <span
                className={
                  testMsg.kind === 'ok'
                    ? 'text-brand-blue'
                    : testMsg.kind === 'err'
                      ? 'text-brand-danger'
                      : 'text-brand-grey-80'
                }
              >
                {testMsg.text}
              </span>
            )}
          </div>
        </div>
      )}

      <div className="border-t pt-3 flex items-center gap-3">
        <button
          type="button"
          onClick={() => void handleApply()}
          disabled={!dirty || applying || (location === 'remote' && (!urlValid || !signedIn))}
          className="px-4 py-2 bg-brand-black text-white rounded text-sm disabled:bg-brand-mid-grey"
        >
          {applying ? 'Applying…' : 'Apply & reconnect'}
        </button>
        {applyMsg.kind !== 'idle' && applyMsg.text && (
          <span
            className={
              'text-sm ' +
              (applyMsg.kind === 'ok'
                ? 'text-brand-blue'
                : applyMsg.kind === 'err'
                  ? 'text-brand-danger'
                  : 'text-brand-grey-80')
            }
          >
            {applyMsg.text}
          </span>
        )}
        {!dirty && savedLocation === 'remote' && (
          <span className="text-xs text-brand-grey-80 font-mono">Active: {savedUrl}</span>
        )}
      </div>
    </div>
  )
}

function LLMProviderCard({
  hasAnthropicKey,
  onClearKey
}: {
  hasAnthropicKey: boolean
  onClearKey: () => void
}): JSX.Element {
  const signedIn = !!auth.currentUser
  const isCredits = !hasAnthropicKey

  const [balance, setBalance] = useState<BalancePayload | null>(null)
  const [balanceErr, setBalanceErr] = useState<string | null>(null)
  const [balanceLoading, setBalanceLoading] = useState(false)

  const refreshBalance = async (): Promise<void> => {
    if (!signedIn) return
    setBalanceLoading(true)
    setBalanceErr(null)
    // Self-heal: the engine holds the Firebase token in memory only,
    // so every sidecar restart starts session-less and the first
    // account.balance call after one fails with NoActiveSession (code
    // -32010) until the auth listener pushes the token. Re-push +
    // verify via account.whoAmI BEFORE the balance call so the user
    // sees real numbers, not a stale balance frozen at the last
    // successful fetch — Mario flagged the suspiciously-static credit
    // count on production@example.com, that was the underlying cause.
    const sessionOk = await ensureEngineSession()
    if (!sessionOk) {
      setBalance(null)
      setBalanceErr('Session not yet established — sign in again or wait a moment.')
      setBalanceLoading(false)
      return
    }
    try {
      const r = await window.zylch.account.balance()
      if ('error' in r && r.error === 'auth_expired') {
        // One retry: maybe the re-push just landed and a follow-up
        // call now has a fresh session.
        const recovered = await ensureEngineSession()
        if (recovered) {
          const r2 = await window.zylch.account.balance()
          if ('balance_credits' in r2) {
            setBalance(r2)
            return
          }
        }
        setBalance(null)
        setBalanceErr('Session expired — please sign in again.')
      } else if ('balance_credits' in r) {
        setBalance(r)
      }
    } catch (e: unknown) {
      setBalance(null)
      setBalanceErr(errorMessage(e))
    } finally {
      setBalanceLoading(false)
    }
  }

  // Fetch balance on mount when on credits, and every time the window
  // regains focus (user may have topped up in another tab).
  useEffect(() => {
    if (!isCredits || !signedIn) return
    void refreshBalance()
    const onFocus = (): void => {
      void refreshBalance()
    }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isCredits, signedIn])

  return (
    <div className="bg-white border border-brand-mid-grey rounded-lg p-4 space-y-3">
      <div className="text-xs font-medium text-brand-grey-80">LLM billing mode</div>
      {isCredits ? (
        <div className="text-sm text-brand-black">
          <strong>MrCall credits</strong> (Firebase signin)
          <div className="text-xs text-brand-grey-80 mt-0.5">
            Claude calls are routed through <code className="text-[11px]">mrcall-agent</code>{' '}
            and billed against your MrCall credit balance.
          </div>
          {!signedIn && (
            <div className="text-xs text-brand-danger mt-1">
              Sign in with Firebase to actually make calls.
            </div>
          )}
        </div>
      ) : (
        <div className="text-sm text-brand-black">
          <strong>BYOK (Anthropic key)</strong>
          <div className="text-xs text-brand-grey-80 mt-0.5">
            Calls go directly to Anthropic. No MrCall credits consumed.
          </div>
          <button
            type="button"
            onClick={onClearKey}
            className="mt-2 text-xs text-brand-grey-80 underline hover:text-brand-black"
            title="Clear ANTHROPIC_API_KEY and switch back to MrCall credits"
          >
            Switch to MrCall credits
          </button>
        </div>
      )}

      {isCredits && signedIn && (
        <div className="mt-2 border-t pt-3 space-y-2">
          {balanceLoading && <div className="text-xs text-brand-grey-80">Loading balance…</div>}
          {balanceErr && (
            <div className="text-xs text-brand-danger">Balance: {balanceErr}</div>
          )}
          {balance && !balanceLoading && (
            <div className="text-xs">
              <span className="text-brand-grey-80">Balance: </span>
              <span className="font-medium text-brand-black">
                {balance.balance_credits.toLocaleString()} credits
              </span>
              <span className="text-brand-grey-80">
                {' '}
                (~${balance.balance_usd.toFixed(2)})
              </span>
              {typeof balance.estimate_messages_remaining === 'number' && (
                <span className="text-brand-grey-80">
                  {' '}
                  · ~{balance.estimate_messages_remaining} messages left
                </span>
              )}
            </div>
          )}
          <div className="flex items-center gap-3 text-xs">
            <button
              type="button"
              onClick={() => void window.zylch.shell.openExternal(TOPUP_URL)}
              className="text-brand-blue underline hover:no-underline"
            >
              Top up credits
            </button>
            <button
              type="button"
              onClick={() => void refreshBalance()}
              disabled={balanceLoading}
              className="text-brand-grey-80 underline hover:no-underline disabled:opacity-50"
            >
              Refresh
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function MaintenanceCard(): JSX.Element {
  // Two on-demand sweeps that mirror the automatic post-/update path.
  // Independent state for each so a slow reconsolidation doesn't hide
  // the result of a fast dedup, and vice versa.
  const [dedupBusy, setDedupBusy] = React.useState(false)
  const [memBusy, setMemBusy] = React.useState(false)
  const [dedupResult, setDedupResult] = React.useState<string | null>(null)
  const [memResult, setMemResult] = React.useState<string | null>(null)

  const runDedup = async (): Promise<void> => {
    setDedupBusy(true)
    setDedupResult(null)
    try {
      const r = await window.zylch.tasks.dedupNow()
      if (r.no_llm) {
        setDedupResult('No LLM transport configured. Sign in or paste an Anthropic key.')
        return
      }
      const parts: string[] = []
      parts.push(`Examined ${r.clusters_examined} cluster(s)`)
      if (r.tasks_closed > 0) {
        parts.push(`closed ${r.tasks_closed} duplicate(s) across ${r.clusters_with_dups} group(s)`)
      } else {
        parts.push('no duplicates found')
      }
      if (r.skipped_oversize > 0) {
        parts.push(`${r.skipped_oversize} oversize cluster(s) skipped`)
      }
      if (r.skipped_recently_reopened > 0) {
        parts.push(`${r.skipped_recently_reopened} reopened-recently protected`)
      }
      setDedupResult(parts.join(' · '))
    } catch (e) {
      setDedupResult(`Failed: ${(e as Error).message}`)
    } finally {
      setDedupBusy(false)
    }
  }

  const runReconsolidate = async (): Promise<void> => {
    setMemBusy(true)
    setMemResult(null)
    try {
      const r = await window.zylch.memory.reconsolidateNow()
      if (!r.ok) {
        setMemResult(`Failed: ${r.error || 'unknown error'}`)
        return
      }
      if (r.no_llm) {
        setMemResult('No LLM transport configured. Sign in or paste an Anthropic key.')
        return
      }
      const parts: string[] = []
      parts.push(`Examined ${r.blobs_examined ?? 0} blob(s) across ${r.groups_examined ?? 0} group(s)`)
      if ((r.blobs_merged ?? 0) > 0) {
        parts.push(`merged ${r.blobs_merged}`)
      } else {
        parts.push('no merges')
      }
      if ((r.blobs_kept_distinct ?? 0) > 0) {
        parts.push(`${r.blobs_kept_distinct} kept as distinct entities`)
      }
      if (r.pair_cap_hit) {
        parts.push('per-call cap hit — re-run to continue')
      }
      setMemResult(parts.join(' · '))
    } catch (e) {
      setMemResult(`Failed: ${(e as Error).message}`)
    } finally {
      setMemBusy(false)
    }
  }

  return (
    <div className="bg-white border border-brand-mid-grey rounded-lg shadow-sm p-4 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1">
          <div className="text-sm font-semibold text-brand-black">Clean up tasks</div>
          <p className="text-xs text-brand-grey-80 mt-1">
            Find duplicate open tasks (same contact or shared memory blobs) and merge them.
            Runs the same sweep that fires at the end of every <code>Update</code>.
          </p>
          {dedupResult && (
            <div className="text-xs text-brand-grey-80 mt-2 bg-brand-light-grey/50 rounded p-2">
              {dedupResult}
            </div>
          )}
        </div>
        <button
          onClick={runDedup}
          disabled={dedupBusy}
          className="px-3 py-1.5 text-xs border rounded text-brand-grey-80 hover:bg-brand-light-grey disabled:opacity-50 shrink-0"
        >
          {dedupBusy ? 'Running…' : 'Clean up'}
        </button>
      </div>

      <div className="border-t pt-4 flex items-start justify-between gap-3">
        <div className="flex-1">
          <div className="text-sm font-semibold text-brand-black">Reconsolidate memory</div>
          <p className="text-xs text-brand-grey-80 mt-1">
            Merge duplicate entity blobs (e.g. multiple records for the same person extracted
            from different emails). Walks the local memory namespace and asks the LLM to merge
            same-named entities.
          </p>
          {memResult && (
            <div className="text-xs text-brand-grey-80 mt-2 bg-brand-light-grey/50 rounded p-2">
              {memResult}
            </div>
          )}
        </div>
        <button
          onClick={runReconsolidate}
          disabled={memBusy}
          className="px-3 py-1.5 text-xs border rounded text-brand-grey-80 hover:bg-brand-light-grey disabled:opacity-50 shrink-0"
        >
          {memBusy ? 'Running…' : 'Reconsolidate'}
        </button>
      </div>
    </div>
  )
}

function AccountCard(): JSX.Element {
  // Read Firebase user synchronously — by the time Settings renders,
  // FirebaseAuthGate has already accepted the session.
  const user = auth.currentUser
  const email = user?.email || '—'
  const uid = user?.uid || ''
  return (
    <div className="bg-white border border-brand-mid-grey rounded-lg shadow-sm p-4 flex items-start justify-between gap-3">
      <div>
        <div className="text-sm font-semibold text-brand-black">{email}</div>
        {uid && (
          <div className="text-xs text-brand-grey-80 mt-0.5 font-mono">
            uid <span className="opacity-60">{uid}</span>
          </div>
        )}
        <p className="text-xs text-brand-grey-80 mt-1">
          Same MrCall account used in the dashboard. Sign out to switch users.
        </p>
      </div>
      <button
        onClick={() => performSignOut()}
        className="px-3 py-1.5 text-xs border rounded text-brand-grey-80 hover:bg-brand-light-grey shrink-0"
      >
        Sign out
      </button>
    </div>
  )
}

interface FieldRowProps {
  field: FieldDescriptor
  value: string
  onChange: (v: string) => void
  isDirty: boolean
}

function FieldRow({ field, value, onChange, isDirty }: FieldRowProps): JSX.Element {
  const id = `field-${field.key}`
  const baseInput =
    'w-full px-3 py-2 border rounded text-sm focus:outline-none focus:ring-2 focus:ring-brand-mid-grey ' +
    (isDirty ? 'border-brand-orange bg-brand-orange/10' : 'border-brand-mid-grey')

  let control: JSX.Element
  if (field.type === 'select' && field.options) {
    // When the stored value is empty, show the schema default as the
    // selected option (purely visual — we don't write it back unless the
    // user actively changes the select, so an untouched default stays
    // unset in the .env and the engine applies its own default).
    control = (
      <select
        id={id}
        value={value || field.default || ''}
        onChange={(e) => onChange(e.target.value)}
        className={baseInput}
      >
        {field.options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    )
  } else if (field.type === 'textarea') {
    control = (
      <textarea
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={3}
        className={baseInput}
      />
    )
  } else if (field.type === 'password') {
    control = (
      <input
        id={id}
        type="password"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="new-password"
        className={baseInput}
      />
    )
  } else if (field.type === 'number') {
    control = (
      <input
        id={id}
        type="number"
        value={value}
        placeholder={field.default}
        onChange={(e) => onChange(e.target.value)}
        className={baseInput}
      />
    )
  } else {
    control = (
      <input
        id={id}
        type="text"
        value={value}
        placeholder={field.default}
        onChange={(e) => onChange(e.target.value)}
        className={baseInput}
      />
    )
  }

  const pickDirectories = async (): Promise<void> => {
    try {
      const picked = await window.zylch.files.selectDirectories()
      if (picked.length === 0) return
      if (field.picker === 'directory') {
        // Single-directory field — last pick wins.
        onChange(picked[picked.length - 1])
      } else {
        // Multi-directory field — append, dedup, join with ", ".
        const existing = value
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean)
        const merged = Array.from(new Set([...existing, ...picked])).join(', ')
        onChange(merged)
      }
    } catch {
      /* user cancelled or dialog failed — silent */
    }
  }

  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-brand-grey-80 mb-1">
        {field.label}
        {!field.optional && <span className="text-brand-danger ml-1">*</span>}
        <span className="ml-2 text-brand-mid-grey font-mono text-[10px]">{field.key}</span>
      </label>
      {field.picker ? (
        <div className="flex gap-2">
          <div className="flex-1">{control}</div>
          <button
            type="button"
            onClick={pickDirectories}
            className="px-3 py-2 text-sm border border-brand-mid-grey rounded hover:bg-brand-light-grey transition-colors inline-flex items-center gap-1.5"
            title="Pick folder(s) in Finder"
          >
            <Icon name="folder" size={14} />
            Browse…
          </button>
        </div>
      ) : (
        control
      )}
      {field.help && <div className="text-xs text-brand-grey-80 mt-1">{field.help}</div>}
    </div>
  )
}
