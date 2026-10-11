import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'

const require = createRequire(import.meta.url)
const ts = require('typescript')
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve() }
let checks = 0
const check = async (name, run) => {
  await run()
  checks++
  console.log(`PASS ${name}`)
}

function load(path, dependencies, globals) {
  const source = readFileSync(resolve(root, path), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX
  }, fileName: path }).outputText
  const exports = {}
  vm.runInNewContext(code, { exports, require: dependencies, ...globals }, { filename: path })
  return exports
}

function fixture() {
  const events = new Map()
  const replies = []
  const pushes = []
  const intervals = new Map()
  const authListeners = new Set()
  const logs = []
  const auth = { currentUser: null }
  let timerId = 0
  let api
  let pushReply = async () => ({ ok: true })
  let mainLogout = async () => ({ ok: true })
  let firebaseLogout = async () => { await emitUser(null) }
  const globals = {
    console: Object.fromEntries(['log', 'warn', 'error', 'debug'].map(level => [level, () => logs.push(level)])),
    setInterval: callback => { const id = ++timerId; intervals.set(id, callback); return id },
    clearInterval: id => intervals.delete(id),
    setTimeout: callback => { queueMicrotask(callback); return ++timerId },
    clearTimeout: () => {},
    window: { get zylch() { return api } }
  }
  const electron = {
    contextBridge: { exposeInMainWorld: (_name, exposed) => { api = exposed } },
    ipcRenderer: {
      on: (channel, callback) => events.set(channel, callback),
      send: (channel, payload) => replies.push({ channel, payload }),
      invoke: async (channel, ...args) => {
        if (channel === 'account:pushToken') { pushes.push(args[0]); return pushReply() }
        if (channel === 'rpc:call' && args[0] === 'account.sign_out') return mainLogout()
        if (channel === 'rpc:call' && args[0] === 'account.who_am_i') {
          return { signed_in: true, uid: auth.currentUser?.uid }
        }
        if (channel === 'auth:bindProfile') return { ok: true, found: true }
        throw new Error('Unexpected fixture bridge call')
      }
    }
  }
  load('src/preload/index.ts', name => {
    assert.equal(name, 'electron'); return electron
  }, globals)
  const firebase = {
    onAuthStateChanged: (_auth, callback) => {
      authListeners.add(callback)
      queueMicrotask(() => { if (authListeners.has(callback)) callback(auth.currentUser) })
      return () => authListeners.delete(callback)
    },
    signOut: async () => firebaseLogout()
  }
  const utils = load('src/renderer/src/firebase/authUtils.ts', name => {
    if (name === 'firebase/auth') return firebase
    if (name === './config') return { auth }
    throw new Error('Unexpected auth dependency')
  }, globals)
  let hooks = [], cursor = 0, pendingEffects = [], dirty = false
  const react = {
    useState: initial => {
      const index = cursor++
      if (!hooks[index]) hooks[index] = { value: initial }
      return [hooks[index].value, value => {
        hooks[index].value = typeof value === 'function' ? value(hooks[index].value) : value
        dirty = true
      }]
    },
    useEffect: (effect, deps) => {
      const index = cursor++
      const prev = hooks[index]
      if (!prev || deps.some((value, i) => !Object.is(value, prev.deps[i]))) {
        hooks[index] = { deps, cleanup: prev?.cleanup }
        pendingEffects.push(() => { hooks[index].cleanup?.(); hooks[index].cleanup = effect() })
      }
    },
    useRef: value => ({ current: value })
  }
  const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }), Fragment: 'fragment' }
  const app = load('src/renderer/src/App.tsx', name => {
    if (name === 'react') return react
    if (name === 'react/jsx-runtime') return jsx
    if (name === 'firebase/auth') return firebase
    if (name === './firebase/config') return { auth }
    if (name === './firebase/authUtils') return utils
    return { default: () => null }
  }, globals)
  let gate
  const render = () => {
    cursor = 0; dirty = false
    gate ||= app.default()
    const tree = gate.type(gate.props)
    const effects = pendingEffects; pendingEffects = []
    for (const effect of effects) effect()
    return tree
  }
  const settleGate = async () => {
    for (let i = 0; i < 10; i++) { await flush(); if (dirty) render() }
  }
  const emitUser = async user => {
    auth.currentUser = user
    for (const callback of [...authListeners]) callback(user)
    await flush()
  }
  const user = (uid = 'synthetic-user') => {
    const state = { requests: 0, forced: [], result: null }
    const identity = {
      uid, email: null, refreshToken: 'synthetic-refresh', isAnonymous: false,
      getIdTokenResult: async force => {
        state.requests++; state.forced.push(force)
        return state.result ? state.result.promise : {
          token: 'synthetic-token', expirationTime: new Date(Date.now() + 3600000).toISOString()
        }
      }
    }
    return { identity, state }
  }
  return {
    auth, app, utils, api, pushes, replies, intervals, authListeners, user, emitUser, render, settleGate,
    refresh: payload => events.get('account:requestTokenRefresh')({}, payload),
    setPushReply: value => { pushReply = value },
    setMainLogout: value => { mainLogout = value },
    setFirebaseLogout: value => { firebaseLogout = value },
    cleanup: () => { for (const hook of hooks) hook?.cleanup?.() }
  }
}

await check('explicit auth invalidation notifies subscribers and revokes the current user until a new session', async () => {
  const f = fixture(); const u = f.user()
  assert.equal(f.utils.isAuthSessionActive(), false)
  f.auth.currentUser = u.identity
  const offAuth = f.utils.setupAuthListener(); await flush()
  assert.equal(f.utils.isAuthSessionActive(), true)
  let notifications = 0
  const offInvalidation = f.utils.onAuthSessionInvalidated(() => {
    notifications++
    assert.equal(f.utils.isAuthSessionActive(), false)
  })
  f.utils.invalidateAuthSession()
  assert.equal(notifications, 1)
  assert.equal(f.auth.currentUser, u.identity)
  assert.equal(f.utils.isAuthSessionActive(), false)
  await f.emitUser(u.identity)
  assert.equal(f.utils.isAuthSessionActive(), false)
  offInvalidation(); offInvalidation()
  f.utils.invalidateAuthSession()
  assert.equal(notifications, 1)
  await f.emitUser(f.user().identity)
  assert.equal(f.utils.isAuthSessionActive(), true)
  offAuth()
})

await check('on-demand refresh forces Firebase once, uses existing push path, and returns metadata only', async () => {
  const f = fixture(); const u = f.user()
  f.auth.currentUser = u.identity
  const off = f.utils.setupAuthListener(); await flush()
  f.utils.setTokenPusher(info => f.api.account.pushToken(info).then(result => { if (!result.ok) throw new Error('Refused') }))
  await f.refresh({ requestId: 1, uid: u.identity.uid })
  assert.equal(u.state.requests, 1); assert.deepEqual(u.state.forced, [true])
  assert.equal(f.pushes.length, 1)
  assert.equal(JSON.stringify(f.replies[0]), JSON.stringify({ channel: 'account:tokenRefreshResult', payload: { requestId: 1, ok: true } }))
  off(); off(); assert.equal(f.intervals.size, 0); assert.equal(f.authListeners.size, 0)
})

await check('wrong UID and invalid refresh payloads never obtain credentials', async () => {
  const f = fixture(); const u = f.user(); f.auth.currentUser = u.identity
  const off = f.utils.setupAuthListener(); await flush()
  f.utils.setTokenPusher(info => f.api.account.pushToken(info))
  for (const payload of [null, {}, { requestId: NaN, uid: u.identity.uid }, { requestId: 1, uid: 9 },
    { requestId: 2, uid: 'another-user' }, { requestId: 3, uid: ' ' }]) await f.refresh(payload)
  assert.equal(u.state.requests, 0); assert.equal(f.pushes.length, 0)
  assert.equal(f.replies.length, 3); assert.ok(f.replies.every(reply => reply.payload.ok === false))
  off()
})

await check('Firebase and bridge rejection acknowledge refresh failure', async () => {
  const f = fixture(); const u = f.user(); f.auth.currentUser = u.identity
  const off = f.utils.setupAuthListener(); await flush()
  f.utils.setTokenPusher(info => f.api.account.pushToken(info).then(result => { if (!result.ok) throw new Error('Refused') }))
  u.state.result = deferred()
  const refreshing = f.refresh({ requestId: 1, uid: u.identity.uid })
  u.state.result.reject(new Error('Synthetic Firebase rejection')); await refreshing
  u.state.result = null; f.setPushReply(async () => ({ ok: false }))
  await f.refresh({ requestId: 2, uid: u.identity.uid })
  assert.ok(f.replies.every(reply => reply.payload.ok === false)); off()
})

await check('preload replacement and repeated unsubscribe preserve only current registration', async () => {
  const f = fixture(); const pending = deferred(); let currentCalls = 0
  const oldOff = f.api.account.onTokenRefreshRequest(() => pending.promise)
  const oldRequest = f.refresh({ requestId: 1, uid: 'synthetic-user' })
  const currentOff = f.api.account.onTokenRefreshRequest(async () => { currentCalls++; return true })
  oldOff(); oldOff(); pending.resolve(true); await oldRequest
  assert.equal(f.replies[0].payload.ok, false)
  await f.refresh({ requestId: 2, uid: 'synthetic-user' }); assert.equal(currentCalls, 1)
  assert.equal(f.replies[1].payload.ok, true)
  currentOff(); currentOff()
  await f.refresh({ requestId: 3, uid: 'synthetic-user' }); assert.equal(currentCalls, 1)
  assert.equal(f.replies[2].payload.ok, false)
})

await check('actual App onboarding pusher retries explicit main refusal', async () => {
  const f = fixture(); f.auth.currentUser = f.user().identity
  let attempts = 0; f.setPushReply(async () => ({ ok: ++attempts >= 3 }))
  assert.equal(await f.app.installEngineTokenPusher(), true); assert.equal(attempts, 3)
  f.setPushReply(async () => ({ ok: false }))
  assert.equal(await f.app.installEngineTokenPusher(), false); assert.equal(f.pushes.length, 6)
})

await check('actual App bind effect pusher retries explicit main refusal', async () => {
  const f = fixture(); f.auth.currentUser = f.user().identity
  let attempts = 0; f.setPushReply(async () => ({ ok: ++attempts >= 3 }))
  f.render(); await f.settleGate()
  assert.equal(attempts, 3)
  f.setPushReply(async () => ({ ok: false }))
  await assert.rejects(f.utils.repushTokenForCurrentUser())
  f.cleanup()
})

for (const uid of ['synthetic-user', 'another-user']) {
  await check(`pending result cannot cross ${uid === 'synthetic-user' ? 'same-UID new user object' : 'account change'}`, async () => {
    const f = fixture(); const old = f.user(); f.auth.currentUser = old.identity
    const off = f.utils.setupAuthListener(); await flush()
    f.utils.setTokenPusher(info => f.api.account.pushToken(info))
    old.state.result = deferred(); const pending = f.utils.repushTokenForCurrentUser().catch(() => false)
    const next = f.user(uid); f.auth.currentUser = next.identity
    old.state.result.resolve({ token: 'synthetic-old-token', expirationTime: new Date(Date.now() + 3600000).toISOString() })
    assert.equal(await pending, false); assert.equal(f.pushes.length, 0)
    await f.emitUser(next.identity); await f.utils.repushTokenForCurrentUser()
    assert.ok(f.pushes.every(info => info.uid === next.identity.uid)); off()
  })
}

await check('actual App offline logout invalidates before main and blocks late refresh despite Firebase failure', async () => {
  const f = fixture(); const old = f.user(); f.auth.currentUser = old.identity
  const off = f.utils.setupAuthListener(); await flush()
  await f.app.installEngineTokenPusher(); f.pushes.length = 0
  old.state.result = deferred()
  const pending = f.utils.repushTokenForCurrentUser().catch(() => false)
  const logoutWait = deferred()
  f.setMainLogout(async () => {
    assert.equal(f.intervals.size, 0)
    await assert.rejects(f.utils.repushTokenForCurrentUser())
    return logoutWait.promise
  })
  f.setFirebaseLogout(async () => { throw new Error('Synthetic offline Firebase logout') })
  const logout = f.app.performSignOut()
  old.state.result.resolve({ token: 'synthetic-late-token', expirationTime: new Date(Date.now() + 3600000).toISOString() })
  assert.equal(await pending, false); assert.equal(f.pushes.length, 0)
  logoutWait.reject(new Error('Synthetic offline main bridge')); await logout
  assert.equal(f.auth.currentUser, old.identity)
  assert.equal(await f.utils.refreshAuthToken(), null)
  await f.refresh({ requestId: 1, uid: old.identity.uid }); assert.equal(f.replies.at(-1).payload.ok, false)
  await f.emitUser(old.identity); await assert.rejects(f.utils.repushTokenForCurrentUser())
  const next = f.user(); await f.emitUser(next.identity)
  assert.equal(await f.app.installEngineTokenPusher(), true)
  assert.equal(f.pushes.length, 1); off()
})

await check('actual App successful logout and same-object relogin rejects old deferred generation', async () => {
  const f = fixture(); const u = f.user(); f.auth.currentUser = u.identity
  const off = f.utils.setupAuthListener(); await flush(); await f.app.installEngineTokenPusher()
  f.pushes.length = 0; u.state.result = deferred()
  const pending = f.utils.refreshAuthToken()
  await f.app.performSignOut(); assert.equal(f.auth.currentUser, null)
  await f.emitUser(u.identity)
  u.state.result.resolve({ token: 'synthetic-late-token', expirationTime: new Date(Date.now() + 3600000).toISOString() })
  assert.equal(await pending, null); assert.equal(f.pushes.length, 0)
  u.state.result = null
  assert.equal(await f.app.installEngineTokenPusher(), true); assert.equal(f.pushes.length, 1); off()
})

await check('expired or malformed Firebase expiry is rejected before credential forwarding', async () => {
  const f = fixture(); const u = f.user(); f.auth.currentUser = u.identity
  const off = f.utils.setupAuthListener(); await flush()
  f.utils.setTokenPusher(info => f.api.account.pushToken(info))
  for (const expirationTime of ['invalid', new Date(Date.now() - 1000).toISOString()]) {
    u.state.result = deferred()
    const pending = f.refresh({ requestId: u.state.requests + 1, uid: u.identity.uid })
    u.state.result.resolve({ token: 'synthetic-token', expirationTime })
    await pending
    assert.equal(f.replies.at(-1).payload.ok, false)
  }
  assert.equal(f.pushes.length, 0); off()
})

await check('proactive interval forwards once and cannot resume after App logout', async () => {
  const f = fixture(); const u = f.user(); f.auth.currentUser = u.identity
  const off = f.utils.setupAuthListener(); await flush(); await f.app.installEngineTokenPusher()
  f.pushes.length = 0
  const tick = [...f.intervals.values()][0]
  await tick(); assert.equal(f.pushes.length, 1)
  f.setFirebaseLogout(async () => { throw new Error('Synthetic Firebase logout failure') })
  await f.app.performSignOut(); await tick()
  assert.equal(f.pushes.length, 1); assert.equal(f.intervals.size, 0); off()
})

await check('listener cleanup discards in-flight refresh and stops interval', async () => {
  const f = fixture(); const u = f.user(); f.auth.currentUser = u.identity
  const off = f.utils.setupAuthListener(); await flush(); await f.app.installEngineTokenPusher()
  f.pushes.length = 0; u.state.result = deferred()
  const pending = f.refresh({ requestId: 1, uid: u.identity.uid })
  off(); off()
  u.state.result.resolve({ token: 'synthetic-late-token', expirationTime: new Date(Date.now() + 3600000).toISOString() })
  await pending; assert.equal(f.pushes.length, 0); assert.equal(f.replies[0].payload.ok, false)
  assert.equal(f.intervals.size, 0)
})

console.log(`Renderer auth recovery: ${checks} behavioral checks passed`)
