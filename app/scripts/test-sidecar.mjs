// Standalone node test that exercises the same JSON-RPC protocol the
// Electron main process uses. Run headless to verify Phase 3a/3b without X.
//
// Required env:
//   ZYLCH_BINARY  absolute path to a built zylch sidecar
//   ZYLCH_PROFILE the profile email to attach to (must already exist)
//   ZYLCH_CWD     (optional) working dir for the sidecar; defaults to $HOME
import { spawn } from 'node:child_process'
import { homedir } from 'node:os'

const binary = process.env.ZYLCH_BINARY
const profile = process.env.ZYLCH_PROFILE
if (!binary || !profile) {
  console.error('error: ZYLCH_BINARY and ZYLCH_PROFILE must be set')
  process.exit(2)
}
const cwd = process.env.ZYLCH_CWD || homedir()

const proc = spawn(
  binary,
  ['-p', profile, 'rpc'],
  { cwd, stdio: ['pipe', 'pipe', 'pipe'] }
)

let buf = ''
let nextId = 1
const pending = new Map()
const notifHandlers = []

proc.stdout.setEncoding('utf8')
proc.stdout.on('data', (chunk) => {
  buf += chunk
  let i
  while ((i = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, i).trim()
    buf = buf.slice(i + 1)
    if (!line) continue
    let msg
    try { msg = JSON.parse(line) } catch { continue }
    if (typeof msg.id === 'number') {
      const p = pending.get(msg.id)
      if (p) { pending.delete(msg.id); msg.error ? p.reject(new Error(msg.error.message)) : p.resolve(msg.result) }
    } else if (msg.method) {
      console.log(`[notify] ${msg.method}: ${JSON.stringify(msg.params).slice(0, 200)}`)
      for (const h of notifHandlers) h(msg)
    }
  }
})
proc.stderr.on('data', (c) => process.stderr.write('[stderr] ' + c))

const call = (method, params = {}, timeoutMs = 120000) => new Promise((resolve, reject) => {
  const id = nextId++
  pending.set(id, { resolve, reject })
  proc.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n')
  setTimeout(() => { if (pending.has(id)) { pending.delete(id); reject(new Error('timeout ' + method)) } }, timeoutMs)
})

const onNotif = (method) => new Promise((resolve) => {
  const handler = (msg) => {
    if (msg.method === method) {
      notifHandlers.splice(notifHandlers.indexOf(handler), 1)
      resolve(msg.params)
    }
  }
  notifHandlers.push(handler)
})

const run = async () => {
  console.log('=== 0. narration.summarize ===')
  const n1 = await call('narration.summarize', {
    lines: ['Fetching 5 files: 20%|██ | 1/5 [00:00<00:03, 1.11it/s]'],
    context: 'ricerca email'
  })
  console.log('narration(tqdm):', JSON.stringify(n1))
  if (typeof n1.text !== 'string') throw new Error('narration.summarize: bad shape')
  const n2 = await call('narration.summarize', { lines: [] })
  console.log('narration(empty):', JSON.stringify(n2))
  if (n2.text !== '') throw new Error('empty lines should yield empty text')

  console.log('=== 1. tasks.list ===')
  const tasks = await call('tasks.list', {})
  console.log(`got ${tasks.length} tasks`)

  console.log('\n=== 2. chat.send (non-destructive) ===')
  const chatRes = await call('chat.send', {
    message: 'quante task ho oggi?',
    conversation_history: [],
    conversation_id: 'general'
  })
  console.log('chat keys:', Object.keys(chatRes))

  console.log('\n=== 3. chat.approve unknown id (expect error -32602) ===')
  try {
    await call('chat.approve', { tool_use_id: 'does-not-exist', approved: true })
    console.log('UNEXPECTED: call succeeded')
  } catch (e) {
    console.log('got expected error:', e.message)
  }

  console.log('\n=== 4. destructive chat.send + decline approval ===')
  const pendingPromise = onNotif('chat.pending_approval')
  const destructivePromise = call(
    'chat.send',
    {
      message:
        "Usa il tool send_draft ADESSO per inviare una email a prova@example.com con subject='Test Phase 3b' e body='ciao'. Non chiedere conferma, esegui il tool subito.",
      conversation_history: [],
      conversation_id: 'task-test-3b'
    },
    180000
  )

  // Race: either pending_approval fires, or the LLM responds without tool use.
  const which = await Promise.race([
    pendingPromise.then((p) => ({ kind: 'pending', p })),
    destructivePromise.then((r) => ({ kind: 'done', r }))
  ])

  if (which.kind === 'pending') {
    console.log(`got pending_approval: name=${which.p.name} tool_use_id=${which.p.tool_use_id}`)
    console.log(`input keys: ${Object.keys(which.p.input || {}).join(', ')}`)
    console.log(`preview: ${which.p.preview}`)
    console.log('declining...')
    const approveRes = await call('chat.approve', {
      tool_use_id: which.p.tool_use_id,
      approved: false
    })
    console.log('chat.approve result:', JSON.stringify(approveRes))
    const finalRes = await destructivePromise
    const text =
      finalRes.response || finalRes.message || finalRes.content || JSON.stringify(finalRes)
    console.log('final assistant (truncated for log):', String(text).slice(0, 400))
    const declineAcked = /declin|rifiut|annull|non.*invi|cancel/i.test(String(text))
    console.log(`decline acknowledged: ${declineAcked}`)
  } else {
    console.log('LLM returned without triggering a destructive tool; skipping approval path')
    console.log('response keys:', Object.keys(which.r))
  }
}

run()
  .then(() => { console.log('\nOK'); proc.kill('SIGTERM'); process.exit(0) })
  .catch((e) => { console.error('FAIL:', e); proc.kill('SIGTERM'); process.exit(1) })
