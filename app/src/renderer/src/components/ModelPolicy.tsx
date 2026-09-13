import { useEffect, useState } from 'react'

const BASE_KEYS: Record<string, string> = {
  anthropic: 'ANTHROPIC_MODEL', openrouter: 'OPENROUTER_MODEL', mrcall: 'MRCALL_CREDITS_MODEL'
}
const ROLES: Record<string, string> = {
  MODEL_MEMORY_EXTRACT: 'Memory extraction', MODEL_MEMORY_MERGE: 'Memory comparison',
  MODEL_TASK_DETECTION: 'Task detection', MODEL_REANALYZE: 'Task review', MODEL_DEDUP: 'Task deduplication'
}
export const MODEL_FIELDS = new Set([...Object.values(BASE_KEYS), ...Object.keys(ROLES)])
type Model = { id: string; label: string; provider: string }

export default function ModelPolicy({ provider, values, refreshKey, onChange }: {
  provider: string; values: Record<string, string>; refreshKey: string
  onChange: (key: string, value: string) => void
}): JSX.Element {
  const [models, setModels] = useState<Model[]>([])
  const [reason, setReason] = useState('Loading available models…')
  useEffect(() => {
    let active = true
    setModels([])
    setReason('Loading available models…')
    const invalidate = () => { active = false; setModels([]); setReason('Connection changed. Reload settings to select a model.') }
    const unsubscribe = window.zylch.onSidecarStatus(invalidate)
    window.zylch.llm.models(provider).then(result => {
      if (!active) return
      setModels(result.models)
      setReason(result.available ? '' : result.reason)
    }).catch(() => { if (active) setReason('Model catalog unavailable. Check the connection or update the engine.') })
    return () => { active = false; unsubscribe() }
  }, [provider, refreshKey])
  const base = BASE_KEYS[provider]
  const preset = values.LLM_MODEL_PRESET || 'custom'
  const activePresetModel = provider === 'openrouter' ? 'GLM 5.2'
    : preset === 'balanced' ? 'Claude Sonnet 5' : 'Claude Haiku 4.5'
  const overrides = Object.keys(ROLES).filter(key => values[key])
  const control = (key: string, label: string) => {
    const value = values[key] || ''
    return <label key={key} className="block text-sm">{label}
      <select aria-label={label} className="block w-full border rounded p-2" value={value}
        disabled={!models.length} onChange={event => {
          if (key === base) onChange('LLM_MODEL_PRESET', 'custom')
          onChange(key, event.target.value)
        }}>
        <option value="">{key === base ? 'Keep engine default' : 'Inherit default model'}</option>
        {value && !models.some(model => model.id === value) && <option value={value}>{value} — saved; unavailable with this billing choice</option>}
        {models.map(model => <option key={model.id} value={model.id}>{model.label} · {model.provider}</option>)}
      </select>
    </label>
  }
  return <div className="border rounded p-3 space-y-3" aria-label="Model selection">
    <p className="font-medium text-sm">Which model works on your data?</p>
    <p className="text-xs text-brand-grey-80">{provider === 'mrcall'
      ? 'Paid with MrCall credits. Models below come from your billing server; no personal API key is needed.'
      : 'Paid directly using the personal API key saved on your engine.'}</p>
    {reason && <p role="status" className="text-sm">{reason}</p>}
    {preset !== 'custom' && <p role="status" className="text-sm font-medium">
      {preset} preset controls the default: {activePresetModel}. The saved custom model below is inactive.
    </p>}
    {control(base, preset === 'custom' ? 'Default model' : 'Saved custom model — inactive while preset is selected')}
    {overrides.length > 0 && <p className="text-sm">{overrides.length} saved job override(s) remain active and take priority over the default. Review Advanced job models.</p>}
    <details className="space-y-3">
      <summary className="text-sm cursor-pointer">Advanced job models</summary>
      {Object.entries(ROLES).map(([key, label]) => control(key, label))}
    </details>
    <p className="text-xs text-brand-grey-80">Policy: {preset}. Choosing a default switches to custom; existing job overrides stay active. Nothing changes until Save. Model quality on your work must be evaluated separately from price.</p>
  </div>
}
