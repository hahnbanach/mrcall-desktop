<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useSyncStore } from '@/stores/sync'
import {
  Bars3Icon,
  MagnifyingGlassIcon,
  BellIcon,
  ArrowPathIcon
} from '@heroicons/vue/24/outline'

const emit = defineEmits<{
  'toggle-sidebar': []
}>()

const route = useRoute()
const syncStore = useSyncStore()

const searchQuery = ref('')

const pageTitle = computed(() => {
  const titles: Record<string, string> = {
    '/': 'Dashboard',
    '/chat': 'Chat with Zylch',
    '/emails': 'Emails',
    '/tasks': 'Tasks',
    '/calendar': 'Calendar',
    '/contacts': 'Contacts',
    '/gaps': 'Relationship Gaps',
    '/memory': 'Behavioral Memory',
    '/sync': 'Sync Status',
    '/settings': 'Settings',
    '/triggers': 'Triggered Instructions',
    '/cache': 'Cache Management',
    '/mrcall': 'MrCall Integration',
    '/sharing': 'Sharing & Access'
  }
  return titles[route.path] || 'Zylch'
})

async function handleSync() {
  if (!syncStore.isRunning) {
    await syncStore.startSync()
  }
}

function handleSearch() {
  // TODO: Implement global search
  console.log('Search:', searchQuery.value)
}
</script>

<template>
  <header class="sticky top-0 z-40 bg-white border-b border-gray-200">
    <div class="flex items-center justify-between h-16 px-4 sm:px-6 lg:px-8">
      <!-- Left: Menu & Title -->
      <div class="flex items-center">
        <button
          @click="emit('toggle-sidebar')"
          class="lg:hidden p-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100"
        >
          <Bars3Icon class="h-6 w-6" />
        </button>

        <h1 class="ml-2 lg:ml-0 text-xl font-semibold text-gray-900">
          {{ pageTitle }}
        </h1>
      </div>

      <!-- Center: Search -->
      <div class="hidden md:flex flex-1 max-w-md mx-8">
        <div class="relative w-full">
          <MagnifyingGlassIcon class="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-400" />
          <input
            v-model="searchQuery"
            @keyup.enter="handleSearch"
            type="text"
            placeholder="Search emails, contacts, tasks..."
            class="w-full pl-10 pr-4 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-zylch-accent/50 focus:border-zylch-accent"
          />
        </div>
      </div>

      <!-- Right: Actions -->
      <div class="flex items-center space-x-4">
        <!-- Sync Button -->
        <button
          @click="handleSync"
          :disabled="syncStore.isRunning"
          class="flex items-center px-3 py-2 text-sm font-medium rounded-lg transition-colors"
          :class="syncStore.isRunning
            ? 'bg-zylch-accent/10 text-zylch-accent cursor-not-allowed'
            : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'"
        >
          <ArrowPathIcon
            class="h-5 w-5 mr-2"
            :class="{ 'animate-spin': syncStore.isRunning }"
          />
          <span class="hidden sm:inline">
            {{ syncStore.isRunning ? 'Syncing...' : 'Sync' }}
          </span>
        </button>

        <!-- Notifications -->
        <button class="p-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 relative">
          <BellIcon class="h-6 w-6" />
          <!-- Notification dot -->
          <span class="absolute top-1 right-1 h-2 w-2 bg-red-500 rounded-full"></span>
        </button>
      </div>
    </div>

    <!-- Sync Progress Bar -->
    <div
      v-if="syncStore.isRunning && syncStore.progress"
      class="h-1 bg-gray-100"
    >
      <div
        class="h-full bg-zylch-accent transition-all duration-300"
        :style="{ width: `${(syncStore.progress.current / syncStore.progress.total) * 100}%` }"
      ></div>
    </div>
  </header>
</template>
