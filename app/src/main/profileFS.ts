/**
 * Node-side profile creator. Writes `~/.zylch/profiles/<email>/.env`
 * directly, without going through the Python `profiles.create` RPC.
 *
 * Why: during onboarding (first-run) there is no sidecar yet — we
 * deliberately do NOT spawn one against a bogus placeholder profile just
 * to call back into it. Instead, the main process does the minimum
 * needed (dir + .env) and then the caller spawns the real sidecar
 * against the freshly written profile.
 *
 * Quoting / validation mirrors `zylch/services/settings_io.py::_quote`
 * and `zylch/rpc/methods.py::profiles_create` (see the KNOWN_KEYS dump
 * + _quote sources for parity). Everything else (unknown-key rejection,
 * required provider/key/email) matches server-side.
 */
import { existsSync, mkdirSync, writeFileSync, openSync, closeSync, fsyncSync } from 'fs'
import { join } from 'path'
import { homedir } from 'os'

// Keys accepted by the Zylch settings schema. Kept in sync with
// `zylch/services/settings_schema.py::KNOWN_KEYS` (source of truth).
// If the backend adds keys, keep this list in lockstep — unknown keys
// are rejected outright.
export const KNOWN_KEYS: ReadonlySet<string> = new Set([
  'ANTHROPIC_API_KEY',
  'DOCUMENT_PATHS',
  'DOWNLOADS_DIR',
  'EMAIL_ADDRESS',
  'EMAIL_PASSWORD',
  'IMAP_HOST',
  'IMAP_PORT',
  'MRCALL_BASE_URL',
  'MRCALL_CLIENT_ID',
  'MRCALL_CLIENT_SECRET',
  'MRCALL_DASHBOARD_URL',
  'MRCALL_REALM',
  'OPENAI_API_KEY',
  'SMTP_HOST',
  'SMTP_PORT',
  'SYSTEM_LLM_PROVIDER',
  'TELEGRAM_ALLOWED_USER_ID',
  'TELEGRAM_BOT_TOKEN',
  'USER_ADDRESS',
  'USER_CODICE_FISCALE',
  'USER_COMPANY',
  'USER_DATE_OF_BIRTH',
  'USER_FULL_NAME',
  'USER_IBAN',
  'USER_NOTES',
  'USER_PHONE',
  'USER_SECRET_INSTRUCTIONS',
  'USER_VAT_NUMBER'
])

const NEEDS_QUOTE = new Set([' ', '\t', '\n', '\r', '"', "'", '\\', '#', '=', '$', '`'])

// Byte-for-byte parity with python3 `shlex.quote`: wrap in single
// quotes and escape any embedded single quote as `'"'"'` (close single,
// quoted single, open single). Both `'\''` and `'"'"'` are legal and
// semantically equivalent, but CPython uses the latter and matching its
// output keeps the written .env files diff-identical with those
// produced by `zylch init` / the server-side `profiles.create` RPC.
function shlexQuote(value: string): string {
  if (value === '') return "''"
  return "'" + value.split("'").join("'\"'\"'") + "'"
}

/**
 * Quote `value` for inclusion as `KEY=value` in a .env file.
 * Parity with zylch/services/settings_io.py::_quote.
 */
export function dotenvQuote(value: string): string {
  if (value === '') return ''
  if (value.includes('\n') || value.includes('\r')) {
    let escaped = value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
    escaped = escaped.replace(/\r\n/g, '\\n').replace(/\n/g, '\\n').replace(/\r/g, '\\n')
    return `"${escaped}"`
  }
  for (const ch of value) {
    if (NEEDS_QUOTE.has(ch)) {
      return shlexQuote(value)
    }
  }
  return value
}

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function isValidEmail(email: string): boolean {
  return EMAIL_REGEX.test((email || '').trim())
}

export function profilesRoot(): string {
  return join(homedir(), '.zylch', 'profiles')
}

export function profileDir(email: string): string {
  return join(profilesRoot(), email)
}

export function profileExists(email: string): boolean {
  return existsSync(profileDir(email))
}

export interface CreateProfileResult {
  ok: true
  profile: string
  path: string
}

/**
 * Create a new profile directory and write its `.env`. Mirrors the
 * Python RPC `profiles.create`: same validation, same quoting, same
 * file permissions (0o700 dir, 0o600 file). Throws on any problem so
 * the IPC handler can surface a proper error string.
 */
export function createProfileFS(
  email: string,
  values: Record<string, string>
): CreateProfileResult {
  const trimmedEmail = (email || '').trim()
  if (!isValidEmail(trimmedEmail)) {
    throw new Error(`Invalid email address: ${JSON.stringify(email)}`)
  }
  if (!values || typeof values !== 'object') {
    throw new Error("'values' must be an object {key: value}")
  }

  // Validate keys.
  const cleaned: Record<string, string> = {}
  const unknown: string[] = []
  for (const [k, rawV] of Object.entries(values)) {
    if (!KNOWN_KEYS.has(k)) {
      unknown.push(k)
      continue
    }
    const v = rawV == null ? '' : typeof rawV === 'string' ? rawV : String(rawV)
    cleaned[k] = v
  }
  if (unknown.length > 0) {
    throw new Error(`unknown setting keys: ${JSON.stringify(unknown.sort())}`)
  }

  const provider = (cleaned['SYSTEM_LLM_PROVIDER'] || '').trim().toLowerCase()
  if (provider !== 'anthropic' && provider !== 'openai') {
    throw new Error("SYSTEM_LLM_PROVIDER must be 'anthropic' or 'openai'")
  }
  if (provider === 'anthropic' && !cleaned['ANTHROPIC_API_KEY']) {
    throw new Error('ANTHROPIC_API_KEY is required when provider=anthropic')
  }
  if (provider === 'openai' && !cleaned['OPENAI_API_KEY']) {
    throw new Error('OPENAI_API_KEY is required when provider=openai')
  }
  if (!cleaned['EMAIL_ADDRESS']) {
    cleaned['EMAIL_ADDRESS'] = trimmedEmail
  }

  const dir = profileDir(trimmedEmail)
  if (existsSync(dir)) {
    throw new Error(`Profile directory already exists: ${trimmedEmail}`)
  }

  // Ensure the parent dir exists (first-run flows almost always don't have it).
  const root = profilesRoot()
  if (!existsSync(root)) {
    mkdirSync(root, { recursive: true, mode: 0o700 })
  }
  mkdirSync(dir, { mode: 0o700 })

  const envPath = join(dir, '.env')
  const lines: string[] = ['# Created by MrCall Desktop onboarding\n']
  for (const [k, v] of Object.entries(cleaned)) {
    lines.push(`${k}=${dotenvQuote(v)}\n`)
  }

  // Exclusive create; matches Python os.open(O_WRONLY|O_CREAT|O_EXCL, 0o600).
  const fd = openSync(envPath, 'wx', 0o600)
  try {
    writeFileSync(fd, lines.join(''), 'utf8')
    fsyncSync(fd)
  } finally {
    closeSync(fd)
  }

  return { ok: true, profile: trimmedEmail, path: envPath }
}

/**
 * First-run detector. True iff `~/.zylch/profiles/` does not exist OR
 * contains no subdirectories (an empty dir or only files is treated as
 * "no profiles" — the sidecar would crash looking for any of them).
 */
export function isFirstRun(): boolean {
  const root = profilesRoot()
  if (!existsSync(root)) return true
  try {
    const { readdirSync, statSync } = require('fs') as typeof import('fs')
    const names = readdirSync(root)
    for (const n of names) {
      try {
        if (statSync(join(root, n)).isDirectory()) return false
      } catch {
        // ignore unreadable entries
      }
    }
    return true
  } catch {
    return true
  }
}
