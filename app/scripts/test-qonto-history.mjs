import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import Module, { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { randomUUID } from 'node:crypto'

const here = path.dirname(fileURLToPath(import.meta.url))
const appRequire = createRequire(path.join(here, '../package.json'))
const testRequire = createRequire(path.join(process.env.MRCALL_UI_TEST_DEPS ?? '/tmp/mrcall-preparation-ui-tests', 'package.json'))
const ts = appRequire('typescript')
const React = testRequire('react')
const { create, act } = testRequire('react-test-renderer')
const auth = { currentUser: { uid: 'fixture-uid' } }
const authListeners = new Set()
const ipcListeners = new Map()
const rpcCalls = []
const storage = new Map()
let bridge, capability = 1, connected = true, backend = { location: 'local' }, pending
let providerTurns = 0, narrationCalls = 0
let pendingCapabilities
const bindings = new Map()
const ipc = {
  on: (name, callback) => ipcListeners.set(name, callback),
  invoke: async (channel, method, params) => {
    if (channel === 'profile:current') return { id: auth.currentUser?.uid, email: 'fixture@example.test' }
    if (channel === 'settings:getBackendLocation') return backend
    assert.equal(channel, 'rpc:call')
    rpcCalls.push({ method, params })
    if (method === 'system.capabilities') return pendingCapabilities ? pendingCapabilities() : { chat_history_binding: capability }
    if (method === 'qonto.status') return { status: connected ? 'connected' : 'disconnected', account_count: connected ? 1 : 0 }
    if (method === 'tasks.list') return []
    if (method.startsWith('narration.')) { narrationCalls++; return { text: 'Thinking' } }
    if (method === 'chat.send') {
      if (pending) return pending(params)
      if (params.history_mode === 'managed_finance') {
        assert.deepEqual(params.conversation_history, [], 'Managed history must never travel back from renderer')
        assert.deepEqual(params.context, {}, 'No caller-set provenance')
        const existing = bindings.get(params.conversation_id)
        if (existing) {
          assert.equal(params.history_handle, existing.handle)
          assert.equal(params.history_revision, existing.revision)
          existing.revision++
        } else {
          assert.equal(params.history_handle, undefined)
          assert.equal(params.history_revision, undefined)
          assert.equal(connected, true)
          bindings.set(params.conversation_id, { handle: randomUUID(), revision: 1 })
        }
        providerTurns++
        const binding = bindings.get(params.conversation_id)
        return { response: 'Authorized fixture answer', history_mode: 'managed_finance', history_handle: binding.handle, history_revision: binding.revision }
      }
      providerTurns++
      return { response: 'Email follow-up answer' }
    }
    throw new Error('Unexpected fixture RPC: ' + method)
  }
}
const cache = new Map()
function load(file) {
  if (cache.has(file)) return cache.get(file).exports
  const mod = new Module(file)
  cache.set(file, mod)
  mod.require = (name) => {
    if (name === 'electron') return { ipcRenderer: ipc, contextBridge: { exposeInMainWorld: (_, value) => { bridge = value } } }
    if (name === 'firebase/auth') return { onAuthStateChanged: (_, callback) => { authListeners.add(callback); return () => authListeners.delete(callback) } }
    if (name.endsWith('/firebase/config')) return { auth }
    if (name.endsWith('/firebase/authUtils')) return { isAuthSessionActive: () => !!auth.currentUser, onAuthSessionInvalidated: () => () => {} }
    if (name === 'react-markdown') return { __esModule: true, default: ({ children }) => React.createElement('span', null, children) }
    if (name.endsWith('/Icon') || name.endsWith('/ThreadPanel')) return { __esModule: true, default: () => null }
    if (name.startsWith('.')) {
      const target = path.resolve(path.dirname(file), name)
      return load(['.ts', '.tsx', ''].map(ext => target + ext).find(candidate => fs.existsSync(candidate)))
    }
    return testRequire(name)
  }
  mod._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, esModuleInterop: true }
  }).outputText, file)
  return mod.exports
}
if (!global.crypto) Object.defineProperty(global, 'crypto', { value: { randomUUID } })
global.localStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) }
load(path.join(here, '../src/preload/index.ts'))
const domListeners = new Map()
global.window = { zylch: bridge,
  addEventListener: (name, callback) => { const listeners = domListeners.get(name) || new Set(); listeners.add(callback); domListeners.set(name, listeners) },
  removeEventListener: (name, callback) => domListeners.get(name)?.delete(callback),
  dispatchEvent: event => { for (const callback of domListeners.get(event.type) || []) callback(event) }
}
const { ConversationsProvider, useConversations } = load(path.join(here, '../src/renderer/src/store/conversations.ts'))
const { TasksProvider } = load(path.join(here, '../src/renderer/src/store/tasks.ts'))
const { ThreadProvider } = load(path.join(here, '../src/renderer/src/store/thread.ts'))
const Workspace = load(path.join(here, '../src/renderer/src/views/Workspace.tsx')).default
const ChatComposer = load(path.join(here, '../src/renderer/src/components/ChatComposer.tsx')).default
let state, view
function Probe() { state = useConversations(); return null }
const text = () => JSON.stringify(view.toJSON())
const button = label => view.root.findAllByType('button').find(node => node.children.join('') === label)
const mount = async () => act(async () => {
  view = create(React.createElement(ConversationsProvider, null,
    React.createElement(ThreadProvider, null, React.createElement(TasksProvider, null,
      React.createElement(Probe), React.createElement(Workspace)))))
})
const unmount = () => act(() => view.unmount())
const newFinance = async () => act(async () => button('New Qonto chat').props.onClick())
const send = async message => {
  await act(async () => view.root.findByType('textarea').props.onChange({ target: { value: message } }))
  await act(async () => button('Invia').props.onClick())
}
const legacy = { id: 'thread-fixture', title: 'Existing email', threadId: 'fixture', history: [{ role: 'user', content: 'Prior email request' }, { role: 'assistant', content: 'Prior email answer' }], draftInput: '', busy: false, pendingApproval: null }
storage.set('zylch:conversations:fixture-uid', JSON.stringify({ conversations: [{ ...legacy, id: 'general' }, legacy], activeId: legacy.id }))
await mount()
await send('Email follow-up')
const raw = rpcCalls.filter(call => call.method === 'chat.send').at(-1).params
assert.equal(raw.history_mode, undefined)
assert.deepEqual(raw.conversation_history, legacy.history)
capability = undefined
await newFinance()
assert.match(text(), /engine needs an update/)
assert.equal(state.state.conversations.length, 2)
capability = 1
connected = false
await newFinance()
assert.match(text(), /Connect Qonto in Settings/)
assert.equal(state.state.conversations.length, 2)
connected = true
await newFinance()
let finance = state.state.conversations.find(conv => conv.id === state.state.activeId)
assert.equal(finance.title, 'Qonto finance')
assert.deepEqual(finance.history, [])
assert.deepEqual(state.state.conversations.find(conv => conv.id === legacy.id).history.slice(0, 2), legacy.history)
const priorNarrationCalls = narrationCalls
await send('Bounded account question')
finance = state.state.conversations.find(conv => conv.id === state.state.activeId)
assert.equal(finance.finance.revision, 1)
assert.ok(finance.finance.handle)
const financeId = finance.id
const handle = finance.finance.handle
await send('Managed follow-up')
assert.equal(state.state.conversations.find(conv => conv.id === financeId).finance.revision, 2)
assert.equal(narrationCalls, priorNarrationCalls, 'Finance prompts must not go to narration')
unmount()
await mount()
assert.equal(state.state.activeId, financeId)
assert.equal(state.state.conversations.find(conv => conv.id === financeId).finance.handle, handle)
await send('Follow-up after reload')
assert.equal(state.state.conversations.find(conv => conv.id === financeId).finance.revision, 3)
await newFinance()
pending = async () => ({ response: 'UNBOUND BANK RESPONSE' })
await send('Missing binding response')
assert.doesNotMatch(text(), /UNBOUND BANK RESPONSE/)
assert.equal(view.root.findByType('textarea').props.disabled, true)
assert.match(text(), /invalid finance history binding/)
pending = undefined
await act(async () => state.setActive(financeId))
backend = { location: 'remote', url: 'wss://different.fixture.test' }
const beforeSwitch = providerTurns
await send('Do not replay to another host')
assert.equal(providerTurns, beforeSwitch)
assert.match(text(), /belongs to another account or engine/)
assert.equal(view.root.findByType('textarea').props.disabled, true)
backend = { location: 'local' }
await newFinance()
let finish
pending = () => new Promise(resolve => { finish = resolve })
act(() => {
  view.root.findByType('textarea').props.onChange({ target: { value: 'Delayed question' } })
})
let sendPromise
act(() => { sendPromise = button('Invia').props.onClick() })
await act(async () => {})
await act(async () => ipcListeners.get('sidecar:status')({}, { alive: false, profile: 'fixture-uid', code: 'restarting' }))
await act(async () => finish({ response: 'OLD HOST BANK RESPONSE', history_mode: 'managed_finance', history_handle: 'late', history_revision: 1 }))
await sendPromise
assert.doesNotMatch(text(), /OLD HOST BANK RESPONSE/)
pending = undefined
await newFinance()
pending = () => new Promise(resolve => { finish = resolve })
act(() => view.root.findByType('textarea').props.onChange({ target: { value: 'Delayed context question' } }))
act(() => { sendPromise = button('Invia').props.onClick() })
await act(async () => {})
await act(async () => state.setActive(legacy.id))
await act(async () => finish({ response: 'OLD CONTEXT BANK RESPONSE', history_mode: 'managed_finance', history_handle: 'late', history_revision: 1 }))
await sendPromise
assert.doesNotMatch(JSON.stringify(state.state), /OLD CONTEXT BANK RESPONSE/)
pending = undefined
await newFinance()

pending = undefined
await newFinance()
const oldCompanyFinanceId = state.state.activeId
pending = () => new Promise(resolve => { finish = resolve })
act(() => view.root.findByType('textarea').props.onChange({ target: { value: 'Delayed company question' } }))
act(() => { sendPromise = button('Invia').props.onClick() })
await act(async () => {})
assert.equal(typeof finish, 'function')
await act(async () => {
  window.dispatchEvent(new Event('mrcall:company-changing'))
  window.dispatchEvent(new Event('mrcall:company-changed'))
})
await act(async () => finish({ response: 'OLD COMPANY BANK RESPONSE', history_mode: 'managed_finance', history_handle: 'valid-late-company-handle', history_revision: 1 }))
await sendPromise
assert.doesNotMatch(JSON.stringify(state.state), /OLD COMPANY BANK RESPONSE/)
const discardedCompanyConversation = state.state.conversations.find(conv => conv.id === oldCompanyFinanceId)
assert.equal(discardedCompanyConversation.finance.handle, undefined, 'A delayed old-company binding must not be retained')
assert.equal(discardedCompanyConversation.finance.revision, undefined)
pending = undefined
await newFinance()
await act(async () => window.dispatchEvent(new Event('mrcall:company-changing')))
assert.equal(button('New Qonto chat').props.disabled, true)
assert.equal(view.root.findByType('textarea').props.disabled, true)
const callsDuringJoin = rpcCalls.length
const conversationsDuringJoin = state.state.conversations.length
await newFinance()
await act(async () => view.root.findByType(ChatComposer).props.onSubmit('Refused during company join', []))
assert.equal(rpcCalls.length, callsDuringJoin, 'Pending company join refuses finance start/send before any RPC')
assert.equal(state.state.conversations.length, conversationsDuringJoin)
await act(async () => window.dispatchEvent(new Event('mrcall:company-changed')))
await act(async () => state.setActive(legacy.id))
pending = () => new Promise(resolve => { finish = resolve })
act(() => view.root.findByType('textarea').props.onChange({ target: { value: 'Ordinary email during company change' } }))
act(() => { sendPromise = button('Invia').props.onClick() })
await act(async () => {})
await act(async () => {
  window.dispatchEvent(new Event('mrcall:company-changing'))
  assert.equal(view.root.findByType('textarea').props.disabled, true, 'Ordinary chat is disabled only because its request is busy')
  window.dispatchEvent(new Event('mrcall:company-changed'))
})
await act(async () => finish({ response: 'ORDINARY EMAIL AFTER COMPANY CHANGE' }))
await sendPromise
assert.match(JSON.stringify(state.state.conversations.find(conv => conv.id === legacy.id)), /ORDINARY EMAIL AFTER COMPANY CHANGE/)
pending = undefined
await act(async () => window.dispatchEvent(new Event('mrcall:company-changing')))
assert.equal(view.root.findByType('textarea').props.disabled, false, 'Company join leaves ordinary raw-history chat available')
await act(async () => window.dispatchEvent(new Event('mrcall:company-changed')))
let finishCapabilities, startPromise
pendingCapabilities = () => new Promise(resolve => { finishCapabilities = resolve })
const conversationsBeforeLateStart = state.state.conversations.length
act(() => { startPromise = button('New Qonto chat').props.onClick() })
await act(async () => {})
await act(async () => {
  window.dispatchEvent(new Event('mrcall:company-changing'))
  window.dispatchEvent(new Event('mrcall:company-changed'))
})
await act(async () => finishCapabilities({ chat_history_binding: 1 }))
await startPromise
assert.equal(state.state.conversations.length, conversationsBeforeLateStart, 'A delayed old-company start cannot create a finance context')
pendingCapabilities = undefined

await newFinance()
capability = 0
const beforeOldEngine = providerTurns
await send('Old engine must refuse finance')
assert.equal(providerTurns, beforeOldEngine)
assert.match(text(), /engine needs an update/)
assert.equal(view.root.findByType('textarea').props.disabled, true)
capability = 1
await newFinance()
pending = () => new Promise(resolve => { finish = resolve })
act(() => view.root.findByType('textarea').props.onChange({ target: { value: 'Delayed UID question' } }))
act(() => { sendPromise = button('Invia').props.onClick() })
await act(async () => {})
await act(async () => {
  auth.currentUser = { uid: 'different-uid' }
  for (const callback of authListeners) callback(auth.currentUser)
})
await act(async () => finish({ response: 'OLD UID BANK RESPONSE', history_mode: 'managed_finance', history_handle: 'late', history_revision: 1 }))
await sendPromise
assert.doesNotMatch(text(), /OLD UID BANK RESPONSE/)
unmount()
console.log('Qonto history UI: actual Workspace, conversation persistence and preload journeys passed (legacy follow-up, capability/connection refusal, managed creation/follow-up/reload, invalid binding, old engine follow-up and transport/context/UID/company late replies, pending join refusal, delayed finance start and unchanged ordinary delivery).')
