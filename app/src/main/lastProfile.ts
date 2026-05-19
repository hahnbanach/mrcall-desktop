/**
 * Track the most-recently-bound profile UID in `~/.zylch/last-profile`.
 *
 * Used at boot to decide which profile's BrowserWindow to spawn first.
 * Combined with the per-profile `FIREBASE_PARTITION` stored in
 * `<profile>/.env`, this lets the desktop restore the prior Firebase
 * session without showing SignIn — the user sees their app, not the
 * sign-in screen, on a normal relaunch.
 *
 * A separate single-file index (instead of `mtime` on each profile dir)
 * because mtime is touched by anything that writes inside the profile
 * (sidecar SQLite, settings save, etc.), so it's a noisy signal. We want
 * "last *bound*" — the explicit user-level event of signing into a
 * profile — which happens exactly once per bindProfile and we control.
 */
import {
  existsSync,
  mkdirSync,
  openSync,
  closeSync,
  fsyncSync,
  readFileSync,
  writeFileSync
} from 'fs'
import { join } from 'path'
import { homedir } from 'os'

function lastProfilePath(): string {
  return join(homedir(), '.zylch', 'last-profile')
}

export function readLastProfile(): string | null {
  const p = lastProfilePath()
  if (!existsSync(p)) return null
  try {
    const raw = readFileSync(p, 'utf-8').trim()
    return raw || null
  } catch {
    return null
  }
}

export function writeLastProfile(uid: string): void {
  const trimmed = (uid || '').trim()
  if (!trimmed) return
  const path = lastProfilePath()
  const dir = join(homedir(), '.zylch')
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true, mode: 0o700 })
  }
  // Atomic write via tmp + rename so a crashed write never leaves a
  // half-truncated `last-profile` file behind.
  const tmpPath = path + '.tmp'
  const fd = openSync(tmpPath, 'w', 0o600)
  try {
    writeFileSync(fd, trimmed, 'utf8')
    fsyncSync(fd)
  } finally {
    closeSync(fd)
  }
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { renameSync } = require('fs') as typeof import('fs')
  renameSync(tmpPath, path)
}
