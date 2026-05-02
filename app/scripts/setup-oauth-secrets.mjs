// Postinstall step: ensure `src/main/oauthSecrets.ts` exists by
// copying the committed `.example` template the first time. The actual
// file is gitignored — the real Client secret only ever lives in the
// developer's checkout / the CI build environment, never in git.
//
// Idempotent: existing files are left alone, so editing the real
// secret won't be clobbered by subsequent `npm install` runs.

import { copyFileSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const target = join(here, '..', 'src', 'main', 'oauthSecrets.ts')
const template = join(here, '..', 'src', 'main', 'oauthSecrets.example.ts')

if (existsSync(target)) {
  // Don't touch — preserves any value the developer pasted in.
  process.exit(0)
}

if (!existsSync(template)) {
  console.warn(
    '[setup-oauth-secrets] template not found at',
    template,
    '— skipping (Google sign-in will report "not configured" until you create src/main/oauthSecrets.ts manually).'
  )
  process.exit(0)
}

copyFileSync(template, target)
console.log(
  '[setup-oauth-secrets] wrote',
  target,
  '(edit it and paste the Google Client secret to enable signin in dev).'
)
