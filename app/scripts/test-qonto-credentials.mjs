import assert from 'node:assert/strict'
import { appendFileSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const os = require('node:os')
const { buildSync } = require('esbuild')
const sandbox = mkdtempSync(join(os.tmpdir(), 'mrcall-qonto-credentials-'))
const oldHome = os.homedir
const oldFetch = globalThis.fetch
os.homedir = () => sandbox

function compile(path, name) {
  const destination = join(sandbox, name + '.cjs')
  buildSync({ entryPoints: [fileURLToPath(new URL(path, import.meta.url))], bundle: true, platform: 'node', format: 'cjs', outfile: destination })
  return require(destination)
}

try {
  const profiles = compile('../src/main/profileFS.ts', 'profiles')
  const provisioning = compile('../src/main/provisionClient.ts', 'provisioning')
  const schema = compile('../src/renderer/src/lib/profileSchema.ts', 'schema')
  assert(!schema.PROFILE_SCHEMA.some(field => field.key.startsWith('QONTO_')))
  profiles.KNOWN_KEYS.add('QONTO_API_LOGIN')
  assert.throws(() => profiles.createProfileForFirebaseUser('fixtureFirebaseUid', 'fixture@example.test', { QONTO_API_LOGIN: 'fixture-login' }), /unknown setting keys/)
  const created = profiles.createProfileForFirebaseUser('fixtureFirebaseUid', 'fixture@example.test', {})
  appendFileSync(created.path, 'QONTO_API_LOGIN=fixture-login\nQONTO_API_KEY=fixture-key\n')
  const original = readFileSync(created.path)
  assert.equal(profiles.readProfileEnvValue('fixtureFirebaseUid', 'QONTO_API_LOGIN'), null)
  assert.deepEqual(profiles.writeProfileEnvValue('fixtureFirebaseUid', 'QONTO_API_KEY', null), { ok: false })
  assert.deepEqual(readFileSync(created.path), original)
  let payload
  globalThis.fetch = async (_url, options) => {
    payload = JSON.parse(options.body)
    return new Response(JSON.stringify({ uid: 'fixtureFirebaseUid', state: 'preparing' }), { status: 200 })
  }
  assert.equal((await provisioning.provisionProfile('fixture-token', {
    EMAIL_ADDRESS: 'fixture@example.test', OWNER_ID: 'fixtureFirebaseUid', MEMORY_KEY: 'fixture-capability',
    QONTO_API_LOGIN: 'fixture-login', QONTO_API_KEY: 'fixture-key',
    QONTO_BOOTSTRAP_ENV_FILE: '/private/source', QONTO_HOST_ID_FILE: '/private/host', qonto_api_key: 'fixture-key'
  })).ok, true)
  assert.deepEqual(payload, { EMAIL_ADDRESS: 'fixture@example.test' })
  console.log('PASS: Qonto credentials excluded from onboarding, readback, edits and provisioning')
} finally {
  os.homedir = oldHome
  globalThis.fetch = oldFetch
  rmSync(sandbox, { recursive: true, force: true })
}
