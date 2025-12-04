import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

// Lazy load views for better performance
const LoginView = () => import('@/views/LoginView.vue')
const AuthCallbackView = () => import('@/views/AuthCallbackView.vue')
const NotAllowedView = () => import('@/views/NotAllowedView.vue')
const DashboardView = () => import('@/views/DashboardView.vue')
const EmailsView = () => import('@/views/EmailsView.vue')
const EmailThreadView = () => import('@/views/EmailThreadView.vue')
const DraftsView = () => import('@/views/DraftsView.vue')
const TasksView = () => import('@/views/TasksView.vue')
const CalendarView = () => import('@/views/CalendarView.vue')
const ContactsView = () => import('@/views/ContactsView.vue')
const GapsView = () => import('@/views/GapsView.vue')
const MemoryView = () => import('@/views/MemoryView.vue')
const ChatView = () => import('@/views/ChatView.vue')
const SyncView = () => import('@/views/SyncView.vue')
const SettingsView = () => import('@/views/SettingsView.vue')
const TriggersView = () => import('@/views/TriggersView.vue')
const CacheView = () => import('@/views/CacheView.vue')
const MrCallView = () => import('@/views/MrCallView.vue')
const SharingView = () => import('@/views/SharingView.vue')

const routes: RouteRecordRaw[] = [
  // Public routes
  {
    path: '/login',
    name: 'login',
    component: LoginView,
    meta: { requiresAuth: false }
  },
  {
    path: '/auth/callback',
    name: 'auth-callback',
    component: AuthCallbackView,
    meta: { requiresAuth: false }
  },
  {
    path: '/not-allowed',
    name: 'not-allowed',
    component: NotAllowedView,
    meta: { requiresAuth: false }
  },

  // Protected routes
  {
    path: '/',
    name: 'dashboard',
    component: DashboardView,
    meta: { requiresAuth: true }
  },
  {
    path: '/emails',
    name: 'emails',
    component: EmailsView,
    meta: { requiresAuth: true }
  },
  {
    path: '/emails/thread/:threadId',
    name: 'email-thread',
    component: EmailThreadView,
    meta: { requiresAuth: true },
    props: true
  },
  {
    path: '/drafts',
    name: 'drafts',
    component: DraftsView,
    meta: { requiresAuth: true }
  },
  {
    path: '/tasks',
    name: 'tasks',
    component: TasksView,
    meta: { requiresAuth: true }
  },
  {
    path: '/calendar',
    name: 'calendar',
    component: CalendarView,
    meta: { requiresAuth: true }
  },
  {
    path: '/contacts',
    name: 'contacts',
    component: ContactsView,
    meta: { requiresAuth: true }
  },
  {
    path: '/gaps',
    name: 'gaps',
    component: GapsView,
    meta: { requiresAuth: true }
  },
  {
    path: '/memory',
    name: 'memory',
    component: MemoryView,
    meta: { requiresAuth: true }
  },
  {
    path: '/chat',
    name: 'chat',
    component: ChatView,
    meta: { requiresAuth: true }
  },
  {
    path: '/sync',
    name: 'sync',
    component: SyncView,
    meta: { requiresAuth: true }
  },
  {
    path: '/settings',
    name: 'settings',
    component: SettingsView,
    meta: { requiresAuth: true }
  },
  {
    path: '/triggers',
    name: 'triggers',
    component: TriggersView,
    meta: { requiresAuth: true }
  },
  {
    path: '/cache',
    name: 'cache',
    component: CacheView,
    meta: { requiresAuth: true }
  },
  {
    path: '/mrcall',
    name: 'mrcall',
    component: MrCallView,
    meta: { requiresAuth: true }
  },
  {
    path: '/sharing',
    name: 'sharing',
    component: SharingView,
    meta: { requiresAuth: true }
  },

  // Catch all - redirect to dashboard
  {
    path: '/:pathMatch(.*)*',
    redirect: '/'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(_to, _from, savedPosition) {
    if (savedPosition) {
      return savedPosition
    }
    return { top: 0 }
  }
})

// Navigation guard
router.beforeEach(async (to, _from, next) => {
  const authStore = useAuthStore()

  // Wait for auth to initialize
  if (authStore.isLoading) {
    await authStore.initAuth()
  }

  const requiresAuth = to.meta.requiresAuth !== false

  if (requiresAuth && !authStore.isAuthenticated) {
    next({ name: 'login', query: { redirect: to.fullPath } })
  } else if (to.name === 'login' && authStore.isAuthenticated) {
    next({ name: 'dashboard' })
  } else {
    next()
  }
})

export default router
