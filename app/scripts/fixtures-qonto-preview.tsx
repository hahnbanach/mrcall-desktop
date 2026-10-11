import React from 'react'
import { createRoot } from 'react-dom/client'
import '../src/preload/index'
import Settings from '../src/renderer/src/views/Settings'
import Tasks from '../src/renderer/src/views/Tasks'
import { ConversationsProvider } from '../src/renderer/src/store/conversations'
import { TasksProvider } from '../src/renderer/src/store/tasks'
import { ThreadProvider } from '../src/renderer/src/store/thread'
import { createQontoFixture } from './fixtures-qonto-rpc'

const rpc = createQontoFixture(JSON.parse(sessionStorage.getItem('qonto-fixture-engine') || '{}'))
const transport = {
  ...rpc,
  invoke: async (...args: Parameters<typeof rpc.invoke>) => {
    const result = await rpc.invoke(...args)
    sessionStorage.setItem('qonto-fixture-engine', JSON.stringify(rpc.state()))
    return result
  }
}
for (const [name, callback] of (window as any).fixtureIpcRegistrations || []) rpc.on(name, callback)
const authListeners = new Set<() => void>()
Object.assign(window, {
  fixtureRpc: transport,
  fixtureAuth: { uid: 'fixture-uid', email: 'fixture@example.test' },
  fixtureAuthListeners: authListeners,
  fixture: {
    ...rpc,
    changeUid: () => {
      Object.assign(window, { fixtureAuth: { uid: 'different-uid', email: 'other@example.test' } })
      rpc.changeUid('different-uid')
      for (const listener of authListeners) listener()
    },
    signOut: () => {
      Object.assign(window, { fixtureAuth: null })
      rpc.signOut()
      for (const listener of authListeners) listener()
    }
  }
})
createRoot(document.getElementById('root')!).render(
  <ConversationsProvider><ThreadProvider><TasksProvider>
    <main><Settings /><Tasks /></main>
  </TasksProvider></ThreadProvider></ConversationsProvider>
)
