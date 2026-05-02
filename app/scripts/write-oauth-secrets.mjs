// CI step: materialise `src/main/oauthSecrets.ts` from the
// `GOOGLE_SIGNIN_CLIENT_SECRET` env var before `npm run dist`.
//
// Why a script and not an inline `cat > file` in the workflow YAML
// -----------------------------------------------------------------
// The value gets interpolated into a TypeScript string literal — the
// quoting / escaping rules are easier to read and audit here than in
// a multi-shell heredoc. The script also fails loudly with a clear
// message when the env var is missing, instead of silently producing
// an empty secret and letting the build ship a broken signin button.
//
// Idempotent: overwrites whatever postinstall placed there (which is
// the empty `.example` template, so no real value gets clobbered).

import { writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const target = join(here, '..', 'src', 'main', 'oauthSecrets.ts')

const value = (process.env.GOOGLE_SIGNIN_CLIENT_SECRET ?? '').trim()
if (!value) {
  console.error(
    '[write-oauth-secrets] GOOGLE_SIGNIN_CLIENT_SECRET env var is empty. ' +
      'Add the repo secret at Settings → Secrets and variables → Actions, ' +
      'or set it locally in your shell. Refusing to ship a build with ' +
      'Google sign-in disabled.'
  )
  process.exit(1)
}

// Defensive check: bail if the value doesn't match Google's
// installed-app secret prefix. Catches typos / wrong secret values
// before the binary ships.
if (!value.startsWith('GOCSPX-')) {
  console.error(
    `[write-oauth-secrets] value does not start with the expected ` +
      `'GOCSPX-' prefix — refusing to write. Got prefix '${value.slice(0, 8)}…'.`
  )
  process.exit(1)
}

// Quote-safe TS string literal. The Google secret format is restricted
// to URL-safe characters so a backslash-escape of single quotes is
// belt-and-braces, but we do it anyway to match what a human would
// write defensively.
const escaped = value.replace(/\\/g, '\\\\').replace(/'/g, "\\'")
const body =
  `// AUTO-GENERATED at build time by scripts/write-oauth-secrets.mjs.\n` +
  `// Do not commit. The committed companion is oauthSecrets.example.ts.\n` +
  `export const GOOGLE_SIGNIN_CLIENT_SECRET = '${escaped}'\n`

writeFileSync(target, body, { mode: 0o600 })
console.log(`[write-oauth-secrets] wrote ${target} (${value.length} chars).`)
