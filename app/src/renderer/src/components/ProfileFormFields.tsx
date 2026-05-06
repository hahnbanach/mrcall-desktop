/**
 * Schema-driven set of form fields for creating or editing a profile.
 *
 * Used by Onboarding (first-run, before any sidecar exists for the new
 * profile) and NewProfileWizard (signed-in user creating an additional
 * profile). Settings.tsx renders the same shape but fetches the schema
 * from the live sidecar — kept separate because that path supports
 * masking, dirty-state and per-field "save" semantics that don't apply
 * to "create from scratch".
 */
import Icon from './Icon'
import { PROFILE_SCHEMA, type SchemaField } from '../lib/profileSchema'

interface Props {
  values: Record<string, string>
  onChange: (key: string, value: string) => void
  /**
   * If set, only fields belonging to one of these groups are rendered.
   * Defaults to all groups.
   */
  includeGroups?: string[]
}

export default function ProfileFormFields({
  values,
  onChange,
  includeGroups
}: Props): JSX.Element {
  const groups = new Map<string, SchemaField[]>()
  for (const f of PROFILE_SCHEMA) {
    if (includeGroups && !includeGroups.includes(f.group)) continue
    const arr = groups.get(f.group) || []
    arr.push(f)
    groups.set(f.group, arr)
  }
  const entries = Array.from(groups.entries())

  return (
    <div className="space-y-5">
      {entries.map(([group, items]) => (
        <section key={group}>
          <h3 className="text-xs font-semibold uppercase text-brand-grey-80 mb-2 border-b pb-1">
            {group}
          </h3>
          <div className="space-y-3">
            {items.map((f) => (
              <FieldRow
                key={f.key}
                field={f}
                value={values[f.key] ?? ''}
                onChange={(v) => onChange(f.key, v)}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

function FieldRow({
  field,
  value,
  onChange
}: {
  field: SchemaField
  value: string
  onChange: (v: string) => void
}): JSX.Element {
  const id = `onb-${field.key}`
  const baseInput =
    'w-full px-3 py-2 border border-brand-mid-grey rounded text-sm focus:outline-none focus:ring-2 focus:ring-brand-mid-grey'

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
        onChange(picked[picked.length - 1])
      } else {
        const existing = value
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean)
        const merged = Array.from(new Set([...existing, ...picked])).join(', ')
        onChange(merged)
      }
    } catch {
      /* user cancelled — silent */
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
