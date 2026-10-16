import React from 'react'
import { createRoot } from 'react-dom/client'
import '../src/preload/index'
import StripeCard from '../src/renderer/src/components/StripeCard'
import { createQontoFixture } from './fixtures-qonto-rpc'
const base = createQontoFixture()
let connected = false, generation = 0, old = false, delayed = false, ttl = 300000
let release: (() => void) | undefined
const account = { id: 'acct_fixture', name: 'Fixture Stripe company' }
const calls: unknown[] = []
const listeners = new Set<() => void>(), invalidation = new Set<() => void>()
const status = () => ({ status: connected ? 'connected' : 'disconnected', generation, ...(connected ? { account, mode: 'test' } : {}), capabilities: ['customers', 'payments', 'invoices', 'subscriptions'] })
Object.assign(window, {
  fixtureAuth: { uid: 'fixture-uid', email: 'fixture@example.test' }, fixtureAuthListeners: listeners, fixtureInvalidation: invalidation,
  fixture: {
    calls: () => calls, defer: () => { delayed = true }, release: () => release?.(), ttl: (value: number) => { ttl = value },
    oldEngine: () => { old = true }, generation: () => { generation++ }, changeHost: base.changeHost,
    invalidate: () => { for (const f of invalidation) f() },
    relogin: () => { for (const f of invalidation) f(); for (const f of listeners) f() },
    companyChange: () => { window.dispatchEvent(new Event('mrcall:company-changing')); void base.invoke('rpc:call', 'memory.join').then(() => window.dispatchEvent(new Event('mrcall:company-changed'))) }
  },
  fixtureRpc: { invoke: async (channel: string, method?: string, params: Record<string, unknown> = {}) => {
    if (!method?.startsWith('stripe.')) return base.invoke(channel, method, params)
    calls.push({ method, params })
    if (old) throw new Error('Method not found')
    if (method === 'stripe.status') return status()
    if (method === 'stripe.disconnect') { connected = false; generation++; return status() }
    if (method === 'stripe.connect') {
      if (!params.api_key || params.authority_confirmed !== true || params.challenge_id !== 'fixture-challenge') throw new Error('challenge_invalid')
      connected = true; generation++; return status()
    }
    if (method === 'stripe.test') {
      const result = { account, mode: 'test', capabilities: status().capabilities, challenge_id: 'fixture-challenge', expires_at: (Date.now() + ttl) / 1000, company_name: 'Fixture MrCall company' }
      if (delayed) { delayed = false; return new Promise(resolve => { release = () => resolve(result) }) }
      return result
    }
    throw new Error('Unexpected Stripe method')
  } }
})
for (const [name, callback] of (window as any).fixtureIpcRegistrations || []) base.on(name, callback)
createRoot(document.getElementById('root')!).render(<StripeCard />)
