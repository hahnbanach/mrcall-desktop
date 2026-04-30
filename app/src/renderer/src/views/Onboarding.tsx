/**
 * First-run onboarding screen.
 *
 * Shown instead of the normal sidebar/tabs layout when the app detects
 * no profiles on disk. No sidecar is running in this state — the
 * wizard talks directly to the main process via
 * `window.zylch.onboarding.*` which writes the profile `.env` on the
 * filesystem and then spawns a real sidecar-bound window.
 *
 * Field set deliberately mirrors `NewProfileWizard` (LLM provider +
 * key, email + app-password, IMAP/SMTP, optional Telegram). Everything
 * else is editable from Settings once the user is in.
 */
import { useEffect, useMemo, useState } from 'react'
import { errorMessage } from '../lib/errors'

type Provider = 'anthropic' | 'openai'

const PRESETS: Record<string, { imapHost: string; smtpHost: string }> = {
  'gmail.com': { imapHost: 'imap.gmail.com', smtpHost: 'smtp.gmail.com' },
  'googlemail.com': { imapHost: 'imap.gmail.com', smtpHost: 'smtp.gmail.com' },
  'outlook.com': { imapHost: 'outlook.office365.com', smtpHost: 'smtp.office365.com' },
  'hotmail.com': { imapHost: 'outlook.office365.com', smtpHost: 'smtp.office365.com' },
  'live.com': { imapHost: 'outlook.office365.com', smtpHost: 'smtp.office365.com' },
  'yahoo.com': { imapHost: 'imap.mail.yahoo.com', smtpHost: 'smtp.mail.yahoo.com' },
  'icloud.com': { imapHost: 'imap.mail.me.com', smtpHost: 'smtp.mail.me.com' }
}

function inferHosts(email: string): { imapHost: string; smtpHost: string } {
  const at = email.lastIndexOf('@')
  if (at < 0) return { imapHost: '', smtpHost: '' }
  const domain = email.slice(at + 1).toLowerCase()
  const preset = PRESETS[domain]
  if (preset) return preset
  return { imapHost: `imap.${domain}`, smtpHost: `smtp.${domain}` }
}

function isValidEmail(s: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s.trim())
}

export default function Onboarding(): JSX.Element {
  const [email, setEmail] = useState('')
  const [provider, setProvider] = useState<Provider>('anthropic')
  const [apiKey, setApiKey] = useState('')
  const [emailPassword, setEmailPassword] = useState('')
  const [imapHost, setImapHost] = useState('')
  const [imapPort, setImapPort] = useState('993')
  const [smtpHost, setSmtpHost] = useState('')
  const [smtpPort, setSmtpPort] = useState('587')
  const [telegramToken, setTelegramToken] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  // Auto-fill IMAP/SMTP hosts when the user types a valid email — but
  // don't clobber values the user typed themselves.
  useEffect(() => {
    if (!email || !isValidEmail(email)) return
    const inferred = inferHosts(email)
    if (!imapHost) setImapHost(inferred.imapHost)
    if (!smtpHost) setSmtpHost(inferred.smtpHost)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [email])

  const canSubmit = useMemo(() => {
    if (!isValidEmail(email)) return false
    if (!apiKey.trim()) return false
    if (!emailPassword.trim()) return false
    if (!imapHost.trim() || !smtpHost.trim()) return false
    if (!imapPort.trim() || !smtpPort.trim()) return false
    return true
  }, [email, apiKey, emailPassword, imapHost, smtpHost, imapPort, smtpPort])

  const handleSubmit = async (): Promise<void> => {
    if (!canSubmit || submitting) return
    setSubmitting(true)
    setFormError(null)
    const values: Record<string, string> = {
      SYSTEM_LLM_PROVIDER: provider,
      EMAIL_ADDRESS: email.trim(),
      EMAIL_PASSWORD: emailPassword,
      IMAP_HOST: imapHost.trim(),
      IMAP_PORT: imapPort.trim(),
      SMTP_HOST: smtpHost.trim(),
      SMTP_PORT: smtpPort.trim()
    }
    if (provider === 'anthropic') values.ANTHROPIC_API_KEY = apiKey
    else values.OPENAI_API_KEY = apiKey
    if (telegramToken.trim()) values.TELEGRAM_BOT_TOKEN = telegramToken.trim()
    try {
      const r = await window.zylch.onboarding.createProfile(email.trim(), values)
      if (!r.ok) {
        setFormError(r.error || 'Failed to create profile')
        setSubmitting(false)
        return
      }
      // Main process spawns a new profile-bound window and closes the
      // onboarding window. We intentionally do NOT try to reset our own
      // React state after this — the window is about to disappear.
      const fin = await window.zylch.onboarding.finalize(r.profile)
      if (!fin.ok) {
        setFormError('Profile created but failed to open the main window.')
        setSubmitting(false)
      }
    } catch (e: unknown) {
      setFormError(errorMessage(e))
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen w-full flex items-start justify-center bg-brand-light-grey p-6 overflow-auto">
      <div className="w-full max-w-[560px]">
        <div className="mb-5">
          <h1 className="text-2xl font-semibold text-brand-black">Welcome to MrCall Desktop</h1>
          <p className="text-sm text-brand-grey-80 mt-1">
            Create your first profile. All data stays on this machine — your credentials
            are written only to <code>~/.zylch/profiles/</code>.
          </p>
        </div>

        {formError && (
          <div className="mb-3 p-2 bg-brand-danger/10 border border-brand-danger/30 text-brand-danger rounded text-sm whitespace-pre-wrap">
            {formError}
          </div>
        )}

        <div className="bg-white border border-brand-mid-grey rounded-lg shadow-sm p-5 space-y-3">
          <Field label="Email address" required>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="user@example.com"
              autoComplete="off"
              className="w-full px-3 py-2 border rounded text-sm"
            />
          </Field>

          <Field label="LLM provider" required>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value as Provider)}
              className="w-full px-3 py-2 border rounded text-sm"
            >
              <option value="anthropic">anthropic</option>
              <option value="openai">openai</option>
            </select>
          </Field>

          <Field
            label={provider === 'anthropic' ? 'Anthropic API key' : 'OpenAI API key'}
            required
          >
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              autoComplete="new-password"
              className="w-full px-3 py-2 border rounded text-sm"
            />
          </Field>

          <Field
            label="Email app password"
            required
            help="App password from your email provider — not your account password."
          >
            <input
              type="password"
              value={emailPassword}
              onChange={(e) => setEmailPassword(e.target.value)}
              autoComplete="new-password"
              className="w-full px-3 py-2 border rounded text-sm"
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="IMAP host" required>
              <input
                type="text"
                value={imapHost}
                onChange={(e) => setImapHost(e.target.value)}
                className="w-full px-3 py-2 border rounded text-sm"
              />
            </Field>
            <Field label="IMAP port" required>
              <input
                type="number"
                value={imapPort}
                onChange={(e) => setImapPort(e.target.value)}
                className="w-full px-3 py-2 border rounded text-sm"
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="SMTP host" required>
              <input
                type="text"
                value={smtpHost}
                onChange={(e) => setSmtpHost(e.target.value)}
                className="w-full px-3 py-2 border rounded text-sm"
              />
            </Field>
            <Field label="SMTP port" required>
              <input
                type="number"
                value={smtpPort}
                onChange={(e) => setSmtpPort(e.target.value)}
                className="w-full px-3 py-2 border rounded text-sm"
              />
            </Field>
          </div>

          <Field
            label="Telegram bot token"
            help="Optional — paste a token from @BotFather to enable the Telegram bot."
          >
            <input
              type="password"
              value={telegramToken}
              onChange={(e) => setTelegramToken(e.target.value)}
              autoComplete="new-password"
              className="w-full px-3 py-2 border rounded text-sm"
            />
          </Field>

          <p className="text-xs text-brand-grey-80">
            Other optional fields (personal data, MrCall credentials, notes…) can be edited
            from Settings after this setup.
          </p>

          <div className="flex items-center justify-end pt-2">
            <button
              onClick={handleSubmit}
              disabled={!canSubmit || submitting}
              className="px-4 py-2 text-sm bg-brand-black text-white rounded disabled:bg-brand-mid-grey"
            >
              {submitting ? 'Creating…' : 'Create profile and continue'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

interface FieldProps {
  label: string
  required?: boolean
  help?: string
  children: React.ReactNode
}

function Field({ label, required, help, children }: FieldProps): JSX.Element {
  return (
    <div>
      <label className="block text-xs font-medium text-brand-grey-80 mb-1">
        {label}
        {required && <span className="text-brand-danger ml-1">*</span>}
      </label>
      {children}
      {help && <div className="text-xs text-brand-grey-80 mt-1">{help}</div>}
    </div>
  )
}
