/**
 * Onboarding screen — shown when FirebaseAuthGate has a signed-in user
 * but no UID-keyed profile dir exists on disk for them. No sidecar is
 * attached to the window yet; the wizard writes
 * `~/.zylch/profiles/<firebase_uid>/.env` from main via
 * `onboarding.createProfileForFirebaseUser`, then `finalize` attaches a
 * sidecar to THIS window in-place (preserving Firebase auth state — no
 * second signin), and finally `onReady` signals the gate to transition
 * into the bound app.
 *
 * Two steps:
 *   1. 'form'    — every editable schema field (mirrors Settings); the
 *                  user fills what they want, only IMAP/SMTP fields are
 *                  required for the email-sync features. On submit we
 *                  create + finalize, which gives THIS window a live
 *                  sidecar bound to the new profile.
 *   2. 'connect' — Google Calendar OAuth (now that the sidecar is up
 *                  and the engine can run the PKCE flow). Skip with
 *                  "Continue to app" if the user doesn't want it now.
 */
import { useEffect, useMemo, useState } from 'react'
import { errorMessage } from '../lib/errors'
import { auth } from '../firebase/config'
import { performSignOut } from '../App'
import ProfileFormFields from '../components/ProfileFormFields'
import ConnectGoogleCalendar from './ConnectGoogleCalendar'
import ConnectWhatsApp from './ConnectWhatsApp'

interface OnboardingProps {
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

type Step = 'form' | 'connect'

export default function Onboarding({ onReady }: OnboardingProps = {}): JSX.Element {
  const firebaseUser = auth.currentUser
  const firebaseUid = firebaseUser?.uid || ''
  const firebaseEmail = firebaseUser?.email || ''

  const [step, setStep] = useState<Step>('form')
  // Profile created during step 1 — just for the "Continue" callback.
  const [createdProfile, setCreatedProfile] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  // All schema-driven values, keyed by the field's key. Pre-seed
  // EMAIL_ADDRESS from Firebase + default IMAP/SMTP ports.
  const [values, setValues] = useState<Record<string, string>>(() => ({
    EMAIL_ADDRESS: firebaseEmail,
    IMAP_PORT: '993',
    SMTP_PORT: '587'
  }))

  // Auto-fill IMAP/SMTP hosts when the user types a valid email — only
  // if they haven't already typed a host themselves (don't clobber).
  useEffect(() => {
    const email = values.EMAIL_ADDRESS || ''
    if (!email || !isValidEmail(email)) return
    const inferred = inferHosts(email)
    setValues((prev) => ({
      ...prev,
      IMAP_HOST: prev.IMAP_HOST || inferred.imapHost,
      SMTP_HOST: prev.SMTP_HOST || inferred.smtpHost
    }))
  }, [values.EMAIL_ADDRESS])

  const setField = (key: string, v: string): void => {
    setValues((prev) => ({ ...prev, [key]: v }))
  }

  // The minimum required to launch — IMAP-side only. Optional groups
  // (Telegram, MrCall, personal data, notes) are all… optional.
  const canSubmit = useMemo(() => {
    if (!isValidEmail(values.EMAIL_ADDRESS || '')) return false
    if (!(values.EMAIL_PASSWORD || '').trim()) return false
    if (!(values.IMAP_HOST || '').trim() || !(values.SMTP_HOST || '').trim()) return false
    if (!(values.IMAP_PORT || '').trim() || !(values.SMTP_PORT || '').trim()) return false
    return true
  }, [values])

  const handleSubmit = async (): Promise<void> => {
    if (!canSubmit || submitting) return
    setSubmitting(true)
    setFormError(null)

    // Strip empty values so we don't write empty .env keys for fields
    // the user didn't touch. The engine's settings_io quotes everything
    // it gets, so an empty string would still be persisted.
    const payload: Record<string, string> = {}
    for (const [k, v] of Object.entries(values)) {
      if (v && v.trim()) payload[k] = v
    }
    // Trim whitespace on IMAP fields specifically — paste artifacts.
    for (const k of ['EMAIL_ADDRESS', 'IMAP_HOST', 'IMAP_PORT', 'SMTP_HOST', 'SMTP_PORT']) {
      if (payload[k]) payload[k] = payload[k].trim()
    }

    try {
      let r:
        | { ok: true; profile: string }
        | { ok: false; error: string }
      if (firebaseUid && firebaseEmail) {
        r = await window.zylch.onboarding.createProfileForFirebaseUser(
          firebaseUid,
          (payload.EMAIL_ADDRESS || firebaseEmail).trim(),
          payload
        )
      } else {
        // Path B: legacy email-keyed profile (FirebaseAuthGate is off
        // or the user object went missing). Kept as a safety net.
        r = await window.zylch.onboarding.createProfile(
          (payload.EMAIL_ADDRESS || '').trim(),
          payload
        )
      }
      if (!r.ok) {
        setFormError(r.error || 'Failed to create profile')
        setSubmitting(false)
        return
      }
      // Attach a sidecar to THIS window in-place. Same renderer
      // context, so Firebase auth state survives.
      const fin = await window.zylch.onboarding.finalize(r.profile)
      if (!fin.ok) {
        setFormError('Profile created but failed to attach the sidecar.')
        setSubmitting(false)
        return
      }
      setCreatedProfile(r.profile)
      setSubmitting(false)
      setStep('connect')
    } catch (e: unknown) {
      setFormError(errorMessage(e))
      setSubmitting(false)
    }
  }

  const handleContinue = (): void => {
    if (onReady) onReady(createdProfile)
  }

  return (
    <div className="min-h-screen w-full flex items-start justify-center bg-brand-light-grey p-6 overflow-auto">
      <div className="w-full max-w-[640px]">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold text-brand-black">Welcome to MrCall Desktop</h1>
            <p className="text-sm text-brand-grey-80 mt-1">
              {step === 'form'
                ? 'Set up your profile. All data stays on this machine.'
                : 'Optional integrations — connect now or later from Settings.'}
            </p>
            {firebaseEmail && (
              <p className="text-xs text-brand-grey-80 mt-2">
                Signed in as <strong>{firebaseEmail}</strong>
                <span className="ml-1 opacity-60">(uid {firebaseUid.slice(0, 8)}…)</span>
              </p>
            )}
          </div>
          {firebaseUser && step === 'form' && (
            <button
              type="button"
              onClick={() => performSignOut()}
              className="px-2 py-1 text-xs text-brand-grey-80 hover:text-brand-black border rounded shrink-0"
            >
              Sign out
            </button>
          )}
        </div>

        {formError && step === 'form' && (
          <div className="mb-3 p-2 bg-brand-danger/10 border border-brand-danger/30 text-brand-danger rounded text-sm whitespace-pre-wrap">
            {formError}
          </div>
        )}

        {step === 'form' ? (
          <div className="bg-white border border-brand-mid-grey rounded-lg shadow-sm p-5">
            <p className="text-xs text-brand-grey-80 mb-4">
              Email + IMAP/SMTP fields are required to launch — everything else is optional and
              can be edited later in Settings.
            </p>
            <ProfileFormFields values={values} onChange={setField} />
            <div className="flex items-center justify-end gap-2 pt-4 mt-4 border-t">
              <button
                onClick={handleSubmit}
                disabled={!canSubmit || submitting}
                className="px-4 py-2 text-sm bg-brand-black text-white rounded disabled:bg-brand-mid-grey"
              >
                {submitting ? 'Creating…' : 'Create profile and continue'}
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <ConnectGoogleCalendar />
            <ConnectWhatsApp />
            <p className="text-xs text-brand-grey-80">
              You can also connect / disconnect from Settings → Integrations any time.
            </p>
            <div className="flex items-center justify-end pt-2">
              <button
                onClick={handleContinue}
                className="px-4 py-2 text-sm bg-brand-black text-white rounded"
              >
                Continue to app
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
