/**
 * Accepting a memory change that is not the one that was asked for.
 *
 * Ordinary approval cards grant a tool: "may the assistant run `run_python`",
 * and "Allow for session" is a reasonable answer to that. This card is a
 * different question. The engine's mnemonic role has already decided, and what
 * it decided differs from the tool call — a different memory, a different
 * action, a different scope, or an effect that absorbs another memory. So the
 * question is "is THIS change right", and there is no standing answer to it.
 *
 * Which is why accepting means echoing two fields the engine put on the card
 * back to it: the single-use nonce and the digest of the proposal shown here. A
 * client that only says "yes" — a remembered session grant, a headless
 * `cs --allow`, a future surface that forgets — is refused by the engine
 * without anyone having to maintain a list of trusted clients. This module is
 * that echo, kept out of the component so the wire contract can be driven by a
 * test that does not need a browser.
 *
 * Editing is deliberately not offered. Revising the text means the accepted
 * change is no longer the decided one, and the engine treats an edited card as
 * a refusal; the revision has to be submitted as its own instruction.
 */

/** The engine's approval name for a changed final memory mutation. */
export const CONFIRM_MEMORY_WRITE = 'confirm_memory_write'

export type MemoryWriteTarget = {
  blob_id: string
  expected_version: string
  role: string
}

/** What the card renders, read out of the approval input the engine sent. */
export type MemoryChange = {
  action: string
  entityType: string
  scope: string
  content: string
  reason: string
  /** Why this needed confirming at all, in the engine's own sentences. */
  why: string[]
  writeSet: MemoryWriteTarget[]
  declaredEffects: string[]
  /** What the tool call had asked for, so the difference is visible. */
  requestedAction: string
  requestedBlobId: string
  /** The words the change was read from. */
  observation: string
  source: string
}

/** The two fields an acceptance must carry back. */
export type MemoryAcceptance = {
  acceptance_nonce: string
  proposal_digest: string
}

export function isMemoryChange(toolName: string): boolean {
  return toolName === CONFIRM_MEMORY_WRITE
}

/**
 * Never, for this card. A session grant is a standing yes, and the engine
 * refuses one here — so offering the button would collect a click that does
 * nothing, which is worse than not offering it.
 */
export function offersSessionGrant(toolName: string): boolean {
  return !isMemoryChange(toolName)
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []
}

export function describeMemoryChange(input: Record<string, unknown>): MemoryChange {
  const rawSet = Array.isArray(input.write_set) ? input.write_set : []
  return {
    action: str(input.action),
    entityType: str(input.entity_type),
    scope: str(input.scope),
    content: str(input.content),
    reason: str(input.reason),
    why: strings(input.why),
    writeSet: rawSet.flatMap((entry) => {
      if (typeof entry !== 'object' || entry === null) return []
      const row = entry as Record<string, unknown>
      return [
        {
          blob_id: str(row.blob_id),
          expected_version: str(row.expected_version),
          role: str(row.role) || 'target'
        }
      ]
    }),
    declaredEffects: strings(input.declared_effects),
    requestedAction: str(input.requested_action),
    requestedBlobId: str(input.requested_blob_id),
    observation: str(input.observation),
    source: str(input.source)
  }
}

/**
 * The acceptance payload for this card, or null when the card did not carry
 * what an acceptance needs.
 *
 * Null is not a failure to handle by guessing: a card with no nonce is a card
 * this client cannot honestly accept, and sending an empty echo would ask the
 * engine to treat a missing field as consent.
 */
export function acceptanceFor(input: Record<string, unknown>): MemoryAcceptance | null {
  const nonce = str(input.acceptance_nonce)
  const digest = str(input.proposal_digest)
  if (!nonce || !digest) return null
  return { acceptance_nonce: nonce, proposal_digest: digest }
}

/**
 * What a "decline" must send, per surface.
 *
 * A solve's ordinary approval card has only two answers: run the tool, or abort
 * the solve — declining a send has no other meaning. A memory change does: the
 * engine answers a decline with a reason the model reads, and the turn carries
 * on. So declining one is `tasks.solve.approve(approved:false)`, not
 * `tasks.solve.cancel` — cancelling throws that answer away and kills work the
 * user did not ask to stop.
 *
 * Lives here rather than inline in the component so the rule is testable without
 * a browser, beside the acceptance it belongs with.
 */
export function declineActionFor(mode: 'chat' | 'solve', toolName: string): 'decline' | 'cancel' {
  if (mode !== 'solve') return 'decline'
  return isMemoryChange(toolName) ? 'decline' : 'cancel'
}

/** One line naming what will change, for a collapsed or notification view. */
export function summarize(change: MemoryChange): string {
  const target = change.writeSet.find((t) => t.role === 'target' || t.role === 'keeper')
  const where = target ? ` ${target.blob_id}` : ''
  const family = change.entityType ? ` (${change.entityType})` : ''
  return `${change.action}${where}${family}`
}
