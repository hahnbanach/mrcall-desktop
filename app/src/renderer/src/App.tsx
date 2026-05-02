import { useEffect, useRef, useState } from 'react'
import { signOut, type User } from 'firebase/auth'
import Tasks from './views/Tasks'
import Workspace from './views/Workspace'
import Update from './views/Update'
import Settings from './views/Settings'
import Email from './views/Email'
import NewProfileWizard from './views/NewProfileWizard'
import Onboarding from './views/Onboarding'
import SignIn from './views/SignIn'
import { auth } from './firebase/config'
import { repushTokenForCurrentUser, setupAuthListener, setTokenPusher } from './firebase/authUtils'
import { ConversationsProvider } from './store/conversations'
import { ThreadProvider, useThread } from './store/thread'
import { TasksProvider } from './store/tasks'
import { profileColor } from './lib/profileColor'
import type { SidecarStatusEvent } from './types'
import { errorMessage, isProfileLockedError } from './lib/errors'
import Icon, { type IconName } from './components/Icon'
import mrcallIcon from './assets/logos/mrcall-icon.png'
import mrcallWordmark from './assets/logos/mrcall-wordmark.png'
import './types'

type View = 'tasks' | 'workspace' | 'email' | 'update' | 'settings'

// Banner shown at the top of the window when the sidecar is dead. The
// most common case is a profile lock: the user opened a second window on
// a profile already in use, the Python child detected the lock and
// exited immediately. Without this banner the user only sees a cryptic
// "sidecar not running" toast on the next RPC.
//
// Restart UX (Settings → Save): the main process pushes a
// `code: 'restarting'` event before killing the old child, so we render
// a small blue "Restarting sidecar…" indicator instead of the red crash
// banner. While in this state we ignore exit events (which would
// otherwise race in and re-classify as crashed). If we don't see an
// `alive:true` within RESTART_TIMEOUT_MS we fall back to whatever the
// most recent status said, so a real boot failure still surfaces.
function SidecarStatusBanner(): JSX.Element | null {
  const [status, setStatus] = useState<SidecarStatusEvent | null>(null)
  const [restarting, setRestarting] = useState(false)

  useEffect(() => {
    const RESTART_TIMEOUT_MS = 10_000
    let restartTimer: ReturnType<typeof setTimeout> | null = null
    let restartFlag = false

    const off = window.zylch.onSidecarStatus((s) => {
      if (s.alive) {
        // Sidecar is up. Clear any restart spinner and any prior error.
        if (restartTimer) {
          clearTimeout(restartTimer)
          restartTimer = null
        }
        restartFlag = false
        setRestarting(false)
        setStatus(null)
        return
      }
      // alive === false branch
      if (s.code === 'restarting') {
        restartFlag = true
        setRestarting(true)
        setStatus(s)
        if (restartTimer) clearTimeout(restartTimer)
        // Safety net: if no `alive:true` arrives within 10s we assume
        // the new child is wedged. Drop the spinner so the next status
        // event (or a stale one) renders normally.
        restartTimer = setTimeout(() => {
          restartFlag = false
          setRestarting(false)
        }, RESTART_TIMEOUT_MS)
        return
      }
      // Any other failure event: if we are mid-restart, swallow it —
      // the old child's exit is expected and not a crash. Otherwise
      // surface as the existing crash/lock banner.
      if (restartFlag) return
      setStatus(s)
    })
    return () => {
      if (restartTimer) clearTimeout(restartTimer)
      off()
    }
  }, [])

  // Restart spinner takes priority over any stale "exited" status.
  if (restarting) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex items-center gap-2 px-4 py-1.5 text-xs border-b bg-brand-light-grey border-brand-mid-grey text-brand-grey-80"
      >
        <span
          aria-hidden="true"
          className="inline-block w-3 h-3 border-2 border-brand-mid-grey border-t-transparent rounded-full animate-spin"
        />
        <span>Restarting sidecar…</span>
      </div>
    )
  }

  if (!status || status.alive) return null

  const isLock = status.code === 'profile_locked'
  const icon = isLock ? '[LOCK]' : '[!]'
  return (
    <div
      role="alert"
      className={
        'flex items-center gap-3 px-4 py-2 text-sm border-b ' +
        (isLock
          ? 'bg-brand-orange/10 border-brand-orange/40 text-brand-orange'
          : 'bg-brand-danger/10 border-brand-danger/40 text-brand-danger')
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
            className="text-brand-grey-80 hover:text-brand-black text-lg leading-none"
            aria-label="Close"
          >
            x
          </button>
        </div>
        {loading && <div className="text-sm text-brand-grey-80">Loading profiles...</div>}
        {error && <div className="text-sm text-brand-danger mb-2">{error}</div>}
        {!loading && profiles.length === 0 && (
          <div className="text-sm text-brand-grey-80">
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
                  className="w-full text-left px-3 py-2 rounded border border-brand-mid-grey hover:bg-brand-light-grey flex items-center gap-2"
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
        <p className="text-xs text-brand-grey-80 mt-3">
          If the profile is already in use by another session, the new window will display an
          error.
        </p>
      </div>
    </div>
  )
}

// Lightweight dropdown listing all profiles. Click on a row opens a
// new BrowserWindow bound to that profile via
// `window.zylch.window.openForProfile(email)` — no intermediate modal.
// The current profile is shown but disabled (clicking it would just
// focus a duplicate). Reloads the profile list every time the menu is
// opened, so a brand-new profile created via NewProfileWizard appears
// without a manual refresh.
function ProfilesDropdown({
  currentEmail,
  refreshKey
}: {
  currentEmail: string
  refreshKey: number
}): JSX.Element {
  const [open, setOpen] = useState(false)
  const [profiles, setProfiles] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)

  // Load profiles whenever the menu opens or the parent signals a
  // refresh (e.g. after the wizard creates a new profile while the
  // menu happens to be open — unlikely but cheap to support).
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
  }, [open, refreshKey])

  // Close on outside click or Escape.
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent): void => {
      const node = containerRef.current
      if (node && !node.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const choose = async (email: string): Promise<void> => {
    if (email === currentEmail) return
    try {
      const r = await window.zylch.window.openForProfile(email)
      if (!r.ok) {
        setError(`Failed to open window for ${email}`)
        return
      }
      setOpen(false)
    } catch (e) {
      if (isProfileLockedError(e)) {
        setError(null)
      } else {
        setError(errorMessage(e))
      }
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        title="Open another profile in a new window"
        aria-haspopup="menu"
        aria-expanded={open}
        className="px-2 py-1 rounded text-xs border border-brand-mid-grey text-brand-grey-80 bg-white hover:bg-brand-light-grey text-left flex items-center justify-between"
      >
        <span>Profiles</span>
        <span>{open ? '\u25B4' : '\u25BE'}</span>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute left-0 bottom-full mb-1 min-w-[220px] bg-white border border-brand-mid-grey rounded shadow-lg z-40 py-1"
        >
          {loading && (
            <div className="px-3 py-2 text-xs text-brand-grey-80">Loading profiles...</div>
          )}
          {error && (
            <div className="px-3 py-2 text-xs text-brand-danger">{error}</div>
          )}
          {!loading && profiles.length === 0 && !error && (
            <div className="px-3 py-2 text-xs text-brand-grey-80">
              No profiles found. Run <code>zylch init</code> first.
            </div>
          )}
          {profiles.map((email) => {
            const c = profileColor(email)
            const isCurrent = email === currentEmail
            return (
              <button
                key={email}
                role="menuitem"
                onClick={() => choose(email)}
                disabled={isCurrent}
                className={
                  'w-full text-left px-3 py-2 text-xs flex items-center gap-2 ' +
                  (isCurrent
                    ? 'text-brand-mid-grey cursor-default'
                    : 'text-brand-grey-80 hover:bg-brand-light-grey')
                }
              >
                <span
                  className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
                  style={{ backgroundColor: c.css }}
                />
                <span className="font-mono truncate">{email}</span>
                {isCurrent && (
                  <span className="ml-auto text-[10px] uppercase tracking-wide">
                    current
                  </span>
                )}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

function AppInner(): JSX.Element {
  const [view, setView] = useState<View>('tasks')
  const [profileEmail, setProfileEmail] = useState<string>('')
  const [pickerOpen, setPickerOpen] = useState(false)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [profilesRefreshKey, setProfilesRefreshKey] = useState(0)
  // Email address is required to render the Email nav item (we hide it
  // rather than showing a broken tab when the profile isn't set up for
  // IMAP). Loaded once via settings.get().
  const [hasEmailConfigured, setHasEmailConfigured] = useState<boolean>(false)
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
        document.title = safe ? `MrCall Desktop - ${safe}` : 'MrCall Desktop'
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

  // Detect whether this profile has EMAIL_ADDRESS configured; gates the
  // Email sidebar item. Runs once on mount — a profile edit reloads the
  // sidecar which remounts this whole tree.
  useEffect(() => {
    let cancelled = false
    window.zylch.settings
      .get()
      .then((r) => {
        if (cancelled) return
        const addr = (r.values?.EMAIL_ADDRESS || '').trim()
        setHasEmailConfigured(!!addr)
      })
      .catch(() => {
        /* non-fatal — leave Email hidden */
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="flex flex-col h-full">
      <IdentityBanner />
      <SidecarStatusBanner />
      <div className="flex flex-1 min-h-0">
        <Sidebar
          view={view}
          setView={setView}
          profileEmail={profileEmail}
          hasEmailConfigured={hasEmailConfigured}
          onNewProfile={() => setWizardOpen(true)}
          onOpenProfilePicker={() => setPickerOpen(true)}
          profilesRefreshKey={profilesRefreshKey}
        />
        {/* All views are always mounted; inactive ones are hidden. This
            keeps in-flight state (e.g. Update's running spinner,
            Settings' loaded schema) alive across tab switches so the
            user doesn't come back to a view that's "Loading…" or has
            lost its progress. */}
        <main className="flex-1 overflow-hidden relative">
          <div
            className="absolute inset-0 overflow-auto"
            style={{ display: view === 'tasks' ? 'block' : 'none' }}
          >
            <Tasks
              onOpenWorkspace={(threadId, taskId) => {
                setActiveThreadId(threadId)
                setActiveTaskId(taskId)
                setView('workspace')
              }}
            />
          </div>
          <div
            className="absolute inset-0 overflow-auto"
            style={{ display: view === 'workspace' ? 'block' : 'none' }}
          >
            <Workspace onGoToTasks={() => setView('tasks')} />
          </div>
          {hasEmailConfigured && (
            <div
              className="absolute inset-0 overflow-hidden"
              style={{ display: view === 'email' ? 'block' : 'none' }}
            >
              {/* Clicking "Open" on a thread always navigates to the
                  Tasks view filtered by that thread (via
                  `taskThreadFilter` on the thread store). The target
                  view is the same whether the thread has 0, 1, or many
                  tasks — no direct-open shortcut. */}
              <Email onOpenTasks={() => setView('tasks')} />
            </div>
          )}
          <div
            className="absolute inset-0 overflow-auto"
            style={{ display: view === 'update' ? 'block' : 'none' }}
          >
            <Update />
          </div>
          <div
            className="absolute inset-0 overflow-auto"
            style={{ display: view === 'settings' ? 'block' : 'none' }}
          >
            <Settings />
          </div>
        </main>
      </div>
      <NewProfileWizard
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        onCreated={() => {
          setWizardOpen(false)
          // Bump key so the dropdown reloads its profile list next time
          // it opens (cheap; no harm if it isn't currently open).
          setProfilesRefreshKey((k) => k + 1)
        }}
      />
      <ProfilePickerDialog open={pickerOpen} onClose={() => setPickerOpen(false)} />
    </div>
  )
}

/**
 * Sidebar — left-aligned primary navigation. Replaces the previous top
 * nav bar. Layout (top → bottom):
 *   - profile badge + "+ New Window" button
 *   - nav items (Task / Email [gated] / WhatsApp [placeholder] / MrCall [placeholder])
 *   - divider
 *   - Update / Settings
 *   - profiles footer
 */
function Sidebar({
  view,
  setView,
  profileEmail,
  hasEmailConfigured,
  onNewProfile,
  onOpenProfilePicker,
  profilesRefreshKey
}: {
  view: View
  setView: (v: View) => void
  profileEmail: string
  hasEmailConfigured: boolean
  onNewProfile: () => void
  onOpenProfilePicker: () => void
  profilesRefreshKey: number
}): JSX.Element {
  type NavItem = {
    id: View
    label: string
    icon: IconName
    disabled?: boolean
    disabledTitle?: string
    hidden?: boolean
  }

  const primary: NavItem[] = [
    { id: 'tasks', label: 'Task', icon: 'tasks' },
    { id: 'workspace', label: 'Chat', icon: 'chat' },
    {
      id: 'email',
      label: 'Email',
      icon: 'mail',
      hidden: !hasEmailConfigured
    },
    {
      // placeholder — not yet wired; clicking does nothing.
      id: 'tasks',
      label: 'WhatsApp',
      icon: 'whatsapp',
      disabled: true,
      disabledTitle: 'Not connected'
    },
    {
      id: 'tasks',
      label: 'MrCall',
      icon: 'phone',
      disabled: true,
      disabledTitle: 'Not connected'
    }
  ]

  const secondary: NavItem[] = [
    { id: 'update', label: 'Update', icon: 'refresh' },
    { id: 'settings', label: 'Settings', icon: 'settings' }
  ]

  const renderItem = (item: NavItem, key: string): JSX.Element | null => {
    if (item.hidden) return null
    const active = !item.disabled && view === item.id
    return (
      <button
        key={key}
        onClick={() => {
          if (item.disabled) return
          setView(item.id)
        }}
        title={item.disabled ? item.disabledTitle : undefined}
        disabled={item.disabled}
        className={
          'flex items-center gap-2 px-3 py-2 rounded text-sm text-left transition-colors ' +
          (item.disabled
            ? 'text-brand-mid-grey cursor-not-allowed'
            : active
              ? 'bg-brand-blue text-white'
              : 'text-brand-grey-80 hover:bg-white')
        }
      >
        <Icon name={item.icon} size={18} className="shrink-0" />
        <span className="truncate">{item.label}</span>
      </button>
    )
  }

  return (
    <aside className="w-[220px] shrink-0 border-r border-brand-mid-grey bg-brand-light-grey flex flex-col">
      <header className="px-3 py-3 border-b border-brand-mid-grey/60 flex flex-col gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <img
            src={mrcallIcon}
            alt=""
            aria-hidden="true"
            className="w-7 h-7 shrink-0"
          />
          <img
            src={mrcallWordmark}
            alt="MrCall Desktop"
            className="h-5 w-auto"
          />
        </div>
        {profileEmail && (
          <div
            className="text-[11px] font-mono truncate px-2 py-1 rounded border border-brand-mid-grey bg-white text-brand-grey-80 flex items-center gap-2"
            title={profileEmail}
          >
            <span
              className="inline-block w-2 h-2 rounded-full shrink-0"
              style={{ backgroundColor: 'var(--profile-accent)' }}
              aria-hidden="true"
            />
            <span className="truncate">{profileEmail}</span>
          </div>
        )}
        <button
          onClick={onOpenProfilePicker}
          title="Open another profile in a new window"
          className="px-2 py-1 rounded text-xs border border-brand-mid-grey text-brand-grey-80 bg-white hover:bg-brand-light-grey"
        >
          + New Window
        </button>
      </header>

      <nav className="flex-1 overflow-y-auto px-2 py-3 flex flex-col gap-1">
        {primary.map((it, i) => renderItem(it, `p-${i}`))}
        <div className="h-px bg-brand-mid-grey/60 my-2 mx-1" />
        {secondary.map((it, i) => renderItem(it, `s-${i}`))}
      </nav>

      <footer className="border-t border-brand-mid-grey/60 px-2 py-2 flex flex-col gap-1.5">
        <button
          onClick={onNewProfile}
          title="Create a brand-new MrCall Desktop profile"
          className="px-2 py-1 rounded text-xs border border-brand-mid-grey text-brand-grey-80 bg-white hover:bg-brand-light-grey text-left"
        >
          + New Profile
        </button>
        <ProfilesDropdown
          currentEmail={profileEmail}
          refreshKey={profilesRefreshKey}
        />
      </footer>
    </aside>
  )
}

// Three-state machine driving the Firebase signin → profile binding
// flow:
//
//   pending     — Firebase auth hasn't reported back yet (in-memory
//                 persistence: this is one tick at most)
//   signed-out  — user is null, render SignIn
//   binding     — user just signed in, asking main to bindProfile
//   bound       — sidecar attached, render AppInner
//   onboarding  — no profile dir for this UID yet, render Onboarding
//   error       — bindProfile said no with an explicit reason
type AuthGateState =
  | { phase: 'pending' }
  | { phase: 'signed-out' }
  | { phase: 'binding'; user: User }
  | { phase: 'bound'; user: User }
  | { phase: 'onboarding'; user: User }
  | { phase: 'error'; user: User; reason: string }

// Gates the entire UI behind a Firebase signin AND a successful
// profile bind. With in-memory persistence and UID-keyed profiles,
// these two are inseparable: a window with a Firebase user but no
// matching profile dir on disk has no engine to talk to.
function FirebaseAuthGate({ children }: { children: React.ReactNode }): JSX.Element {
  const [state, setState] = useState<AuthGateState>({ phase: 'pending' })

  useEffect(() => {
    // Wire the token-push hook so authUtils can hand fresh tokens to
    // the Python sidecar via JSON-RPC. The initial push fires before
    // any sidecar is attached (the auth-pending window has none); the
    // catch swallows the failure and we re-push after bindProfile
    // succeeds via repushTokenForCurrentUser().
    setTokenPusher(async ({ uid, email, idToken, expiresAtMs }) => {
      try {
        await window.zylch.account.setFirebaseToken({
          uid,
          email,
          idToken,
          expiresAtMs
        })
      } catch (e) {
        console.debug('[App] account.setFirebaseToken push skipped:', e)
      }
    })
    const unsub = setupAuthListener((u) => {
      if (!u || u.isAnonymous) {
        setState({ phase: 'signed-out' })
      } else {
        setState({ phase: 'binding', user: u })
      }
    })
    return () => {
      setTokenPusher(null)
      unsub()
    }
  }, [])

  // When we transition into 'binding', ask main to attach a sidecar
  // for this UID. Three outcomes shape the next state.
  useEffect(() => {
    if (state.phase !== 'binding') return
    let cancelled = false
    const u = state.user
    ;(async () => {
      try {
        const r = await window.zylch.auth.bindProfile(u.uid)
        if (cancelled) return
        if (r.ok && r.found) {
          // Sidecar is attached. Re-push the token now that the RPC
          // channel exists (the initial push during onAuthStateChanged
          // fired before the sidecar was bound and was swallowed).
          await repushTokenForCurrentUser()
          if (cancelled) return
          setState({ phase: 'bound', user: u })
        } else if (r.ok && !r.found) {
          setState({ phase: 'onboarding', user: u })
        } else {
          setState({
            phase: 'error',
            user: u,
            reason: r.reason || 'Unable to bind profile'
          })
        }
      } catch (e) {
        if (cancelled) return
        console.error('[App] auth.bindProfile failed', e)
        setState({
          phase: 'error',
          user: u,
          reason: e instanceof Error ? e.message : String(e)
        })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [state])

  if (state.phase === 'pending' || state.phase === 'binding') {
    return <div className="min-h-screen w-full bg-brand-light-grey" />
  }
  if (state.phase === 'signed-out') {
    return <SignIn />
  }
  if (state.phase === 'onboarding') {
    // Onboarding wizard creates the UID-keyed profile and then calls
    // onboarding:finalize, which attaches a sidecar to THIS window
    // in-place. The wizard then signals back via onReady, and we flip
    // ourselves into 'binding' so the existing useEffect re-pushes
    // the token and transitions to 'bound'. No reload, no second
    // signin — the renderer context (and Firebase auth state) stays
    // alive across the transition.
    const u = state.user
    return (
      <Onboarding
        onReady={() => {
          setState({ phase: 'binding', user: u })
        }}
      />
    )
  }
  if (state.phase === 'error') {
    return <AuthGateError user={state.user} reason={state.reason} />
  }
  return <>{children}</>
}

// Persistent top bar showing the current Firebase identity. Surfaces
// at the very top of every signed-in window so a wrong-account state
// is visible within seconds — not buried in Settings → AccountCard.
// Hidden in legacy windows (those have no Firebase user and routinely
// run with `auth.currentUser === null`).
function IdentityBanner(): JSX.Element | null {
  const user = auth.currentUser
  if (!user || user.isAnonymous) return null
  const email = user.email || '—'
  const uid = user.uid || ''
  return (
    <div
      role="banner"
      className="flex items-center gap-2 px-4 py-1.5 text-xs border-b bg-brand-light-grey border-brand-mid-grey text-brand-grey-80"
    >
      <span className="opacity-70">Signed in as</span>
      <span className="font-mono text-brand-black">{email}</span>
      {uid && (
        <span className="font-mono opacity-50" title={uid}>
          (uid {uid.slice(0, 8)}…)
        </span>
      )}
      <button
        onClick={() => performSignOut()}
        className="ml-auto px-2 py-0.5 text-[11px] border rounded hover:bg-white"
      >
        Sign out
      </button>
    </div>
  )
}

function AuthGateError({ user, reason }: { user: User; reason: string }): JSX.Element {
  return (
    <div className="min-h-screen w-full flex items-start justify-center bg-brand-light-grey p-6 overflow-auto">
      <div className="w-full max-w-[480px] mt-10 bg-white border border-brand-mid-grey rounded-lg shadow-sm p-5">
        <h1 className="text-lg font-semibold text-brand-black">Profile bind failed</h1>
        <p className="text-sm text-brand-grey-80 mt-1">
          Signed in as <strong>{user.email || '—'}</strong>{' '}
          <span className="opacity-60">(uid {user.uid.slice(0, 8)}…)</span>
        </p>
        <pre className="mt-3 p-2 bg-brand-light-grey border rounded text-xs whitespace-pre-wrap break-all">
          {reason}
        </pre>
        <p className="text-xs text-brand-grey-80 mt-3">
          This window is already bound to a different profile. Sign out
          and sign back in, or open a fresh window from the File menu.
        </p>
        <div className="mt-4 flex gap-2">
          <button
            onClick={() => performSignOut()}
            className="px-3 py-1.5 text-xs border rounded text-brand-grey-80 hover:bg-brand-light-grey"
          >
            Sign out
          </button>
        </div>
      </div>
    </div>
  )
}

// Small button shown wherever we need a signout affordance. Currently
// surfaced from Settings via a top-bar action; kept here so it lives
// next to the gate that consumes it.
export async function performSignOut(): Promise<void> {
  // Tell the engine first so its cached session is cleared even if
  // Firebase's signOut throws (offline, etc). On a no-sidecar window
  // this is a no-op.
  try {
    await window.zylch.account.signOut()
  } catch (e) {
    console.debug('[App] engine signOut push skipped:', e)
  }
  try {
    await signOut(auth)
  } catch (e) {
    console.error('[App] firebase signOut failed', e)
  }
}

function AppShell(): JSX.Element {
  return (
    <ConversationsProvider>
      <ThreadProvider>
        <TasksProvider>
          <AppInner />
        </TasksProvider>
      </ThreadProvider>
    </ConversationsProvider>
  )
}

// `?legacy=1` is set by main when a window is opened via the
// "+ New Window for Profile" picker (or via ZYLCH_PROFILE). Such
// windows already have a sidecar bound to a chosen profile dir; they
// pre-date the Firebase-as-identity model, so we skip the auth gate
// entirely and render AppInner directly. Engine-side StarChat /
// mrcall.* / google.calendar.* calls will fail with -32010 in this
// mode, since no Firebase token has been pushed — that's fine, those
// features simply don't work in legacy windows until/unless the user
// signs in through Settings.
function isLegacyWindow(): boolean {
  try {
    const qs = new URLSearchParams(window.location.search)
    return qs.get('legacy') === '1'
  } catch {
    return false
  }
}

export default function App(): JSX.Element {
  if (isLegacyWindow()) {
    return <AppShell />
  }
  return (
    <FirebaseAuthGate>
      <AppShell />
    </FirebaseAuthGate>
  )
}
