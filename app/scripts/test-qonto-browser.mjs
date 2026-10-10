import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'node:http'
import { execFileSync } from 'node:child_process'
const require = createRequire(import.meta.url)
const browserRequire = createRequire(join(process.env.MRCALL_BROWSER_DEPS ?? '/tmp/mrcall-qonto-browser', 'package.json'))
const { build } = browserRequire('esbuild')
const { chromium } = require(process.env.MRCALL_PLAYWRIGHT_MODULE || '/tmp/mrcall-qonto-browser/node_modules/playwright')
const app = resolve(fileURLToPath(new URL('..', import.meta.url)))
const output = mkdtempSync(join(tmpdir(), 'mrcall-qonto-fixture-'))
await build({ entryPoints: [join(app, 'scripts/fixtures-qonto-preview.tsx')], bundle: true, platform: 'browser', format: 'iife', jsx: 'automatic', outfile: join(output, 'preview.js'), plugins: [{
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
const server = createServer((request, response) => {
  const name = request.url.split('?')[0]
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
  await page.getByPlaceholder('Memory key', { exact: true }).fill('fixture-new-company-key')
  await page.getByRole('button', { name: 'Test', exact: true }).click()
  await page.getByRole('button', { name: 'Join', exact: true }).click()
  await qonto.getByText(/MrCall company: Other company 1/).waitFor()
  await qonto.getByLabel('Qonto API login', { exact: true }).fill('fixture-login')
  await qonto.getByLabel('Qonto API key', { exact: true }).fill('fixture-key')
  await qonto.getByRole('button', { name: 'Test Qonto', exact: true }).click()
  await qonto.getByText(/Qonto legal company: Fixture Qonto legal company/).waitFor()
  assert.equal(await qonto.getByLabel('Qonto API key', { exact: true }).inputValue(), '')
  assert.equal(await qonto.getByRole('button', { name: 'Save Qonto and sync', exact: true }).isDisabled(), true)
  await qonto.getByLabel('Select Qonto account fixture-usd').uncheck()
  await qonto.getByLabel('Confirm Qonto authority').check()
  await qonto.getByRole('button', { name: 'Save Qonto and sync', exact: true }).click()
  await qonto.getByText(/Connection: connected/).waitFor()
  await page.reload()
  await qonto.getByText(/Connection: connected/).waitFor()
  assert.equal(await qonto.getByLabel('Qonto API key', { exact: true }).inputValue(), '')
  await qonto.getByRole('button', { name: 'Sync Qonto now', exact: true }).click()
  await qonto.getByText(/Sync completed/).waitFor()
  await qonto.getByRole('button', { name: 'Prepare one finance batch', exact: true }).click()
  await page.getByRole('button', { name: 'Review Qonto source', exact: true }).waitFor()
  await page.getByRole('button', { name: 'Review Qonto source', exact: true }).click()
  const source = page.getByRole('region', { name: 'Qonto source review', exact: true })
  await source.getByText(/Transaction amount: 1.00 EUR/).waitFor()
  assert.equal(await source.getByText(/Synthetic fixture evidence/).isVisible(), true)
  assert.equal(await page.locator('article').getByRole('button', { name: 'Open', exact: true }).count(), 0)
  assert.equal(await page.locator('article').getByRole('button', { name: 'Update', exact: true }).count(), 0)
  await page.locator('article').getByRole('button', { name: 'Pin', exact: true }).click()
  await page.locator('article').getByRole('button', { name: 'Pinned', exact: true }).waitFor()
  await source.getByRole('button', { name: 'Close source review', exact: true }).click()
  await page.locator('article').getByRole('button', { name: 'Close', exact: true }).click()
  await page.getByRole('button', { name: 'Close (no note)', exact: true }).click()
  assert.equal(await page.locator('article').count(), 0)
  await qonto.getByRole('button', { name: 'Preview company fact', exact: true }).click()
  await qonto.getByText(/Exact company fact:/).waitFor()
  assert.equal(await qonto.getByRole('button', { name: 'Publish confirmed fact', exact: true }).isDisabled(), true)
  await qonto.getByLabel('Confirm Qonto publication').check()
  await qonto.getByRole('button', { name: 'Publish confirmed fact', exact: true }).click()
  await qonto.getByText('Publication committed.', { exact: true }).waitFor()
  await qonto.getByRole('button', { name: 'Disconnect Qonto', exact: true }).click()
  await qonto.getByText(/Connection: disconnected/).waitFor()
  assert.equal(await qonto.getByRole('button', { name: 'Sync Qonto now', exact: true }).isDisabled(), true)
  await qonto.getByLabel('Confirm deletion of Qonto imported data').check()
  await qonto.getByRole('button', { name: 'Delete imported Qonto data', exact: true }).click()
  await qonto.getByText(/Imported finance data deleted/).waitFor()
  assert.equal(await page.evaluate(() => window.fixture.calls().some(call => call.method.startsWith('emails.'))), false)
  assert.deepEqual(errors, [])
  console.log('Qonto browser: actual Settings/Tasks/preload fixture user path passed (actual company join/retest, connect, reload, sync, bounded preparation, source review, pin/close, publication consent, disconnect/delete). Native Python integration is checked separately by test-qonto-native-browser.mjs. Artifacts:', output)
} finally { await browser.close(); await new Promise(done => server.close(done)) }
