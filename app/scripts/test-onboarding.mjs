// Onboarding filesystem test.
//
// Drives `createProfileFS` / `isFirstRun` from the compiled Electron
// main bundle. We synthesise a fresh HOME under /tmp and assert:
//   1. isFirstRun() is true when the profiles dir is missing.
//   2. isFirstRun() is true when profiles dir exists but is empty.
//   3. createProfileFS writes the expected .env (keys + quoting).
//   4. Dir perms = 0700, file perms = 0600.
//   5. isFirstRun() flips to false once a profile dir exists.
//   6. A second create on the same email fails.
//   7. Unknown keys are rejected.
//   8. Invalid emails are rejected.
//   9. Missing provider / api-key are rejected.
//
// We do NOT spawn the Electron runtime — we import the compiled module
// directly under Node, overriding `os.homedir` to point at a tmp dir.
// The whole test runs in <1s.

import { mkdirSync, rmSync, existsSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import Module from 'node:module'

const sandboxHome = join(tmpdir(), `zylch_onboarding_test_${Date.now()}`)
rmSync(sandboxHome, { recursive: true, force: true })
mkdirSync(sandboxHome, { recursive: true })

// Monkey-patch os.homedir BEFORE importing the compiled module. Node's
// module cache means only the first require() wins, so this must run
// first. We use the CJS interop path because `out/main` is built as CJS.
const require = Module.createRequire(import.meta.url)
const osModule = require('node:os')
const origHomedir = osModule.homedir
osModule.homedir = () => sandboxHome

// Also monkey-patch spawn so we can assert "no sidecar spawn" during
// onboarding flows. Any invocation of spawn() during this test is a bug.
const cp = require('node:child_process')
const origSpawn = cp.spawn
let spawnCalls = 0
cp.spawn = (...args) => {
  spawnCalls++
  console.error('[test] UNEXPECTED spawn call:', args[0], args[1])
  // Return a harmless object so we don't crash the test host on
  // whatever synchronous access happens next.
  const { EventEmitter } = require('node:events')
  const fake = new EventEmitter()
  fake.stdin = { write: () => {}, end: () => {} }
  fake.stdout = new EventEmitter()
  fake.stdout.setEncoding = () => {}
  fake.stderr = new EventEmitter()
  fake.stderr.setEncoding = () => {}
  fake.kill = () => {}
  return fake
}

// Import the compiled helper. The build puts it at out/main/index.js —
// profileFS is inlined into that bundle, but the bundler also emits
// standalone chunks. We compile a tiny ESM shim on the fly instead of
// relying on compiled paths, by re-exporting from the TS sources via
// esbuild if available. For robustness, we just spawn `tsc` to emit
// the .js files once — or, simpler: since tsc --noEmit is what the
// project's typecheck uses, we emit on demand.

// Build the module using esbuild if installed, else a one-shot tsc.
const esbuild = (() => {
  try { return require('esbuild') } catch { return null }
})()

const outPath = join(sandboxHome, '_compiled_profileFS.cjs')
const srcPath = join(
  '/home/mal/private/zylch-desktop/src/main/profileFS.ts'
)
if (esbuild) {
  esbuild.buildSync({
    entryPoints: [srcPath],
    bundle: true,
    platform: 'node',
    format: 'cjs',
    outfile: outPath,
    target: 'node20'
  })
} else {
  // Fallback: strip the TS types with a regex-level cheat isn't safe.
  // Instead, write a tsc tsconfig.
  const tsconfigPath = join(sandboxHome, 'tsconfig.json')
  writeFileSync(
    tsconfigPath,
    JSON.stringify({
      compilerOptions: {
        target: 'ES2020',
        module: 'CommonJS',
        outDir: sandboxHome,
        strict: false,
        esModuleInterop: true,
        skipLibCheck: true
      },
      include: [srcPath]
    })
  )
  const { execSync } = require('node:child_process')
  execSync(`npx --yes tsc -p ${tsconfigPath}`, {
    cwd: '/home/mal/private/zylch-desktop',
    stdio: 'inherit'
  })
  // tsc will place the compiled file under sandboxHome/.../profileFS.js
  // Find and rename it to outPath.
  const { readdirSync } = require('node:fs')
  const found = []
  function walk(d) {
    for (const n of readdirSync(d)) {
      const p = join(d, n)
      if (statSync(p).isDirectory()) walk(p)
      else if (n === 'profileFS.js') found.push(p)
    }
  }
  walk(sandboxHome)
  if (!found.length) throw new Error('tsc did not produce profileFS.js')
  writeFileSync(outPath, readFileSync(found[0], 'utf8'))
}

const { createProfileFS, isFirstRun, dotenvQuote, KNOWN_KEYS } = require(outPath)

let failures = 0
function assert(cond, msg) {
  if (!cond) {
    failures++
    console.error(`  FAIL: ${msg}`)
  } else {
    console.log(`  ok:   ${msg}`)
  }
}

// 1. isFirstRun true when profiles dir missing
assert(isFirstRun() === true, 'isFirstRun=true when ~/.zylch/profiles is missing')

// 2. isFirstRun true when profiles dir exists but empty
mkdirSync(join(sandboxHome, '.zylch', 'profiles'), { recursive: true, mode: 0o700 })
assert(isFirstRun() === true, 'isFirstRun=true when profiles dir is empty')

// 2b. isFirstRun true when profiles dir has only files (no subdirs)
writeFileSync(join(sandboxHome, '.zylch', 'profiles', 'stray.txt'), 'x')
assert(isFirstRun() === true, 'isFirstRun=true when profiles dir has only files')

// 3. createProfileFS writes expected .env
const email = 'alice@example.com'
const values = {
  SYSTEM_LLM_PROVIDER: 'anthropic',
  ANTHROPIC_API_KEY: 'sk-ant-xxxxxxxx',
  EMAIL_ADDRESS: email,
  EMAIL_PASSWORD: 'app password with spaces',
  IMAP_HOST: 'imap.example.com',
  IMAP_PORT: '993',
  SMTP_HOST: 'smtp.example.com',
  SMTP_PORT: '587',
  USER_FULL_NAME: "Alice O'Brien"
}
let r
try {
  r = createProfileFS(email, values)
  assert(r.ok === true, 'createProfileFS returned ok')
  assert(r.profile === email, `profile=${r.profile}`)
  assert(existsSync(r.path), `env written at ${r.path}`)
} catch (e) {
  assert(false, `createProfileFS threw: ${e.message}`)
  r = null
}

if (r) {
  // 4. Perms
  const dirStat = statSync(join(sandboxHome, '.zylch', 'profiles', email))
  const dirMode = dirStat.mode & 0o777
  assert(dirMode === 0o700, `profile dir mode 0o${dirMode.toString(8)} == 700`)
  const fileStat = statSync(r.path)
  const fileMode = fileStat.mode & 0o777
  assert(fileMode === 0o600, `env file mode 0o${fileMode.toString(8)} == 600`)

  // Content checks
  const content = readFileSync(r.path, 'utf8')
  assert(content.startsWith('# Created by Zylch desktop'), 'header comment present')
  assert(
    content.includes(`SYSTEM_LLM_PROVIDER=anthropic\n`),
    'SYSTEM_LLM_PROVIDER unquoted'
  )
  assert(
    content.includes(`ANTHROPIC_API_KEY=sk-ant-xxxxxxxx\n`),
    'ANTHROPIC_API_KEY unquoted'
  )
  // Space in the password triggers shlex.quote-style quoting.
  assert(
    content.includes(`EMAIL_PASSWORD='app password with spaces'\n`),
    'EMAIL_PASSWORD single-quoted'
  )
  // Apostrophe in name handled via Python-style shlex.quote escape:
  // `'Alice O'"'"'Brien'`.
  const expectedName = `USER_FULL_NAME='Alice O'"'"'Brien'\n`
  assert(
    content.includes(expectedName),
    `USER_FULL_NAME apostrophe shlex-style (got ${JSON.stringify(
      content.split('\n').find((l) => l.startsWith('USER_FULL_NAME'))
    )})`
  )

  // 5. isFirstRun now false
  assert(isFirstRun() === false, 'isFirstRun=false after profile exists')

  // 6. Second create on same email fails
  try {
    createProfileFS(email, values)
    assert(false, 'duplicate profile should throw')
  } catch (e) {
    assert(/already exists/i.test(e.message), `duplicate rejected: ${e.message}`)
  }
}

// 7. Unknown keys rejected
try {
  createProfileFS('bob@example.com', {
    SYSTEM_LLM_PROVIDER: 'anthropic',
    ANTHROPIC_API_KEY: 'k',
    EMAIL_ADDRESS: 'bob@example.com',
    TOTALLY_BOGUS_KEY: 'x'
  })
  assert(false, 'unknown key should throw')
} catch (e) {
  assert(
    /unknown setting keys/i.test(e.message),
    `unknown key rejected: ${e.message}`
  )
}

// 8. Invalid email
try {
  createProfileFS('not-an-email', {
    SYSTEM_LLM_PROVIDER: 'anthropic',
    ANTHROPIC_API_KEY: 'k'
  })
  assert(false, 'invalid email should throw')
} catch (e) {
  assert(/invalid email/i.test(e.message), `invalid email rejected: ${e.message}`)
}

// 9. Missing provider
try {
  createProfileFS('carol@example.com', {
    ANTHROPIC_API_KEY: 'k',
    EMAIL_ADDRESS: 'carol@example.com'
  })
  assert(false, 'missing provider should throw')
} catch (e) {
  assert(/provider/i.test(e.message), `missing provider rejected: ${e.message}`)
}

// 9b. Missing API key for chosen provider
try {
  createProfileFS('dave@example.com', {
    SYSTEM_LLM_PROVIDER: 'anthropic',
    EMAIL_ADDRESS: 'dave@example.com'
  })
  assert(false, 'missing api key should throw')
} catch (e) {
  assert(/api_key/i.test(e.message), `missing api key rejected: ${e.message}`)
}

// Parity check with _quote on a few tricky values
assert(dotenvQuote('') === '', 'empty → empty')
assert(dotenvQuote('plain') === 'plain', 'plain → unquoted')
assert(dotenvQuote('has space') === "'has space'", 'space → quoted')
assert(
  dotenvQuote('a#b') === "'a#b'",
  'hash → quoted'
)
assert(
  dotenvQuote('with\nnewline') === '"with\\nnewline"',
  'newline → double-quoted with \\n escape'
)

// spawn count must be zero
assert(spawnCalls === 0, `no sidecar spawn during onboarding flow (saw ${spawnCalls})`)

// Cleanup spawn patch
cp.spawn = origSpawn
osModule.homedir = origHomedir

console.log('')
if (failures > 0) {
  console.error(`FAIL: ${failures} assertion(s) failed`)
  process.exit(1)
} else {
  console.log('PASS: all assertions passed')
}
