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
import {
  existsSync,
  mkdirSync,
  writeFileSync,
  openSync,
  closeSync,
  fsyncSync,
  readFileSync,
  readdirSync,
  statSync
} from 'fs'
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
  'GOOGLE_CALENDAR_CLIENT_ID',
  'IMAP_HOST',
  'IMAP_PORT',
  'MRCALL_BASE_URL',
  'MRCALL_CLIENT_ID',
  'MRCALL_CLIENT_SECRET',
  'MRCALL_DASHBOARD_URL',
  'MRCALL_REALM',
  'OWNER_ID',
  'SMTP_HOST',
  'SMTP_PORT',
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

/**
 * Strip dotenv-style quoting (parity with what `dotenvQuote` produces).
 *  - `'foo'`         → `foo`     (shlex-style single quotes)
 *  - `"foo\nbar"`    → `foo\nbar` with `\n`/`\\`/`\"` unescaped
 *  - bare `foo`      → `foo`
 *
 * .env files are structured input — a small regex / state machine here is
 * appropriate (the "no regex on prose" rule is about parsing unstructured
 * text, not key=value config).
 */
function stripDotenvQuoting(raw: string): string {
  const v = raw.trim()
  if (v.length >= 2) {
    if (v[0] === "'" && v[v.length - 1] === "'") {
      // shlex.quote inverse: `'"'"'` collapses back into a single `'`.
      return v.slice(1, -1).split(`'"'"'`).join("'")
    }
    if (v[0] === '"' && v[v.length - 1] === '"') {
      const inner = v.slice(1, -1)
      return inner
        .replace(/\\n/g, '\n')
        .replace(/\\"/g, '"')
        .replace(/\\\\/g, '\\')
    }
  }
  return v
}

/**
 * Read a single key from a profile's `.env`. Returns null if the file
 * doesn't exist, isn't readable, or doesn't carry the key. Used by the
 * profile-listing IPC to surface human-friendly emails next to the
 * UID-keyed directory names.
 */
export function readProfileEnvValue(id: string, key: string): string | null {
  const envPath = join(profileDir(id), '.env')
  let text: string
  try {
    text = readFileSync(envPath, 'utf-8')
  } catch {
    return null
  }
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    // Optional `export ` prefix tolerated for hand-written .envs.
    const stripped = line.startsWith('export ') ? line.slice(7) : line
    const eq = stripped.indexOf('=')
    if (eq <= 0) continue
    const k = stripped.slice(0, eq).trim()
    if (k !== key) continue
    return stripDotenvQuoting(stripped.slice(eq + 1))
  }
  return null
}

export interface ProfileSummary {
  /** Directory name under `~/.zylch/profiles/`. Firebase UID for new
   *  profiles, email for legacy ones. Stable across email changes —
   *  use this as the key when opening / selecting / persisting. */
  id: string
  /** `EMAIL_ADDRESS` from the profile's `.env`, or null if missing /
   *  unreadable. Display-only — never use as a lookup key. */
  email: string | null
}

/**
 * Enumerate every profile under `~/.zylch/profiles/` and resolve each
 * to a `{id, email}` summary. Mirrors the listing rules used to live
 * inline in `main/index.ts:listProfiles()`: every readable subdirectory
 * counts, even if its `.env` is missing or unreadable (the user can
 * recover via the Settings tab).
 */
export function listProfilesWithEmail(): ProfileSummary[] {
  const dir = profilesRoot()
  if (!existsSync(dir)) return []
  const out: ProfileSummary[] = []
  let names: string[]
  try {
    names = readdirSync(dir).sort()
  } catch {
    return []
  }
  for (const name of names) {
    const full = join(dir, name)
    try {
      if (!statSync(full).isDirectory()) continue
    } catch {
      continue
    }
    out.push({ id: name, email: readProfileEnvValue(name, 'EMAIL_ADDRESS') })
  }
  return out
}

export interface CreateProfileResult {
  ok: true
  profile: string
  path: string
}

// Firebase UIDs are alphanumeric (28 chars in practice) and never
// contain a `@`. This regex is intentionally permissive: anything that
// is non-empty, no `/`, no whitespace, no leading dot. We use it to
// distinguish "directory name = uid" from "directory name = email" in
// the existing email-keyed code paths without adding a side channel.
const PROFILE_DIR_REGEX = /^[A-Za-z0-9_.-]{4,128}$/

function isValidProfileName(name: string): boolean {
  return PROFILE_DIR_REGEX.test((name || '').trim())
}

/**
 * Create a profile keyed by an opaque identifier (the Firebase UID).
 *
 * This is the post-signin onboarding path: the renderer pre-populates
 * `email` from the Firebase user object so we can write EMAIL_ADDRESS
 * into the .env without a second prompt, but the on-disk directory is
 * named after the UID — emails change, UIDs don't, so this keeps the
 * profile stable across email changes.
 *
 * `OWNER_ID` is also written so the engine's owner-scoped storage
 * (OAuthToken, etc.) keys cleanly off the same UID.
 */
export function createProfileForFirebaseUser(
  uid: string,
  email: string,
  values: Record<string, string>
): CreateProfileResult {
  const trimmedUid = (uid || '').trim()
  const trimmedEmail = (email || '').trim()
  if (!isValidProfileName(trimmedUid)) {
    throw new Error(`Invalid Firebase UID: ${JSON.stringify(uid)}`)
  }
  if (!isValidEmail(trimmedEmail)) {
    throw new Error(`Invalid email address: ${JSON.stringify(email)}`)
  }
  if (!values || typeof values !== 'object') {
    throw new Error("'values' must be an object {key: value}")
  }

  const cleaned: Record<string, string> = {}
  const unknown: string[] = []
  for (const [k, rawV] of Object.entries(values)) {
    if (!KNOWN_KEYS.has(k)) {
      unknown.push(k)
      continue
    }
    cleaned[k] = rawV == null ? '' : typeof rawV === 'string' ? rawV : String(rawV)
  }
  if (unknown.length > 0) {
    throw new Error(`unknown setting keys: ${JSON.stringify(unknown.sort())}`)
  }

  // No LLM-side validation: the wizard doesn't write SYSTEM_LLM_PROVIDER
  // or BYOK keys at all, and the engine resolver tolerates any value
  // (unrecognised → falls through to key-presence inference).
  //
  // Tie the engine's owner_id to the Firebase UID so OAuth tokens
  // (Google Calendar, future MrCall delegations) all key off the same
  // identifier the renderer pushes to the engine via account.set_firebase_token.
  cleaned['OWNER_ID'] = trimmedUid
  if (!cleaned['EMAIL_ADDRESS']) {
    cleaned['EMAIL_ADDRESS'] = trimmedEmail
  }

  const dir = profileDir(trimmedUid)
  if (existsSync(dir)) {
    throw new Error(`Profile directory already exists: ${trimmedUid}`)
  }

  const root = profilesRoot()
  if (!existsSync(root)) {
    mkdirSync(root, { recursive: true, mode: 0o700 })
  }
  mkdirSync(dir, { mode: 0o700 })

  const envPath = join(dir, '.env')
  const lines: string[] = [
    '# Created by MrCall Desktop onboarding (Firebase signin path)\n',
    `# email=${trimmedEmail}\n`
  ]
  for (const [k, v] of Object.entries(cleaned)) {
    lines.push(`${k}=${dotenvQuote(v)}\n`)
  }

  const fd = openSync(envPath, 'wx', 0o600)
  try {
    writeFileSync(fd, lines.join(''), 'utf8')
    fsyncSync(fd)
  } finally {
    closeSync(fd)
  }

  return { ok: true, profile: trimmedUid, path: envPath }
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

  // No LLM-side validation — see the matching note in
  // createProfileForFirebaseUser.
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
