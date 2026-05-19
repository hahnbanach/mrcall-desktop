/**
 * MrCall tab — read-only list of the user's MrCall assistants (businesses).
 *
 * Authenticated via the active Firebase session (same JWT the dashboard
 * uses). No OAuth PKCE secondary flow; the engine RPC
 * `mrcall.list_my_businesses` hits StarChat
 * `POST /mrcall/v1/{realm}/crm/business/search` directly.
 *
 * Phase 0bis scope: just show the list. Conversations + transcript view
 * land in Phase 3 of `docs/execution-plans/mrcall-pipeline-parity.md`.
 */
import { useCallback, useEffect, useState } from 'react'
import { errorMessage } from '../lib/errors'

type Business = {
  businessId?: string | null
  name?: string | null
  surname?: string | null
  companyName?: string | null
  nickname?: string | null
  businessPhoneNumber?: string | null
  emailAddress?: string | null
  countryAlpha2?: string | null
  languageCountry?: string | null
  subscriptionStatus?: string | null
  creationDateTime?: string | null
  lastUpdateDateTime?: string | null
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; needsSignIn: boolean }
  | { kind: 'ready'; businesses: Business[]; role: string }

function displayName(b: Business): string {
  return (
    b.companyName?.trim() ||
    [b.name, b.surname].filter(Boolean).join(' ').trim() ||
    b.nickname?.trim() ||
    b.businessId ||
    '(unnamed business)'
  )
}

export default function MrcallView(): JSX.Element {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(async (): Promise<void> => {
    setState({ kind: 'loading' })
    try {
      const r = (await window.zylch.mrcall.listMyBusinesses({})) as {
        businesses: Business[]
        role: string
      }
      const businesses = Array.isArray(r?.businesses) ? r.businesses : []
      setState({ kind: 'ready', businesses, role: r?.role ?? '' })
    } catch (e) {
      const msg = errorMessage(e)
      // -32010 = NoActiveSession on engine side; surfaces as the literal
      // string in the JSON-RPC error message. Map to a re-signin hint
      // instead of dumping the raw error.
      const needsSignIn = /not signed in|noactivesession|-32010|sign in again/i.test(msg)
      setState({ kind: 'error', message: msg, needsSignIn })
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  if (state.kind === 'loading') {
    return (
      <div className="p-6 text-sm text-brand-grey-80">
        Caricamento assistenti MrCall…
      </div>
    )
  }

  if (state.kind === 'error') {
    return (
      <div className="p-6">
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-900">
          <div className="font-medium mb-1">
            {state.needsSignIn
              ? 'Sessione Firebase scaduta o assente'
              : 'Errore caricando gli assistenti MrCall'}
          </div>
          <div className="text-xs font-mono whitespace-pre-wrap break-all opacity-80">
            {state.message}
          </div>
          <button
            className="mt-3 text-xs px-3 py-1 rounded bg-white border border-red-300 hover:bg-red-100"
            onClick={() => void load()}
          >
            Riprova
          </button>
        </div>
      </div>
    )
  }

  const { businesses, role } = state

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <header className="mb-4 flex items-baseline justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold">I tuoi assistenti MrCall</h1>
          <p className="text-xs text-brand-grey-80 mt-1">
            {businesses.length} business associati a questo account Firebase
            {role ? ` · ruolo: ${role}` : ''}
          </p>
        </div>
        <button
          className="text-xs px-3 py-1 rounded border border-brand-mid-grey bg-white hover:bg-brand-light-grey"
          onClick={() => void load()}
        >
          Ricarica
        </button>
      </header>

      {businesses.length === 0 ? (
        <div className="rounded border border-brand-mid-grey bg-white p-6 text-sm text-brand-grey-80">
          Nessun business MrCall trovato su questo account.
          <br />
          <span className="text-xs">
            Se ne hai uno sulla dashboard ma non lo vedi qui, verifica di esserti
            loggato con lo stesso account Firebase.
          </span>
        </div>
      ) : (
        <ul className="grid gap-3">
          {businesses.map((b, i) => {
            const id = b.businessId ?? `idx-${i}`
            return (
              <li
                key={id}
                className="rounded border border-brand-mid-grey bg-white p-4 flex flex-col gap-1"
              >
                <div className="flex items-baseline justify-between gap-3">
                  <h2 className="font-medium text-sm truncate">{displayName(b)}</h2>
                  {b.subscriptionStatus && (
                    <span className="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded bg-brand-light-grey text-brand-grey-80 shrink-0">
                      {b.subscriptionStatus}
                    </span>
                  )}
                </div>
                {b.businessPhoneNumber && (
                  <div className="text-xs text-brand-grey-80">
                    Tel: <span className="font-mono">{b.businessPhoneNumber}</span>
                  </div>
                )}
                {b.emailAddress && (
                  <div className="text-xs text-brand-grey-80">
                    Email: <span className="font-mono">{b.emailAddress}</span>
                  </div>
                )}
                {(b.countryAlpha2 || b.languageCountry) && (
                  <div className="text-xs text-brand-grey-80">
                    {[b.countryAlpha2, b.languageCountry].filter(Boolean).join(' · ')}
                  </div>
                )}
                {b.businessId && (
                  <div
                    className="text-[10px] font-mono text-brand-grey-80 truncate"
                    title={b.businessId}
                  >
                    id: {b.businessId}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
