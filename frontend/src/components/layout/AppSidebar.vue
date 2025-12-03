<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useSyncStore } from '@/stores/sync'
import {
  HomeIcon,
  EnvelopeIcon,
  CalendarIcon,
  ClipboardDocumentListIcon,
  UserGroupIcon,
  ExclamationTriangleIcon,
  ChatBubbleLeftRightIcon,
  ArrowPathIcon,
  Cog6ToothIcon,
  BoltIcon,
  ArchiveBoxIcon,
  PhoneIcon,
  ShareIcon,
  ChevronLeftIcon,
  ArrowRightOnRectangleIcon,
  LightBulbIcon
} from '@heroicons/vue/24/outline'

defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  toggle: []
}>()

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const syncStore = useSyncStore()

// Computed properties for user info
const userName = computed(() => authStore.user?.name || 'User')
const userEmail = computed(() => authStore.user?.email || '')
const userPicture = computed(() => authStore.user?.picture)

const navigation = [
  { name: 'Dashboard', href: '/', icon: HomeIcon },
  { name: 'Chat', href: '/chat', icon: ChatBubbleLeftRightIcon },
  { name: 'Emails', href: '/emails', icon: EnvelopeIcon },
  { name: 'Tasks', href: '/tasks', icon: ClipboardDocumentListIcon },
  { name: 'Calendar', href: '/calendar', icon: CalendarIcon },
  { name: 'Contacts', href: '/contacts', icon: UserGroupIcon },
  { name: 'Gaps', href: '/gaps', icon: ExclamationTriangleIcon },
  { name: 'Memory', href: '/memory', icon: LightBulbIcon },
  { name: 'Sync', href: '/sync', icon: ArrowPathIcon },
]

const settingsNav = [
  { name: 'Settings', href: '/settings', icon: Cog6ToothIcon },
  { name: 'Triggers', href: '/triggers', icon: BoltIcon },
  { name: 'Cache', href: '/cache', icon: ArchiveBoxIcon },
  { name: 'MrCall', href: '/mrcall', icon: PhoneIcon },
  { name: 'Sharing', href: '/sharing', icon: ShareIcon },
]

const isActive = (href: string) => {
  if (href === '/') return route.path === '/'
  return route.path.startsWith(href)
}

async function handleLogout() {
  await authStore.logout()
  router.push('/login')
}
</script>

<template>
  <aside
    class="fixed inset-y-0 left-0 z-50 flex flex-col bg-white border-r border-gray-200 transition-all duration-300"
    :class="open ? 'w-64' : 'w-20'"
  >
    <!-- Logo -->
    <div class="flex items-center h-16 px-4 border-b border-gray-200">
      <img
        src="/logo/zylch-horizontal.svg"
        alt="Zylch"
        class="h-8 transition-opacity"
        :class="open ? 'opacity-100' : 'opacity-0 w-0'"
      />
      <img
        src="/logo/zylch-mark.svg"
        alt="Z"
        class="h-8 transition-opacity"
        :class="open ? 'opacity-0 w-0' : 'opacity-100'"
      />
    </div>

    <!-- Navigation -->
    <nav class="flex-1 overflow-y-auto py-4">
      <div class="px-3 space-y-1">
        <router-link
          v-for="item in navigation"
          :key="item.name"
          :to="item.href"
          class="flex items-center px-3 py-2 text-sm font-medium rounded-lg transition-colors"
          :class="[
            isActive(item.href)
              ? 'bg-zylch-accent/10 text-zylch-accent'
              : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
          ]"
        >
          <component
            :is="item.icon"
            class="h-5 w-5 flex-shrink-0"
            :class="open ? 'mr-3' : 'mx-auto'"
          />
          <span v-if="open">{{ item.name }}</span>

          <!-- Sync indicator -->
          <span
            v-if="item.name === 'Sync' && syncStore.isRunning"
            class="ml-auto"
          >
            <span class="flex h-2 w-2">
              <span class="animate-ping absolute inline-flex h-2 w-2 rounded-full bg-zylch-accent opacity-75"></span>
              <span class="relative inline-flex rounded-full h-2 w-2 bg-zylch-accent"></span>
            </span>
          </span>
        </router-link>
      </div>

      <!-- Settings Section -->
      <div class="mt-8 px-3">
        <h3
          v-if="open"
          class="px-3 text-xs font-semibold text-gray-400 uppercase tracking-wider"
        >
          Settings
        </h3>
        <div class="mt-2 space-y-1">
          <router-link
            v-for="item in settingsNav"
            :key="item.name"
            :to="item.href"
            class="flex items-center px-3 py-2 text-sm font-medium rounded-lg transition-colors"
            :class="[
              isActive(item.href)
                ? 'bg-zylch-accent/10 text-zylch-accent'
                : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
            ]"
          >
            <component
              :is="item.icon"
              class="h-5 w-5 flex-shrink-0"
              :class="open ? 'mr-3' : 'mx-auto'"
            />
            <span v-if="open">{{ item.name }}</span>
          </router-link>
        </div>
      </div>
    </nav>

    <!-- User & Collapse -->
    <div class="border-t border-gray-200 p-4">
      <!-- User info -->
      <div v-if="open" class="flex items-center mb-4">
        <img
          v-if="userPicture"
          :src="userPicture"
          :alt="userName"
          class="h-8 w-8 rounded-full"
        />
        <div v-else class="h-8 w-8 rounded-full bg-zylch-accent flex items-center justify-center text-white text-sm font-medium">
          {{ userName.charAt(0).toUpperCase() }}
        </div>
        <div class="ml-3 flex-1 min-w-0">
          <p class="text-sm font-medium text-gray-900 truncate">{{ userName }}</p>
          <p class="text-xs text-gray-500 truncate">{{ userEmail }}</p>
        </div>
      </div>

      <div class="flex items-center" :class="open ? 'justify-between' : 'justify-center'">
        <button
          v-if="open"
          @click="handleLogout"
          class="flex items-center text-sm text-gray-600 hover:text-gray-900"
        >
          <ArrowRightOnRectangleIcon class="h-5 w-5 mr-2" />
          Logout
        </button>

        <button
          @click="emit('toggle')"
          class="p-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100"
        >
          <ChevronLeftIcon
            class="h-5 w-5 transition-transform"
            :class="{ 'rotate-180': !open }"
          />
        </button>
      </div>
    </div>
  </aside>
</template>
