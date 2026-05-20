/**
 * MrCall tab — read-only business lookup (Livello A: "simplified dashboard").
 *
 * Authenticated via the active Firebase session (same JWT the dashboard
 * uses). No OAuth PKCE secondary flow. Two engine RPCs:
 *   - mrcall.list_my_businesses  → all businesses visible to the caller
 *   - mrcall.search_businesses   → filtered (email / name / phone / VAT)
 * StarChat applies role-based owner scoping: an admin sees businesses
 * cross-owner, an owner only their own — the desktop adds no permission
 * logic of its own.
 *
 * Read-only on purpose: no subscription edits, no writes, no other
 * owners' conversations (StarChat blocks those anyway). Phone-call
 * memory ingestion is a separate future workstream (Livello B).
 */
import { useCallback, useEffect, useState } from 'react'
import { errorMessage } from '../lib/errors'

type Business = {
  businessId?: string | null
  name?: string | null
  surname?: string | null
  companyName?: string | null
  nickname?: string | null
  owner?: string | null
  businessPhoneNumber?: string | null
  serviceNumber?: string | null
  emailAddress?: string | null
  address?: string | null
  vatId?: string | null
  sdi?: string | null
  countryAlpha2?: string | null
  languageCountry?: string | null
  subscriptionStatus?: string | null
  trialExpirationDatetime?: string | null
  stripeCustomerId?: string | null
  creationDateTime?: string | null
  lastUpdateDateTime?: string | null
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; needsSignIn: boolean }
  | { kind: 'ready'; businesses: Business[]; role: string }

// Field the search box queries against. Maps 1:1 onto the StarChat
// CrmBusinessSearch filter; the backend matches that specific column,
// there is no free-text-everywhere search.
const SEARCH_FIELDS = [
  { key: 'emailAddress', label: 'Email' },
  { key: 'companyName', label: 'Nome azienda' },
  { key: 'name', label: 'Nome' },
  { key: 'businessPhoneNumber', label: 'Telefono' },
  { key: 'vatId', label: 'P.IVA' },
  { key: 'businessId', label: 'Business ID' }
] as const

type SearchField = (typeof SEARCH_FIELDS)[number]['key']

// Subscription-status values for the dropdown filter (StarChat
// CrmBusiness.subscriptionStatus). Empty = no status filter.
const STATUS_OPTIONS = ['FREE', 'TEST', 'ACTIVE', 'TRIALLING', 'EXTERNAL']

function displayName(b: Business): string {
  return (
    b.companyName?.trim() ||
    [b.name, b.surname].filter(Boolean).join(' ').trim() ||
    b.nickname?.trim() ||
    b.businessId ||
    '(unnamed business)'
  )
}

function Field({ label, value }: { label: string; value?: string | null }): JSX.Element | null {
  if (!value) return null
  return (
    <div className="flex gap-2 text-xs">
      <span className="text-brand-grey-80 shrink-0 w-32">{label}</span>
      <span className="font-mono break-all">{value}</span>
    </div>
  )
}

export default function MrcallView(): JSX.Element {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [field, setField] = useState<SearchField>('emailAddress')
  const [value, setValue] = useState('')
  const [status, setStatus] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // No filters → list all (role-scoped); any filter → filtered search.
  const run = useCallback(async (filters: Record<string, string>): Promise<void> => {
    setState({ kind: 'loading' })
    setExpandedId(null)
    try {
      const hasFilters = Object.keys(filters).length > 0
      const r = (await (hasFilters
        ? window.zylch.mrcall.searchBusinesses(filters)
        : window.zylch.mrcall.listMyBusinesses({}))) as {
        businesses: Business[]
        role: string
      }
      const businesses = Array.isArray(r?.businesses) ? r.businesses : []
      setState({ kind: 'ready', businesses, role: r?.role ?? '' })
    } catch (e) {
      const msg = errorMessage(e)
      const needsSignIn = /not signed in|noactivesession|-32010|sign in again/i.test(msg)
      setState({ kind: 'error', message: msg, needsSignIn })
    }
  }, [])

  // Assemble the CrmBusinessSearch filter from the field/value box plus
  // the status dropdown. Both AND together server-side.
  const buildFilters = (f: SearchField, v: string, s: string): Record<string, string> => {
    const filters: Record<string, string> = {}
    const trimmed = v.trim()
    if (trimmed) filters[f] = trimmed
    if (s) filters.subscriptionStatus = s
    return filters
  }

  useEffect(() => {
    void run({})
  }, [run])

  const onSubmit = (e: React.FormEvent): void => {
    e.preventDefault()
    void run(buildFilters(field, value, status))
  }

  const onClear = (): void => {
    setValue('')
    setStatus('')
    void run({})
  }

  const onStatusChange = (s: string): void => {
    setStatus(s)
    void run(buildFilters(field, value, s))
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <header className="mb-4">
        <h1 className="text-lg font-semibold">Assistenti MrCall</h1>
        <p className="text-xs text-brand-grey-80 mt-1">
          Cerca un business per dato del cliente. I permessi li applica MrCall: come
          owner vedi i tuoi, come admin tutti.
        </p>
      </header>

      <form onSubmit={onSubmit} className="flex gap-2 mb-4">
        <select
          value={field}
          onChange={(e) => setField(e.target.value as SearchField)}
          className="text-sm border border-brand-mid-grey rounded px-2 py-1.5 bg-white"
        >
          {SEARCH_FIELDS.map((f) => (
            <option key={f.key} value={f.key}>
              {f.label}
            </option>
          ))}
        </select>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Cerca… (vuoto = tutti)"
          className="flex-1 text-sm border border-brand-mid-grey rounded px-3 py-1.5"
        />
        <select
          value={status}
          onChange={(e) => onStatusChange(e.target.value)}
          className="text-sm border border-brand-mid-grey rounded px-2 py-1.5 bg-white"
          title="Filtra per stato abbonamento"
        >
          <option value="">Status: tutti</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <button
          type="submit"
          className="text-sm px-4 py-1.5 rounded bg-brand-blue text-white hover:opacity-90"
        >
          Cerca
        </button>
        {(value || status) && (
          <button
            type="button"
            onClick={onClear}
            className="text-sm px-3 py-1.5 rounded border border-brand-mid-grey bg-white hover:bg-brand-light-grey"
          >
            Pulisci
          </button>
        )}
      </form>

      {state.kind === 'loading' && (
        <div className="text-sm text-brand-grey-80">Caricamento…</div>
      )}

      {state.kind === 'error' && (
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-900">
          <div className="font-medium mb-1">
            {state.needsSignIn
              ? 'Sessione Firebase scaduta o assente'
              : 'Errore caricando i business MrCall'}
          </div>
          <div className="text-xs font-mono whitespace-pre-wrap break-all opacity-80">
            {state.message}
          </div>
          <button
            className="mt-3 text-xs px-3 py-1 rounded bg-white border border-red-300 hover:bg-red-100"
            onClick={() => void run(buildFilters(field, value, status))}
          >
            Riprova
          </button>
        </div>
      )}

      {state.kind === 'ready' && (
        <>
          <p className="text-xs text-brand-grey-80 mb-2">
            {state.businesses.length} business
            {state.role ? ` · ruolo: ${state.role}` : ''}
          </p>
          {state.businesses.length === 0 ? (
            <div className="rounded border border-brand-mid-grey bg-white p-6 text-sm text-brand-grey-80">
              Nessun business trovato.
            </div>
          ) : (
            <ul className="grid gap-2">
              {state.businesses.map((b, i) => {
                const id = b.businessId ?? `idx-${i}`
                const expanded = expandedId === id
                return (
                  <li key={id} className="rounded border border-brand-mid-grey bg-white">
                    <button
                      onClick={() => setExpandedId(expanded ? null : id)}
                      className="w-full text-left p-4 flex items-baseline justify-between gap-3 hover:bg-brand-light-grey rounded"
                    >
                      <span className="font-medium text-sm truncate">{displayName(b)}</span>
                      <span className="flex items-center gap-2 shrink-0">
                        {b.subscriptionStatus && (
                          <span className="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded bg-brand-light-grey text-brand-grey-80">
                            {b.subscriptionStatus}
                          </span>
                        )}
                        <span className="text-brand-grey-80 text-xs">{expanded ? '−' : '+'}</span>
                      </span>
                    </button>
                    {expanded && (
                      <div className="px-4 pb-4 pt-1 flex flex-col gap-1 border-t border-brand-mid-grey/50">
                        <Field label="Email" value={b.emailAddress} />
                        <Field label="Telefono" value={b.businessPhoneNumber} />
                        <Field label="Numero servizio" value={b.serviceNumber} />
                        <Field label="P.IVA" value={b.vatId} />
                        <Field label="SDI" value={b.sdi} />
                        <Field label="Indirizzo" value={b.address} />
                        <Field
                          label="Paese / lingua"
                          value={[b.countryAlpha2, b.languageCountry].filter(Boolean).join(' · ') || null}
                        />
                        <Field label="Abbonamento" value={b.subscriptionStatus} />
                        <Field label="Trial fino a" value={b.trialExpirationDatetime} />
                        <Field label="Stripe customer" value={b.stripeCustomerId} />
                        <Field label="Creato" value={b.creationDateTime} />
                        <Field label="Aggiornato" value={b.lastUpdateDateTime} />
                        <Field label="Owner (uid)" value={b.owner} />
                        <Field label="Business ID" value={b.businessId} />
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </>
      )}
    </div>
  )
}
