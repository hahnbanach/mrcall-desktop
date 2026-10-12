// A job paused on the billing choice is shown with the engine's reason (milestone 10, S6).
// Actual components and hook with fake RPCs; no engine, browser, or paid calls.
// Test dependencies: see test-preparation.mjs (react, react-test-renderer in
// MRCALL_UI_TEST_DEPS). Run: node app/scripts/test-role-pause-ui.mjs
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
function load(relative) {
  const file = path.join(here, '../src/renderer/src', relative)
  const mod = new Module(file)
  mod.require = name => {
    if (!name.startsWith('.')) return testRequire(name)
    if (name.endsWith('/errors')) return { errorMessage: String }
    return { default: () => null }
  }
  mod._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 }
  }).outputText, file)
  return mod.exports
}
const Budget = load('components/DailyBudget.tsx').default
const { narrationReply, useNarration } = load('hooks/useNarration.ts')

// Synthetic reasons in the engine's two shapes (role_pause.py): the app shows them verbatim.
const ANTHROPIC = 'AI paused: no Anthropic model for role NARRATION: none of the models ranked for it under the economy preset is an Anthropic model, so a personal Anthropic key cannot run it. Choose a model for it in Settings.'
const CREDITS = 'AI paused: no model served for role MEMORY_MERGE: the MrCall billing server serves none of the models ranked for it under the economy preset. Choose a model for it in Settings.'
const stderr = new Set()
let snapshot
global.window = {
  addEventListener() {}, removeEventListener() {},
  zylch: {
    onSidecarStatus: () => () => {},
    onStderr: fn => { stderr.add(fn); return () => stderr.delete(fn) },
    usage: { today: async () => snapshot, reconcile: async () => ({}) },
    narration: { summarize: async () => ({ text: '', paused: ANTHROPIC }) }
  }
}
let view
const text = () => JSON.stringify(view.toJSON())
const lines = () => view.root.findAll(node => node.type === 'p' && node.props.role === 'status' && /paused/.test(JSON.stringify(node.children)))
const base = { spent_usd: 0, reserved_usd: 0, remaining_usd: 5, budget_usd: 5, billing_supported: true, paused: false, pricing_fault: false }

// 1. Settings: each paused job shows its name and the engine's reason, on both billing choices.
for (const [provider, role, reason, name] of [
  ['anthropic', 'MODEL_NARRATION', ANTHROPIC, 'MODEL_NARRATION'],
  ['mrcall', 'MODEL_MEMORY_MERGE', CREDITS, 'Update memory']
]) {
  snapshot = { ...base, model_policy: { provider, preset: 'economy', model: 'runs-chat', roles: { MODEL_CHAT: 'runs-chat', [role]: null }, paused: { [role]: reason }, quality_status: 'q', credential_configured: true } }
  await act(async () => { view = create(React.createElement(Budget)) })
  const shown = lines()
  assert.equal(shown.length, 1, provider)
  assert.equal(shown[0].children.join(''), `${name}: ${reason}`)
  assert.match(shown[0].props.className, /text-brand-orange/)
  assert.doesNotMatch(text(), /no model available for this job/, 'the reason replaces the generic line')
  await act(async () => view.unmount())
}
// An older engine sends no reason: the generic paused line remains.
snapshot = { ...base, model_policy: { provider: 'mrcall', preset: 'economy', model: null, roles: { MODEL_DEDUP: null }, quality_status: 'q', credential_configured: true } }
await act(async () => { view = create(React.createElement(Budget)) })
assert.deepEqual(lines().map(node => node.children.join('')), [
  'Conversation: paused: no model available for this job with this billing choice',
  'Merge duplicate tasks: paused: no model available for this job with this billing choice'
])
await act(async () => view.unmount())

// 2. Narration: a paused reply shows its message in place of the fallback text.
assert.equal(narrationReply({ text: '', paused: ANTHROPIC }), ANTHROPIC)
assert.equal(narrationReply({ text: ' Sto leggendo ' }), 'Sto leggendo')
assert.equal(narrationReply({ text: '' }), '')
assert.equal(narrationReply(undefined), '')
let narrated = ''
function Probe() { narrated = useNarration(true, '', 'Sto pensando alla tua richiesta.'); return null }
await act(async () => { view = create(React.createElement(Probe)) })
assert.equal(narrated, 'Sto pensando alla tua richiesta.')
await act(async () => { for (const fn of stderr) fn('INFO fetching the inbox') })
await act(async () => { await new Promise(resolve => setTimeout(resolve, 4300)) })
assert.equal(narrated, ANTHROPIC, 'the hook shows the pause in place of the fallback text')
await act(async () => view.unmount())
console.log('Role pause UI: Settings shows each paused job with its reason (Anthropic key and credits), the generic line for an older engine, and narration shows the pause in place of the fallback.')
