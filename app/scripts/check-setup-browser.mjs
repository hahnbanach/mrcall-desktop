// Browser acceptance of the actual Setup component with a synthetic bridge.
// Install Playwright outside the repo; see docs/operator-setup.md.
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { execFileSync } from 'node:child_process'
import { createServer } from 'node:http'
import { readFileSync, mkdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.MRCALL_PLAYWRIGHT_MODULE || 'playwright')
const app = dirname(dirname(fileURLToPath(import.meta.url)))
const output = execFileSync(process.execPath, [join(app, 'scripts/test-setup.mjs')], { cwd: app, encoding: 'utf8' })
const preview = output.match(/preview:\s*(.+)/)?.[1]?.trim()
assert.ok(preview, output)
execFileSync(process.execPath, [join(app, 'node_modules/tailwindcss/lib/cli.js'),
  '-i', join(app, 'src/renderer/src/index.css'), '-o', join(preview, 'style.css')], { cwd: app })
const artifacts = process.env.MRCALL_SETUP_ARTIFACTS || join(preview, 'screenshots')
mkdirSync(artifacts, { recursive: true })
const server = createServer((req, res) => {
  const path = new URL(req.url, 'http://localhost').pathname
  const files = { '/': ['index.html', 'text/html'], '/preview.js': ['preview.js', 'text/javascript'], '/style.css': ['style.css', 'text/css'] }
  if (!files[path]) {res.writeHead(404); res.end(); return}
  res.writeHead(200, { 'content-type': files[path][1] })
  res.end(readFileSync(join(preview, files[path][0])))
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const origin = `http://127.0.0.1:${server.address().port}`
const browser = await chromium.launch({ headless: true,
  ...(process.env.MRCALL_BROWSER_BINARY ? { executablePath: process.env.MRCALL_BROWSER_BINARY } : {}) })
const context = await browser.newContext({ permissions: ['clipboard-read', 'clipboard-write'] })
const errors = []
// No live fonts, Firebase, engine, or model traffic is allowed.
await context.route('**/*', route => route.request().url().startsWith(origin) ? route.continue() : route.abort())
const page = await context.newPage()
page.on('pageerror', error => errors.push(error.message))
async function open(state, width = 1200) {
  await page.setViewportSize({ width, height: 920 })
  await page.goto(`${origin}/?state=${state}`)
  await page.getByRole('heading', { name: 'Your company, ready for your agent.' }).waitFor()
  await page.waitForFunction(() => ![...document.querySelectorAll('button')].some(button => button.textContent === 'Checking…'))
}
try {
  await open('fresh')
  assert.equal(await page.getByRole('button', { name: 'Copy workspace command' }).count(), 0)
  await page.getByRole('button', {name: 'Open settings', exact: true}).click()
  assert.match(await page.locator('#navigation').innerText(), /settings/)
  await page.getByRole('button', {name: 'Connect remote engine', exact: true}).first().click()
  await page.getByText('Connected as production@example.test.', { exact: false }).waitFor()
  assert.ok((await page.evaluate(() => window.setupFixture.calls)).includes('connection.select'))
  await page.screenshot({ path: join(artifacts, 'setup-connected-empty.png'), fullPage: true })

  await open('partial')
  assert.match(await page.locator('body').innerText(), /7 awaiting analysis/)
  assert.equal(await page.getByRole('button', {name: 'Copy workspace command'}).count(), 0)
  await page.screenshot({ path: join(artifacts, 'setup-partial.png'), fullPage: true })

  await open('failed')
  await page.getByRole('alert').waitFor()
  await page.getByRole('button', {name: 'Retry checks'}).click()
  await page.waitForFunction(() => !document.querySelector('[role="alert"]'))

  await open('preparing')
  await page.getByRole('button', {name: 'Connect remote engine', exact: true}).first().click()
  await page.getByRole('status').filter({hasText:'being prepared'}).waitFor()
  assert.ok(!(await page.evaluate(() => window.setupFixture.calls)).includes('provision.start'))
  await page.evaluate(() => window.setupFixture.activate())
  await page.getByRole('button', {name: 'Connect remote engine', exact: true}).last().click()
  await page.getByText('Connected as production@example.test.', {exact: false}).waitFor()

  await open('activate')
  await page.getByRole('button', {name: 'Connect remote engine', exact: true}).first().click()
  await page.getByRole('status').filter({hasText:'being prepared'}).waitFor()
  assert.equal((await page.evaluate(() => window.setupFixture.calls)).filter(name => name === 'provision.start').length, 1)

  await open('wrong-identity')
  await page.getByRole('button', {name: 'Connect remote engine', exact: true}).first().click()
  await page.getByRole('alert').filter({hasText: 'identity could not be verified'}).waitFor()
  assert.ok(!(await page.evaluate(() => window.setupFixture.calls)).includes('connection.select'))

  await open('old-engine')
  await page.getByText('This engine does not yet provide mailbox analysis evidence.', {exact: false}).waitFor()
  assert.equal(await page.getByRole('button', {name: 'Copy workspace command'}).count(), 0)

  await open('byok')
  assert.match(await page.locator('body').innerText(), /AI billing: your Anthropic account/)
  await open('unsigned')
  assert.match(await page.locator('body').innerText(), /Sign in to use MrCall credits/)
  assert.equal(await page.getByRole('button', {name: 'Copy workspace command'}).count(), 0)

  await open('ready')
  assert.match(await page.locator('body').innerText(), /AI billing: MrCall credits/)
  await page.getByRole('button', {name: 'Open kernel installation guide'}).click()
  assert.ok((await page.evaluate(() => window.setupFixture.calls)).includes('https://github.com/hahnbanach/mrcall-desktop/blob/main/docs/operator-setup.md#kernel-macos-or-linux'))
  await page.evaluate(() => {
    window.setupFixture.calls.length = 0
    window.fixtureAlerts = []
    new MutationObserver(() => {
      const alert = document.querySelector('[role="alert"]')
      if (alert) window.fixtureAlerts.push(alert.textContent)
    }).observe(document.body, {childList: true, subtree: true})
  })
  await page.getByRole('button', {name: 'Check connection', exact: true}).click()
  await page.getByRole('status').filter({hasText: 'Connection verified as production@example.test.'}).waitFor()
  assert.deepEqual(await page.evaluate(() => window.setupFixture.calls), ['connection.currentIdentity'])
  assert.deepEqual(await page.evaluate(() => window.fixtureAlerts), [], 'no transient connection error')
  await page.evaluate(() => window.setupFixture.changeIdentity())
  await page.getByRole('button', {name: 'Check connection', exact: true}).click()
  await page.getByRole('alert').filter({hasText: 'identity could not be verified'}).waitFor()
  assert.equal(await page.getByRole('button', {name: 'Copy workspace command'}).count(), 0)
  assert.deepEqual(await page.evaluate(() => window.setupFixture.calls), ['connection.currentIdentity', 'connection.currentIdentity'])

  for (const width of [1200, 390]) {
    await open('ready', width)
    await page.getByRole('button', {name: 'Copy workspace command'}).click()
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), "cs init --descriptor '/tmp/fixture profile/cs-descriptor.json'")
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'no horizontal overflow')
    await page.screenshot({ path: join(artifacts, `setup-ready-${width}.png`), fullPage: true })
  }
  assert.deepEqual(errors, [], 'no unhandled browser exceptions')
  console.log(`Setup browser acceptance passed: readiness, saved billing, non-mutating connection proof, recovery, identity refusal, clipboard, 2 widths. Screenshots: ${artifacts}`)
} finally {
  await browser.close()
  await new Promise(resolve => server.close(resolve))
}
