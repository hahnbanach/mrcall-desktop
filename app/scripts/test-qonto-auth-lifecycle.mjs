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
const cache = new Map()
const auth = { currentUser: { uid: 'fixture-uid', email: 'fixture@example.test' } }
const authListeners = new Set()
const domListeners = new Map()
const storage = new Map()
let fixture, bridge
const emptyComponent = { __esModule: true, default: () => null }
function load(file) {
  if (cache.has(file)) return cache.get(file).exports
  const mod = new Module(file)
  cache.set(file, mod)
  mod.require = name => {
    if (name === 'electron') return { ipcRenderer: { on: (...args) => fixture.on(...args), invoke: (...args) => fixture.invoke(...args) }, contextBridge: { exposeInMainWorld: (_, value) => { bridge = value } } }
    if (name === 'firebase/auth') return { onAuthStateChanged: (_, callback) => { authListeners.add(callback); queueMicrotask(() => callback(auth.currentUser)); return () => authListeners.delete(callback) } }
    if (name.endsWith('/firebase/config') || (name === './config' && file.endsWith('/firebase/authUtils.ts'))) return { auth }
    if (name === 'react-markdown') return { __esModule: true, default: ({ children }) => React.createElement('span', null, children) }
    if (name.endsWith('/App')) return { performSignOut: async () => {} }
    if (name.endsWith('/Icon') || name.endsWith('/DailyBudget') || name.endsWith('/ConnectGoogleCalendar') || name.endsWith('/ConnectWhatsApp') || name.endsWith('/ThreadPanel')) return emptyComponent
    if (name.endsWith('/ModelPolicy')) return { ...emptyComponent, MODEL_FIELDS: new Set() }
    if (name.startsWith('.')) {
      const target = path.resolve(path.dirname(file), name)
      return load(['.ts', '.tsx', ''].map(ext => target + ext).find(candidate => fs.existsSync(candidate)))
    }
    return testRequire(name)
  }
  mod._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText, file)
  return mod.exports
}
const { createQontoFixture } = load(path.join(here, 'fixtures-qonto-rpc.ts'))
fixture = createQontoFixture()
load(path.join(here, '../src/preload/index.ts'))
global.localStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) }
global.window = {
  zylch: bridge,
  addEventListener: (name, callback) => { const set = domListeners.get(name) || new Set(); set.add(callback); domListeners.set(name, set) },
  removeEventListener: (name, callback) => domListeners.get(name)?.delete(callback),
  dispatchEvent: event => { for (const callback of domListeners.get(event.type) || []) callback(event) }
}
global.alert = message => { throw new Error('Unexpected alert: ' + message) }

const authUtils = load(path.join(here, '../src/renderer/src/firebase/authUtils.ts'))
const vm = await import('node:vm')
const appExports = {}
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(here, '../src/renderer/src/App.tsx'), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText, {
  exports: appExports,
  require: name => {
    if (name === './firebase/authUtils') return authUtils
    if (name === './firebase/config') return { auth }
    if (name === 'firebase/auth') return { signOut: async () => { throw Error('Synthetic offline Firebase signout') } }
    if (name === 'react') return React
    if (name === 'react/jsx-runtime') return testRequire(name)
    return emptyComponent
  }, console, window, setTimeout
})
const QontoCard = load(path.join(here, '../src/renderer/src/components/QontoCard.tsx')).default
const QontoSource = load(path.join(here, '../src/renderer/src/components/QontoSource.tsx')).default
const Workspace = load(path.join(here, '../src/renderer/src/views/Workspace.tsx')).default
const { ConversationsProvider, useConversations } = load(path.join(here, '../src/renderer/src/store/conversations.ts'))
const { TasksProvider, useTasks } = load(path.join(here, '../src/renderer/src/store/tasks.ts'))
const Tasks = load(path.join(here, '../src/renderer/src/views/Tasks.tsx')).default
const { ThreadProvider } = load(path.join(here, '../src/renderer/src/store/thread.ts'))
const ChatComposer = load(path.join(here, '../src/renderer/src/components/ChatComposer.tsx')).default
let view, state, taskState, finishChat, finishTasks, deferTasks = false, chatCalls = 0
function Probe() { state = useConversations(); taskState = useTasks(); return null }
const invoke = fixture.invoke
fixture.invoke = async (channel, method, ...args) => {
  if (method === 'chat.send') { chatCalls++; return new Promise(resolve => { finishChat = resolve }) }
  if (method === 'tasks.list' && deferTasks) {
    deferTasks = false
    const result = await invoke(channel, method, ...args)
    return new Promise(resolve => { finishTasks = () => resolve(result) })
  }
  return invoke(channel, method, ...args)
}
window.zylch.account.signOut = async () => { fixture.signOut(); return { ok: true } }
const stopAuth = authUtils.setupAuthListener()
const emitUser = async user => act(async () => {
  auth.currentUser = user
  for (const callback of authListeners) callback(user)
})
const relogin = async () => {
  const user = auth.currentUser
  await emitUser(null)
  fixture.signIn()
  await emitUser(user)
  assert.equal(authUtils.isAuthSessionActive(), true, 'Same-user object relogin must be usable after the null transition')
}
const mount = async () => act(async () => {
  view = create(React.createElement(ConversationsProvider, null,
    React.createElement(ThreadProvider, null, React.createElement(TasksProvider, null,
      React.createElement(Probe), React.createElement(QontoCard),
      React.createElement(QontoSource, { sourceId: 'fixture-source', onClose: () => {} }),
      React.createElement(Workspace)))))
})
const unmount = () => act(() => view.unmount())
const text = () => JSON.stringify(view.toJSON())
const button = label => view.root.findAllByType('button').find(node => node.children.join('') === label)
const input = label => view.root.findAllByType('input').find(node => node.props['aria-label'] === label)
const click = async label => act(async () => button(label).props.onClick())
const fill = async (label, value) => act(async () => input(label).props.onChange({ target: { value, checked: value } }))
const logout = async () => {
  const user = auth.currentUser
  await act(async () => appExports.performSignOut())
  assert.equal(auth.currentUser, user, 'Offline Firebase logout emits no auth change')
  assert.equal(authUtils.isAuthSessionActive(), false)
}
try {
  fixture.connectFixture()
  fixture.defer('qonto.transaction')
  await mount()
  assert.equal(fixture.pending('qonto.transaction'), true)
  await fill('Qonto API login', 'fixture-login')
  await fill('Qonto API key', 'fixture-key-secret')
  await logout()
  assert.equal(input('Qonto API key').props.value, '')
  assert.equal(input('Qonto API login').props.value, '')
  assert.equal(button('Test Qonto').props.disabled, true)
  await act(async () => fixture.release('qonto.transaction'))
  assert.doesNotMatch(text(), /Synthetic fixture evidence/)
  const callsAfterLogout = fixture.calls().length
  await click('Refresh Qonto status')
  assert.equal(fixture.calls().length, callsAfterLogout, 'Revoked context refuses before any RPC')
  unmount()
  await mount()
  assert.equal(fixture.calls().filter(call => call.method.startsWith('qonto.')).length,
    fixture.calls().slice(0, callsAfterLogout).filter(call => call.method.startsWith('qonto.')).length,
    'A newly mounted finance view cannot capture a revoked identity')
  unmount()
  await relogin()

  await mount()
  assert.match(text(), /Synthetic fixture evidence/)
  await click('Preview company fact')
  await fill('Confirm Qonto publication', true)
  assert.ok(button('Publish confirmed fact'))
  await logout()
  assert.ok(!button('Publish confirmed fact'))
  assert.doesNotMatch(text(), /Synthetic fixture evidence|Exact company fact/)
  unmount()
  await relogin()

  await mount()
  await fill('Qonto API login', 'fixture-login')
  await fill('Qonto API key', 'fixture-key-secret')
  await click('Test Qonto')
  await fill('Confirm Qonto authority', true)
  assert.equal(button('Save Qonto and sync').props.disabled, false)
  await logout()
  assert.ok(!button('Save Qonto and sync'), 'Tested secret reference and consent are discarded')
  unmount()
  await relogin()

  await mount()
  fixture.defer('qonto.publication_preview')
  let previewPromise
  act(() => { previewPromise = button('Preview company fact').props.onClick() })
  await act(async () => {})
  assert.equal(fixture.pending('qonto.publication_preview'), true)
  await logout()
  await relogin()
  await act(async () => fixture.release('qonto.publication_preview'))
  await previewPromise
  assert.ok(!button('Publish confirmed fact'), 'Old preview stays rejected after same-UID login')

  await click('New Qonto chat')
  const delayedStart = button('New Qonto chat').props.onClick
  const send = view.root.findByType(ChatComposer).props.onSubmit
  let chatPromise
  act(() => { chatPromise = send('Delayed bank question', []) })
  await act(async () => {})
  assert.equal(typeof finishChat, 'function')
  const priorCalls = fixture.calls().length
  const priorChats = chatCalls
  await logout()
  assert.ok(!button('New Qonto chat'))
  assert.doesNotMatch(text(), /Delayed bank question/)
  await act(async () => { await delayedStart(); await send('Refused while revoked', []) })
  assert.equal(chatCalls, priorChats)
  assert.equal(fixture.calls().length, priorCalls, 'Revoked start/send must not make RPC calls')
  await relogin()
  await act(async () => finishChat({ response: 'STALE PRIVATE ANSWER', history_mode: 'managed_finance', history_handle: 'old-handle', history_revision: 1 }))
  await chatPromise
  assert.doesNotMatch(JSON.stringify(state.state), /STALE PRIVATE ANSWER|old-handle/)
  await click('New Qonto chat')
  const active = state.state.conversations.find(item => item.id === state.state.activeId)
  assert.equal(active.finance.started, false)
  unmount()
  // Mount the actual App auth gate around real Tasks/TasksProvider. This is
  // the production ownership boundary for all private views, not just Qonto.
  auth.currentUser.getIdTokenResult = async () => ({ token: 'fixture-id-token', expirationTime: new Date(Date.now() + 3600000).toISOString() })
  window.zylch.auth.bindProfile = async () => ({ ok: true, found: true })
  window.zylch.account.pushToken = async () => ({ ok: true })
  await window.zylch.qonto.prepare(true)
  const mountGate = async () => act(async () => {
    view = create(React.cloneElement(appExports.default(), {},
      React.createElement(ConversationsProvider, null, React.createElement(ThreadProvider, null,
        React.createElement(TasksProvider, null, React.createElement(Probe), React.createElement(Tasks))))))
  })
  await mountGate()
  assert.match(text(), /Review this declined outgoing transaction/)
  assert.ok(button('Review Qonto source'))
  deferTasks = true
  let lateTasks
  act(() => { lateTasks = taskState.refresh() })
  await act(async () => {})
  assert.equal(typeof finishTasks, 'function')
  await logout()
  assert.doesNotMatch(text(), /Review this declined outgoing transaction/)
  assert.ok(!button('Review Qonto source'), 'Actual App gate unmounts private tasks immediately')
  // Remove tasks before a new login, then resolve the old private list only
  // after the new same-UID shell has mounted. It must not enter that store.
  fixture.changeUid('fixture-uid')
  await relogin()
  assert.doesNotMatch(text(), /Review this declined outgoing transaction/)
  await act(async () => finishTasks())
  await lateTasks
  assert.doesNotMatch(text(), /Review this declined outgoing transaction/)
  fixture.connectFixture()
  await act(async () => taskState.refresh())
  assert.match(text(), /Review this declined outgoing transaction/, 'New authenticated shell loads current authorized tasks')
  console.log('PASS: actual App offline logout clears finance credentials, consent, sources/previews and unmounts private Tasks; deferred source/preview/chat/task replies are refused, revoked actions make no bank RPC, same-UID relogin restores an authorized shell.')
} finally {
  if (view) unmount()
  stopAuth()
}
