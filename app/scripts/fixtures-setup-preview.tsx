import React from 'react'
import { createRoot } from 'react-dom/client'
import Setup from '../src/renderer/src/views/Setup'
const scenario = new URLSearchParams(location.search).get('state') || 'fresh'
let failed = scenario === 'failed'
let wrongIdentity = scenario === 'wrong-identity'
const complete = ['ready', 'byok', 'unsigned'].includes(scenario)
const partial = scenario === 'partial'
let remote = complete || partial || ['failed', 'wrong-identity', 'old-engine'].includes(scenario)
let provisionState = scenario === 'preparing' ? 'preparing' : scenario === 'activate' ? 'not_provisioned' : 'active'
const listeners = new Set<(value: any) => void>()
const calls: string[] = []
const emit = (value: any) => listeners.forEach(listener => listener(value))
const fake = {
  settings: {
    getBackendLocation: async () => ({location: remote ? 'remote' : 'local', url: 'wss://desktop.mrcall.ai'}),
    get: async () => { if (failed) throw Error('offline'); return {values: {EMAIL_ADDRESS: 'production@example.test', IMAP_HOST: 'imap.example.test', EMAIL_PASSWORD: '********', ...(scenario === 'byok' ? {ANTHROPIC_API_KEY: '<set>'} : {})}} },
    testBackendConnection: async () => {calls.push('connection.proof'); return {ok: true, signedIn: true, uid: wrongIdentity ? 'another-profile' : 'fixture-profile'}},
    setBackendLocation: async () => {calls.push('connection.select'); remote = true; return {ok: true}}
  },
  workspace: {status: async () => ({available: true, uid: 'fixture-profile', email: 'production@example.test', engineWsUrl: 'wss://desktop.mrcall.ai/ws/fixture-profile', descriptorPath: '/tmp/fixture profile/cs-descriptor.json', command: "cs init --descriptor '/tmp/fixture profile/cs-descriptor.json'"})},
  account: {whoAmI: async () => {calls.push('connection.currentIdentity'); if(failed) throw Error('offline'); return {signed_in: scenario !== 'unsigned', uid: wrongIdentity ? 'another-profile' : 'fixture-profile', email: 'production@example.test'}}},
  memory: {status: async () => ({available: true, has_key: true, reason: '', blob_count: 15})},
  setup: {state: async () => ({has_synced: complete || partial, has_trained: complete || partial, agents_trained: ['memory_message','task_email','emailer'], emails_count: complete || partial ? 12 : 0, emails_analyzed_count: scenario === 'old-engine' ? undefined : complete ? 12 : partial ? 5 : 0, emails_pending_analysis: scenario === 'old-engine' ? undefined : complete ? 0 : partial ? 7 : 0})},
  provision: {
    status: async () => {calls.push('provision.status'); return {ok: true, state: provisionState}},
    start: async () => {calls.push('provision.start'); provisionState = 'preparing'; return {ok: true, uid: 'fixture-profile', state: 'preparing'}}
  },
  sidecar: {restart: async () => {calls.push('connection.restart'); emit({alive: false, code: 'restarting'}); emit({alive: true, ready: true}); return {ok: true}}},
  onSidecarStatus: (listener: (value: any) => void) => {listeners.add(listener); return () => listeners.delete(listener)}
}
Object.assign(window, {zylch: fake, setupFixture: {calls, changeIdentity: () => {wrongIdentity = true}, activate: () => {provisionState = 'active'}}})
document.addEventListener('click', e => {if ((e.target as HTMLElement).textContent === 'Retry checks') failed = false}, true)
createRoot(document.getElementById('root')!).render(<Setup refreshSession={async () => {}} onNavigate={view => {document.getElementById('navigation')!.textContent = `Opened ${view}`}} />)
