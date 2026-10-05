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
    if (name.endsWith('/firebase/config')) return { auth }
    if (name.endsWith('/firebase/authUtils')) return { ensureEngineSession: async () => true, isAuthSessionActive: () => !!auth.currentUser, onAuthSessionInvalidated: () => () => {} }
    if (name.endsWith('/App')) return { performSignOut: async () => {} }
    if (name.endsWith('/Icon') || name.endsWith('/DailyBudget') || name.endsWith('/ConnectGoogleCalendar') || name.endsWith('/ConnectWhatsApp')) return emptyComponent
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
const Settings = load(path.join(here, '../src/renderer/src/views/Settings.tsx')).default
const Tasks = load(path.join(here, '../src/renderer/src/views/Tasks.tsx')).default
const { ConversationsProvider } = load(path.join(here, '../src/renderer/src/store/conversations.ts'))
const { TasksProvider } = load(path.join(here, '../src/renderer/src/store/tasks.ts'))
const { ThreadProvider } = load(path.join(here, '../src/renderer/src/store/thread.ts'))
let view
const mount = async () => act(async () => { view = create(React.createElement(ConversationsProvider, null,
  React.createElement(ThreadProvider, null, React.createElement(TasksProvider, null, React.createElement(Settings), React.createElement(Tasks))))) })
const unmount = () => act(() => view.unmount())
const section = () => view.root.findAllByType('section').find(node => node.props['aria-label'] === 'Qonto connection')
const button = label => section().findAllByType('button').find(node => node.children.join('') === label)
const click = async label => { const node = button(label); assert.ok(node, label); assert.equal(node.props.disabled, false, label + ' should be enabled'); await act(async () => node.props.onClick()) }
const input = label => section().findAllByType('input').find(node => node.props['aria-label'] === label)
const setInput = async (label, value) => act(async () => input(label).props.onChange({ target: { value, checked: value } }))
const text = () => JSON.stringify(view.toJSON())
const secrets = async () => { await setInput('Qonto API login', 'fixture-login'); await setInput('Qonto API key', 'fixture-key') }
const test = async () => { await secrets(); await click('Test Qonto') }
const save = async () => { await setInput('Confirm Qonto authority', true); await click('Save Qonto and sync') }
await mount()
assert.equal(input('Qonto API key').props.type, 'password')
await test()
assert.match(text(), /Fixture Qonto legal company/)
assert.equal(input('Qonto API key').props.value, '')
assert.equal(input('Qonto API login').props.value, '')
assert.equal(button('Save Qonto and sync').props.disabled, true)
await setInput('Qonto API key', 'edited-key')
assert.equal(button('Save Qonto and sync'), undefined, 'Credential editing invalidates Test')
await test()
fixture.fail('accounts_invalid')
await save()
assert.equal(fixture.state().connected, false)
assert.match(text(), /Choose at least one account/)
assert.equal(button('Save Qonto and sync'), undefined)
await test()
fixture.fail('authority_required')
await save()
assert.equal(fixture.state().connected, false)
assert.match(text(), /Confirm that you are authorized/)
fixture.testTtl(150)
await test()
await act(async () => new Promise(resolve => setTimeout(resolve, 180)))
assert.equal(button('Save Qonto and sync'), undefined)
assert.match(text(), /test expired/)
fixture.testTtl(300000)
await secrets()
fixture.defer('qonto.test')
let editedTest
act(() => { editedTest = button('Test Qonto').props.onClick() })
await act(async () => {})
await setInput('Qonto API key', 'updated-during-test')
await act(async () => fixture.release('qonto.test'))
await editedTest
assert.equal(button('Save Qonto and sync'), undefined)
assert.equal(input('Qonto API key').props.value, 'updated-during-test')
await test()
await setInput('Select Qonto account fixture-eur', false)
await setInput('Select Qonto account fixture-usd', false)
await setInput('Confirm Qonto authority', true)
assert.equal(button('Save Qonto and sync').props.disabled, true, 'Empty account selection must not save')
await setInput('Select Qonto account fixture-eur', true)
assert.equal(input('Confirm Qonto authority').props.checked, false, 'Account editing invalidates authority')
await save()
assert.equal(fixture.state().connected, true)
assert.equal(input('Qonto API key').props.value, '')
assert.match(text(), /Sync coverage/)
assert.equal(JSON.stringify([...storage.values()]).includes('fixture-key'), false, 'Credentials must not persist')
const connectCall = fixture.calls().filter(call => call.method === 'qonto.connect').at(-1)
assert.deepEqual(connectCall.params.account_ids, ['fixture-eur'])
assert.equal(connectCall.params.authority_confirmed, true)
unmount()
await mount()
assert.match(text(), /Connection:.*connected/)
assert.equal(input('Qonto API key').props.value, '')
fixture.partialSync()
await click('Sync Qonto now')
assert.match(text(), /Qonto could not be reached/)
assert.match(text(), /initial-history windows remain/)
fixture.goodSync()
await click('Sync Qonto now')
await click('Prepare one finance batch')
assert.match(text(), /Saved pause remains enabled/)
const taskArticle = () => view.root.findByType('article')
assert.equal(taskArticle().findAllByType('button').some(node => node.children.join('') === 'Open'), false)
assert.equal(taskArticle().findAllByType('button').some(node => node.children.join('') === 'Update'), false)
await act(async () => taskArticle().findAllByType('button').find(node => node.children.join('') === 'Review Qonto source').props.onClick())
assert.match(text(), /Transaction amount/)
assert.match(text(), /Synthetic fixture evidence/)
assert.equal(fixture.calls().some(call => call.method.startsWith('emails.')), false)
await act(async () => taskArticle().findAllByType('button').find(node => node.children.includes('Pin')).props.onClick())
assert.equal(fixture.state().pinned, true)
await act(async () => taskArticle().findAllByType('button').find(node => node.children.join('') === 'Close source review').props.onClick())
fixture.fail('source_unavailable')
await act(async () => taskArticle().findAllByType('button').find(node => node.children.join('') === 'Review Qonto source').props.onClick())
assert.match(text(), /private Qonto source is unavailable/)
assert.match(text(), /does not use an email fallback/)
assert.equal(fixture.calls().some(call => call.method.startsWith('emails.')), false)
await click('Preview company fact')
assert.match(text(), /selected EUR business account/)
assert.equal(button('Publish confirmed fact').props.disabled, true)
await setInput('Confirm Qonto publication', true)
await click('Publish confirmed fact')
assert.match(text(), /Publication committed/)
assert.deepEqual(fixture.calls().find(call => call.method === 'qonto.publish').params, { preview_id: 'fixture-preview-1', confirmed: true, resume: true })
await click('Disconnect Qonto')
assert.equal(fixture.state().connected, false)
assert.match(text(), /bootstrap configuration remains user-managed/)
assert.equal(view.root.findAllByType('article').length, 0, 'Disconnect hides finance tasks')
assert.equal(button('Delete imported Qonto data').props.disabled, true)
await setInput('Confirm deletion of Qonto imported data', true)
await click('Delete imported Qonto data')
assert.match(text(), /Historical company facts remain shared/)
assert.equal(fixture.state().prepared, false)
const bootstrapCheckbox = () => section().findAllByType('input').find(node => node.props.type === 'checkbox' && !node.props['aria-label'])
await act(async () => bootstrapCheckbox().props.onChange({ target: { checked: true } }))
await click('Test Qonto')
await save()
const bootstrapConnect = fixture.calls().filter(call => call.method === 'qonto.connect').at(-1).params
assert.equal(bootstrapConnect.credential_source, 'bootstrap')
assert.equal(bootstrapConnect.api_key, undefined)
assert.equal(bootstrapConnect.login, undefined)
await click('Disconnect Qonto')
fixture.bootstrap('login_required')
await click('Test Qonto')
assert.match(text(), /needs the Qonto organization API login/)
fixture.bootstrap('available')
fixture.defer('qonto.test')
let lateTest
act(() => { lateTest = button('Test Qonto').props.onClick() })
await act(async () => {})
assert.equal(fixture.pending('qonto.test'), true)
await act(async () => fixture.changeHost())
await act(async () => fixture.release('qonto.test'))
await lateTest
assert.equal(button('Save Qonto and sync'), undefined, 'Prior host Test response must not return')
fixture.defer('qonto.test')
act(() => { lateTest = button('Test Qonto').props.onClick() })
await act(async () => {})
await act(async () => {
  auth.currentUser = { uid: 'different-uid', email: 'other@example.test' }
  fixture.changeUid('different-uid')
  for (const callback of authListeners) callback(auth.currentUser)
})
await act(async () => fixture.release('qonto.test'))
await lateTest
assert.equal(button('Save Qonto and sync'), undefined, 'Prior UID Test response must not return')
await act(async () => bootstrapCheckbox().props.onChange({ target: { checked: false } }))
await secrets()
fixture.defer('qonto.test')
act(() => { lateTest = button('Test Qonto').props.onClick() })
await act(async () => {})
await act(async () => {
  auth.currentUser = null
  fixture.signOut()
  for (const callback of authListeners) callback(null)
})
await act(async () => fixture.release('qonto.test'))
await lateTest
assert.equal(button('Save Qonto and sync'), undefined)
assert.equal(input('Qonto API key').props.value, '')
assert.equal(button('Test Qonto').props.disabled, true)
await act(async () => {
  fixture.signIn()
  auth.currentUser = { uid: 'different-uid', email: 'other@example.test' }
  for (const callback of authListeners) callback(auth.currentUser)
})

const companyEvents = []
for (const name of ['mrcall:company-changing', 'mrcall:company-changed']) window.addEventListener(name, event => companyEvents.push(event))
const memoryButton = label => view.root.findAllByType('button').find(node => node.children.join('') === label)
const companyText = () => JSON.stringify(section().findAllByType('p').map(node => node.children))
const prepareJoin = async () => {
  await act(async () => view.root.findAllByType('input').find(node => node.props.placeholder === 'Memory key').props.onChange({ target: { value: 'fixture-new-company-key' } }))
  await act(async () => memoryButton('Test').props.onClick())
}
const joinCompany = async () => { await prepareJoin(); await act(async () => memoryButton('Join').props.onClick()) }
await test()
await setInput('Confirm Qonto authority', true)
await joinCompany()
assert.equal(button('Save Qonto and sync'), undefined, 'Actual Settings Join invalidates tested credentials, accounts and authority')
assert.equal(input('Qonto API key').props.value, '')
assert.match(companyText(), /Other company 1/)
await test()
assert.match(companyText(), /Other company 1/)
await save()
await click('Preview company fact')
await setInput('Confirm Qonto publication', true)
await joinCompany()
assert.equal(button('Publish confirmed fact'), undefined, 'Join clears an existing publication preview and its consent')
await secrets()
fixture.defer('qonto.test')
let lateCompanyTest
act(() => { lateCompanyTest = button('Test Qonto').props.onClick() })
await act(async () => {})
assert.equal(fixture.pending('qonto.test'), true)
await joinCompany()
await act(async () => fixture.release('qonto.test'))
await lateCompanyTest
assert.equal(button('Save Qonto and sync'), undefined, 'Late Test from the previous company must not restore a challenge')
assert.equal(input('Qonto API key').props.value, '')
await test()
await setInput('Confirm Qonto authority', true)
fixture.defer('qonto.connect')
let lateCompanySave
act(() => { lateCompanySave = button('Save Qonto and sync').props.onClick() })
await act(async () => {})
assert.equal(fixture.pending('qonto.connect'), true)
await joinCompany()
await act(async () => fixture.release('qonto.connect'))
await lateCompanySave
assert.equal(button('Save Qonto and sync'), undefined)
assert.equal(button('Sync Qonto now').props.disabled, true, 'Late Save must not claim connection to the prior company')
await test()
await save()
fixture.defer('qonto.publication_preview')
let lateCompanyPreview
act(() => { lateCompanyPreview = button('Preview company fact').props.onClick() })
await act(async () => {})
assert.equal(fixture.pending('qonto.publication_preview'), true)
await joinCompany()
await act(async () => fixture.release('qonto.publication_preview'))
await lateCompanyPreview
assert.equal(button('Publish confirmed fact'), undefined, 'Late preview from the prior company must not return')
await prepareJoin()
fixture.defer('memory.join')
let pendingJoin
act(() => { pendingJoin = memoryButton('Join').props.onClick() })
await act(async () => {})
assert.equal(button('Test Qonto').props.disabled, true, 'Finance actions stay unavailable while the actual Settings Join is pending')
assert.equal(button('Preview company fact').props.disabled, true)
assert.equal(button('Save Qonto and sync'), undefined)
await act(async () => fixture.release('memory.join'))
await pendingJoin
await act(async () => {})
assert.equal(companyEvents.length, 12)
assert.equal(companyEvents.every(event => event.detail === undefined), true, 'Company events carry no memory capability or identity')
await test()
assert.match(companyText(), /Other company 6/)
assert.equal(input('Confirm Qonto authority').props.checked, false)

await setInput('Confirm Qonto authority', true)
const callsBeforeExternalChange = fixture.calls().filter(call => call.method === 'qonto.connect').length
await act(async () => window.zylch.memory.join('fixture-external-company-key'))
await click('Save Qonto and sync')
assert.equal(fixture.calls().filter(call => call.method === 'qonto.connect').length, callsBeforeExternalChange, 'Fresh memory preflight refuses Save after a company change without a renderer event')
assert.equal(button('Save Qonto and sync'), undefined)
await test()
assert.match(companyText(), /Other company 7/)
fixture.companyDescriptor(false)
await test()
assert.equal(button('Save Qonto and sync'), undefined, 'An engine without the authoritative company descriptor cannot request consent')
assert.match(text(), /engine needs an update/)
fixture.companyDescriptor(true)
fixture.oldEngine()
await click('Refresh Qonto status')
assert.match(text(), /engine needs an update/)
assert.equal(button('Test Qonto').props.disabled, true)
assert.equal(button('Sync Qonto now').props.disabled, true)
unmount()
console.log('Qonto UI: actual Settings/Tasks/preload fixture journeys passed (test/edit/retest/expiry, account/authority refusal, save/restart, bootstrap, manual sync, task review/unavailable/pin, publication confirmation, disconnect/delete, old engine, actual company join/retest and signout/UID/host/company late replies). Native Python integration is checked separately by test-qonto-native-browser.mjs.')
