import React from 'react'
import { createRoot } from 'react-dom/client'
import '../src/preload/index'
import Settings from '../src/renderer/src/views/Settings'
import Tasks from '../src/renderer/src/views/Tasks'
import { ConversationsProvider } from '../src/renderer/src/store/conversations'
import { TasksProvider } from '../src/renderer/src/store/tasks'
import { ThreadProvider } from '../src/renderer/src/store/thread'

const authListeners = new Set<() => void>()
const methods: string[] = []
const request = async (body: unknown) => {
  const result = await fetch('/rpc', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(response => response.json())
  if (result.error) throw new Error(result.error.message)
  return result.result
}
const emit = (value: unknown) => {
  for (const [name, callback] of (window as any).fixtureIpcRegistrations || []) if (name === 'sidecar:status') callback({}, value)
}
Object.assign(window, {
  fixtureAuth: { uid: 'fixtureFirebaseUid', email: 'display@example.test' },
  fixtureAuthListeners: authListeners,
  fixtureRpc: { invoke: async (channel: string, method?: string, params?: unknown) => {
    if (channel === 'profile:current') return { id: 'fixtureFirebaseUid', email: 'display@example.test' }
    if (channel === 'settings:getBackendLocation') return { location: 'local', url: '' }
    if (channel !== 'rpc:call' || !method) throw new Error('Unexpected native IPC')
    methods.push(method)
    return request({ method, params: params || {} })
  } },
  fixture: {
    methods: () => methods,
    inspect: () => request({ control: 'inspect' }),
    restart: async () => {
      emit({ alive: false, profile: 'fixtureFirebaseUid', code: 'restarting' })
      await fetch('/restart', { method: 'POST' })
      emit({ alive: true, ready: true, profile: 'fixtureFirebaseUid' })
    },
    signOut: () => { Object.assign(window, { fixtureAuth: null }); for (const callback of authListeners) callback() }
  }
})
createRoot(document.getElementById('root')!).render(
  <ConversationsProvider><ThreadProvider><TasksProvider><main><Settings /><Tasks /></main></TasksProvider></ThreadProvider></ConversationsProvider>
)
