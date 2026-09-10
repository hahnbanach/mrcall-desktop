export interface PreparationEvidence {
  emails_count: number
  has_trained: boolean
  agents_trained?: string[]
  emails_analyzed_count?: number | null
  emails_pending_analysis?: number | null
}
export function preparationSummary(state: PreparationEvidence | null): { complete: boolean; text: string } {
  if (!state) return { complete: false, text: 'Preparation has not been checked.' }
  if (state.emails_analyzed_count == null || state.emails_pending_analysis == null) {
    return { complete: false, text: 'This engine does not yet provide mailbox analysis evidence. Update the engine to verify preparation.' }
  }
  if (![state.emails_count, state.emails_analyzed_count, state.emails_pending_analysis].every(value => Number.isInteger(value) && value >= 0) || state.emails_analyzed_count + state.emails_pending_analysis !== state.emails_count) {
    return { complete: false, text: 'Mailbox preparation counts could not be verified. Refresh the checks.' }
  }
  if (!state.emails_count) return { complete: false, text: 'No email downloaded yet. Connect a mailbox and prepare its data.' }
  const trained = ['memory_message', 'task_email', 'emailer'].every(agent => state.agents_trained?.includes(agent))
  const complete = trained && state.emails_analyzed_count > 0 && state.emails_pending_analysis === 0
  return { complete, text: `${state.emails_count} emails downloaded · ${state.emails_analyzed_count} processed for memory · ${state.emails_pending_analysis} awaiting analysis. ${trained ? 'Assistant prompts available.' : 'Assistant training still needed.'}` }
}

/** Connection recovery must stay reachable even before the first engine-ready event. */
export function needsEngineSplash(view: string, engineReady: boolean, bypassed: boolean): boolean {
  return !engineReady && !bypassed && !['setup', 'settings', 'logs'].includes(view)
}
