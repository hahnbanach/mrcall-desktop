import type { Approval } from '../store/conversations'
import { acceptanceFor, describeMemoryChange } from '../lib/memoryApproval'

/**
 * Confirming a memory change the assistant did not literally ask for.
 *
 * Read-only on purpose. The engine's mnemonic role decided this change; editing
 * the prose here would mean accepting something other than what was decided,
 * and the engine treats an edited card as a refusal. A revision is a new
 * instruction, typed in the composer, not a correction smuggled into a
 * confirmation.
 *
 * No "Allow for session" either: a standing yes cannot be an answer to "is this
 * particular change right", and the engine refuses one. The rule lives in
 * `lib/memoryApproval.ts` so this component and the engine-facing test agree.
 */
export default function MemoryChangeCard({
  approval,
  onAccept,
  onDecline
}: {
  approval: Approval
  onAccept: (editedInput?: Record<string, unknown>) => void
  onDecline: () => void
}): React.JSX.Element {
  const change = describeMemoryChange(approval.input)
  const acceptance = acceptanceFor(approval.input)

  return (
    <div className="border border-brand-orange bg-brand-orange/10 rounded-lg p-4 mr-12">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs px-2 py-0.5 bg-brand-orange/30 text-brand-orange rounded font-mono">
          {change.action || 'memory'}
        </span>
        <span className="text-sm text-brand-orange font-medium">
          Conferma la modifica alla memoria
        </span>
      </div>

      {change.why.length > 0 && (
        <div className="text-sm text-brand-black mb-3">
          <div className="font-medium mb-1">Non è quello che era stato chiesto:</div>
          <ul className="list-disc list-inside space-y-0.5">
            {change.why.map((sentence) => (
              <li key={sentence}>{sentence}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="bg-white border border-brand-orange/30 rounded p-3 mb-3 space-y-2">
        <Field label="Azione">
          {change.action}
          {change.requestedAction && change.requestedAction !== change.action
            ? ` (richiesta: ${change.requestedAction})`
            : ''}
        </Field>
        {change.entityType && (
          <Field label="Tipo">
            {change.entityType}
            {change.scope ? ` · ${change.scope}` : ''}
          </Field>
        )}
        {change.writeSet.map((target) => (
          <Field key={target.blob_id} label={`Scrive (${target.role})`}>
            <span className="font-mono text-xs">{target.blob_id}</span>
            <span className="text-brand-grey-80"> @ {target.expected_version}</span>
            {change.requestedBlobId && change.requestedBlobId !== target.blob_id && (
              <span className="text-brand-orange">
                {' '}
                — non {change.requestedBlobId.slice(0, 8)}…, che era stato indicato
              </span>
            )}
          </Field>
        ))}
        {change.declaredEffects.length > 0 && (
          <Field label="Effetti">{change.declaredEffects.join(', ')}</Field>
        )}
        {change.reason && <Field label="Motivo">{change.reason}</Field>}
        {change.observation && (
          <Field label="Letto da">
            {change.observation}
            {change.source ? ` (${change.source})` : ''}
          </Field>
        )}
        {/* The complete text that will be stored — never a preview of it. */}
        <Field label="Testo completo">{change.content}</Field>
      </div>

      {acceptance === null ? (
        <div className="text-sm text-brand-orange mb-3">
          Questa scheda non porta i dati necessari per confermare la modifica.
          Niente è stato scritto; rifiuta e riprova.
        </div>
      ) : null}

      <div className="flex gap-2 flex-wrap">
        <button
          onClick={() => onAccept(acceptance ?? undefined)}
          disabled={acceptance === null}
          className="px-3 py-1.5 text-sm bg-brand-blue text-white rounded hover:bg-brand-grey-80 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Conferma la modifica
        </button>
        <button
          onClick={onDecline}
          className="px-3 py-1.5 text-sm bg-brand-mid-grey text-brand-black rounded hover:bg-brand-mid-grey"
        >
          Annulla
        </button>
      </div>
    </div>
  )
}

function Field({
  label,
  children
}: {
  label: string
  children: React.ReactNode
}): React.JSX.Element {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wide text-brand-grey-80 mb-0.5">
        {label}
      </div>
      <div className="text-sm text-brand-black whitespace-pre-wrap break-words">{children}</div>
    </div>
  )
}
