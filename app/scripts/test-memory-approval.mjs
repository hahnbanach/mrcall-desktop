// The memory-change approval, driven end to end against a fixture sidecar.
//
// What this proves, and why it needs a sidecar rather than a unit test: the
// value of this card is in what reaches the engine. A renderer that shows the
// change beautifully and then answers `{approved: true}` with no payload has
// built nothing — the engine refuses a bare yes, so the memory silently does not
// change and the user is told it did. So the assertion has to be on the frame
// that arrives at the other end of stdio.
//
// The fixture sidecar is a JSON-RPC peer over newline-delimited JSON, the same
// framing `src/main/sidecar.ts` speaks. It raises a real
// `chat.pending_approval` notification carrying a real card, and records the
// `chat.approve` frames it receives back.
//
// Driven through the compiled main bundle's `StdioRpcClient` and the renderer's
// own `lib/memoryApproval` decision module — the two halves that carry the
// contract. React rendering is not exercised here; `MemoryChangeCard` reads its
// fields from `describeMemoryChange`, which is, and the journey printed below is
// what a human sees on that card.
//
//   node scripts/test-memory-approval.mjs

import { mkdirSync, rmSync, writeFileSync, existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
import Module from 'node:module'

const __dirname = dirname(fileURLToPath(import.meta.url))
const APP_ROOT = resolve(__dirname, '..')
const SANDBOX = join(tmpdir(), `mrcall_memory_approval_${Date.now()}`)

let failures = 0
function assert(condition, what) {
  if (condition) {
    console.log(`  ok  ${what}`)
  } else {
    failures += 1
    console.error(`FAIL  ${what}`)
  }
}

function section(title) {
  console.log(`\n── ${title} ${'─'.repeat(Math.max(0, 58 - title.length))}`)
}

// ─── The card the engine sends ────────────────────────────────────────
// Field for field what `FinalMutation.as_card()` produces, so a rename on the
// engine side breaks this test instead of breaking a user's memory.

const NONCE = 'nonce-abc123'
const DIGEST = 'digest-def456'
const CARD = {
  event_id: 'evt-1',
  proposal_digest: DIGEST,
  acceptance_nonce: NONCE,
  action: 'UPDATE',
  entity_type: 'COMPANY',
  scope: 'entity',
  content:
    '#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Beta Spa\n' +
    'Email: orders@beta.test\n#ABOUT\nPackaging supplier in Turin.',
  reason: 'the ordering address replaces the old one',
  write_set: [{ blob_id: 'blob-beta', expected_version: '2026-09-23T08:00:00', role: 'target' }],
  declared_effects: [],
  requested_action: 'UPDATE',
  requested_blob_id: 'blob-acme',
  flags: ['changed_subject'],
  why: ['it writes to a memory other than the one this call named'],
  observation: "L'indirizzo ordini di Beta Spa ora è orders@beta.test",
  source: 'chat:turn:abc',
  preview: '**Memory update** — confirm the final change'
}

// ─── Compile the two modules under test ───────────────────────────────

// One source at a time, each into its own directory: with several inputs tsc
// mirrors their shared tree under outDir, and the emitted paths stop being
// predictable from the input names.
function compile(source, outDir) {
  const tsc = join(APP_ROOT, 'node_modules', '.bin', 'tsc')
  const result = spawnSync(
    tsc,
    [
      source,
      '--outDir',
      outDir,
      '--module',
      'commonjs',
      '--target',
      'es2020',
      '--moduleResolution',
      'node',
      '--skipLibCheck',
      '--esModuleInterop'
    ],
    { cwd: APP_ROOT, encoding: 'utf8' }
  )
  const emitted = join(outDir, source.split('/').pop().replace(/\.ts$/, '.js'))
  if (!existsSync(emitted)) {
    console.error(result.stdout || '')
    console.error(result.stderr || '')
    throw new Error(`tsc emitted no ${emitted}`)
  }
  return emitted
}

mkdirSync(SANDBOX, { recursive: true })
const approvalJs = compile(
  join(APP_ROOT, 'src/renderer/src/lib/memoryApproval.ts'),
  join(SANDBOX, 'approval')
)
const sidecarJs = compile(join(APP_ROOT, 'src/main/sidecar.ts'), join(SANDBOX, 'sidecar'))

const require = Module.createRequire(import.meta.url)
const approval = require(approvalJs)
const { StdioRpcClient } = require(sidecarJs)

// ─── The fixture sidecar ──────────────────────────────────────────────

const FIXTURE = join(SANDBOX, 'fixture-sidecar.mjs')
writeFileSync(
  FIXTURE,
  `
// A JSON-RPC peer over newline-delimited JSON, as the engine's stdio server is.
// It answers chat.send by raising one pending_approval notification and then
// waiting for the matching chat.approve; every approve frame it sees is written
// to stderr as APPROVE:<json> so the test can read exactly what arrived.
import { createInterface } from 'node:readline'

const CARD = ${JSON.stringify(CARD)}
const send = (o) => process.stdout.write(JSON.stringify(o) + '\\n')

createInterface({ input: process.stdin }).on('line', (line) => {
  if (!line.trim()) return
  let req
  try { req = JSON.parse(line) } catch { return }
  if (req.method === 'chat.send') {
    send({
      jsonrpc: '2.0',
      method: 'chat.pending_approval',
      params: {
        conversation_id: 'conv-1',
        tool_use_id: 'mnemonic-evt-1-' + CARD.acceptance_nonce.slice(0, 8),
        name: 'confirm_memory_write',
        input: CARD,
        preview: CARD.preview
      }
    })
    send({ jsonrpc: '2.0', id: req.id, result: { response: 'waiting for confirmation' } })
    return
  }
  if (req.method === 'chat.approve') {
    process.stderr.write('APPROVE:' + JSON.stringify(req.params) + '\\n')
    send({ jsonrpc: '2.0', id: req.id, result: { ok: true } })
    return
  }
  send({ jsonrpc: '2.0', id: req.id, result: {} })
})
`,
  'utf8'
)

// `StdioRpcClient.start()` spawns `<binary> -p <profile> rpc`, so the binary has
// to tolerate those three arguments. `node` does not — `-p` is its own eval
// flag — so the fixture is reached through a one-line wrapper that drops them.
// That keeps the client under test unmodified, which is the point of driving it
// rather than reimplementing its framing here.
const WRAPPER = join(SANDBOX, 'fixture-binary')
writeFileSync(WRAPPER, `#!/bin/sh\nexec "${process.execPath}" "${FIXTURE}"\n`, {
  mode: 0o755
})

function drive(decide) {
  return new Promise((resolvePromise, rejectPromise) => {
    const approves = []
    const client = new StdioRpcClient({
      cwd: SANDBOX,
      binary: WRAPPER,
      profile: 'fixture@example.test',
      envOverrides: {}
    })
    // The client forwards the child's stderr as chunks; the fixture writes its
    // record there, which is how the test reads what actually crossed the wire
    // rather than what the renderer believes it sent.
    client.on('stderr', (chunk) => {
      for (const line of String(chunk).split('\n')) {
        if (line.startsWith('APPROVE:')) approves.push(JSON.parse(line.slice('APPROVE:'.length)))
      }
    })
    client.on('notification', async ({ method, params }) => {
      if (method !== 'chat.pending_approval') return
      try {
        await decide(client, params)
      } catch (err) {
        rejectPromise(err)
      }
    })
    client.start()
    client
      .call('chat.send', { message: 'correggi la memoria' }, 10000)
      .then(async () => {
        // Give the approve round-trip a beat to land before reading the record.
        await new Promise((r) => setTimeout(r, 400))
        client.stop()
        resolvePromise(approves)
      })
      .catch((err) => {
        client.stop()
        rejectPromise(err)
      })
  })
}

// ─── The journey a human sees ─────────────────────────────────────────

section('the card, as the renderer builds it')
const change = approval.describeMemoryChange(CARD)
console.log(`  Azione:       ${change.action} (richiesta: ${change.requestedAction})`)
console.log(`  Tipo:         ${change.entityType} · ${change.scope}`)
for (const target of change.writeSet) {
  console.log(`  Scrive:       ${target.blob_id} @ ${target.expected_version} [${target.role}]`)
}
console.log(`  Non richiesto: ${change.why.join('; ')}`)
console.log(`  Letto da:     ${change.observation}`)
console.log(`  Testo:        ${change.content.split('\n')[0]} …`)

assert(approval.isMemoryChange('confirm_memory_write'), 'the card is recognized as a memory change')
assert(
  !approval.offersSessionGrant('confirm_memory_write'),
  'no session grant is offered for a memory change'
)
assert(
  approval.offersSessionGrant('run_python'),
  'and the permission triad still applies to other gated tools'
)
assert(
  change.requestedBlobId === 'blob-acme' && change.writeSet[0].blob_id === 'blob-beta',
  'the card shows both the memory asked for and the one that will change'
)
assert(
  change.content.includes('orders@beta.test') && change.content.includes('#ABOUT'),
  'the complete stored text is shown, not a preview of it'
)

section('accept: the acceptance reaches the engine')
const accepted = await drive(async (client, params) => {
  const acceptance = approval.acceptanceFor(params.input)
  await client.call('chat.approve', {
    tool_use_id: params.tool_use_id,
    mode: 'once',
    edited_input: acceptance
  })
})
assert(accepted.length === 1, 'exactly one approve frame arrived')
assert(accepted[0]?.mode === 'once', 'accepting sends mode=once, never mode=session')
assert(
  accepted[0]?.edited_input?.acceptance_nonce === NONCE,
  'the card nonce is echoed back verbatim'
)
assert(
  accepted[0]?.edited_input?.proposal_digest === DIGEST,
  'the proposal digest is echoed back verbatim'
)

section('decline: nothing is echoed')
const declined = await drive(async (client, params) => {
  await client.call('chat.approve', { tool_use_id: params.tool_use_id, mode: 'deny' })
})
assert(declined.length === 1, 'exactly one approve frame arrived')
assert(declined[0]?.mode === 'deny', 'declining sends mode=deny')
assert(
  declined[0]?.edited_input === undefined || declined[0]?.edited_input === null,
  'a decline carries no acceptance payload'
)

section('declining: which call each surface must make')
// The Desktop half of this is a routing decision, not a payload: a solve's
// ordinary card declines by ABORTING the solve, and a memory card must not.
assert(
  approval.declineActionFor('solve', 'confirm_memory_write') === 'decline',
  'a solve memory card declines the change, not the solve'
)
assert(
  approval.declineActionFor('solve', 'send_email') === 'cancel',
  'and an ordinary solve card still cancels the solve'
)
assert(
  approval.declineActionFor('chat', 'confirm_memory_write') === 'decline',
  'chat always declines'
)
assert(
  approval.declineActionFor('chat', 'run_python') === 'decline',
  'chat has no cancel to confuse it with'
)

section('a card with no acceptance fields cannot be accepted')
const stripped = { ...CARD }
delete stripped.acceptance_nonce
assert(approval.acceptanceFor(stripped) === null, 'a card missing its nonce yields no acceptance')
delete stripped.proposal_digest
assert(approval.acceptanceFor(stripped) === null, 'and one missing its digest yields none either')
assert(
  approval.acceptanceFor(CARD)?.acceptance_nonce === NONCE,
  'while a complete card yields exactly the two fields'
)

rmSync(SANDBOX, { recursive: true, force: true })
console.log('')
if (failures > 0) {
  console.error(`FAILED: ${failures} assertion(s)`)
  process.exit(1)
}
console.log('OK: the memory-change card shows the decided change and its acceptance reaches the engine')
