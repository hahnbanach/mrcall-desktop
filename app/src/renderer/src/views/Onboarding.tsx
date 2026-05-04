/**
 * Onboarding screen — shown when FirebaseAuthGate has a signed-in
 * user but no UID-keyed profile dir exists on disk for them. No
 * sidecar is attached to the window yet; the wizard writes
 * `~/.zylch/profiles/<firebase_uid>/.env` directly from main via
 * `onboarding.createProfileForFirebaseUser`, then `finalize` attaches
 * a sidecar to THIS window in-place (preserving the Firebase auth
 * state — no second signin), and finally `onReady` signals the gate
 * to transition into the bound app.
 *
 * Field set is intentionally minimal: email + IMAP/SMTP + optional
 * Telegram. No LLM provider / API-key fields — the engine resolver
 * defaults to MrCall credits when no key is in `.env`. Everything
 * else is editable from Settings once the user is in.
 */
import { useEffect, useMemo, useState } from 'react'
import { errorMessage } from '../lib/errors'
import { auth } from '../firebase/config'
import { performSignOut } from '../App'

interface OnboardingProps {
  // Called after createProfile + finalize succeed, both of which write
  // and attach state in main. The gate uses this to re-push the
  // Firebase token to the now-attached sidecar and flip into 'bound'.
  onReady?: (profile: string) => void
}

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

export default function Onboarding({ onReady }: OnboardingProps = {}): JSX.Element {
  // Firebase user is guaranteed by FirebaseAuthGate. We seed the email
  // from it but let the user override (they may want IMAP on a
  // different mailbox than their Firebase identity).
  const firebaseUser = auth.currentUser
  const firebaseUid = firebaseUser?.uid || ''
  const firebaseEmail = firebaseUser?.email || ''
  const [email, setEmail] = useState(firebaseEmail)
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
    if (!emailPassword.trim()) return false
    if (!imapHost.trim() || !smtpHost.trim()) return false
    if (!imapPort.trim() || !smtpPort.trim()) return false
    return true
  }, [email, emailPassword, imapHost, smtpHost, imapPort, smtpPort])

  const handleSubmit = async (): Promise<void> => {
    if (!canSubmit || submitting) return
    setSubmitting(true)
    setFormError(null)
    // No SYSTEM_LLM_PROVIDER, no API key. The engine resolver
    // (`zylch.api.token_storage.get_active_llm_provider`) defaults to
    // MrCall credits when no BYOK key is in the profile .env. To opt
    // into BYOK, the user adds `ANTHROPIC_API_KEY=...` (or
    // `OPENAI_API_KEY=...`) to `.env` after onboarding — or flips the
    // toggle in Settings.
    const values: Record<string, string> = {
      EMAIL_ADDRESS: email.trim(),
      EMAIL_PASSWORD: emailPassword,
      IMAP_HOST: imapHost.trim(),
      IMAP_PORT: imapPort.trim(),
      SMTP_HOST: smtpHost.trim(),
      SMTP_PORT: smtpPort.trim()
    }
    if (telegramToken.trim()) values.TELEGRAM_BOT_TOKEN = telegramToken.trim()
    try {
      // Path A: Firebase signed-in user → profile keyed by UID.
      // FirebaseAuthGate guarantees we land here only when a user
      // exists, but be defensive in case state transitions race.
      let r:
        | { ok: true; profile: string }
        | { ok: false; error: string }
      if (firebaseUid && firebaseEmail) {
        r = await window.zylch.onboarding.createProfileForFirebaseUser(
          firebaseUid,
          email.trim(),
          values
        )
      } else {
        // Path B: legacy email-keyed profile (FirebaseAuthGate is off
        // or the user object went missing). Kept as a safety net.
        r = await window.zylch.onboarding.createProfile(email.trim(), values)
      }
      if (!r.ok) {
        setFormError(r.error || 'Failed to create profile')
        setSubmitting(false)
        return
      }
      // Attach a sidecar to THIS window in-place. Same renderer
      // context, so Firebase auth state survives the transition.
      const fin = await window.zylch.onboarding.finalize(r.profile)
      if (!fin.ok) {
        setFormError('Profile created but failed to attach the sidecar.')
        setSubmitting(false)
        return
      }
      if (onReady) {
        onReady(r.profile)
      }
    } catch (e: unknown) {
      setFormError(errorMessage(e))
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen w-full flex items-start justify-center bg-brand-light-grey p-6 overflow-auto">
      <div className="w-full max-w-[560px]">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold text-brand-black">Welcome to MrCall Desktop</h1>
            <p className="text-sm text-brand-grey-80 mt-1">
              Create your first profile. All data stays on this machine — your credentials
              are written only to <code>~/.zylch/profiles/</code>.
            </p>
            {firebaseEmail && (
              <p className="text-xs text-brand-grey-80 mt-2">
                Signed in as <strong>{firebaseEmail}</strong>
                <span className="ml-1 opacity-60">(uid {firebaseUid.slice(0, 8)}…)</span>
              </p>
            )}
          </div>
          {firebaseUser && (
            <button
              type="button"
              onClick={() => performSignOut()}
              className="px-2 py-1 text-xs text-brand-grey-80 hover:text-brand-black border rounded shrink-0"
            >
              Sign out
            </button>
          )}
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

          <div className="text-xs text-brand-grey-80 bg-brand-light-grey/60 border border-brand-mid-grey rounded p-3">
            Your AI calls run on <strong>MrCall credits</strong> by default — the same
            balance that funds your phone calls. You can top up from Settings.
            <br />
            To use your own API key instead (BYOK), add{' '}
            <code className="text-[11px]">ANTHROPIC_API_KEY=…</code> to{' '}
            <code className="text-[11px]">~/.zylch/profiles/&lt;uid&gt;/.env</code> after
            this setup, or flip the toggle in Settings → LLM.
          </div>

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
