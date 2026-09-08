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
import { performSignOut, installEngineTokenPusher } from '../App'
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
  // Default unknown domains to Google. Most custom domains are on Google
  // Workspace (e.g. @mrcall.ai — MX aspmx.l.google.com), whose mail is at
  // imap.gmail.com / smtp.gmail.com. The old `imap.<domain>` guess was
  // almost always a non-existent host (NXDOMAIN → sync failed). The field
  // stays editable for the rare self-hosted case.
  return { imapHost: 'imap.gmail.com', smtpHost: 'smtp.gmail.com' }
}

function isValidEmail(s: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s.trim())
}

// 'memory' sits between 'form' and 'connect': it needs the sidecar, which
// exists only after `finalize`. The engine mints the company memory key at
// first boot; a key pasted at the form step is acted on here — previewed
// (the echo: whose memory, how big), then joined — never written at
// creation, because a typed key the engine cannot vouch for must not
// silently open (or create) a store.
type Step = 'form' | 'memory' | 'connect'

type MemoryState =
  | { kind: 'busy'; text: string }
  | { kind: 'minted'; key: string }
  | { kind: 'preview'; key: string; echo: string }
  | { kind: 'refused'; key: string; text: string }
  | { kind: 'joined'; text: string }

export default function Onboarding({ onReady }: OnboardingProps = {}): JSX.Element {
  const firebaseUser = auth.currentUser
  const firebaseUid = firebaseUser?.uid || ''
  const firebaseEmail = firebaseUser?.email || ''

  const [step, setStep] = useState<Step>('form')
  // Profile created during step 1 — just for the "Continue" callback.
  const [createdProfile, setCreatedProfile] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  // The optional memory key pasted at the form step (kept out of `values`:
  // it is never part of the creation payload) and the memory step's state.
  const [pastedMemoryKey, setPastedMemoryKey] = useState('')
  const [memoryState, setMemoryState] = useState<MemoryState>({ kind: 'busy', text: '' })
  const [copied, setCopied] = useState(false)

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

  // Nothing is required to launch — the user is already signed in via
  // Firebase (MrCall + Calendar work off that). Email is opt-in: only if
  // the user starts configuring it (enters an app password) do we
  // require the full IMAP/SMTP set, so we never persist a broken
  // half-config.
  const emailStarted = !!(values.EMAIL_PASSWORD || '').trim()
  const canSubmit = useMemo(() => {
    if (emailStarted) {
      if (!isValidEmail(values.EMAIL_ADDRESS || '')) return false
      if (!(values.IMAP_HOST || '').trim() || !(values.SMTP_HOST || '').trim()) return false
      if (!(values.IMAP_PORT || '').trim() || !(values.SMTP_PORT || '').trim()) return false
    }
    return true
  }, [values, emailStarted])

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
    // Email is opt-in. Without an app password, drop the (possibly
    // auto-inferred) IMAP/SMTP fields so we don't persist a half-config
    // that lights up the Email tab. EMAIL_ADDRESS stays — it's the
    // Firebase email, used for display.
    if (!(payload.EMAIL_PASSWORD || '').trim()) {
      for (const k of ['EMAIL_PASSWORD', 'IMAP_HOST', 'IMAP_PORT', 'SMTP_HOST', 'SMTP_PORT']) {
        delete payload[k]
      }
    }

    try {
      // FirebaseAuthGate is the only mount path for this component, so
      // a Firebase user is always present here. The profile dir is
      // keyed by their immutable UID.
      if (!firebaseUid || !firebaseEmail) {
        setFormError('Lost Firebase session. Sign in again.')
        setSubmitting(false)
        return
      }
      const r = await window.zylch.onboarding.createProfileForFirebaseUser(
        firebaseUid,
        (payload.EMAIL_ADDRESS || firebaseEmail).trim(),
        payload
      )
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
      // The sidecar is now attached, but the token pusher was left unset
      // during onboarding (no RPC channel existed when the auth gate ran).
      // Wire it + push the Firebase token now so the 'connect' step's
      // Google Calendar RPC sees a live session instead of failing with
      // "engine isn't seeing your Firebase session".
      await installEngineTokenPusher()
      setCreatedProfile(r.profile)
      setSubmitting(false)
      setStep('memory')
      void runMemoryStep(pastedMemoryKey.trim())
    } catch (e: unknown) {
      setFormError(errorMessage(e))
      setSubmitting(false)
    }
  }

  // Mint-or-join. Empty field: the engine already minted at first boot,
  // key_mint returns it — the show-once moment. Pasted key: preview first
  // (refuse an unknown key, echo a known one), join only on confirmation.
  const runMemoryStep = async (key: string): Promise<void> => {
    if (!key) {
      setMemoryState({ kind: 'busy', text: 'Creating your company memory…' })
      try {
        const r = await window.zylch.memory.keyMint()
        setMemoryState({ kind: 'minted', key: r.key })
      } catch (e) {
        setMemoryState({ kind: 'refused', key: '', text: errorMessage(e) })
      }
      return
    }
    setMemoryState({ kind: 'busy', text: 'Looking up that memory…' })
    try {
      const r = await window.zylch.memory.joinPreview(key)
      if (!r.well_formed) {
        setMemoryState({ kind: 'refused', key, text: `Not a memory key: ${r.reason}.` })
        return
      }
      if (!r.exists) {
        setMemoryState({
          kind: 'refused',
          key,
          text: 'No company memory exists for this key on this engine. Check it with whoever gave it to you.'
        })
        return
      }
      const who = (r.contributors || []).length
      setMemoryState({
        kind: 'preview',
        key,
        echo: `${r.self_notion ? `“${r.self_notion}”` : 'Company self-notion not set'} · ${
          r.blob_count ?? 0
        } memory entries · ${who} contributing account${who === 1 ? '' : 's'}`
      })
    } catch (e) {
      setMemoryState({ kind: 'refused', key, text: errorMessage(e) })
    }
  }

  const handleJoin = async (key: string): Promise<void> => {
    setMemoryState({ kind: 'busy', text: 'Joining…' })
    try {
      const r = await window.zylch.memory.join(key)
      if (!r.ok) {
        setMemoryState({ kind: 'refused', key, text: r.reason || 'Join refused.' })
        return
      }
      setMemoryState({ kind: 'joined', text: 'Joined. This account now shares that company memory.' })
    } catch (e) {
      setMemoryState({ kind: 'refused', key, text: errorMessage(e) })
    }
  }

  const copyMintedKey = async (key: string): Promise<void> => {
    try {
      await navigator.clipboard.writeText(key)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* ignore — some platforms gate clipboard without user gesture */
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
                : step === 'memory'
                  ? 'Company memory — yours, or one you join.'
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
              Everything here is optional — you're already signed in, so MrCall and Calendar work
              right away. Add email only if you want inbox sync; the rest can be set later in
              Settings.
            </p>
            <ProfileFormFields
              values={values}
              onChange={setField}
              includeGroups={['Email', 'Personal data', 'Documents & notes']}
            />
            <div className="pt-4 mt-4 border-t">
              <label className="block text-xs font-semibold text-brand-black" htmlFor="memory-key">
                Memory key <span className="font-normal text-brand-grey-80">(optional)</span>
              </label>
              <p className="text-xs text-brand-grey-80 mt-1 mb-2">
                Paste it if a colleague gave you one, to share their company memory. Leave it
                empty to start a memory of your own — you will get a key to hand out.
              </p>
              <input
                id="memory-key"
                type="text"
                value={pastedMemoryKey}
                onChange={(e) => setPastedMemoryKey(e.target.value)}
                spellCheck={false}
                autoComplete="off"
                placeholder="Memory key"
                className="w-full text-sm font-mono border border-brand-mid-grey rounded px-2 py-1"
              />
            </div>
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
        ) : step === 'memory' ? (
          <div className="bg-white border border-brand-mid-grey rounded-lg shadow-sm p-5 space-y-4">
            {memoryState.kind === 'busy' && (
              <p className="text-sm text-brand-grey-80">{memoryState.text}</p>
            )}
            {memoryState.kind === 'minted' && (
              <>
                <p className="text-sm text-brand-black">
                  This is your company memory key. Every account that holds it shares this
                  memory — copy it and hand it to colleagues the way you would a Wi-Fi password.
                  It stays in Settings, so you can copy it again later.
                </p>
                <div className="flex items-center gap-2">
                  <code className="text-sm font-mono select-all break-all text-brand-black">
                    {memoryState.key}
                  </code>
                  <button
                    type="button"
                    onClick={() => copyMintedKey(memoryState.key)}
                    className="px-2 py-1 text-xs border rounded text-brand-grey-80 hover:text-brand-black shrink-0"
                  >
                    {copied ? 'Copied' : 'Copy'}
                  </button>
                </div>
              </>
            )}
            {memoryState.kind === 'preview' && (
              <>
                <p className="text-sm text-brand-black">You are about to join an existing company memory:</p>
                <p className="text-sm text-brand-grey-80">{memoryState.echo}</p>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => handleJoin(memoryState.key)}
                    className="px-3 py-1 text-sm bg-brand-black text-white rounded"
                  >
                    Join this memory
                  </button>
                  <button
                    type="button"
                    onClick={() => runMemoryStep('')}
                    className="px-3 py-1 text-sm border rounded text-brand-grey-80 hover:text-brand-black"
                  >
                    Start a memory of my own instead
                  </button>
                </div>
              </>
            )}
            {memoryState.kind === 'refused' && (
              <>
                <p className="text-sm text-brand-danger">{memoryState.text}</p>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    defaultValue={memoryState.key}
                    onChange={(e) => setPastedMemoryKey(e.target.value)}
                    spellCheck={false}
                    placeholder="Memory key"
                    className="flex-1 text-sm font-mono border border-brand-mid-grey rounded px-2 py-1"
                  />
                  <button
                    type="button"
                    onClick={() => runMemoryStep(pastedMemoryKey.trim())}
                    className="px-3 py-1 text-sm border rounded text-brand-grey-80 hover:text-brand-black"
                  >
                    Try again
                  </button>
                  <button
                    type="button"
                    onClick={() => runMemoryStep('')}
                    className="px-3 py-1 text-sm border rounded text-brand-grey-80 hover:text-brand-black"
                  >
                    Start a memory of my own
                  </button>
                </div>
              </>
            )}
            {memoryState.kind === 'joined' && (
              <p className="text-sm text-brand-black">{memoryState.text}</p>
            )}
            <div className="flex items-center justify-end pt-2 border-t">
              <button
                type="button"
                onClick={() => setStep('connect')}
                disabled={memoryState.kind === 'busy' || memoryState.kind === 'preview'}
                className="px-4 py-2 text-sm bg-brand-black text-white rounded disabled:bg-brand-mid-grey"
              >
                Continue
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
