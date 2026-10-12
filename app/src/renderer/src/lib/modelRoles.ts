// The job each engine model role does, named once for the whole renderer: the
// Settings job-model fields (ModelPolicy) and the Saved models lines
// (DailyBudget) read the same name, so a pause line that says "choose a model
// for it in Settings" points at a field with the same name.
// Keys are the engine's `MODEL_<ROLE>` keys (`usage.today` `model_policy.roles`,
// one per role in engine/zylch/llm/roles/requirements.json); the order is the
// order Saved models lists them in.
export const ROLE_LABELS: Readonly<Record<string, string>> = {
  MODEL_CHAT: 'Conversation',
  MODEL_TASK_SOLVE: 'Task solving',
  MODEL_WEB_SEARCH: 'Web search',
  MODEL_COMPACTION: 'Conversation summaries',
  MODEL_NARRATION: 'Progress narration',
  MODEL_INTENT: 'Request classification',
  MODEL_SYNC_ANALYSIS: 'Mail and calendar analysis',
  MODEL_REPLY_NEED: 'Reply-needed check',
  MODEL_MEMORY_EXTRACT: 'Memory extraction',
  MODEL_MNEMONIC: 'Memory decisions',
  MODEL_MEMORY_MERGE: 'Memory comparison',
  MODEL_TASK_DETECTION: 'Task detection',
  MODEL_REANALYZE: 'Task review',
  MODEL_DEDUP: 'Task deduplication',
  MODEL_TRAIN: 'Assistant training',
  MODEL_CORRECTION_LEARNING: 'Learning from draft edits'
}

// The roles Settings offers a model field for (engine roles/table.py SETTINGS_ROLES).
export const SETTINGS_ROLES = [
  'MODEL_MEMORY_EXTRACT', 'MODEL_MEMORY_MERGE', 'MODEL_TASK_DETECTION', 'MODEL_REANALYZE', 'MODEL_DEDUP'
] as const

// A role a newer engine adds reads as its key without `MODEL_`, title-cased:
// MODEL_FUTURE_ROLE -> "Future Role".
export function roleLabel(key: string): string {
  if (Object.prototype.hasOwnProperty.call(ROLE_LABELS, key)) return ROLE_LABELS[key]
  const words = String(key).replace(/^MODEL_/, '').split(/[_\s]+/).filter(Boolean)
  return words.map(word => word[0].toUpperCase() + word.slice(1).toLowerCase()).join(' ') || String(key)
}

// The keys to show, each once: the known roles in ROLE_LABELS order, then any
// unknown ones in the order the engine sent them.
export function orderedRoles(keys: readonly string[]): string[] {
  const unique = [...new Set(keys)]
  const known = Object.keys(ROLE_LABELS).filter(key => unique.includes(key))
  return [...known, ...unique.filter(key => !known.includes(key))]
}
