// Standalone node test that exercises the same JSON-RPC protocol the
// Electron main process uses. Run headless to verify Phase 3a without X.
import { spawn } from 'node:child_process'

const proc = spawn(
  '/home/mal/private/zylch-standalone/venv/bin/zylch',
  ['-p', 'mario.alemi@cafe124.it', 'rpc'],
  { cwd: '/home/mal/private/zylch-standalone', stdio: ['pipe', 'pipe', 'pipe'] }
)

let buf = ''
let nextId = 1
const pending = new Map()
const notifications = []

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
      notifications.push(msg)
      console.log(`[notify] ${msg.method}:`, JSON.stringify(msg.params).slice(0, 120))
    }
  }
})
proc.stderr.on('data', (c) => process.stderr.write('[stderr] ' + c))

const call = (method, params = {}) => new Promise((resolve, reject) => {
  const id = nextId++
  pending.set(id, { resolve, reject })
  proc.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n')
  setTimeout(() => { if (pending.has(id)) { pending.delete(id); reject(new Error('timeout ' + method)) } }, 120000)
})

const run = async () => {
  console.log('=== 1. tasks.list ===')
  const tasks = await call('tasks.list', {})
  console.log(`got ${tasks.length} tasks`)
  for (const t of tasks.slice(0, 3)) {
    console.log(`  - [${t.urgency}] ${t.contact_email}: ${t.suggested_action.slice(0, 80)}`)
  }
  if (tasks.length === 0) { console.log('no tasks to test skip/complete'); return }

  const toSkip = tasks[tasks.length - 1].id
  console.log(`\n=== 2. tasks.skip ${toSkip} ===`)
  console.log(await call('tasks.skip', { task_id: toSkip }))

  console.log('\n=== 3. verify skip via include_skipped ===')
  const afterSkip = await call('tasks.list', { include_skipped: true })
  const skipped = afterSkip.find((t) => t.id === toSkip)
  console.log(`task in list: ${!!skipped}  sources.skipped_at=${skipped?.sources?.skipped_at ?? '(not set directly; checked via filter)'}`)
  const visibleAfter = await call('tasks.list', {})
  console.log(`visible tasks now: ${visibleAfter.length} (was ${tasks.length})`)

  if (tasks.length >= 2) {
    const toComplete = tasks[tasks.length - 2].id
    console.log(`\n=== 4. tasks.complete ${toComplete} ===`)
    console.log(await call('tasks.complete', { task_id: toComplete }))
  }

  console.log('\n=== 5. chat.send ===')
  const chatRes = await call('chat.send', { message: 'quante task ho oggi?', conversation_history: [] })
  console.log('chat keys:', Object.keys(chatRes))
  const text = chatRes.response || chatRes.message || chatRes.content || JSON.stringify(chatRes).slice(0, 200)
  console.log('reply:', String(text).slice(0, 300))

  // sync.run would actually hit IMAP — skip in headless test to avoid slow network
  console.log('\n(skipping sync.run — makes live IMAP calls, too slow for headless smoke test)')
}

run()
  .then(() => { console.log('\nOK'); proc.kill('SIGTERM'); process.exit(0) })
  .catch((e) => { console.error('FAIL:', e); proc.kill('SIGTERM'); process.exit(1) })
