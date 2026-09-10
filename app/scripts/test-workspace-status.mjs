// Real filesystem descriptor handoff, without Electron, a profile, or a network.
import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { execFileSync } from 'node:child_process'
const require = createRequire(import.meta.url)
const { buildSync } = require('esbuild')
const root = dirname(dirname(fileURLToPath(import.meta.url)))
const temp = mkdtempSync(join(tmpdir(), 'mrcall-workspace-status-'))
try {
  const modulePath = join(temp, 'workspace.cjs')
  buildSync({ entryPoints: [join(root, 'src/main/workspaceStatus.ts')], bundle: true,
    platform: 'node', format: 'cjs', outfile: modulePath })
  const { readWorkspaceStatus, workspaceCommand } = require(modulePath)
  const uid = 'test-owner'
  const url = 'wss://engine.example.test/ws/test-owner'
  const path = join(temp, "Owner's workspace descriptor.json")
  assert.equal(readWorkspaceStatus(uid, url, path).available, false)
  writeFileSync(path, 'not-json')
  assert.equal(readWorkspaceStatus(uid, url, path).available, false)
  const descriptor = { version: 1, uid, email: 'owner@example.test', engine_ws_url: url,
    firebase_web_api_key: 'public-test-key', refresh_token: 'secret-test-refresh',
    MEMORY_KEY: 'secret-test-memory', unexpected: 'must-not-escape' }
  const write = (overrides = {}) => writeFileSync(path, JSON.stringify({ ...descriptor, ...overrides }))
  write()
  const result = readWorkspaceStatus(uid, url, path, 'linux')
  assert.equal(result.available, true)
  assert.deepEqual(Object.keys(result).sort(),
    ['available', 'uid', 'email', 'engineWsUrl', 'descriptorPath', 'command'].sort())
  assert.equal(result.email, descriptor.email)
  for (const secret of ['secret-test-refresh', 'secret-test-memory', 'public-test-key', 'must-not-escape']) {
    assert.ok(!JSON.stringify(result).includes(secret))
  }
  // Have a real POSIX shell parse the quoted command into argv, never run cs.
  const argumentScript = 'cs() { printf "%s\\n" "$@"; }; ' + result.command
  assert.equal(execFileSync('/bin/sh', ['-c', argumentScript], { encoding: 'utf8' }),
    `init\n--descriptor\n${path}\n`)
  const winPath = "C:\\Users\\O'Brien\\workspace access.json"
  assert.equal(workspaceCommand(winPath, 'win32'),
    "cs init --descriptor 'C:\\Users\\O''Brien\\workspace access.json'")
  for (const invalid of [{ version: 2 }, { uid: 'other-owner' }, { refresh_token: '' },
    { engine_ws_url: 'wss://old.example.test/ws/test-owner' }, { email: null }]) {
    write(invalid)
    const failure = readWorkspaceStatus(uid, url, path)
    assert.equal(failure.available, false)
    assert.ok(!JSON.stringify(failure).includes('secret-test'))
  }
  console.log('Workspace handoff: filesystem, identity, endpoint, redaction, and shell quoting passed.')
} finally {
  rmSync(temp, { recursive: true, force: true })
}
