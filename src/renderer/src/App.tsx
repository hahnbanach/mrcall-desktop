import { useEffect, useState } from 'react'
import Dashboard from './views/Dashboard'
import Chat from './views/Chat'
import Update from './views/Update'
import Emails from './views/Emails'
import Settings from './views/Settings'
import { ConversationsProvider } from './store/conversations'
import { ThreadProvider, useThread } from './store/thread'
import { profileColor } from './lib/profileColor'
import type { SidecarStatusEvent } from './types'
import { errorMessage, isProfileLockedError } from './lib/errors'
import './types'

type View = 'dashboard' | 'chat' | 'emails' | 'update' | 'settings'

// Banner shown at the top of the window when the sidecar is dead. The
// most common case is a profile lock: the user opened a second window on
// a profile already in use, the Python child detected the lock and
// exited immediately. Without this banner the user only sees a cryptic
// "sidecar not running" toast on the next RPC.
function SidecarStatusBanner(): JSX.Element | null {
  const [status, setStatus] = useState<SidecarStatusEvent | null>(null)

  useEffect(() => {
    const off = window.zylch.onSidecarStatus((s) => {
      // Clear the banner once we hear the sidecar is alive again.
      if (s.alive) {
        setStatus(null)
      } else {
        setStatus(s)
      }
    })
    return off
  }, [])

  if (!status || status.alive) return null

  const isLock = status.code === 'profile_locked'
  const icon = isLock ? '[LOCK]' : '[!]'
  return (
    <div
      role="alert"
      className={
        'flex items-center gap-3 px-4 py-2 text-sm border-b ' +
        (isLock
          ? 'bg-amber-50 border-amber-300 text-amber-900'
          : 'bg-red-50 border-red-300 text-red-900')
      }
    >
      <span className="font-mono text-xs">{icon}</span>
      <div className="flex-1">
        <div className="font-medium">{status.message}</div>
        {status.hint && <div className="text-xs opacity-80">{status.hint}</div>}
      </div>
      <button
        onClick={() => window.close()}
        className="px-2 py-1 rounded border text-xs hover:bg-white/50"
      >
        Close window
      </button>
    </div>
  )
}

// Small modal listing all available profiles. Clicking one opens a new
// Electron BrowserWindow bound to that profile. If the profile is already
// locked by another session, the new window's sidecar will error out and
// rpc:calls there will fail with a clear message — this dialog does not
// pre-check lock state.
function ProfilePickerDialog({
  open,
  onClose
}: {
  open: boolean
  onClose: () => void
}): JSX.Element | null {
  const [profiles, setProfiles] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError(null)
    window.zylch.profiles
      .list()
      .then((list) => {
        if (!cancelled) setProfiles(list)
      })
      .catch((e) => {
        if (cancelled) return
        // Profile-locked: covered by the top banner; don't double up.
        if (isProfileLockedError(e)) {
          setError(null)
        } else {
          setError(errorMessage(e))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open])

  if (!open) return null

  const choose = async (email: string): Promise<void> => {
    try {
      const r = await window.zylch.window.openForProfile(email)
      if (!r.ok) {
        setError(`Failed to open window for ${email}`)
        return
      }
      onClose()
    } catch (e) {
      if (isProfileLockedError(e)) {
        setError(null)
      } else {
        setError(errorMessage(e))
      }
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl p-5 w-[420px] max-h-[80vh] overflow-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold">Open Profile in New Window</h2>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-900 text-lg leading-none"
            aria-label="Close"
          >
            x
          </button>
        </div>
        {loading && <div className="text-sm text-slate-500">Loading profiles...</div>}
        {error && <div className="text-sm text-red-600 mb-2">{error}</div>}
        {!loading && profiles.length === 0 && (
          <div className="text-sm text-slate-500">
            No profiles found. Run <code>zylch init</code> first.
          </div>
        )}
        <ul className="flex flex-col gap-1">
          {profiles.map((email) => {
            const c = profileColor(email)
            return (
              <li key={email}>
                <button
                  onClick={() => choose(email)}
                  className="w-full text-left px-3 py-2 rounded border hover:bg-slate-50 flex items-center gap-2"
                  style={{ borderColor: c.css }}
                >
                  <span
                    className="inline-block w-3 h-3 rounded-full"
                    style={{ backgroundColor: c.css }}
                  />
                  <span className="font-mono text-sm">{email}</span>
                </button>
              </li>
            )
          })}
        </ul>
        <p className="text-xs text-slate-500 mt-3">
          If the profile is already in use by another session, the new window will display an
          error.
        </p>
      </div>
    </div>
  )
}

function AppInner(): JSX.Element {
  const [view, setView] = useState<View>('dashboard')
  const [profileEmail, setProfileEmail] = useState<string>('')
  const [pickerOpen, setPickerOpen] = useState(false)
  const { setActiveThreadId, setActiveTaskId } = useThread()

  // Resolve the active profile once on mount, derive the accent colour, and
  // publish it as CSS custom properties so any component can theme itself
  // via `var(--profile-accent)` / `var(--profile-accent-soft)`. With
  // per-window sidecars, `profile.current()` returns the profile of THIS
  // window's sidecar (resolved via event.sender in main), so each window
  // gets its own accent.
  useEffect(() => {
    let cancelled = false
    window.zylch.profile
      .current()
      .then((email) => {
        if (cancelled) return
        const safe = email || ''
        setProfileEmail(safe)
        const c = profileColor(safe)
        const root = document.documentElement
        root.style.setProperty('--profile-accent', c.css)
        root.style.setProperty('--profile-accent-soft', c.cssBg)
        document.title = safe ? `Zylch - ${safe}` : 'Zylch'
      })
      .catch((e) => console.error('[App] profile.current failed', e))
    return () => {
      cancelled = true
    }
  }, [])

  // Native menu "File > New Window for Profile..." asks the renderer to
  // open the picker dialog.
  useEffect(() => {
    const off = window.zylch.onOpenProfilePicker(() => setPickerOpen(true))
    return off
  }, [])

  const tabs: { id: View; label: string }[] = [
    { id: 'dashboard', label: 'Dashboard' },
    { id: 'chat', label: 'Chat' },
    { id: 'emails', label: 'Email' },
    { id: 'update', label: 'Update' },
    { id: 'settings', label: 'Settings' }
  ]
  return (
    <div className="flex flex-col h-full">
      <SidecarStatusBanner />
      <nav
        className="flex items-center gap-2 px-4 py-2 border-b"
        style={{
          backgroundColor: 'var(--profile-accent-soft)',
          borderBottomColor: 'var(--profile-accent)',
          borderBottomWidth: 2
        }}
      >
        <span className="font-semibold text-lg mr-6">Zylch</span>
        {tabs.map((t) => {
          const active = view === t.id
          return (
            <button
              key={t.id}
              onClick={() => setView(t.id)}
              className={
                'px-3 py-1.5 rounded text-sm transition-colors ' +
                (active ? 'text-white' : 'text-slate-700 hover:bg-white/60')
              }
              style={
                active
                  ? { backgroundColor: 'var(--profile-accent)' }
                  : undefined
              }
            >
              {t.label}
            </button>
          )
        })}
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setPickerOpen(true)}
            title="Open another profile in a new window"
            className="px-2 py-1 rounded text-xs border hover:bg-white/60"
            style={{
              borderColor: 'var(--profile-accent)',
              color: 'var(--profile-accent)'
            }}
          >
            + New Window
          </button>
          {profileEmail && (
            <span
              className="text-xs font-mono px-2 py-1 rounded border"
              style={{
                backgroundColor: 'var(--profile-accent-soft)',
                borderColor: 'var(--profile-accent)',
                color: 'var(--profile-accent)'
              }}
              title="Active profile"
            >
              {profileEmail}
            </span>
          )}
        </div>
      </nav>
      <main className="flex-1 overflow-auto">
        {view === 'dashboard' && (
          <Dashboard
            onOpenChat={() => setView('chat')}
            onOpenEmails={(threadId, taskId) => {
              setActiveThreadId(threadId)
              setActiveTaskId(taskId ?? null)
              setView('emails')
            }}
          />
        )}
        {view === 'chat' && <Chat onGoToDashboard={() => setView('dashboard')} />}
        {view === 'emails' && <Emails />}
        {view === 'update' && <Update />}
        {view === 'settings' && <Settings />}
      </main>
      <ProfilePickerDialog open={pickerOpen} onClose={() => setPickerOpen(false)} />
    </div>
  )
}

export default function App(): JSX.Element {
  return (
    <ConversationsProvider>
      <ThreadProvider>
        <AppInner />
      </ThreadProvider>
    </ConversationsProvider>
  )
}
