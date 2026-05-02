/**
 * Firebase signin screen — email/password and "Continue with Google".
 *
 * Email/password signin is handled entirely in the renderer by the
 * Firebase JS SDK. Google signin runs a PKCE OAuth flow in the Electron
 * main process (no Python sidecar exists yet in onboarding mode), which
 * returns a Google id_token; we then hand it to Firebase via
 * `signInWithCredential` so the auth state graduates the user past
 * `FirebaseAuthGate`. Magic links remain deferred.
 *
 * Successful signin is observed by FirebaseAuthGate via
 * onAuthStateChanged — this component does not push the user up itself.
 */
import { useState } from 'react'
import {
  createUserWithEmailAndPassword,
  GoogleAuthProvider,
  sendPasswordResetEmail,
  signInWithCredential,
  signInWithEmailAndPassword
} from 'firebase/auth'
import { auth } from '../firebase/config'
import mrcallIcon from '../assets/logos/mrcall-icon.png'
import mrcallWordmark from '../assets/logos/mrcall-wordmark.png'

type Mode = 'signin' | 'signup' | 'reset'

function describeFirebaseError(code: string | undefined): string {
  switch (code) {
    case 'auth/invalid-email':
      return 'That email address looks malformed.'
    case 'auth/user-not-found':
    case 'auth/invalid-credential':
    case 'auth/wrong-password':
      return 'Email or password is incorrect.'
    case 'auth/email-already-in-use':
      return 'An account already exists for that email — try signing in instead.'
    case 'auth/weak-password':
      return 'Password too weak — use at least 6 characters.'
    case 'auth/too-many-requests':
      return 'Too many attempts. Wait a minute and try again.'
    case 'auth/network-request-failed':
      return 'Network error reaching Firebase. Check your connection.'
    case 'auth/account-exists-with-different-credential':
      return 'An account with this email already exists with a different sign-in method. Try signing in with email/password instead.'
    case 'auth/popup-closed-by-user':
    case 'auth/cancelled-popup-request':
      return 'Sign-in was cancelled before completing.'
    default:
      return code ? `Firebase error (${code}).` : 'Sign-in failed. Try again.'
  }
}

export default function SignIn(): JSX.Element {
  const [mode, setMode] = useState<Mode>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [googleBusy, setGoogleBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)

  // "Continue with Google" runs the PKCE flow in the main process,
  // hands us back a Google id_token, and we trade it for a Firebase
  // session via signInWithCredential. The browser tab handles the
  // user-facing consent UX; we just show busy state.
  const onGoogleClick = async (): Promise<void> => {
    if (googleBusy) return
    setError(null)
    setInfo(null)
    setGoogleBusy(true)
    setInfo('Opening Google sign-in in your browser…')
    try {
      const r = await window.zylch.signin.googleStart()
      if (!r.ok || !r.idToken) {
        setInfo(null)
        setError(r.error || 'Google sign-in failed.')
        return
      }
      setInfo('Signing in to Firebase…')
      const credential = GoogleAuthProvider.credential(r.idToken)
      await signInWithCredential(auth, credential)
      // FirebaseAuthGate observes onAuthStateChanged and unmounts us.
      setInfo(null)
    } catch (e: unknown) {
      const code = (e as { code?: string }).code
      setInfo(null)
      setError(describeFirebaseError(code))
    } finally {
      setGoogleBusy(false)
    }
  }

  const submit = async (): Promise<void> => {
    if (busy) return
    setError(null)
    setInfo(null)
    const trimmedEmail = email.trim()
    if (!trimmedEmail) {
      setError('Email is required.')
      return
    }
    setBusy(true)
    try {
      if (mode === 'signin') {
        await signInWithEmailAndPassword(auth, trimmedEmail, password)
        // FirebaseAuthGate will react to onAuthStateChanged.
      } else if (mode === 'signup') {
        if (password.length < 6) {
          setError('Password must be at least 6 characters.')
          setBusy(false)
          return
        }
        await createUserWithEmailAndPassword(auth, trimmedEmail, password)
      } else {
        await sendPasswordResetEmail(auth, trimmedEmail)
        setInfo('Password reset email sent. Check your inbox.')
        setMode('signin')
      }
    } catch (e: unknown) {
      const code = (e as { code?: string }).code
      setError(describeFirebaseError(code))
    } finally {
      setBusy(false)
    }
  }

  const onKey = (e: React.KeyboardEvent): void => {
    if (e.key === 'Enter') submit()
  }

  return (
    <div className="min-h-screen w-full flex items-start justify-center bg-brand-light-grey p-6 overflow-auto">
      <div className="w-full max-w-[420px] mt-10">
        <div className="flex items-center gap-3 mb-6">
          <img src={mrcallIcon} alt="" aria-hidden="true" className="w-9 h-9 shrink-0" />
          <img src={mrcallWordmark} alt="MrCall Desktop" className="h-6 w-auto" />
        </div>

        <h1 className="text-2xl font-semibold text-brand-black">
          {mode === 'signup'
            ? 'Create your MrCall account'
            : mode === 'reset'
              ? 'Reset your password'
              : 'Sign in to MrCall'}
        </h1>
        <p className="text-sm text-brand-grey-80 mt-1 mb-5">
          {mode === 'reset'
            ? "Enter your account email and we'll send a reset link."
            : 'Use the same account as the MrCall dashboard. Your account identity is shared; the data on this machine stays local.'}
        </p>

        {error && (
          <div className="mb-3 p-2 bg-brand-danger/10 border border-brand-danger/30 text-brand-danger rounded text-sm">
            {error}
          </div>
        )}
        {info && (
          <div className="mb-3 p-2 bg-brand-blue/10 border border-brand-blue/30 text-brand-blue rounded text-sm">
            {info}
          </div>
        )}

        <div className="bg-white border border-brand-mid-grey rounded-lg shadow-sm p-5 space-y-3">
          {mode !== 'reset' && (
            <>
              <button
                onClick={onGoogleClick}
                disabled={googleBusy || busy}
                className="w-full px-4 py-2 text-sm bg-white border border-brand-mid-grey rounded hover:bg-brand-light-grey disabled:opacity-60 disabled:cursor-not-allowed text-brand-black"
                aria-label="Continue with Google"
              >
                {googleBusy ? 'Waiting for Google…' : 'Continue with Google'}
              </button>
              <div className="flex items-center gap-2 text-[11px] text-brand-grey-80 uppercase tracking-wide">
                <span className="flex-1 h-px bg-brand-mid-grey" />
                <span>or</span>
                <span className="flex-1 h-px bg-brand-mid-grey" />
              </div>
            </>
          )}
          <div>
            <label className="block text-xs font-medium text-brand-grey-80 mb-1">
              Email address
            </label>
            <input
              type="email"
              value={email}
              autoComplete="email"
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={onKey}
              className="w-full px-3 py-2 border rounded text-sm"
              placeholder="user@example.com"
            />
          </div>

          {mode !== 'reset' && (
            <div>
              <label className="block text-xs font-medium text-brand-grey-80 mb-1">Password</label>
              <input
                type="password"
                value={password}
                autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={onKey}
                className="w-full px-3 py-2 border rounded text-sm"
              />
            </div>
          )}

          <div className="pt-2">
            <button
              onClick={submit}
              disabled={busy}
              className="w-full px-4 py-2 text-sm bg-brand-black text-white rounded disabled:bg-brand-mid-grey"
            >
              {busy
                ? 'Working…'
                : mode === 'signup'
                  ? 'Create account'
                  : mode === 'reset'
                    ? 'Send reset link'
                    : 'Sign in'}
            </button>
          </div>

          <div className="flex items-center justify-between pt-1 text-xs">
            {mode === 'signin' && (
              <>
                <button
                  className="text-brand-blue hover:underline"
                  onClick={() => {
                    setMode('signup')
                    setError(null)
                    setInfo(null)
                  }}
                >
                  Create an account
                </button>
                <button
                  className="text-brand-grey-80 hover:underline"
                  onClick={() => {
                    setMode('reset')
                    setError(null)
                    setInfo(null)
                  }}
                >
                  Forgot password?
                </button>
              </>
            )}
            {(mode === 'signup' || mode === 'reset') && (
              <button
                className="text-brand-grey-80 hover:underline"
                onClick={() => {
                  setMode('signin')
                  setError(null)
                  setInfo(null)
                }}
              >
                Back to sign in
              </button>
            )}
          </div>
        </div>

        <p className="text-xs text-brand-grey-80 mt-4">
          Continue with Google opens your default browser for consent and brings you back here
          automatically. Magic links arrive in a follow-up release. Either path unlocks the
          MrCall phone integration.
        </p>
      </div>
    </div>
  )
}
