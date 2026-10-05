import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { EventEmitter } from 'node:events'
import http from 'node:http'
const require = createRequire(import.meta.url), ts = require('typescript')
const { WebSocketServer } = require('ws')
const root = fileURLToPath(new URL('../', import.meta.url))
const load = (path, deps = require, suffix = '', globals = {}) => {
  const code = ts.transpileModule(readFileSync(resolve(root, path), 'utf8') + suffix,
    { compilerOptions: { esModuleInterop: true, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  const exports = {}
  vm.runInNewContext(code, { exports, require: deps, Buffer, AbortController, setTimeout, clearTimeout,
    setInterval, clearInterval, queueMicrotask, console: { log() {}, warn() {}, error() {} },
    process: { ...process, title: '', env: {} }, __dirname: root, ...globals }, { filename: path })
  return exports
}
const auth = load('src/main/windowAuth.ts'), ws = load('src/main/wsRpcClient.ts')
const token = (uid = 'account-A', exp = Date.now() + 3600000, claimedUid = uid) => ({
  uid: claimedUid, email: null,
  idToken: `e30.${Buffer.from(JSON.stringify({ sub: uid, exp: Math.floor(exp / 1000) })).toString('base64url')}.synthetic`,
  expiresAtMs: exp
})
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
let checks = 0
const check = async (name, fn) => { await fn(); checks++; console.log(`PASS ${name}`) }
await check('subject, profile, expiry, and invalid push preserves good cache', () => {
  const cache = new auth.WindowAuthSessions(), good = cache.accept(1, token(), 'account-A')
  assert.ok(good)
  for (const candidate of [token('account-B'), token('account-B', undefined, 'account-A'),
    token('account-A', Date.now() - 1000), { ...token(), idToken: 'malformed' }]) {
    assert.equal(cache.accept(1, candidate, 'account-A'), null); assert.equal(cache.get(1), good)
  }
  assert.equal(cache.get(2), undefined)
})
await check('coalesced refresh, sender correlation and independent windows', async () => {
  const cache = new auth.WindowAuthSessions(), broker = new auth.TokenRefreshRequests()
  let payload, calls = 0
  const refresh = signal => broker.request(1, 'account-A', signal, p => { payload = p; calls++ })
  const a = cache.fresh(1, 'account-A', refresh), b = cache.fresh(1, 'account-A', refresh)
  let done = false; a.then(() => { done = true })
  broker.respond(2, { requestId: payload.requestId, ok: true }); await Promise.resolve(); assert.equal(done, false)
  cache.accept(1, token(), 'account-A'); broker.respond(1, { requestId: payload.requestId, ok: true })
  assert.ok(await a); assert.ok(await b); assert.equal(calls, 1); assert.equal(cache.get(2), undefined)
})
await check('logout cancels requests; bounded timeout and late reply', async () => {
  const cache = new auth.WindowAuthSessions(Date.now, 15), broker = new auth.TokenRefreshRequests()
  let payload
  const request = signal => broker.request(1, 'account-A', signal, p => { payload = p })
  const old = cache.fresh(1, 'account-A', request)
  cache.delete(1); broker.respond(1, { requestId: payload.requestId, ok: true }); assert.equal(await old, null)
  assert.equal(await cache.fresh(1, 'account-A', request), null)
  cache.accept(1, token(), 'account-A'); assert.ok(cache.get(1)); cache.clear(); assert.equal(cache.get(1), undefined)
})
function fixture(options = {}) {
  const handles = new Map(), events = new Map(), windows = new Map(), provisionCalls = []
  let location = 'remote'
  const intervals = new Map(), sent = []
  let sequence = 0, logText = 'synthetic first line\n'
  class Transport extends EventEmitter {
    alive = false; stopped = false; calls = []
    start() {}; isAlive() { return this.alive }; stop() { this.stopped = true }; markIntentionalRestart() {}
    call(...args) { this.calls.push(args); return Promise.resolve({ ok: true }) }
  }
  let nextWindowId = 100
  class Window extends EventEmitter {
    constructor() {
      super(); this.id = ++nextWindowId
      this.webContents = new EventEmitter()
      this.webContents.id = this.id
      this.webContents.setWindowOpenHandler = () => {}
      this.webContents.send = (channel, payload) => sent.push({ channel, payload })
      windows.set(this.id, this)
    }
    static fromWebContents(sender) { return windows.get(sender.id) }
    isDestroyed() { return false }
    loadFile() {}
    show() {}
  }
  const electron = {
    app: { setName() {}, requestSingleInstanceLock: () => true, on() {}, whenReady: () => ({ then() {} }) },
    BrowserWindow: Window,
    ipcMain: { handle: (name, cb) => handles.set(name, cb), on: (name, cb) => events.set(name, cb) }
  }
  const dependencies = name => {
    if (name === 'fs' && options.logs) return {
      existsSync: () => false, statSync: () => ({ size: Buffer.byteLength(logText) }), openSync: () => 1, closeSync() {},
      readSync: (_fd, buffer, offset, length, position) => Buffer.from(logText).copy(buffer, offset, position, position + length)
    }
    if (name === 'electron') return electron
    if (name === './windowAuth') return auth
    if (name === './wsRpcClient') return ws
    if (name === './sidecar') return { StdioRpcClient: Transport }
    if (name === './backendConfig') return { readBackendConfig: () => ({ location }) }
    if (name === './profileFS') return { KNOWN_KEYS: [], readProfileEnvValue: (_uid, key) => key === 'OWNER_ID' ? 'account-A' : null }
    if (name === './csDescriptor') return { writeCsDescriptor() {} }
    if (name === './provisionClient') return {
      provisionProfile: async value => { provisionCalls.push(value); return { ok: true } },
      getProvisionStatus: async value => { provisionCalls.push(value); return { ok: true } }
    }
    if (name.startsWith('./')) return {}
    return require(name)
  }
  const main = load('src/main/index.ts', dependencies,
    '\nexports.fixture = { registerIpc, windowEntries, windowTokens, freshWindowToken, startLogTailer, detachWindowSession, makeStdioClient, createAuthPendingWindow };',
    options.logs ? { setInterval: callback => { const id = ++sequence; intervals.set(id, callback); return id },
      clearInterval: id => intervals.delete(id) } : {}).fixture
  main.registerIpc()
  const makeWindow = (id, profile = 'account-A') => {
    const sidecar = new Transport()
    const window = { id, isDestroyed: () => false, webContents: { id, send: (channel, payload) => {
      sent.push({ channel, payload })
      if (channel === 'account:requestTokenRefresh') queueMicrotask(async () => {
        const reply = await handles.get('account:pushToken')({ sender: { id } }, token(profile))
        events.get('account:tokenRefreshResult')({ sender: { id } }, { requestId: payload.requestId, ok: reply.ok })
      })
    } } }
    windows.set(id, window); main.windowEntries.set(id, { window, profile, sidecar })
    return { window, sidecar, event: { sender: { id } } }
  }
  return { main, handles, makeWindow, provisionCalls, intervals, sent, appendLog: value => { logText += value }, setLocation: value => { location = value } }
}
await check('actual offline logout detaches; same-UID relogin uses a new transport', async () => {
  const f = fixture(), old = f.makeWindow(1)
  assert.equal((await f.handles.get('account:pushToken')(old.event, token())).ok, true)
  assert.equal((await f.handles.get('rpc:call')(old.event, 'account.sign_out', {})).ok, true)
  assert.equal(old.sidecar.stopped, true); assert.equal(old.sidecar.calls.length, 0)
  assert.equal(f.main.windowEntries.has(1), false); assert.equal(f.main.windowTokens.get(1), undefined)
  const next = f.makeWindow(1); assert.notEqual(next.sidecar, old.sidecar)
  assert.ok(await f.main.freshWindowToken(next.window, 'account-A'))
})
await check('actual push rejects another UID; provisioning refreshes per bound window', async () => {
  const f = fixture(), a = f.makeWindow(1), b = f.makeWindow(2, 'account-B')
  assert.equal((await f.handles.get('account:pushToken')(a.event, token('account-B'))).ok, false)
  assert.equal((await f.handles.get('provision:start')(a.event)).ok, true)
  assert.equal((await f.handles.get('provision:status')(b.event)).ok, true)
  assert.equal(f.provisionCalls.length, 2)
  assert.equal(f.main.windowTokens.get(1).uid, 'account-A'); assert.equal(f.main.windowTokens.get(2).uid, 'account-B')
})
await check('bounded online logout stops only captured old transport', async () => {
  const f = fixture(), old = f.makeWindow(1), wait = deferred()
  old.sidecar.alive = true; old.sidecar.call = () => wait.promise
  const logout = f.handles.get('rpc:call')(old.event, 'account.sign_out', {})
  const next = f.makeWindow(1); wait.resolve({ ok: true }); await logout
  assert.equal(old.sidecar.stopped, true); assert.equal(next.sidecar.stopped, false)
  const stuck = f.makeWindow(3); stuck.sidecar.alive = true; stuck.sidecar.call = () => new Promise(() => {})
  await auth.retireAuthTransport(stuck.sidecar, 10); assert.equal(stuck.sidecar.stopped, true)
})
await check('local forward matches bound UID; old completion cannot write a new session', async () => {
  const f = fixture(), a = f.makeWindow(1), wait = deferred()
  f.setLocation('local'); a.sidecar.alive = true
  a.sidecar.call = (...args) => { a.sidecar.calls.push(args); return wait.promise }
  const pushing = f.handles.get('account:pushToken')(a.event, token())
  assert.equal(a.sidecar.calls.length, 1)
  assert.equal(a.sidecar.calls[0][0], 'account.set_firebase_token')
  assert.equal(a.sidecar.calls[0][1].uid, 'account-A')
  f.main.windowTokens.delete(1); f.makeWindow(1, 'account-B')
  wait.resolve({ ok: true }); assert.equal((await pushing).ok, false)
  assert.equal(f.main.windowTokens.get(1), undefined)
})
await check('near-expiry cache requires refresh; advertised expiry cannot extend JWT', async () => {
  let now = Date.now()
  const cache = new auth.WindowAuthSessions(() => now)
  const original = token('account-A', now + 60_000)
  const stored = cache.accept(1, { ...original, expiresAtMs: now + 3600000 }, 'account-A')
  assert.ok(stored.expiresAtMs <= now + 60000)
  now += 31_000; assert.equal(cache.get(1), undefined)
  let refreshes = 0
  const fresh = await cache.fresh(1, 'account-A', async () => {
    refreshes++; cache.accept(1, token('account-A', now + 3600000), 'account-A'); return true
  })
  assert.ok(fresh); assert.equal(refreshes, 1)
})
await check('actual restart continuation cannot resurrect logout, replace rebind, or revive a closed window', async () => {
  for (const scenario of ['logout', 'rebind', 'closed']) {
    const f = fixture(), old = f.makeWindow(1)
    const restarting = f.handles.get('sidecar:restart')(old.event)
    assert.equal(old.sidecar.stopped, true)
    let next
    if (scenario === 'logout') await f.handles.get('rpc:call')(old.event, 'account.sign_out', {})
    if (scenario === 'rebind') next = f.makeWindow(1, 'account-B')
    if (scenario === 'closed') old.window.isDestroyed = () => true
    const result = await restarting
    assert.equal(result.ok, false)
    if (scenario === 'logout') assert.equal(f.main.windowEntries.has(1), false)
    if (scenario === 'rebind') {
      assert.equal(f.main.windowEntries.get(1).sidecar, next.sidecar)
      assert.equal(next.sidecar.stopped, false)
    }
    if (scenario === 'closed') assert.equal(f.main.windowEntries.get(1).sidecar, old.sidecar)
  }
})
await check('logout clears tailer/scrollback; relogin and close leave no old polling', async () => {
  const f = fixture({ logs: true }), old = f.makeWindow(1)
  f.main.startLogTailer(1, 'account-A', old.window)
  assert.equal(f.intervals.size, 1)
  assert.equal((await f.handles.get('logs:tail')(old.event)).length, 1)
  const oldPoll = [...f.intervals.values()][0]
  await f.handles.get('rpc:call')(old.event, 'account.sign_out', {})
  assert.equal(f.intervals.size, 0); assert.equal((await f.handles.get('logs:tail')(old.event)).length, 0)
  f.appendLog('synthetic late line\n'); oldPoll()
  assert.equal(f.sent.filter(e => e.channel === 'logs:line').length, 0)
  const next = f.makeWindow(1)
  f.main.startLogTailer(1, 'account-A', next.window); assert.equal(f.intervals.size, 1)
  f.main.startLogTailer(1, 'account-B', next.window); assert.equal(f.intervals.size, 1)
  f.main.detachWindowSession(1); next.sidecar.stop()
  assert.equal(f.intervals.size, 0); oldPoll()
  const actualWindow = f.main.createAuthPendingWindow(undefined, 'synthetic-partition')
  const transport = f.main.makeStdioClient('account-A', actualWindow)
  f.main.windowEntries.set(actualWindow.id, { profile: 'account-A', window: actualWindow, sidecar: transport })
  f.main.startLogTailer(actualWindow.id, 'account-A', actualWindow)
  assert.equal(f.intervals.size, 1)
  actualWindow.emit('closed')
  assert.equal(f.intervals.size, 0); assert.equal(transport.stopped, true)
  assert.equal(f.main.windowEntries.has(actualWindow.id), false)
  assert.equal((await f.handles.get('logs:tail')(next.event)).length, 0)
})
await check('retired local transport cannot send late stderr, readiness or notifications', async () => {
  const f = fixture(), old = f.makeWindow(1)
  const transport = f.main.makeStdioClient('account-A', old.window)
  f.main.windowEntries.set(1, { profile: 'account-A', window: old.window, sidecar: transport })
  transport.emit('stderr', 'synthetic before logout\n')
  assert.equal((await f.handles.get('logs:tail')(old.event)).length, 1)
  await f.handles.get('rpc:call')(old.event, 'account.sign_out', {})
  const next = f.makeWindow(1, 'account-B'), before = f.sent.length
  transport.emit('stderr', 'synthetic late metadata\n')
  transport.emit('notification', { method: 'engine.ready' })
  transport.emit('notification', { method: 'synthetic.event' })
  transport.emit('exit', { code: 0 })
  assert.equal(f.sent.length, before)
  assert.equal((await f.handles.get('logs:tail')(next.event)).length, 0)
})
await check('actual Test connection: rejected handshake then fresh successful connection', async () => {
  const server = http.createServer(), wss = new WebSocketServer({ noServer: true })
  let reject = true, attempts = 0
  server.on('upgrade', (req, socket, head) => {
    attempts++
    if (reject) { socket.end('HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n'); return }
    wss.handleUpgrade(req, socket, head, peer => peer.on('message', data => {
      const message = JSON.parse(data.toString())
      peer.send(JSON.stringify({ jsonrpc: '2.0', id: message.id, result: { signed_in: true, uid: 'account-A' } }))
    }))
  })
  await new Promise(r => server.listen(0, '127.0.0.1', r))
  const f = fixture(), a = f.makeWindow(1), url = `ws://127.0.0.1:${server.address().port}`
  try {
    const failed = await f.handles.get('backend:testConnection')(a.event, url)
    assert.equal(failed.ok, false); assert.equal(failed.code, 'ws_unauthorized')
    f.main.windowTokens.delete(1); reject = false
    const success = await f.handles.get('backend:testConnection')(a.event, url)
    assert.equal(success.ok, true); assert.equal(success.uid, 'account-A'); assert.equal(attempts, 2)
  } finally {
    for (const peer of wss.clients) peer.terminate()
    await new Promise(r => wss.close(r)); await new Promise(r => server.close(r))
  }
})
console.log(`Main auth recovery: ${checks} behavioral checks passed`)
