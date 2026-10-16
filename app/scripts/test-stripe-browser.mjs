import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'node:http'
import { execFileSync } from 'node:child_process'
const require = createRequire(import.meta.url)
const browserRequire = require
const { build } = browserRequire('esbuild')
const { chromium } = require(process.env.MRCALL_PLAYWRIGHT_MODULE || 'playwright')
const app = resolve(fileURLToPath(new URL('..', import.meta.url)))
const output = mkdtempSync(join(tmpdir(), 'mrcall-qonto-fixture-'))
await build({ entryPoints: [join(app, 'scripts/fixtures-stripe-preview.tsx')], bundle: true, platform: 'browser', format: 'iife', jsx: 'automatic', outfile: join(output, 'preview.js'), plugins: [{
  name: 'offline-qonto-fixture', setup(builder) {
    builder.onResolve({ filter: /^(electron|firebase\/auth|\.\.\/App|\.\.\/firebase\/(config|authUtils)|\.\/Connect(GoogleCalendar|WhatsApp))$/ }, args => ({ path: args.path, namespace: 'fixture' }))
    builder.onLoad({ filter: /.*/, namespace: 'fixture' }, args => ({ contents:
      args.path === 'electron' ? `const registrations=[];window.fixtureIpcRegistrations=registrations;export const ipcRenderer={on:(...args)=>registrations.push(args),invoke:(...args)=>window.fixtureRpc.invoke(...args)};export const contextBridge={exposeInMainWorld:(name,value)=>{window[name]=value}}` :
      args.path === 'firebase/auth' ? `export const onAuthStateChanged=(_,callback)=>{const listener=()=>callback(window.fixtureAuth);window.fixtureAuthListeners.add(listener);queueMicrotask(listener);return ()=>window.fixtureAuthListeners.delete(listener)}` :
      args.path.endsWith('/config') ? `export const auth={get currentUser(){return window.fixtureAuth}}` :
      args.path.endsWith('/authUtils') ? `export const ensureEngineSession=async()=>!!window.fixtureAuth;export const isAuthSessionActive=()=>!!window.fixtureAuth;export const onAuthSessionInvalidated=(callback)=>{window.fixtureInvalidation.add(callback);return ()=>window.fixtureInvalidation.delete(callback)}` :
      args.path.endsWith('/App') ? `export const performSignOut=()=>window.fixture.signOut()` :
      `export default function Integration(){return null}`, loader: 'js' }))
  }
}] })
writeFileSync(join(output, 'index.html'), '<!doctype html><html><head><meta charset="utf-8"></head><body><div id="root"></div><script src="preview.js"></script></body></html>')
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
  const card = page.getByRole('region', { name: 'Stripe connection' })
  const key = card.getByLabel('Stripe restricted API key')
  const test = card.getByRole('button', { name: 'Test Stripe', exact: true })
  const save = card.getByRole('button', { name: 'Save Stripe', exact: true })
  const confirm = card.getByLabel('Confirm Stripe authority')
  const testKey = async () => {
    await key.fill('rk_test_fixture')
    await test.click()
    await card.getByText(/Stripe account: Fixture Stripe company/).waitFor()
    assert.equal(await key.inputValue(), '')
  }
  await card.getByText('Connection: disconnected', { exact: true }).waitFor()
  await key.fill('sk_test_forbidden')
  assert.equal(await test.isDisabled(), true)
  await testKey()
  assert.equal(await save.isDisabled(), true)
  await confirm.check()
  await save.click()
  await card.getByText(/Connection: connected/).waitFor()
  await card.getByRole('button', { name: 'Disconnect Stripe', exact: true }).click()
  await card.getByText('Connection: disconnected', { exact: true }).waitFor()
  await testKey()
  await key.fill('rk_test_replaced')
  assert.equal(await save.count(), 0)
  await testKey()
  await page.evaluate(() => window.fixture.generation())
  await confirm.check()
  await save.click()
  await card.getByText(/tested connection expired/).waitFor()
  assert.equal(await save.count(), 0)
  for (const action of ['changeHost', 'companyChange', 'invalidate']) {
    await testKey()
    await page.evaluate(action => window.fixture[action](), action)
    await page.waitForTimeout(50)
    assert.equal(await save.count(), 0, action + ' clears tested credentials')
    assert.equal(await key.inputValue(), '')
  }
  await page.evaluate(() => window.fixture.defer())
  await key.fill('rk_test_delayed')
  await test.click()
  await page.evaluate(() => window.fixture.relogin())
  await page.evaluate(() => window.fixture.release())
  await page.waitForTimeout(100)
  assert.equal(await save.count(), 0, 'Same-UID session invalidation discards delayed test reply')
  await page.evaluate(() => window.fixture.ttl(200))
  await testKey()
  await page.waitForTimeout(250)
  assert.equal(await save.count(), 0, 'Expired challenge cannot save')
  await page.evaluate(() => window.fixture.oldEngine())
  await card.getByRole('button', { name: 'Refresh Stripe status', exact: true }).click()
  await card.getByText('Update the selected engine to use the Stripe connection.', { exact: true }).waitFor()
  assert.equal(await test.isDisabled(), true)
  assert.deepEqual(errors, [])
  console.log('PASS: Chromium native StripeCard + actual preload bridge: restricted keys, test/confirm/save/disconnect, secret clearing, edit/expiry/generation/company/transport/session invalidation, delayed same-UID reply and old-engine message. Provider/RPC dispatch is a fixture. Artifacts:', output)
} finally { await browser.close(); await new Promise(done => server.close(done)) }
