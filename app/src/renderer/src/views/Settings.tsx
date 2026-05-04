import { useEffect, useMemo, useState } from 'react'
import { errorMessage, isProfileLockedError } from '../lib/errors'
import Icon from '../components/Icon'
import ConnectGoogleCalendar from './ConnectGoogleCalendar'
import { performSignOut } from '../App'
import { auth } from '../firebase/config'

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
          Integrations
        </h2>
        <ConnectGoogleCalendar />
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
    try {
      const r = await window.zylch.account.balance()
      if ('error' in r && r.error === 'auth_expired') {
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
    control = (
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={baseInput}>
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
