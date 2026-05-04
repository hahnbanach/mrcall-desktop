/**
 * Modal wizard to create a brand-new Zylch profile.
 *
 * The user fills in just the essential fields; the form posts them to
 * the backend via `window.zylch.profiles.create(email, values)`. On
 * success, the new profile is reachable from the top bar's
 * "Profiles" dropdown. We intentionally do NOT auto-open a window
 * for the new profile — opening another window from the wizard is
 * surprising; the user should choose when to switch.
 *
 * Field set kept tight on purpose: the schema has many optional
 * fields (MrCall, personal data, notes, …) that are best edited from
 * the new profile's own Settings tab once it is opened — the wizard
 * only collects what is needed to launch.
 */
import { useEffect, useMemo, useState } from 'react'
import { errorMessage } from '../lib/errors'

interface Props {
  open: boolean
  onClose: () => void
  onCreated: (email: string) => void
}

// Sensible IMAP/SMTP defaults keyed off the email's domain. Mirrors
// what `zylch init` offers as a one-keystroke option in the CLI.
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

export default function NewProfileWizard({ open, onClose, onCreated }: Props): JSX.Element | null {
  const [email, setEmail] = useState('')
  const [emailPassword, setEmailPassword] = useState('')
  const [imapHost, setImapHost] = useState('')
  const [imapPort, setImapPort] = useState('993')
  const [smtpHost, setSmtpHost] = useState('')
  const [smtpPort, setSmtpPort] = useState('587')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  // Reset the form whenever the modal is (re-)opened so a previous
  // attempt's leftovers don't leak into a fresh wizard.
  useEffect(() => {
    if (!open) return
    setEmail('')
    setEmailPassword('')
    setImapHost('')
    setImapPort('993')
    setSmtpHost('')
    setSmtpPort('587')
    setFormError(null)
    setSubmitting(false)
  }, [open])

  // Auto-fill IMAP/SMTP hosts when the user types an email — but only
  // if they haven't already typed a host themselves (don't clobber).
  useEffect(() => {
    if (!email || !isValidEmail(email)) return
    const inferred = inferHosts(email)
    if (!imapHost) setImapHost(inferred.imapHost)
    if (!smtpHost) setSmtpHost(inferred.smtpHost)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [email])

  const canSubmit = useMemo(() => {
    if (!isValidEmail(email)) return false
    if (!emailPassword.trim()) return false
    if (!imapHost.trim() || !smtpHost.trim()) return false
    if (!imapPort.trim() || !smtpPort.trim()) return false
    return true
  }, [email, emailPassword, imapHost, smtpHost, imapPort, smtpPort])

  if (!open) return null

  const handleSubmit = async (): Promise<void> => {
    if (!canSubmit || submitting) return
    setSubmitting(true)
    setFormError(null)
    // No SYSTEM_LLM_PROVIDER, no API key. The engine resolves transport
    // from .env contents at runtime — see Settings → LLM to add a BYOK
    // Anthropic key after the profile is created.
    const values: Record<string, string> = {
      EMAIL_ADDRESS: email.trim(),
      EMAIL_PASSWORD: emailPassword,
      IMAP_HOST: imapHost.trim(),
      IMAP_PORT: imapPort.trim(),
      SMTP_HOST: smtpHost.trim(),
      SMTP_PORT: smtpPort.trim()
    }
    try {
      const r = await window.zylch.profiles.create(email.trim(), values)
      if (!r.ok) {
        setFormError('Server returned ok=false')
        setSubmitting(false)
        return
      }
      onCreated(r.profile)
    } catch (e: unknown) {
      // Any server-side validation error ("Profile already exists",
      // "Invalid email address", etc.) lands here. Render inline; this
      // dialog is the user's current focus.
      setFormError(errorMessage(e))
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
      onClick={() => {
        if (!submitting) onClose()
      }}
    >
      <div
        className="bg-white rounded-lg shadow-xl p-5 w-[520px] max-h-[90vh] overflow-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold">Create new profile</h2>
          <button
            onClick={onClose}
            disabled={submitting}
            className="text-brand-grey-80 hover:text-brand-black text-lg leading-none disabled:opacity-50"
            aria-label="Close"
          >
            x
          </button>
        </div>

        {formError && (
          <div className="mb-3 p-2 bg-brand-danger/10 border border-brand-danger/30 text-brand-danger rounded text-sm whitespace-pre-wrap">
            {formError}
          </div>
        )}

        <div className="space-y-3">
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

          <Field label="Email app password" required help="App password from your email provider — not your account password.">
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

          <p className="text-xs text-brand-grey-80">
            Other optional fields (personal data, MrCall credentials, notes…) can be edited from the
            new profile&apos;s own Settings tab once you open it.
          </p>
        </div>

        <div className="flex items-center justify-end gap-2 mt-5">
          <button
            onClick={onClose}
            disabled={submitting}
            className="px-3 py-1.5 text-sm border rounded text-brand-grey-80 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit || submitting}
            className="px-4 py-1.5 text-sm bg-brand-black text-white rounded disabled:bg-brand-mid-grey"
          >
            {submitting ? 'Creating…' : 'Create profile'}
          </button>
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
