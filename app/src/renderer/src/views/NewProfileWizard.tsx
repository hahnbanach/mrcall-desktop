/**
 * Full-page wizard to create an additional profile from an
 * already-signed-in window. Same fields and visual as Onboarding, but
 * submits via `profiles.create` (email-keyed) so the new profile
 * coexists with the current one without taking over this window's
 * sidecar. Google Calendar Connect doesn't apply here — it would
 * connect against the current window's sidecar, not the new profile;
 * the user finishes that from inside the new profile's window.
 */
import { useEffect, useMemo, useState } from 'react'
import { errorMessage } from '../lib/errors'
import ProfileFormFields from '../components/ProfileFormFields'

interface Props {
  open: boolean
  onClose: () => void
  onCreated: (email: string) => void
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

export default function NewProfileWizard({ open, onClose, onCreated }: Props): JSX.Element | null {
  const [values, setValues] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  // Reset on open so a previous attempt's leftovers don't leak into a
  // fresh run.
  useEffect(() => {
    if (!open) return
    setValues({ IMAP_PORT: '993', SMTP_PORT: '587' })
    setFormError(null)
    setSubmitting(false)
  }, [open])

  // Auto-fill IMAP/SMTP hosts from the email domain — don't clobber
  // user-typed values.
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

  const canSubmit = useMemo(() => {
    if (!isValidEmail(values.EMAIL_ADDRESS || '')) return false
    if (!(values.EMAIL_PASSWORD || '').trim()) return false
    if (!(values.IMAP_HOST || '').trim() || !(values.SMTP_HOST || '').trim()) return false
    if (!(values.IMAP_PORT || '').trim() || !(values.SMTP_PORT || '').trim()) return false
    return true
  }, [values])

  if (!open) return null

  const handleSubmit = async (): Promise<void> => {
    if (!canSubmit || submitting) return
    setSubmitting(true)
    setFormError(null)
    const payload: Record<string, string> = {}
    for (const [k, v] of Object.entries(values)) {
      if (v && v.trim()) payload[k] = v
    }
    for (const k of ['EMAIL_ADDRESS', 'IMAP_HOST', 'IMAP_PORT', 'SMTP_HOST', 'SMTP_PORT']) {
      if (payload[k]) payload[k] = payload[k].trim()
    }
    try {
      const r = await window.zylch.profiles.create(payload.EMAIL_ADDRESS, payload)
      if (!r.ok) {
        setFormError('Server returned ok=false')
        setSubmitting(false)
        return
      }
      onCreated(r.profile)
    } catch (e: unknown) {
      setFormError(errorMessage(e))
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 min-h-screen w-full flex items-start justify-center bg-brand-light-grey p-6 overflow-auto">
      <div className="w-full max-w-[640px]">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold text-brand-black">Create a new profile</h1>
            <p className="text-sm text-brand-grey-80 mt-1">
              Add another mailbox to MrCall Desktop. Open the new profile in its own window to
              connect Google Calendar.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="px-2 py-1 text-xs text-brand-grey-80 hover:text-brand-black border rounded shrink-0 disabled:opacity-50"
          >
            Cancel
          </button>
        </div>

        {formError && (
          <div className="mb-3 p-2 bg-brand-danger/10 border border-brand-danger/30 text-brand-danger rounded text-sm whitespace-pre-wrap">
            {formError}
          </div>
        )}

        <div className="bg-white border border-brand-mid-grey rounded-lg shadow-sm p-5">
          <p className="text-xs text-brand-grey-80 mb-4">
            Email + IMAP/SMTP fields are required — everything else is optional and editable
            later from the new profile&apos;s Settings tab.
          </p>
          <ProfileFormFields values={values} onChange={setField} />
          <div className="flex items-center justify-end gap-2 pt-4 mt-4 border-t">
            <button
              onClick={handleSubmit}
              disabled={!canSubmit || submitting}
              className="px-4 py-2 text-sm bg-brand-black text-white rounded disabled:bg-brand-mid-grey"
            >
              {submitting ? 'Creating…' : 'Create profile'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
