import { useState } from 'react'
import Dashboard from './views/Dashboard'
import Chat from './views/Chat'
import Update from './views/Update'
import { ConversationsProvider } from './store/conversations'
import './types'

type View = 'dashboard' | 'chat' | 'update'

export default function App() {
  const [view, setView] = useState<View>('dashboard')
  const tabs: { id: View; label: string }[] = [
    { id: 'dashboard', label: 'Dashboard' },
    { id: 'chat', label: 'Chat' },
    { id: 'update', label: 'Update' }
  ]
  return (
    <ConversationsProvider>
      <div className="flex flex-col h-full">
        <nav className="flex items-center gap-2 px-4 py-2 border-b bg-white">
          <span className="font-semibold text-lg mr-6">Zylch</span>
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setView(t.id)}
              className={
                'px-3 py-1.5 rounded text-sm ' +
                (view === t.id
                  ? 'bg-slate-900 text-white'
                  : 'text-slate-700 hover:bg-slate-100')
              }
            >
              {t.label}
            </button>
          ))}
        </nav>
        <main className="flex-1 overflow-auto">
          {view === 'dashboard' && (
            <Dashboard onOpenChat={() => setView('chat')} />
          )}
          {view === 'chat' && (
            <Chat onGoToDashboard={() => setView('dashboard')} />
          )}
          {view === 'update' && <Update />}
        </main>
      </div>
    </ConversationsProvider>
  )
}
