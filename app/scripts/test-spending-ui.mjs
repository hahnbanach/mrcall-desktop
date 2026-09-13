// Actual spending components with fake RPCs; no engine, browser, or paid calls.
// Test dependencies: see test-preparation.mjs. Run from the repository root.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import Module, { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const appRequire = createRequire(path.join(here, '../package.json'))
const testRequire = createRequire(path.join(process.env.MRCALL_UI_TEST_DEPS ?? '/tmp/mrcall-preparation-ui-tests', 'package.json'))
const ts = appRequire('typescript')
const React = testRequire('react')
const { create, act } = testRequire('react-test-renderer')
const auth = { currentUser: { uid: 'account-A' } }
const empty = () => null
function load(relative, extra = '') {
  const file = path.join(here, '../src/renderer/src', relative)
  const mod = new Module(file)
  mod.require = name => {
    if (!name.startsWith('.')) return testRequire(name)
    if (name.endsWith('/config')) return { auth }
    if (name.endsWith('/authUtils')) return { ensureEngineSession: async () => true }
    if (name.endsWith('/errors')) return { errorMessage: String }
    return { default: empty }
  }
  mod._compile(ts.transpileModule(fs.readFileSync(file, 'utf8') + extra, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 }
  }).outputText, file)
  return mod.exports
}
const Card = load('views/Settings.tsx', '\nexport { LLMProviderCard };').LLMProviderCard
const Budget = load('components/DailyBudget.tsx').default
const sidecar = new Set(), focus = new Set()
let pending = [], opened = [], receiptCursors = []
const policy = { provider: 'mrcall', preset: 'economy', model: 'saved-model', roles: { MODEL_MEMORY_EXTRACT: 'saved-reader' }, quality_status: 'unmeasured' }
const snapshot = { spent_usd: 1, reserved_usd: 2, remaining_usd: 2, budget_usd: 5,
  billing_supported: true, paused: false, pricing_fault: false, model_policy: policy }
global.window = {
  addEventListener: (_name, fn) => focus.add(fn),
  removeEventListener: (_name, fn) => focus.delete(fn),
  zylch: {
    onSidecarStatus: fn => { sidecar.add(fn); return () => sidecar.delete(fn) },
    account: { balance: () => new Promise(resolve => pending.push(resolve)) },
    shell: { openExternal: async url => { opened.push(url); return { ok: true } } },
    usage: {
      today: async () => snapshot,
      reconcile: async cursor => {
        receiptCursors.push(cursor)
        return { recovered: 1, unresolved: 1, next_cursor: cursor ? null : 'next-page', message: 'Complete' }
      }
    }
  }
}
let view
const text = () => JSON.stringify(view.toJSON())
const button = label => view.root.findAllByType('button').find(node => node.children.join('') === label)
const render = async element => { await act(async () => { view = create(element) }) }
const unmount = () => act(() => view.unmount())
const reconnect = async () => { await act(async () => { for (const callback of sidecar) callback({ alive: true, ready: true }) }) }
const props = { selectedProvider: 'openrouter', savedProvider: 'mrcall', pendingBillingChange: true, onSelectCredits() {}, refreshKey: 'A' }

await render(React.createElement(Card, props))
assert.match(text(), /Unsaved billing change/)
assert.match(text(), /Until then, the engine uses/)
await act(async () => button('Top up credits').props.onClick())
assert.deepEqual(opened, ['https://dashboard.mrcall.ai/plan'])
// A pending selection does not redirect topping up or silently switch billing.
assert.equal(pending.length, 1)
auth.currentUser = { uid: 'account-B' }
await reconnect()
await act(async () => pending[0]({ balance_credits: 111111, balance_usd: 1222 }))
assert.doesNotMatch(text(), /111,111/, 'Account A reply must not appear after switching to B')
await act(async () => pending[1]({ balance_credits: 222222, balance_usd: 2444 }))
assert.match(text(), /222,222/)
await act(async () => { for (const callback of sidecar) callback({ alive: false, ready: false }) })
assert.doesNotMatch(text(), /222,222/, 'Disconnect immediately clears the confirmed old balance')
unmount()
assert.equal(sidecar.size, 0)

await render(React.createElement(Budget))
assert.match(text(), /saved-reader/)
assert.match(text(), /unmeasured/)
assert.match(text(), /reserved/)
await act(async () => button('Check MrCall receipts').props.onClick())
await act(async () => button('Check next receipts').props.onClick())
assert.deepEqual(receiptCursors, [undefined, 'next-page'])
// Reconnect clears pagination; a new account must not inherit a receipt cursor.
await act(async () => button('Check MrCall receipts').props.onClick())
await reconnect()
assert.ok(button('Check MrCall receipts'))
unmount()

window.zylch.usage.today = () => new Promise(resolve => pending.push(resolve))
const start = pending.length
await render(React.createElement(Budget))
await reconnect()
await act(async () => pending[start]({ ...snapshot, spent_usd: 99999 }))
assert.doesNotMatch(text(), /99999/)
await act(async () => pending[start + 1]({ ...snapshot, reserved_usd: undefined, model_policy: undefined }))
assert.match(text(), /Update the engine/)
assert.doesNotMatch(text(), /available for new AI requests/)
unmount()
assert.equal(sidecar.size, 0)
assert.equal(focus.size, 0)
console.log('Spending UI: saved billing, top-up URL, stale balances, saved models, receipt pagination, account invalidation and old engine refusal passed.')

const Models = load('components/ModelPolicy.tsx').default
let catalogs = [], modelEdits = []
window.zylch.llm = { models: provider => new Promise(resolve => catalogs.push({ provider, resolve })) }
const modelProps = { provider: 'mrcall', values: { LLM_MODEL_PRESET: 'balanced', MRCALL_CREDITS_MODEL: 'claude-opus-5', MODEL_MEMORY_MERGE: 'claude-opus-5' }, refreshKey: 'A', onChange: (key, value) => modelEdits.push([key, value]) }
await render(React.createElement(Models, modelProps))
assert.match(text(), /no personal API key is needed/)
assert.match(text(), /preset controls the default:/)
assert.match(text(), /Claude Sonnet 5/)
assert.match(text(), /saved custom model below is inactive/)
assert.match(text(), /saved job override\(s\) remain active/)
assert.equal(view.root.findByType('details').props.open, undefined)
await act(async () => catalogs[0].resolve({ available: true, models: [{ id: 'moonshotai/kimi-k3', label: 'Kimi K3', provider: 'openrouter' }], reason: '' }))
assert.match(text(), /saved; unavailable/)
await act(async () => view.update(React.createElement(Models, { ...modelProps, values: { ...modelProps.values, LLM_MODEL_PRESET: 'economy' } })))
assert.match(text(), /Claude Haiku 4.5/)
assert.match(text(), /Saved custom model — inactive while preset is selected/)
await act(async () => view.root.findAllByType('select')[0].props.onChange({ target: { value: 'moonshotai/kimi-k3' } }))
assert.deepEqual(modelEdits, [['LLM_MODEL_PRESET', 'custom'], ['MRCALL_CREDITS_MODEL', 'moonshotai/kimi-k3']])
// Choosing a model does not clear role overrides or alter credentials/payment.
await act(async () => view.update(React.createElement(Models, { ...modelProps, provider: 'openrouter' })))
assert.equal(catalogs[1].provider, 'openrouter')
await reconnect()
await act(async () => catalogs[1].resolve({ available: true, models: [{ id: 'stale-model', label: 'Wrong account model', provider: 'openrouter' }] }))
assert.doesNotMatch(text(), /Wrong account model/)
assert.match(text(), /Connection changed/)
unmount()
console.log('Model selection: payment separation, explicit custom policy, role/key preservation and stale catalog rejection passed.')
