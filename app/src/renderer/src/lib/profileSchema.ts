/**
 * Schema mirror of `engine/zylch/services/settings_schema.py`.
 *
 * Onboarding and NewProfileWizard need to render the full settings form
 * BEFORE a sidecar exists for the new profile, so they can't fetch the
 * schema via `settings.schema()` (no RPC channel yet). Settings.tsx —
 * which runs after the sidecar is attached — fetches the schema
 * dynamically and is the source of truth post-attach. Keep this file in
 * sync when you change the engine schema; tests don't enforce that yet.
 */
export type FieldType = 'text' | 'password' | 'number' | 'select' | 'textarea'

export interface SchemaField {
  key: string
  label: string
  type: FieldType
  group: string
  optional?: boolean
  options?: string[]
  help?: string
  secret?: boolean
  picker?: 'directory' | 'directories'
}

export const PROFILE_SCHEMA: SchemaField[] = [
  // ─── LLM ─────────────────────────────────────────────────
  {
    key: 'ANTHROPIC_API_KEY',
    label: 'Anthropic API key (BYOK)',
    type: 'password',
    group: 'LLM',
    optional: true,
    secret: true,
    help: 'Set this to use your own Anthropic billing. Leave blank to use MrCall credits — requires Firebase signin in the desktop app.'
  },
  // ─── Email (IMAP) ────────────────────────────────────────
  { key: 'EMAIL_ADDRESS', label: 'Email address', type: 'text', group: 'Email', optional: true },
  {
    key: 'EMAIL_PASSWORD',
    label: 'App password',
    type: 'password',
    group: 'Email',
    optional: true,
    secret: true,
    help: 'Email provider app password (not your account password).'
  },
  { key: 'IMAP_HOST', label: 'IMAP host', type: 'text', group: 'Email', optional: true },
  { key: 'IMAP_PORT', label: 'IMAP port', type: 'number', group: 'Email', optional: true },
  { key: 'SMTP_HOST', label: 'SMTP host', type: 'text', group: 'Email', optional: true },
  { key: 'SMTP_PORT', label: 'SMTP port', type: 'number', group: 'Email', optional: true },
  // ─── Telegram ────────────────────────────────────────────
  {
    key: 'TELEGRAM_BOT_TOKEN',
    label: 'Bot token',
    type: 'password',
    group: 'Telegram',
    optional: true,
    secret: true,
    help: 'From @BotFather.'
  },
  {
    key: 'TELEGRAM_ALLOWED_USER_ID',
    label: 'Allowed user ID',
    type: 'text',
    group: 'Telegram',
    optional: true,
    help: 'Your Telegram numeric user ID (from @userinfobot).'
  },
  // ─── MrCall ──────────────────────────────────────────────
  { key: 'MRCALL_CLIENT_ID', label: 'MrCall client ID', type: 'text', group: 'MrCall', optional: true },
  {
    key: 'MRCALL_CLIENT_SECRET',
    label: 'MrCall client secret',
    type: 'password',
    group: 'MrCall',
    optional: true,
    secret: true
  },
  { key: 'MRCALL_BASE_URL', label: 'MrCall base URL', type: 'text', group: 'MrCall', optional: true },
  { key: 'MRCALL_REALM', label: 'MrCall realm', type: 'text', group: 'MrCall', optional: true },
  {
    key: 'MRCALL_DASHBOARD_URL',
    label: 'MrCall dashboard URL',
    type: 'text',
    group: 'MrCall',
    optional: true
  },
  // ─── Google ─────────────────────────────────────────────
  {
    key: 'GOOGLE_CALENDAR_CLIENT_ID',
    label: 'Google Calendar OAuth client ID (override)',
    type: 'text',
    group: 'Google',
    optional: true,
    help: "Leave empty to reuse the same Desktop OAuth client as 'Continue with Google' sign-in (the default in packaged builds)."
  },
  {
    key: 'GOOGLE_CALENDAR_CLIENT_SECRET',
    label: 'Google Calendar OAuth client secret (override)',
    type: 'password',
    group: 'Google',
    optional: true,
    secret: true,
    help: "Required only when GOOGLE_CALENDAR_CLIENT_ID points at a 'Desktop app' OAuth client."
  },
  // ─── Personal data ──────────────────────────────────────
  {
    key: 'USER_FULL_NAME',
    label: 'Full name',
    type: 'text',
    group: 'Personal data',
    optional: true
  },
  { key: 'USER_PHONE', label: 'Phone number', type: 'text', group: 'Personal data', optional: true },
  {
    key: 'USER_CODICE_FISCALE',
    label: 'Codice fiscale',
    type: 'text',
    group: 'Personal data',
    optional: true
  },
  {
    key: 'USER_DATE_OF_BIRTH',
    label: 'Date of birth',
    type: 'text',
    group: 'Personal data',
    optional: true
  },
  { key: 'USER_ADDRESS', label: 'Address', type: 'text', group: 'Personal data', optional: true },
  { key: 'USER_IBAN', label: 'IBAN', type: 'text', group: 'Personal data', optional: true },
  {
    key: 'USER_COMPANY',
    label: 'Company name',
    type: 'text',
    group: 'Personal data',
    optional: true
  },
  {
    key: 'USER_VAT_NUMBER',
    label: 'VAT / P.IVA',
    type: 'text',
    group: 'Personal data',
    optional: true
  },
  // ─── Documents & notes ──────────────────────────────────
  {
    key: 'DOCUMENT_PATHS',
    label: 'Document folders',
    type: 'text',
    group: 'Documents & notes',
    optional: true,
    help: 'Comma-separated absolute paths.',
    picker: 'directories'
  },
  {
    key: 'DOWNLOADS_DIR',
    label: 'Downloads folder',
    type: 'text',
    group: 'Documents & notes',
    optional: true,
    help: 'Where download_attachment saves files. Defaults to ~/Downloads.',
    picker: 'directory'
  },
  {
    key: 'USER_NOTES',
    label: 'Personal notes',
    type: 'textarea',
    group: 'Documents & notes',
    optional: true,
    help: 'Free-form context the assistant can use.'
  },
  {
    key: 'USER_SECRET_INSTRUCTIONS',
    label: 'Secret instructions',
    type: 'textarea',
    group: 'Documents & notes',
    optional: true,
    help: 'Instructions the assistant follows but never reveals to contacts.'
  }
]
