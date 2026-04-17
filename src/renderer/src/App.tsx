import { useEffect, useState } from 'react'
import Dashboard from './views/Dashboard'
import Chat from './views/Chat'
import Update from './views/Update'
import Emails from './views/Emails'
import Settings from './views/Settings'
import { ConversationsProvider } from './store/conversations'
import { ThreadProvider, useThread } from './store/thread'
import { profileColor } from './lib/profileColor'
import './types'

type View = 'dashboard' | 'chat' | 'emails' | 'update' | 'settings'

function AppInner() {
  const [view, setView] = useState<View>('dashboard')
  const [profileEmail, setProfileEmail] = useState<string>('')
  const { setActiveThreadId, setActiveTaskId } = useThread()

  // Resolve the active profile once on mount, derive the accent colour, and
  // publish it as CSS custom properties so any component can theme itself
  // via `var(--profile-accent)` / `var(--profile-accent-soft)`.
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
        document.title = safe ? `Zylch — ${safe}` : 'Zylch'
      })
      .catch((e) => console.error('[App] profile.current failed', e))
    return () => {
      cancelled = true
    }
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
        {profileEmail && (
          <span
            className="ml-auto text-xs font-mono px-2 py-1 rounded border"
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
    </div>
  )
}

export default function App() {
  return (
    <ConversationsProvider>
      <ThreadProvider>
        <AppInner />
      </ThreadProvider>
    </ConversationsProvider>
  )
}
