export interface StripeStatus {
  status: string
  generation: number
  account?: { id: string; name: string | null }
  mode?: 'test' | 'live'
  capabilities: string[]
  error?: string
}

export interface StripeTestResult {
  account: { id: string; name: string | null }
  mode: 'test' | 'live'
  capabilities: string[]
  challenge_id: string
  expires_at: number
  company_name: string | null
}

export interface StripeConnectParams {
  api_key: string
  challenge_id: string
  authority_confirmed: true
}

export interface StripeAPI {
  status: () => Promise<StripeStatus>
  test: (params: { api_key: string }) => Promise<StripeTestResult>
  connect: (params: StripeConnectParams) => Promise<StripeStatus>
  disconnect: () => Promise<StripeStatus>
}
