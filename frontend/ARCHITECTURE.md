# Zylch Vue Dashboard - Complete Architecture

## Executive Summary

This document defines the complete Vue 3 application architecture that replicates ALL zylch-cli functionality in a modern web dashboard. The design prioritizes the existing visual style from zylch-website while adding interactive dashboard components.

**Component Count**: ~58 Vue components across 14 feature areas including the newly added Triggers, Cache, MrCall, and enhanced Sharing/Memory management.

---

## 1. Technology Stack

### Core Framework
- **Vue 3.5+** - Composition API with `<script setup>`
- **TypeScript 5.6+** - Full type safety
- **Vite 6.0+** - Build tool and dev server

### State Management
- **Pinia 2.2+** - Official Vue state management
- **pinia-plugin-persistedstate** - LocalStorage persistence

### Routing
- **Vue Router 4.4+** - Client-side routing with nested routes

### HTTP & WebSocket
- **Axios 1.7+** - HTTP client with interceptors
- **Socket.io-client 4.8+** - Real-time WebSocket communication

### UI Components
- **Headless UI** - Accessible UI primitives (modals, dropdowns)
- **@heroicons/vue** - Icon library
- **VueDraggable** - Drag-and-drop for task reordering

### Utilities
- **date-fns** - Date manipulation
- **marked** - Markdown rendering for AI responses
- **highlight.js** - Syntax highlighting for code blocks
- **tailwindcss** - Utility-first CSS (configured to match zylch-website)

### Authentication
- **Firebase Auth SDK** - Firebase authentication (Google, Microsoft)
- **firebase-admin** - Server-side token verification

---

## 2. Complete Directory Structure

```
frontend/
├── public/
│   ├── favicon.ico
│   ├── logo/
│   │   ├── zylch-horizontal.svg
│   │   ├── zylch-icon.svg
│   │   └── favicon-*.png
│   └── index.html
│
├── src/
│   ├── main.ts                      # App entry point
│   ├── App.vue                      # Root component
│   │
│   ├── assets/
│   │   ├── styles/
│   │   │   ├── main.css            # Global styles + Tailwind
│   │   │   ├── variables.css       # CSS custom properties (from common.css)
│   │   │   ├── typography.css      # Typography system
│   │   │   └── animations.css      # Transitions and animations
│   │   └── images/
│   │       └── placeholder-avatar.svg
│   │
│   ├── components/
│   │   ├── layout/
│   │   │   ├── AppHeader.vue       # Fixed header with logo + sign out
│   │   │   ├── AppSidebar.vue      # Navigation sidebar
│   │   │   ├── AppFooter.vue       # Fixed footer
│   │   │   └── DashboardLayout.vue # Main layout wrapper
│   │   │
│   │   ├── chat/
│   │   │   ├── ChatInterface.vue   # Main chat container
│   │   │   ├── MessageBubble.vue   # Single message component
│   │   │   ├── MessageInput.vue    # Input area with send button
│   │   │   ├── CommandPalette.vue  # / command autocomplete
│   │   │   ├── TypingIndicator.vue # "Zylch is thinking..."
│   │   │   └── ChatHistory.vue     # Conversation history sidebar
│   │   │
│   │   ├── email/
│   │   │   ├── EmailList.vue       # Thread list view
│   │   │   ├── EmailThreadView.vue # Single thread viewer
│   │   │   ├── EmailComposer.vue   # Draft editor (Monaco-like)
│   │   │   ├── EmailFilters.vue    # Filter by account, date, unread
│   │   │   ├── EmailSearch.vue     # Search by participant/subject
│   │   │   └── DraftsList.vue      # Gmail drafts management
│   │   │
│   │   ├── tasks/
│   │   │   ├── TaskBoard.vue       # Kanban board (Open/Waiting/Closed)
│   │   │   ├── TaskCard.vue        # Person-centric task card
│   │   │   ├── TaskDetail.vue      # Expanded task view with all threads
│   │   │   ├── TaskFilters.vue     # Priority, status filters
│   │   │   ├── PriorityBadge.vue   # 1-10 urgency score indicator
│   │   │   └── TaskStats.vue       # Statistics overview
│   │   │
│   │   ├── calendar/
│   │   │   ├── CalendarView.vue    # Monthly/weekly/daily views
│   │   │   ├── EventCard.vue       # Event display with Meet links
│   │   │   ├── EventEditor.vue     # Create/edit events
│   │   │   ├── MeetingScheduler.vue # Quick meeting scheduler
│   │   │   └── TimezonePicker.vue  # Timezone selector
│   │   │
│   │   ├── contacts/
│   │   │   ├── ContactList.vue     # All contacts with search
│   │   │   ├── ContactCard.vue     # Contact info card
│   │   │   ├── ContactDetail.vue   # Full contact profile
│   │   │   ├── ContactEnrichment.vue # Web search enrichment UI
│   │   │   └── ContactSync.vue     # StarChat/Pipedrive sync
│   │   │
│   │   ├── memory/
│   │   │   ├── MemoryManager.vue   # Memory list/add/remove
│   │   │   ├── MemoryCard.vue      # Single memory display
│   │   │   ├── MemoryStats.vue     # Usage statistics
│   │   │   └── MemorySearch.vue    # Semantic search interface
│   │   │
│   │   ├── archive/
│   │   │   ├── ArchiveViewer.vue   # Email archive browser
│   │   │   ├── ArchiveSearch.vue   # Full-text search
│   │   │   ├── ArchiveStats.vue    # Archive statistics
│   │   │   └── ArchiveSync.vue     # Sync progress indicator
│   │   │
│   │   ├── campaigns/
│   │   │   ├── CampaignList.vue    # All campaigns
│   │   │   ├── CampaignEditor.vue  # Create/edit campaigns
│   │   │   ├── TemplateEditor.vue  # Email template editor
│   │   │   └── CampaignMetrics.vue # SendGrid analytics
│   │   │
│   │   ├── sharing/
│   │   │   ├── SharingManager.vue  # Share/revoke UI
│   │   │   ├── RecipientList.vue   # Authorized recipients
│   │   │   ├── SharedIntel.vue     # Shared intelligence viewer
│   │   │   └── SharingStatus.vue   # Sharing status display
│   │   │
│   │   ├── triggers/
│   │   │   ├── TriggerManager.vue  # Main trigger management
│   │   │   ├── TriggerList.vue     # List all triggers
│   │   │   └── TriggerForm.vue     # Create/edit triggers
│   │   │
│   │   ├── cache/
│   │   │   └── CacheManager.vue    # Cache management interface
│   │   │
│   │   ├── mrcall/
│   │   │   ├── MrCallManager.vue   # MrCall assistant integration
│   │   │   └── MrCallLinkForm.vue  # Link assistant to room
│   │   │
│   │   ├── settings/
│   │   │   ├── SettingsPanel.vue   # Main settings container
│   │   │   ├── AccountSettings.vue # Email accounts, auth
│   │   │   ├── AssistantSettings.vue # Multi-tenant assistants
│   │   │   ├── ModelSettings.vue   # AI model selection
│   │   │   ├── StyleSettings.vue   # Email style preferences
│   │   │   └── IntegrationSettings.vue # Pipedrive, StarChat, etc.
│   │   │
│   │   ├── sync/
│   │   │   ├── SyncDashboard.vue   # Sync status overview
│   │   │   ├── SyncProgress.vue    # Progress bar with phases
│   │   │   ├── GapsBriefing.vue    # Relationship gaps display
│   │   │   └── SyncSchedule.vue    # Scheduled sync config
│   │   │
│   │   ├── tutorial/
│   │   │   ├── TutorialModal.vue   # Interactive tutorial overlay
│   │   │   ├── TutorialStep.vue    # Single tutorial step
│   │   │   └── TutorialProgress.vue # Progress indicator
│   │   │
│   │   └── common/
│   │       ├── Button.vue          # Styled button component
│   │       ├── Input.vue           # Styled input component
│   │       ├── Select.vue          # Dropdown select
│   │       ├── Modal.vue           # Modal dialog wrapper
│   │       ├── Toast.vue           # Notification toast
│   │       ├── Spinner.vue         # Loading spinner
│   │       ├── Avatar.vue          # User avatar component
│   │       ├── Badge.vue           # Status/count badges
│   │       ├── Card.vue            # Card container
│   │       ├── Tabs.vue            # Tab navigation
│   │       └── EmptyState.vue      # Empty state placeholder
│   │
│   ├── views/
│   │   ├── auth/
│   │   │   ├── LoginView.vue       # Login page (Firebase auth)
│   │   │   └── CallbackView.vue    # OAuth callback handler
│   │   │
│   │   ├── DashboardView.vue       # Main dashboard (chat interface)
│   │   ├── EmailView.vue           # Email management page
│   │   ├── TasksView.vue           # Task board page
│   │   ├── CalendarView.vue        # Calendar page
│   │   ├── ContactsView.vue        # Contacts page
│   │   ├── MemoryView.vue          # Memory management page
│   │   ├── ArchiveView.vue         # Email archive page
│   │   ├── CampaignsView.vue       # Campaign management page
│   │   ├── SharingView.vue         # Sharing management page
│   │   ├── TriggersView.vue        # Triggered instructions page
│   │   ├── CacheView.vue           # Cache management page
│   │   ├── MrCallView.vue          # MrCall assistant integration page
│   │   ├── SharingStatusView.vue   # Sharing status display page
│   │   ├── SettingsView.vue        # Settings page
│   │   └── NotFoundView.vue        # 404 page
│   │
│   ├── stores/
│   │   ├── auth.ts                 # Authentication state (Firebase)
│   │   ├── chat.ts                 # Chat conversation state
│   │   ├── email.ts                # Email threads and drafts
│   │   ├── tasks.ts                # Person-centric tasks
│   │   ├── calendar.ts             # Events and scheduling
│   │   ├── contacts.ts             # Contact data
│   │   ├── memory.ts               # Behavioral memory (with --build option)
│   │   ├── archive.ts              # Email archive
│   │   ├── campaigns.ts            # Campaign data
│   │   ├── sharing.ts              # Sharing state
│   │   ├── sync.ts                 # Sync progress
│   │   ├── settings.ts             # User preferences (includes trigger management)
│   │   ├── mrCall.ts               # MrCall assistant state
│   │   └── websocket.ts            # WebSocket connection state
│   │
│   ├── services/
│   │   ├── api/
│   │   │   ├── axios.ts            # Axios instance with interceptors
│   │   │   ├── chat.ts             # Chat API calls
│   │   │   ├── email.ts            # Email API calls
│   │   │   ├── tasks.ts            # Task API calls
│   │   │   ├── calendar.ts         # Calendar API calls
│   │   │   ├── contacts.ts         # Contact API calls
│   │   │   ├── memory.ts           # Memory API calls
│   │   │   ├── archive.ts          # Archive API calls
│   │   │   ├── campaigns.ts        # Campaign API calls
│   │   │   ├── sharing.ts          # Sharing API calls
│   │   │   ├── sync.ts             # Sync API calls
│   │   │   ├── triggerService.ts   # Trigger management API
│   │   │   ├── cacheService.ts     # Cache management API
│   │   │   └── mrCallService.ts    # MrCall assistant API
│   │   │
│   │   ├── websocket.ts            # Socket.io client setup
│   │   ├── firebase.ts             # Firebase auth setup
│   │   ├── storage.ts              # LocalStorage utilities
│   │   └── markdown.ts             # Markdown parsing utilities
│   │
│   ├── router/
│   │   ├── index.ts                # Router configuration
│   │   ├── guards.ts               # Navigation guards (auth)
│   │   └── routes.ts               # Route definitions
│   │
│   ├── composables/
│   │   ├── useAuth.ts              # Authentication composable
│   │   ├── useChat.ts              # Chat interface logic
│   │   ├── useCommands.ts          # / command parsing
│   │   ├── useWebSocket.ts         # WebSocket connection
│   │   ├── useNotifications.ts    # Toast notifications
│   │   ├── useMarkdown.ts          # Markdown rendering
│   │   └── useKeyboard.ts          # Keyboard shortcuts
│   │
│   ├── types/
│   │   ├── api.ts                  # API request/response types
│   │   ├── email.ts                # Email types
│   │   ├── task.ts                 # Task types
│   │   ├── calendar.ts             # Calendar types
│   │   ├── contact.ts              # Contact types
│   │   ├── memory.ts               # Memory types
│   │   ├── campaign.ts             # Campaign types
│   │   └── chat.ts                 # Chat types
│   │
│   ├── utils/
│   │   ├── date.ts                 # Date formatting utilities
│   │   ├── email.ts                # Email validation utilities
│   │   ├── filters.ts              # Data filtering utilities
│   │   ├── formatting.ts           # Text formatting
│   │   └── validation.ts           # Form validation
│   │
│   └── config/
│       ├── constants.ts            # App constants
│       ├── commands.ts             # CLI command definitions
│       └── firebase.ts             # Firebase configuration
│
├── tests/
│   ├── unit/
│   │   ├── components/
│   │   ├── stores/
│   │   └── utils/
│   └── e2e/
│       └── specs/
│
├── .env.example                    # Environment variables template
├── .env.local                      # Local environment (gitignored)
├── .gitignore
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
├── postcss.config.js
└── README.md
```

---

## 3. State Management Architecture (Pinia)

### Store Structure

Each store follows this pattern:

```typescript
// Example: stores/email.ts
import { defineStore } from 'pinia'
import type { EmailThread, EmailDraft } from '@/types/email'

export const useEmailStore = defineStore('email', {
  state: () => ({
    threads: [] as EmailThread[],
    drafts: [] as EmailDraft[],
    selectedThread: null as EmailThread | null,
    loading: false,
    error: null as string | null,
    accounts: [] as string[],
    filters: {
      account: 'all',
      unread: false,
      dateRange: 30
    }
  }),

  getters: {
    filteredThreads: (state) => {
      // Apply filters
      return state.threads.filter(thread => {
        // Filter logic
      })
    },
    unreadCount: (state) => state.threads.filter(t => !t.read).length
  },

  actions: {
    async fetchThreads(days: number = 30) {
      this.loading = true
      try {
        const response = await emailApi.getThreads(days)
        this.threads = response.data
      } catch (error) {
        this.error = error.message
      } finally {
        this.loading = false
      }
    },

    async createDraft(draft: EmailDraft) {
      // Implementation
    }
  },

  persist: {
    paths: ['filters'] // Only persist filters
  }
})
```

### Store Dependencies

```
auth (root)
  ├── email (depends on auth)
  ├── tasks (depends on auth)
  ├── calendar (depends on auth)
  ├── contacts (depends on auth)
  ├── memory (depends on auth)
  ├── archive (depends on auth)
  ├── campaigns (depends on auth)
  ├── sharing (depends on auth)
  └── settings (depends on auth)

chat (standalone)
websocket (standalone, used by chat)
sync (coordinates email, calendar, tasks)
```

---

## 4. Routing Structure (Vue Router)

```typescript
// router/routes.ts
export const routes = [
  {
    path: '/auth',
    component: () => import('@/layouts/AuthLayout.vue'),
    children: [
      { path: 'login', component: () => import('@/views/auth/LoginView.vue') },
      { path: 'callback', component: () => import('@/views/auth/CallbackView.vue') }
    ]
  },
  {
    path: '/',
    component: () => import('@/components/layout/DashboardLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', name: 'dashboard', component: () => import('@/views/DashboardView.vue') },
      { path: 'email', name: 'email', component: () => import('@/views/EmailView.vue') },
      { path: 'email/thread/:id', name: 'email-thread', component: () => import('@/views/EmailThreadView.vue') },
      { path: 'tasks', name: 'tasks', component: () => import('@/views/TasksView.vue') },
      { path: 'tasks/:contactId', name: 'task-detail', component: () => import('@/views/TaskDetailView.vue') },
      { path: 'calendar', name: 'calendar', component: () => import('@/views/CalendarView.vue') },
      { path: 'contacts', name: 'contacts', component: () => import('@/views/ContactsView.vue') },
      { path: 'contacts/:id', name: 'contact-detail', component: () => import('@/views/ContactDetailView.vue') },
      { path: 'memory', name: 'memory', component: () => import('@/views/MemoryView.vue') },
      { path: 'archive', name: 'archive', component: () => import('@/views/ArchiveView.vue') },
      { path: 'campaigns', name: 'campaigns', component: () => import('@/views/CampaignsView.vue') },
      { path: 'campaigns/:id', name: 'campaign-detail', component: () => import('@/views/CampaignDetailView.vue') },
      { path: 'sharing', name: 'sharing', component: () => import('@/views/SharingView.vue') },
      { path: 'triggers', name: 'triggers', component: () => import('@/views/TriggersView.vue') },
      { path: 'cache', name: 'cache', component: () => import('@/views/CacheView.vue') },
      { path: 'mrcall', name: 'mrcall', component: () => import('@/views/MrCallView.vue') },
      { path: 'settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
      { path: 'settings/sharing-status', name: 'sharing-status', component: () => import('@/views/SharingStatusView.vue') }
    ]
  },
  { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('@/views/NotFoundView.vue') }
]
```

---

## 5. API Service Layer

### Axios Configuration

```typescript
// services/api/axios.ts
import axios from 'axios'
import { useAuthStore } from '@/stores/auth'

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:9000',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// Request interceptor - add auth token
apiClient.interceptors.request.use(
  (config) => {
    const authStore = useAuthStore()
    if (authStore.token) {
      config.headers.Authorization = `Bearer ${authStore.token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor - handle errors
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      const authStore = useAuthStore()
      await authStore.logout()
    }
    return Promise.reject(error)
  }
)

export default apiClient
```

### API Module Example

```typescript
// services/api/chat.ts
import apiClient from './axios'
import type { ChatMessage, ChatResponse } from '@/types/chat'

export const chatApi = {
  sendMessage: (message: string, conversationId?: string) =>
    apiClient.post<ChatResponse>('/api/chat/message', { message, conversationId }),

  getConversation: (conversationId: string) =>
    apiClient.get<ChatMessage[]>(`/api/chat/conversation/${conversationId}`),

  getConversations: () =>
    apiClient.get<any[]>('/api/chat/conversations'),

  clearHistory: () =>
    apiClient.delete('/api/chat/history')
}
```

---

## 6. WebSocket Integration

### Connection Management

```typescript
// services/websocket.ts
import { io, Socket } from 'socket.io-client'
import { useWebSocketStore } from '@/stores/websocket'

let socket: Socket | null = null

export const connectWebSocket = (token: string) => {
  if (socket?.connected) return socket

  socket = io(import.meta.env.VITE_API_URL || 'http://localhost:9000', {
    auth: { token },
    transports: ['websocket'],
    reconnection: true,
    reconnectionDelay: 1000,
    reconnectionAttempts: 5
  })

  const wsStore = useWebSocketStore()

  socket.on('connect', () => {
    wsStore.setConnected(true)
  })

  socket.on('disconnect', () => {
    wsStore.setConnected(false)
  })

  socket.on('chat_message', (data) => {
    wsStore.handleChatMessage(data)
  })

  socket.on('sync_progress', (data) => {
    wsStore.handleSyncProgress(data)
  })

  socket.on('notification', (data) => {
    wsStore.handleNotification(data)
  })

  return socket
}

export const disconnectWebSocket = () => {
  if (socket) {
    socket.disconnect()
    socket = null
  }
}

export const getSocket = () => socket
```

### WebSocket Events

```typescript
// Types of WebSocket events
{
  // Chat streaming
  'chat_message': { chunk: string, done: boolean, conversationId: string }

  // Sync progress
  'sync_progress': { phase: string, progress: number, message: string }

  // Real-time notifications
  'notification': { type: 'email' | 'task' | 'calendar', data: any }

  // Task updates
  'task_update': { taskId: string, status: string, priority: number }

  // Email updates
  'email_received': { threadId: string, from: string, subject: string }
}
```

---

## 7. Authentication Flow

### Firebase Authentication

```typescript
// services/firebase.ts
import { initializeApp } from 'firebase/app'
import { getAuth, GoogleAuthProvider, OAuthProvider } from 'firebase/auth'

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID
}

const app = initializeApp(firebaseConfig)
export const auth = getAuth(app)
export const googleProvider = new GoogleAuthProvider()
export const microsoftProvider = new OAuthProvider('microsoft.com')

// Add scopes
googleProvider.addScope('https://www.googleapis.com/auth/gmail.readonly')
googleProvider.addScope('https://www.googleapis.com/auth/calendar')
microsoftProvider.addScope('https://graph.microsoft.com/Mail.Read')
microsoftProvider.addScope('https://graph.microsoft.com/Calendars.ReadWrite')
```

### Auth Store

```typescript
// stores/auth.ts
import { defineStore } from 'pinia'
import { signInWithPopup, signOut, onAuthStateChanged } from 'firebase/auth'
import { auth, googleProvider, microsoftProvider } from '@/services/firebase'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as any | null,
    token: null as string | null,
    loading: false,
    error: null as string | null
  }),

  getters: {
    isAuthenticated: (state) => !!state.user
  },

  actions: {
    async loginWithGoogle() {
      this.loading = true
      try {
        const result = await signInWithPopup(auth, googleProvider)
        this.user = result.user
        this.token = await result.user.getIdToken()
      } catch (error) {
        this.error = error.message
      } finally {
        this.loading = false
      }
    },

    async loginWithMicrosoft() {
      this.loading = true
      try {
        const result = await signInWithPopup(auth, microsoftProvider)
        this.user = result.user
        this.token = await result.user.getIdToken()
      } catch (error) {
        this.error = error.message
      } finally {
        this.loading = false
      }
    },

    async logout() {
      await signOut(auth)
      this.user = null
      this.token = null
    },

    initAuthListener() {
      onAuthStateChanged(auth, async (user) => {
        if (user) {
          this.user = user
          this.token = await user.getIdToken()
        } else {
          this.user = null
          this.token = null
        }
      })
    }
  },

  persist: true
})
```

---

## 8. Styling Approach

### CSS Architecture

```css
/* assets/styles/variables.css - Matches zylch-website */
:root {
  /* Colors */
  --bg-primary: #ffffff;
  --text-primary: #1a1a1a;
  --text-muted: #888888;
  --text-link: #666666;
  --accent: #4a9eff;

  /* Border radius */
  --radius: 24px;
  --radius-sm: 12px;

  /* Shadows */
  --shadow: 0 2px 8px rgba(0,0,0,0.08);
  --shadow-lg: 0 8px 32px rgba(0,0,0,0.12);

  /* Typography */
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;

  /* Spacing */
  --spacing-xs: 0.25rem;
  --spacing-sm: 0.5rem;
  --spacing-md: 1rem;
  --spacing-lg: 1.5rem;
  --spacing-xl: 2rem;

  /* Dashboard-specific */
  --sidebar-width: 240px;
  --header-height: 64px;
  --footer-height: 60px;
}
```

### Tailwind Configuration

```javascript
// tailwind.config.js
module.exports = {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: 'var(--bg-primary)',
        text: 'var(--text-primary)',
        muted: 'var(--text-muted)',
        link: 'var(--text-link)',
        accent: 'var(--accent)'
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif']
      },
      borderRadius: {
        DEFAULT: 'var(--radius-sm)',
        lg: 'var(--radius)'
      },
      boxShadow: {
        DEFAULT: 'var(--shadow)',
        lg: 'var(--shadow-lg)'
      }
    }
  },
  plugins: []
}
```

---

## 9. Component Hierarchy

### Main Chat Interface (DashboardView)

```
DashboardView
├── ChatInterface
│   ├── ChatHistory (sidebar)
│   ├── MessageList
│   │   └── MessageBubble (multiple)
│   │       ├── Avatar
│   │       └── MessageContent (markdown rendering)
│   ├── TypingIndicator
│   └── MessageInput
│       ├── CommandPalette (autocomplete)
│       └── Button (send)
```

### Email Management (EmailView)

```
EmailView
├── EmailFilters
│   ├── Select (account)
│   ├── Input (search)
│   └── Tabs (unread/all)
├── EmailList
│   └── EmailThreadCard (multiple)
│       ├── Avatar
│       ├── Badge (unread count)
│       └── PriorityIndicator
└── EmailThreadView (modal/side panel)
    ├── MessageBubble (multiple)
    ├── Button (reply)
    └── Button (save draft)
```

### Task Board (TasksView)

```
TasksView
├── TaskFilters
│   ├── Select (priority)
│   └── Input (search)
├── TaskStats (overview)
└── TaskBoard (3 columns)
    ├── TaskColumn (Open)
    │   └── TaskCard (multiple, draggable)
    ├── TaskColumn (Waiting)
    │   └── TaskCard (multiple, draggable)
    └── TaskColumn (Closed)
        └── TaskCard (multiple, draggable)
```

---

## 10. CLI Command Mapping to UI

### All CLI Commands → Dashboard Features

| CLI Command | Dashboard Feature | Implementation |
|-------------|-------------------|----------------|
| `/help` | Help menu in CommandPalette | Modal with command list |
| `/quit` | Sign out button | Auth store logout |
| `/clear` | Clear chat button | Chat store action |
| `/history` | Conversation sidebar | ChatHistory component |
| `/sync [days]` | Sync button in header | SyncDashboard modal |
| `/gaps` | Gaps tab in sync view | GapsBriefing component |
| `/briefing` | Daily briefing card | Dashboard summary |
| `/tutorial` | Tutorial launcher | TutorialModal |
| `/memory --list` | Memory page | MemoryView |
| `/memory --add` | Add memory button | MemoryManager form |
| `/memory --stats` | Memory stats widget | MemoryStats component |
| `/memory --build` | Build memory option | MemoryManager (enhanced) |
| `/trigger` | Triggers management page | TriggersView |
| `/trigger --list` | List all triggers | TriggerList component |
| `/trigger --add` | Add trigger form | TriggerForm component |
| `/cache` | Cache management page | CacheView |
| `/cache --clear` | Clear cache button | CacheManager component |
| `/model` | Model selector | ModelSettings |
| `/assistant` | Assistant manager | AssistantSettings |
| `/mrcall` | MrCall integration page | MrCallView |
| `/mrcall --link` | Link assistant to room | MrCallLinkForm |
| `/share` | Sharing page | SharingView |
| `/share --status` | Sharing status display | SharingStatus component |
| `/revoke` | Revoke button in sharing | SharingManager |
| `/archive` | Archive page | ArchiveView |
| `/archive --search` | Archive search | ArchiveSearch |
| `/archive --sync` | Sync button | ArchiveSync |

### Natural Language Commands

All natural language commands (e.g., "search emails from luisa", "show urgent tasks") are handled via the chat interface with the AI agent. The dashboard displays results in appropriate views:

- Email queries → Open EmailView with filtered results
- Task queries → Open TasksView with filtered results
- Calendar queries → Open CalendarView with date range
- Contact queries → Open ContactsView with search results

---

## 11. Real-Time Features

### Live Updates

```typescript
// Composable: composables/useWebSocket.ts
export const useWebSocket = () => {
  const wsStore = useWebSocketStore()
  const chatStore = useChatStore()
  const syncStore = useSyncStore()
  const notificationStore = useNotificationStore()

  const setupListeners = () => {
    const socket = getSocket()
    if (!socket) return

    // Chat message streaming
    socket.on('chat_message', (data) => {
      chatStore.appendMessageChunk(data.chunk, data.conversationId)
      if (data.done) {
        chatStore.finalizeMessage(data.conversationId)
      }
    })

    // Sync progress
    socket.on('sync_progress', (data) => {
      syncStore.updateProgress(data.phase, data.progress, data.message)
    })

    // New email notification
    socket.on('email_received', (data) => {
      notificationStore.show({
        type: 'email',
        title: 'New Email',
        message: `From ${data.from}: ${data.subject}`,
        action: () => router.push(`/email/thread/${data.threadId}`)
      })
    })

    // Task update
    socket.on('task_update', (data) => {
      const taskStore = useTaskStore()
      taskStore.updateTask(data.taskId, data)
    })
  }

  return { setupListeners }
}
```

---

## 12. Performance Optimization

### Code Splitting

```typescript
// Lazy-load all views
const routes = [
  {
    path: '/email',
    component: () => import(/* webpackChunkName: "email" */ '@/views/EmailView.vue')
  },
  {
    path: '/tasks',
    component: () => import(/* webpackChunkName: "tasks" */ '@/views/TasksView.vue')
  }
  // ... etc
]
```

### Virtual Scrolling

```vue
<!-- For large lists (email threads, tasks) -->
<script setup lang="ts">
import { useVirtualList } from '@vueuse/core'

const { list, containerProps, wrapperProps } = useVirtualList(
  threads,
  { itemHeight: 80 }
)
</script>

<template>
  <div v-bind="containerProps" class="h-screen overflow-auto">
    <div v-bind="wrapperProps">
      <EmailThreadCard v-for="item in list" :key="item.index" :thread="item.data" />
    </div>
  </div>
</template>
```

### Pinia Optimizations

```typescript
// Only persist essential data
persist: {
  paths: ['user', 'token'], // Don't persist large arrays
  storage: localStorage
}

// Use computed getters for filtered data
getters: {
  urgentTasks: (state) => state.tasks.filter(t => t.priority >= 8)
}
```

---

## 13. Testing Strategy

### Unit Tests (Vitest)

```typescript
// tests/unit/stores/email.spec.ts
import { setActivePinia, createPinia } from 'pinia'
import { useEmailStore } from '@/stores/email'

describe('Email Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('fetches email threads', async () => {
    const store = useEmailStore()
    await store.fetchThreads(30)
    expect(store.threads.length).toBeGreaterThan(0)
  })
})
```

### E2E Tests (Playwright)

```typescript
// tests/e2e/specs/chat.spec.ts
import { test, expect } from '@playwright/test'

test('sends chat message and receives response', async ({ page }) => {
  await page.goto('/')
  await page.fill('[data-testid="message-input"]', 'search emails from luisa')
  await page.click('[data-testid="send-button"]')
  await expect(page.locator('[data-testid="ai-response"]')).toBeVisible()
})
```

---

## 14. Build & Deployment (Local Development)

**Note**: This section covers local development builds. For production deployment to Vercel and Railway, see Section 15.

### Environment Variables

```bash
# .env.example
VITE_API_URL=http://localhost:9000
VITE_FIREBASE_API_KEY=your-api-key
VITE_FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=your-project-id
```

### Vite Configuration

```typescript
// vite.config.ts
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src')
    }
  },
  server: {
    port: 8080,
    proxy: {
      '/api': {
        target: 'http://localhost:9000',
        changeOrigin: true
      }
    }
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor': ['vue', 'vue-router', 'pinia'],
          'firebase': ['firebase/app', 'firebase/auth'],
          'ui': ['@headlessui/vue', '@heroicons/vue']
        }
      }
    }
  }
})
```

---

## 15. Production Deployment (Vercel + Railway)

### 15.1 Architecture Overview

```
┌─────────────────┐     HTTPS      ┌─────────────────┐
│   Vercel        │ ◄────────────► │   Railway       │
│   (Frontend)    │                │   (Backend)     │
│                 │                │                 │
│   Vue 3 SPA     │   REST API     │   FastAPI       │
│   Static Assets │   WebSocket    │   Python        │
└─────────────────┘                └─────────────────┘
        │                                  │
        │         ┌─────────────┐          │
        └────────►│  Firebase   │◄─────────┘
                  │  Auth       │
                  └─────────────┘
```

### 15.2 Vercel Configuration

**vercel.json:**
```json
{
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "framework": "vite",
  "rewrites": [
    { "source": "/(.*)", "destination": "/index.html" }
  ],
  "headers": [
    {
      "source": "/assets/(.*)",
      "headers": [
        { "key": "Cache-Control", "value": "public, max-age=31536000, immutable" }
      ]
    }
  ]
}
```

**Environment Variables (Vercel Dashboard):**
```bash
VITE_API_URL=https://your-app.up.railway.app
VITE_FIREBASE_API_KEY=your-api-key
VITE_FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=your-project-id
VITE_WS_URL=wss://your-app.up.railway.app
```

### 15.3 Railway Configuration

**railway.json:**
```json
{
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "uvicorn zylch.api.main:app --host 0.0.0.0 --port $PORT",
    "healthcheckPath": "/health",
    "restartPolicyType": "ON_FAILURE"
  }
}
```

**Environment Variables (Railway Dashboard):**
```bash
ANTHROPIC_API_KEY=sk-ant-...
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_PRIVATE_KEY=...
FIREBASE_CLIENT_EMAIL=...
ALLOWED_ORIGINS=https://your-app.vercel.app,http://localhost:5173
MY_EMAILS=you@company.com
OWNER_ID=owner_default
```

### 15.4 CORS Configuration

**Backend (`zylch/api/main.py`):**
```python
import os
from fastapi.middleware.cors import CORSMiddleware

# Production origins from environment
allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 15.5 WebSocket Configuration for Railway

Railway supports persistent WebSocket connections. Update Socket.io config:

**Frontend (`src/services/websocket.ts`):**
```typescript
const socket = io(import.meta.env.VITE_WS_URL || import.meta.env.VITE_API_URL, {
  transports: ['websocket', 'polling'],  // Prefer WebSocket, fallback to polling
  reconnection: true,
  reconnectionAttempts: 5,
  reconnectionDelay: 1000,
  auth: {
    token: authStore.token
  }
})
```

### 15.6 Deployment Checklist

**Pre-deployment:**
- [ ] All environment variables set in Vercel dashboard
- [ ] All environment variables set in Railway dashboard
- [ ] CORS origins updated for production domain
- [ ] Firebase project configured for production
- [ ] API health endpoint working (`/health`)

**Vercel Deployment:**
```bash
# Install Vercel CLI
npm i -g vercel

# Deploy (from frontend directory)
cd frontend
vercel --prod
```

**Railway Deployment:**
```bash
# Install Railway CLI
npm i -g @railway/cli

# Login and deploy (from project root)
railway login
railway up
```

### 15.7 Domain Configuration

**Vercel:**
1. Go to Project Settings → Domains
2. Add custom domain (e.g., `app.zylch.ai`)
3. Configure DNS records as shown by Vercel

**Railway:**
1. Go to Service Settings → Networking
2. Generate domain or add custom domain (e.g., `api.zylch.ai`)
3. Update `VITE_API_URL` in Vercel with Railway domain

### 15.8 Monitoring & Logs

**Vercel:**
- Deployment logs in Vercel dashboard
- Runtime logs for Edge Functions
- Analytics for Core Web Vitals
- Real-time error tracking

**Railway:**
- Real-time logs: `railway logs`
- Metrics dashboard for CPU/Memory usage
- Set up alerts for errors
- Database connection monitoring

**Health Checks:**
```bash
# Check backend health
curl https://your-app.up.railway.app/health

# Check frontend deployment
curl https://your-app.vercel.app
```

### 15.9 CI/CD Integration

**GitHub Actions (Optional Automation):**
```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: amondnet/vercel-action@v20
        with:
          vercel-token: ${{ secrets.VERCEL_TOKEN }}
          vercel-org-id: ${{ secrets.VERCEL_ORG_ID }}
          vercel-project-id: ${{ secrets.VERCEL_PROJECT_ID }}

  deploy-backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: bervProject/railway-deploy@main
        with:
          railway_token: ${{ secrets.RAILWAY_TOKEN }}
          service: backend
```

### 15.10 Performance Optimization for Production

**Vercel Edge Functions:**
```typescript
// Optional: API routes in Vercel for caching
// api/cache.ts
import { NextRequest } from 'next/server'

export const config = {
  runtime: 'edge',
}

export default async function handler(req: NextRequest) {
  // Cache frequently accessed data at the edge
}
```

**Railway Scaling:**
```json
// railway.json (add scaling config)
{
  "deploy": {
    "numReplicas": 2,
    "restartPolicyType": "ON_FAILURE",
    "healthcheckPath": "/health",
    "healthcheckTimeout": 100
  }
}
```

### 15.11 Security Best Practices

**Environment Variables Security:**
- Never commit `.env` files
- Use Vercel/Railway dashboard for secrets
- Rotate API keys regularly
- Use different Firebase projects for dev/prod

**CORS Hardening:**
```python
# Production-only strict CORS
if os.getenv("ENVIRONMENT") == "production":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[os.getenv("FRONTEND_URL")],  # Single origin
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],  # Explicit methods
        allow_headers=["Authorization", "Content-Type"],  # Explicit headers
    )
```

**Rate Limiting:**
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.get("/api/chat/message")
@limiter.limit("10/minute")
async def chat_message(request: Request):
    # Protected endpoint
    pass
```

---

## 15. Implementation Phases (Completed)

### Phase 1: Foundation ✅
1. Project setup (Vite + Vue 3 + TypeScript)
2. Authentication flow (Firebase)
3. API service layer (Axios + interceptors)
4. Basic routing (Vue Router)
5. Layout components (Header, Sidebar, Footer)
6. Pinia stores structure

### Phase 2: Chat Interface ✅
1. ChatInterface component
2. MessageBubble with markdown rendering
3. CommandPalette with autocomplete
4. WebSocket integration
5. Chat history sidebar

### Phase 3: Email Management ✅
1. EmailView with thread list
2. EmailThreadView component
3. EmailComposer (draft editor)
4. Gmail API integration
5. Search and filters

### Phase 4: Task Management ✅
1. TaskBoard with drag-and-drop
2. TaskCard components
3. Task filters and stats
4. Person-centric task detail view

### Phase 5: Calendar & Contacts ✅
1. CalendarView with multiple layouts
2. EventEditor with Meet integration
3. ContactList and ContactDetail
4. Contact enrichment UI

### Phase 6: Advanced Features ✅
1. Memory management UI
2. Email archive viewer
3. Cache management
4. MrCall integration
5. Settings panel with BYOK

### Phase 7: Polish ✅
1. Sync status dashboard
2. Google OAuth integration
3. Anthropic API key management
4. Responsive design

---

## 16. Memory Architecture (JSON)

```json
{
  "architecture": {
    "framework": "Vue 3.5+ with Composition API",
    "language": "TypeScript 5.6+",
    "build": "Vite 6.0+",
    "state": "Pinia 2.2+ with persistence",
    "routing": "Vue Router 4.4+",
    "http": "Axios 1.7+ with interceptors",
    "websocket": "Socket.io-client 4.8+",
    "auth": "Firebase Auth SDK",
    "styling": "Tailwind CSS (matching zylch-website)",
    "ui": "Headless UI + custom components"
  },
  "directory_structure": {
    "components": {
      "layout": ["AppHeader", "AppSidebar", "AppFooter", "DashboardLayout"],
      "chat": ["ChatInterface", "MessageBubble", "MessageInput", "CommandPalette"],
      "email": ["EmailList", "EmailThreadView", "EmailComposer", "DraftsList"],
      "tasks": ["TaskBoard", "TaskCard", "TaskDetail", "TaskFilters"],
      "calendar": ["CalendarView", "EventCard", "EventEditor", "MeetingScheduler"],
      "contacts": ["ContactList", "ContactCard", "ContactDetail"],
      "memory": ["MemoryManager", "MemoryCard", "MemoryStats"],
      "archive": ["ArchiveViewer", "ArchiveSearch", "ArchiveStats"],
      "campaigns": ["CampaignList", "CampaignEditor", "TemplateEditor"],
      "sharing": ["SharingManager", "RecipientList", "SharingStatus"],
      "triggers": ["TriggerManager", "TriggerList", "TriggerForm"],
      "cache": ["CacheManager"],
      "mrcall": ["MrCallManager", "MrCallLinkForm"],
      "settings": ["SettingsPanel", "AccountSettings", "AssistantSettings"],
      "common": ["Button", "Input", "Modal", "Toast", "Spinner"]
    },
    "stores": ["auth", "chat", "email", "tasks", "calendar", "contacts", "memory", "archive", "campaigns", "sharing", "sync", "settings", "mrCall", "websocket"],
    "services": ["api", "websocket", "firebase", "storage", "markdown"],
    "views": ["DashboardView", "EmailView", "TasksView", "CalendarView", "ContactsView", "MemoryView", "ArchiveView", "CampaignsView", "SharingView", "SettingsView"]
  },
  "routing": {
    "protected": ["/", "/email", "/tasks", "/calendar", "/contacts", "/memory", "/archive", "/campaigns", "/sharing", "/triggers", "/cache", "/mrcall", "/settings", "/settings/sharing-status"],
    "public": ["/auth/login", "/auth/callback"]
  },
  "cli_mapping": {
    "commands": {
      "/help": "CommandPalette modal",
      "/sync": "SyncDashboard modal",
      "/memory": "MemoryView page",
      "/memory --build": "MemoryManager with build option",
      "/trigger": "TriggersView page",
      "/cache": "CacheView page",
      "/mrcall": "MrCallView page",
      "/archive": "ArchiveView page",
      "/assistant": "AssistantSettings",
      "/share": "SharingView page",
      "/share --status": "SharingStatus component"
    },
    "natural_language": "ChatInterface → AI agent → open appropriate view"
  },
  "styling": {
    "approach": "Tailwind CSS with CSS custom properties",
    "colors": {
      "bg-primary": "#ffffff",
      "text-primary": "#1a1a1a",
      "text-muted": "#888888",
      "accent": "#4a9eff"
    },
    "radius": {
      "default": "12px",
      "large": "24px"
    },
    "typography": "Inter font family (matching zylch-website)"
  },
  "real_time": {
    "websocket_events": ["chat_message", "sync_progress", "notification", "task_update", "email_received"],
    "connection": "Socket.io with automatic reconnection"
  },
  "authentication": {
    "providers": ["Google", "Microsoft"],
    "method": "Firebase Auth with OAuth2",
    "token": "JWT from Firebase (stored in Pinia + localStorage)"
  }
}
```

---

## 17. Next Steps

### Development Setup

```bash
# Create Vue 3 project with Vite
npm create vite@latest zylch-dashboard -- --template vue-ts

# Install dependencies
cd zylch-dashboard
npm install

# Add core libraries
npm install pinia pinia-plugin-persistedstate vue-router axios socket.io-client
npm install firebase date-fns marked highlight.js
npm install @headlessui/vue @heroicons/vue
npm install -D tailwindcss postcss autoprefixer

# Initialize Tailwind
npx tailwindcss init -p

# Start dev server
npm run dev
```

### Configuration Files

1. Copy CSS variables from `zylch-website/styles/common.css`
2. Configure Tailwind to match existing design system
3. Set up Firebase config from environment variables
4. Configure Axios base URL and interceptors
5. Set up Vue Router with auth guards

### Initial Components to Build

1. **AppHeader.vue** - Fixed header with logo and sign out
2. **DashboardLayout.vue** - Main layout with sidebar
3. **ChatInterface.vue** - Chat container
4. **MessageBubble.vue** - Single message display
5. **MessageInput.vue** - Chat input with command autocomplete

---

## Conclusion

This architecture provides a complete blueprint for building a Vue 3 dashboard that replicates ALL zylch-cli functionality while maintaining the visual identity of zylch-website. The design prioritizes:

- **Type safety** (TypeScript everywhere)
- **State management** (Pinia with persistence)
- **Real-time updates** (WebSocket integration)
- **Performance** (code splitting, virtual scrolling)
- **Maintainability** (clear component hierarchy, service layer)
- **User experience** (smooth animations, responsive design)

All CLI commands are mapped to dashboard features, ensuring feature parity between the CLI and web interface.
