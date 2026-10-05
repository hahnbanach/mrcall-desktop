import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'node:http'
import { execFileSync, spawn } from 'node:child_process'
import { createInterface } from 'node:readline'
const require = createRequire(import.meta.url)
const browserRequire = createRequire(join(process.env.MRCALL_BROWSER_DEPS ?? '/tmp/mrcall-qonto-browser', 'package.json'))
const { build } = browserRequire('esbuild')
const { chromium } = require(process.env.MRCALL_PLAYWRIGHT_MODULE || '/tmp/mrcall-qonto-browser/node_modules/playwright')
const app = resolve(fileURLToPath(new URL('..', import.meta.url)))
const output = mkdtempSync(join(tmpdir(), 'mrcall-qonto-fixture-'))
await build({ entryPoints: [join(app, 'scripts/fixtures-qonto-native.tsx')], bundle: true, platform: 'browser', format: 'iife', jsx: 'automatic', outfile: join(output, 'preview.js'), plugins: [{
  name: 'offline-qonto-fixture', setup(builder) {
    builder.onResolve({ filter: /^(electron|firebase\/auth|\.\.\/App|\.\.\/firebase\/(config|authUtils)|\.\/Connect(GoogleCalendar|WhatsApp))$/ }, args => ({ path: args.path, namespace: 'fixture' }))
    builder.onLoad({ filter: /.*/, namespace: 'fixture' }, args => ({ contents:
      args.path === 'electron' ? `const registrations=[];window.fixtureIpcRegistrations=registrations;export const ipcRenderer={on:(...args)=>registrations.push(args),invoke:(...args)=>window.fixtureRpc.invoke(...args)};export const contextBridge={exposeInMainWorld:(name,value)=>{window[name]=value}}` :
      args.path === 'firebase/auth' ? `export const onAuthStateChanged=(_,callback)=>{const listener=()=>callback(window.fixtureAuth);window.fixtureAuthListeners.add(listener);queueMicrotask(listener);return ()=>window.fixtureAuthListeners.delete(listener)}` :
      args.path.endsWith('/config') ? `export const auth={get currentUser(){return window.fixtureAuth}}` :
      args.path.endsWith('/authUtils') ? `export const ensureEngineSession=async()=>!!window.fixtureAuth;export const isAuthSessionActive=()=>!!window.fixtureAuth;export const onAuthSessionInvalidated=()=>()=>{}` :
      args.path.endsWith('/App') ? `export const performSignOut=()=>window.fixture.signOut()` :
      `export default function Integration(){return null}`, loader: 'js' }))
  }
}] })
execFileSync(process.execPath, [join(app, 'node_modules/tailwindcss/lib/cli.js'), '-i', join(app, 'src/renderer/src/index.css'), '-o', join(output, 'style.css')], { cwd: app, stdio: 'pipe' })
writeFileSync(join(output, 'index.html'), '<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="style.css"></head><body><div id="root"></div><script src="preview.js"></script></body></html>')
const engine = resolve(app, '../engine')
const python = process.env.MRCALL_FIXTURE_PYTHON || join(engine, 'venv/bin/python')
let sidecar
let nextId = 0
let transportReady = Promise.resolve()
const pending = new Map()
const start = () => new Promise((ready, reject) => {
  sidecar = spawn(python, ['-m', 'tests.qonto.ui_sidecar', output], { cwd: engine, env: { ...process.env, PYTHONPATH: engine }, stdio: ['pipe', 'pipe', 'pipe'] })
  sidecar.stderr.on('data', data => writeFileSync(join(output, 'sidecar.log'), data, { flag: 'a' }))
  createInterface({ input: sidecar.stdout }).on('line', line => {
    const response = JSON.parse(line)
    if (response.ready) ready()
    else { pending.get(response.id)?.(response); pending.delete(response.id) }
  })
  sidecar.on('exit', code => { if (code) { reject(new Error('Native sidecar failed; inspect RAM sidecar.log')); for (const done of pending.values()) done({ error: { message: 'Native fixture sidecar failed' } }); pending.clear() } })
})
const stop = async () => { const child = sidecar; if (child.exitCode !== null) return; const exited = new Promise(done => child.once('exit', done)); child.kill('SIGTERM'); await exited }
const rpc = async body => { await transportReady; return new Promise(done => { const id = ++nextId; pending.set(id, done); sidecar.stdin.write(JSON.stringify({ ...body, id }) + '\n') }) }
await start()
const server = createServer(async (request, response) => {
  const name = request.url.split('?')[0]
  if (name === '/rpc') {
    let body = ''
    for await (const chunk of request) body += chunk
    response.setHeader('Content-Type', 'application/json')
    response.end(JSON.stringify(await rpc(JSON.parse(body))))
    return
  }
  if (name === '/restart') { transportReady = (async () => { await stop(); await start() })(); await transportReady; response.end('ok'); return }
  if (!['/', '/preview.js', '/style.css'].includes(name)) { response.writeHead(404); response.end(); return }
  response.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html')
  response.end(readFileSync(join(output, name === '/' ? 'index.html' : name.slice(1))))
})
await new Promise(done => server.listen(0, '127.0.0.1', done))
const browser = await chromium.launch({ headless: true, executablePath: process.env.MRCALL_BROWSER_BINARY, args: ['--no-sandbox'] })
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const base = `http://127.0.0.1:${server.address().port}`
  await page.route('**/*', route => route.request().url().startsWith(base) ? route.continue() : route.abort())
  await page.goto(base)
  const qonto = page.getByRole('region', { name: 'Qonto connection', exact: true })
  await qonto.getByLabel('Qonto API login', { exact: true }).fill('fixture-organization-login')
  await qonto.getByLabel('Qonto API key', { exact: true }).fill('fixture-api-key-secret')
  await qonto.getByRole('button', { name: 'Test Qonto', exact: true }).click()
  await qonto.getByText(/Qonto legal company: Fixture legal company/).waitFor().catch(async error => { writeFileSync(join(output, 'failure.txt'), await page.locator('body').innerText()); throw error })
  assert.equal(await qonto.getByLabel('Qonto API key', { exact: true }).inputValue(), '')
  assert.equal(await qonto.getByRole('button', { name: 'Save Qonto and sync', exact: true }).isDisabled(), true)
  await qonto.getByLabel('Select Qonto account account-gbp').uncheck()
  await qonto.getByLabel('Confirm Qonto authority').check()
  await qonto.getByRole('button', { name: 'Save Qonto and sync', exact: true }).click()
  await qonto.getByText(/Connection: connected/).waitFor()
  await page.evaluate(() => window.fixture.restart())
  await page.reload()
  await qonto.getByText(/Connection: connected/).waitFor()
  assert.equal(await qonto.getByLabel('Qonto API key', { exact: true }).inputValue(), '')
  await qonto.getByRole('button', { name: 'Sync Qonto now', exact: true }).click()
  await qonto.getByText(/Sync completed/).waitFor()
  await qonto.getByRole('button', { name: 'Prepare one finance batch', exact: true }).click()
  await page.getByRole('button', { name: 'Review Qonto source', exact: true }).waitFor()
  const beforePaid = await page.evaluate(() => window.fixture.inspect())
  assert.equal(beforePaid.reservations, 0)
  assert.equal(beforePaid.checkpoints, 1)
  assert.equal(beforePaid.paused, true)
  await page.getByRole('button', { name: 'Review Qonto source', exact: true }).waitFor()
  await page.getByRole('button', { name: 'Review Qonto source', exact: true }).click()
  const source = page.getByRole('region', { name: 'Qonto source review', exact: true })
  await source.getByText(/Transaction amount: 10.00 EUR/).waitFor()
  assert.equal(await source.getByText(/Synthetic native fixture evidence/).isVisible(), true)
  assert.equal(await page.locator('article').getByRole('button', { name: 'Open', exact: true }).count(), 0)
  assert.equal(await page.locator('article').getByRole('button', { name: 'Update', exact: true }).count(), 0)
  await page.locator('article').getByRole('button', { name: 'Pin', exact: true }).click()
  await page.locator('article').getByRole('button', { name: 'Pinned', exact: true }).waitFor()
  await source.getByRole('button', { name: 'Close source review', exact: true }).click()
  await page.locator('article').getByRole('button', { name: 'Close', exact: true }).click()
  await page.getByRole('button', { name: 'Close (no note)', exact: true }).click()
  await page.getByRole('button', { name: 'Closed', exact: true }).click()
  await page.locator('article').getByRole('button', { name: 'Reopen', exact: true }).click()
  await page.getByRole('group', { name: 'Filter by status' }).getByRole('button', { name: 'Open', exact: true }).click()
  await page.locator('article').getByRole('button', { name: 'Review Qonto source', exact: true }).waitFor()
  await qonto.getByRole('button', { name: 'Preview company fact', exact: true }).click()
  await qonto.getByText(/Exact company fact:/).waitFor()
  assert.equal(await qonto.getByRole('button', { name: 'Publish confirmed fact', exact: true }).isDisabled(), true)
  await qonto.getByLabel('Confirm Qonto publication').check()
  await qonto.getByRole('button', { name: 'Publish confirmed fact', exact: true }).click()
  await qonto.getByText(/^Publication committed[.:]/).waitFor()
  const committed = await page.evaluate(() => window.fixture.inspect())
  assert.equal(committed.reservations, 1)
  assert.equal(committed.settled, 1)
  assert.equal(committed.facts, 1)
  assert.equal(committed.receipts, 1)
  assert.equal(committed.committed, true)
  assert.equal(committed.minimal_only, true)
  assert.equal(committed.paused, true)
  assert.equal(committed.get_only, true)
  await page.evaluate(() => window.fixture.restart())
  await page.reload()
  await qonto.getByText(/Connection: connected/).waitFor()
  await page.locator('article').getByRole('button', { name: 'Pinned', exact: true }).waitFor()
  await qonto.getByRole('button', { name: 'Preview company fact', exact: true }).click()
  await qonto.getByLabel('Confirm Qonto publication').check()
  await qonto.getByRole('button', { name: 'Publish confirmed fact', exact: true }).click()
  await qonto.getByText(/^Publication committed[.:]/).waitFor()
  const replayed = await page.evaluate(() => window.fixture.inspect())
  assert.equal(replayed.reservations, 1)
  assert.equal(replayed.wire_calls, 0)
  assert.equal(replayed.paused, true)
  await qonto.getByRole('button', { name: 'Disconnect Qonto', exact: true }).click()
  await qonto.getByText(/Connection: disconnected/).waitFor()
  assert.equal(await qonto.getByRole('button', { name: 'Sync Qonto now', exact: true }).isDisabled(), true)
  await page.getByRole('heading', { name: /^Tasks \(/ }).locator('..').getByRole('button', { name: 'Refresh', exact: true }).click()
  await page.getByText('No tasks. All clear.', { exact: true }).waitFor()
  assert.equal(await page.locator('article').count(), 0)
  assert.equal((await page.evaluate(() => window.fixture.inspect())).transactions, 1)
  await qonto.getByLabel('Confirm deletion of Qonto imported data').check()
  await qonto.getByRole('button', { name: 'Delete imported Qonto data', exact: true }).click()
  await qonto.getByText(/Imported finance data deleted/).waitFor()
  const deleted = await page.evaluate(() => window.fixture.inspect())
  assert.equal(deleted.transactions, 0)
  assert.equal(deleted.checkpoints, 0)
  assert.equal(deleted.tasks, 1)
  assert.equal(deleted.facts, 1)
  assert.equal(deleted.reservations, 1)
  await page.getByRole('heading', { name: /^Tasks \(/ }).locator('..').getByRole('button', { name: 'Refresh', exact: true }).click()
  await page.locator('article').getByRole('button', { name: 'Review Qonto source', exact: true }).click()
  await page.getByRole('region', { name: 'Qonto source review', exact: true }).getByText(/private Qonto source is unavailable/i).waitFor()
  assert.equal(await page.evaluate(() => window.fixture.methods().some(method => method.startsWith('emails.'))), false)
  assert.deepEqual(errors, [])
  console.log('PASS: native Settings/Tasks/preload → Python dispatch journey; verified signed admission, selected-account GET sync, free bounded task/checkpoint, source, pin/close/reopen, paid settled publication/receipt, process restart and free receipt replay, disconnect visibility, private deletion and retained edited task/historical fact. Artifacts:', output)
} catch (error) { console.error(error); throw error } finally { await browser.close(); await new Promise(done => server.close(done)); await stop() }
