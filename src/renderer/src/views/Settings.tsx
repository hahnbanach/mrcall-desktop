import { useEffect, useMemo, useState } from 'react'
import { errorMessage, isProfileLockedError } from '../lib/errors'
import NewProfileWizard from './NewProfileWizard'

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
  const [wizardOpen, setWizardOpen] = useState(false)
  const [createdToast, setCreatedToast] = useState<string | null>(null)

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
          : `Saved ${res.applied.length} field(s). Restart Zylch to apply.`
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
        <div className="text-slate-600">Loading…</div>
      </div>
    )
  }

  return (
    <div className="p-6 max-w-3xl mx-auto pb-24">
      <div className="flex items-center justify-between mb-2">
        <h1 className="text-2xl font-semibold">Settings</h1>
        <button
          onClick={() => setWizardOpen(true)}
          className="px-3 py-1.5 text-sm border rounded hover:bg-slate-100"
          title="Create a brand-new profile (opens a separate config form)"
        >
          + New Profile
        </button>
      </div>
      <p className="text-sm text-slate-600 mb-6">
        Edit the active profile&apos;s configuration. Secrets are masked — type a new value to
        replace, leave as <code className="text-xs bg-slate-100 px-1">{SECRET_PLACEHOLDER}</code> to
        keep the stored value.
      </p>

      {createdToast && (
        <div className="mb-4 p-3 bg-emerald-50 border border-emerald-300 text-emerald-900 rounded">
          Profile <span className="font-mono">{createdToast}</span> created. Open it via{' '}
          <span className="font-mono">+ New Window</span> in the top bar.
        </div>
      )}

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-800 rounded whitespace-pre-wrap">
          {error}
        </div>
      )}

      <NewProfileWizard
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        onCreated={(email) => {
          setWizardOpen(false)
          setCreatedToast(email)
          window.setTimeout(() => setCreatedToast(null), 6000)
        }}
      />


      {grouped.map(([group, items]) => (
        <section key={group} className="mb-6">
          <h2 className="text-sm font-semibold uppercase text-slate-600 mb-3 border-b pb-1">
            {group}
          </h2>
          <div className="space-y-4">
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
          className="px-4 py-2 bg-slate-900 text-white rounded disabled:bg-slate-400"
        >
          {saving ? 'Saving…' : `Save${hasChanges ? ` (${Object.keys(changes).length})` : ''}`}
        </button>
        <button
          onClick={handleDiscard}
          disabled={!hasChanges || saving}
          className="px-4 py-2 border rounded text-slate-700 disabled:text-slate-400"
        >
          Discard changes
        </button>
        {status.kind !== 'idle' && (
          <span
            className={
              'text-sm ' +
              (status.kind === 'success'
                ? 'text-green-700'
                : status.kind === 'error'
                  ? 'text-red-700'
                  : 'text-slate-600')
            }
          >
            {status.text}
          </span>
        )}
      </div>
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
    'w-full px-3 py-2 border rounded text-sm focus:outline-none focus:ring-2 focus:ring-slate-400 ' +
    (isDirty ? 'border-amber-400 bg-amber-50' : 'border-slate-300')

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

  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-slate-700 mb-1">
        {field.label}
        {!field.optional && <span className="text-red-600 ml-1">*</span>}
        <span className="ml-2 text-slate-400 font-mono text-[10px]">{field.key}</span>
      </label>
      {control}
      {field.help && <div className="text-xs text-slate-500 mt-1">{field.help}</div>}
    </div>
  )
}
