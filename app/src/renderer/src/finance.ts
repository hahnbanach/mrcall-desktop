export interface FinanceHistoryBinding {
  mode: 'managed_finance'
  uid: string
  transport: string
  started: boolean
  handle?: string
  revision?: number
  unavailable?: string
}

export interface ChatSendOptions {
  conversationId?: string
  context?: Record<string, unknown>
  historyMode?: 'managed_finance'
  historyHandle?: string
  historyRevision?: number
}

export interface ChatSendResult {
  response?: string
  message?: string
  content?: string
  history_mode?: 'managed_finance'
  history_handle?: string
  history_revision?: number
  [key: string]: unknown
}

export interface QontoStatus {
  status: string
  generation: number
  account_count: number
  source_access: boolean
  credential_stored: boolean
  error?: string
  sync?: QontoCoverage
  last_sync_at?: number | null
}

export function financeTransport(location: { location: 'local' | 'remote'; url?: string }): string {
  return location.location === 'remote' ? `remote:${location.url ?? ''}` : 'local'
}

export interface QontoCredentials {
  credential_source: 'input'
  login?: string
  api_key?: string
}

export interface QontoAccountChoice {
  id: string
  name: string
  currency: string
}

export interface QontoTestResult {
  ok: boolean
  company_name: string | null
  organization: { id: string; name: string; legal_name: string; accounts: QontoAccountChoice[] }
  challenge_id: string
  expires_at: number
  account_ids: string[]
  engine_location: 'local' | 'hosted'
  consent_version: number
}

export interface QontoConnectParams extends QontoCredentials {
  challenge_id: string
  account_ids: string[]
  authority_confirmed: boolean
  consent_version: number
}

export interface QontoCoverage {
  status: string
  completed_windows: number
  remaining_windows: number
  remaining_backfill_windows: number
  history_planned: boolean
  unresolved_pending_windows: number
  error?: string | null
  retry_at?: number | null
  coverage_kind: 'traversed_windows'
  accounts: Array<{
    account_id: string
    emitted_watermark: string | null
    updated_watermark: string | null
    initial_from: string | null
    initial_to: string | null
  }>
}

export interface QontoSyncResult extends QontoCoverage {
  ok: boolean
  generation: number
  requests: number
}

export interface QontoConnectResult {
  ok: boolean
  status: string
  generation: number
  account_count?: number
  initial_sync: QontoSyncResult | { status: string; error: string }
}

export interface QontoRemovalResult {
  ok: boolean
  status: string
  generation: number
  deleted?: boolean
  removed_rows?: number
  published_facts_retained?: boolean
}

export interface QontoPreparationResult {
  status?: string
  success?: boolean
  summary?: string
  attempted?: number
  completed?: number
  failed?: number
  limit?: number
  paused?: boolean
  stop_reason?: string
  errors?: Array<{ stage?: string; detail: string }>
}

export interface QontoPublicationPreview {
  preview_id: string
  fact_text: string
  disclosure: string
  generation?: number
  expires_at?: number
}

export interface QontoPublicationResult {
  status: 'committed' | 'skipped' | 'review_needed' | 'refused'
  reason?: string
}

export interface QontoTransactionResult {
  organization_id: string
  generation: number
  retrieved_at: number
  date_basis: 'source_timestamps'
  partial: boolean
  stale: boolean
  coverage: QontoCoverage
  transaction: {
    source_id: string
    source_revision: string
    account_id: string
    currency: string
    status: string
    side: string
    amount: { minor: number | string; scale: number; decimal: string }
    retrieved_at: number
    emitted_at?: string | null
    settled_at?: string | null
    updated_at?: string | null
    untrusted_source_text: { label?: string; reference?: string; note?: string; counterparty_name?: string }
    source_text_policy: string
  }
}

export interface QontoAPI {
  test: (credentials: QontoCredentials) => Promise<QontoTestResult>
  connect: (params: QontoConnectParams) => Promise<QontoConnectResult>
  status: () => Promise<QontoStatus>
  sync: () => Promise<QontoSyncResult>
  disconnect: () => Promise<QontoRemovalResult>
  deleteImportedData: (confirmed: boolean) => Promise<QontoRemovalResult>
  prepare: (resume?: boolean) => Promise<QontoPreparationResult>
  publicationPreview: () => Promise<QontoPublicationPreview>
  publish: (previewId: string, confirmed: boolean, resume?: boolean) => Promise<QontoPublicationResult>
  transaction: (sourceId: string) => Promise<QontoTransactionResult>
}
