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
    if (name.endsWith('/modelRoles')) return load('lib/modelRoles.ts')
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
// NARRATION has no Settings field, so its remedy is the custom preset (roles/table.py remedy).
const ANTHROPIC = 'AI paused: no Anthropic model for role NARRATION: none of the models ranked for it under the economy preset is an Anthropic model, so a personal Anthropic key cannot run it. In Settings, choose the custom preset with an Anthropic model as the default model, or another billing choice.'
// MEMORY_MERGE has its own Settings field (Advanced job models): the remedy names it.
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
  ['anthropic', 'MODEL_NARRATION', ANTHROPIC, 'Progress narration'],
  ['mrcall', 'MODEL_MEMORY_MERGE', CREDITS, 'Memory comparison']
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
  'Task deduplication: paused: no model available for this job with this billing choice'
])
await act(async () => view.unmount())

// 1b. Saved models names every role the engine sends by its job, each once
// (milestone 10, S8). The keys come from the engine's role list, so a role
// added there without a name here fails this test.
const JOBS = {
  MODEL_CHAT: 'Conversation', MODEL_TASK_SOLVE: 'Task solving', MODEL_WEB_SEARCH: 'Web search',
  MODEL_COMPACTION: 'Conversation summaries', MODEL_NARRATION: 'Progress narration',
  MODEL_INTENT: 'Request classification', MODEL_SYNC_ANALYSIS: 'Mail and calendar analysis',
  MODEL_REPLY_NEED: 'Reply-needed check', MODEL_MEMORY_EXTRACT: 'Memory extraction',
  MODEL_MNEMONIC: 'Memory decisions', MODEL_MEMORY_MERGE: 'Memory comparison',
  MODEL_TASK_DETECTION: 'Task detection', MODEL_REANALYZE: 'Task review',
  MODEL_DEDUP: 'Task deduplication', MODEL_TRAIN: 'Assistant training',
  MODEL_CORRECTION_LEARNING: 'Learning from draft edits'
}
const requirements = JSON.parse(fs.readFileSync(path.join(here, '../../engine/zylch/llm/roles/requirements.json'), 'utf8'))
const engineRoles = Object.keys(requirements.roles).map(role => 'MODEL_' + role)
assert.equal(engineRoles.length, 16)
assert.deepEqual([...engineRoles].sort(), Object.keys(JOBS).sort(), 'every engine role has a job name')
assert.equal(new Set(Object.values(JOBS)).size, 16, 'job names are distinct')
const FUTURE = 'AI paused: no model served for role FUTURE_ROLE.'
// The engine's order, plus a role a newer engine adds (one running, one paused).
const allRoles = Object.fromEntries(engineRoles.map(role => [role, `m-${role.toLowerCase()}`]))
snapshot = { ...base, model_policy: { provider: 'mrcall', preset: 'economy', model: 'm-model_chat',
  roles: { ...allRoles, MODEL_FUTURE_ROLE: 'm-future', MODEL_NEXT_JOB: null },
  paused: { MODEL_NEXT_JOB: FUTURE }, quality_status: 'q', credential_configured: true } }
await act(async () => { view = create(React.createElement(Budget)) })
const rows = view.root.findAll(node => node.type === 'p' && /^[^·]+: /.test(node.children.join('')) && !node.props.className?.includes('grey'))
  .map(node => node.children.join(''))
const expected = [...Object.entries(JOBS).map(([role, job]) => `${job}: m-${role.toLowerCase()}`),
  'Future Role: m-future', `Next Job: ${FUTURE}`]
assert.deepEqual(rows, expected, 'each role once, by its job name, known roles first then new ones')
assert.equal(rows.filter(row => row.startsWith('Conversation:')).length, 1, 'CHAT is shown once')
assert.doesNotMatch(text(), /MODEL_/, 'no raw role key is shown')
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
console.log('Role pause UI: Settings shows each paused job with its reason (Anthropic key and credits), the generic line for an older engine, all sixteen engine roles by job name once each with a readable name for a new role, and narration shows the pause in place of the fallback.')
