/**
 * Per-installation backend location, stored machine-global in
 * `~/.zylch/backend-config.json`.
 *
 * This is a property of THIS machine, not of the Firebase identity or the
 * profile: the same account may run a local stdio engine on one laptop and
 * point at a remote `wss://` engine from another. So it lives alongside
 * `last-profile` under `~/.zylch/` (mirroring `lastProfile.ts`), NOT in
 * the profile's `.env`.
 *
 * Default — and the value a fresh install always reads — is
 * `{ location: 'local' }`: spawn the local sidecar, exactly as every
 * current user runs today. The remote path is opt-in via Settings.
 */
import {
  existsSync,
  mkdirSync,
  openSync,
  closeSync,
  fsyncSync,
  readFileSync,
  writeFileSync,
  renameSync
} from 'fs'
import { join } from 'path'
import { homedir } from 'os'

export type BackendLocation = 'local' | 'remote'

export interface BackendConfig {
  location: BackendLocation
  /** Present only when `location === 'remote'`. e.g. `wss://desktop.mrcall.ai` */
  url?: string
}

const DEFAULT_CONFIG: BackendConfig = { location: 'local' }

function backendConfigPath(): string {
  return join(homedir(), '.zylch', 'backend-config.json')
}

/**
 * Read the persisted config. Any read/parse error, a missing file, or a
 * malformed payload falls back to the local default — a corrupt config
 * must never strand the user without an engine.
 */
export function readBackendConfig(): BackendConfig {
  const p = backendConfigPath()
  if (!existsSync(p)) return { ...DEFAULT_CONFIG }
  try {
    const raw = readFileSync(p, 'utf-8').trim()
    if (!raw) return { ...DEFAULT_CONFIG }
    const parsed = JSON.parse(raw)
    if (parsed?.location === 'remote') {
      const url = typeof parsed.url === 'string' ? parsed.url.trim() : ''
      // A 'remote' config with no usable URL is meaningless — degrade to
      // local rather than try to open ws://undefined.
      if (!url) return { ...DEFAULT_CONFIG }
      return { location: 'remote', url }
    }
    return { location: 'local' }
  } catch {
    return { ...DEFAULT_CONFIG }
  }
}

/**
 * Atomically persist the config (tmp + fsync + rename) so a crashed write
 * never leaves a half-truncated file behind — same discipline as
 * `writeLastProfile`.
 */
export function writeBackendConfig(config: BackendConfig): void {
  const normalized: BackendConfig =
    config.location === 'remote' && config.url && config.url.trim()
      ? { location: 'remote', url: config.url.trim() }
      : { location: 'local' }
  const path = backendConfigPath()
  const dir = join(homedir(), '.zylch')
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true, mode: 0o700 })
  }
  const tmpPath = path + '.tmp'
  const fd = openSync(tmpPath, 'w', 0o600)
  try {
    writeFileSync(fd, JSON.stringify(normalized, null, 2) + '\n', 'utf8')
    fsyncSync(fd)
  } finally {
    closeSync(fd)
  }
  renameSync(tmpPath, path)
}
