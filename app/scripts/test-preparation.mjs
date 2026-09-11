// Actual React component journeys with fake RPCs, no browser or paid provider.
// npm install --prefix /tmp/mrcall-preparation-ui-tests react@18.3.1 react-test-renderer@18.3.1
// node app/scripts/test-preparation.mjs
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
function load(file) {
  const mod = new Module(file)
  mod.require = (name) => name.startsWith('.')
    ? load(path.resolve(path.dirname(file), name + '.ts'))
    : testRequire(name)
  mod._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 }
  }).outputText, file)
  return mod.exports
}
const Panel = load(path.join(here, '../src/renderer/src/components/PreparationPanel.tsx')).default
const base = { paused: true, running: false, attempted: 0, completed: 0, failed: 0,
  limit: 25, next_run_limit: 25, pending: 100, checkpoints_completed: 0, suspended: 0,
  retry_waiting: 0, stop_reason: 'Paused', failed_items: [] }
let status = async () => ({ ...base })
let resume = async () => ({ ...base, success: true, errors: [], summary: 'Done' })
let resumes = 0, pauses = 0, sidecar
const focusListeners = new Map()
global.window = {
  addEventListener: (name, fn) => focusListeners.set(name, fn),
  removeEventListener: (name) => focusListeners.delete(name),
  zylch: {
    preparation: {
      status: () => status(), resume: () => { resumes++; return resume() },
      pause: async () => { pauses++; return { ...base, running: true } }
    },
    update: { run: () => { throw new Error('Unbounded fallback must never run') } },
    onSidecarStatus: (fn) => { sidecar = fn; return () => {} }
  }
}
let view
const button = (label) => view.root.findAllByType('button').find(b => b.children.join('') === label)
const text = () => JSON.stringify(view.toJSON())
const mount = async () => { await act(async () => {
  view = create(React.createElement(Panel, { disabled: false, hasData: true, onBusy() {}, onFinished() {}, onAvailability() {} }))
}) }
const unmount = () => act(() => view.unmount())

status = async () => { throw new Error('Method not found: preparation.status') }
await mount()
assert.match(text(), /engine needs an update/)
assert.equal(button('Analyze next batch').props.disabled, true)
assert.equal(resumes, 0)
unmount()

status = async () => ({ ...base })
resume = async () => ({ ...base, success: false, errors: [{ stage: 'billing', detail: 'Daily allowance unavailable' }] })
await mount()
await act(async () => button('Analyze next batch').props.onClick())
assert.equal(resumes, 1)
assert.match(text(), /Daily allowance unavailable/)
await act(async () => focusListeners.get('focus')())
assert.match(text(), /Daily allowance unavailable/, 'Refreshing status must not erase actionable failure')
unmount()

let finish
resume = () => new Promise(resolve => { finish = resolve })
await mount()
act(() => button('Analyze next batch').props.onClick())
assert.equal(button('Analyzing…').props.disabled, true)
await act(async () => button('Pause analysis').props.onClick())
assert.equal(pauses, 1)
assert.match(text(), /Pause saved/)
// Switching account invalidates both UI data and the first account's late reply.
await act(async () => sidecar({ alive: true, ready: true }))
await act(async () => finish({ ...base, success: false, errors: [{ detail: 'OLD ACCOUNT ERROR' }] }))
assert.doesNotMatch(text(), /OLD ACCOUNT ERROR/)
assert.equal(button('Analyze next batch').props.disabled, false)
unmount()
console.log('Preparation UI: old engine refusal, bounded action, persistent errors, pause and account-switch journeys passed.')
