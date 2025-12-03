<script setup lang="ts">
import { onMounted } from 'vue'
import { useSyncStore } from '@/stores/sync'

const syncStore = useSyncStore()

onMounted(() => {
  syncStore.fetchStatus()
})

function formatDate(date: string | null) {
  if (!date) return 'Never'
  return new Date(date).toLocaleString()
}

const serviceIcons: Record<string, string> = {
  gmail: '📧',
  google_calendar: '📅',
  google_tasks: '✅',
  outlook: '📨',
  outlook_calendar: '🗓️'
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex-shrink-0 p-4 border-b border-gray-200">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-semibold text-gray-900">Sync Status</h1>
          <p class="text-sm text-gray-500">Manage data synchronization</p>
        </div>
        <button
          @click="syncStore.startSync()"
          :disabled="syncStore.isRunning"
          class="px-4 py-2 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors disabled:opacity-50 flex items-center gap-2"
        >
          <svg
            :class="['w-5 h-5', syncStore.isRunning && 'animate-spin']"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
          </svg>
          {{ syncStore.isRunning ? 'Syncing...' : 'Sync Now' }}
        </button>
      </div>
    </div>

    <!-- Sync Content -->
    <div class="flex-1 overflow-y-auto p-4">
      <div v-if="syncStore.isLoading" class="flex items-center justify-center h-32">
        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-accent"></div>
      </div>

      <div v-else class="max-w-2xl mx-auto space-y-6">
        <!-- Overall Status -->
        <div class="bg-white border border-gray-200 rounded-xl p-6">
          <div class="flex items-center justify-between mb-4">
            <h2 class="font-semibold text-gray-900">Overall Status</h2>
            <span
              :class="[
                'px-3 py-1 rounded-full text-sm',
                syncStore.isRunning ? 'bg-blue-50 text-blue-600' :
                syncStore.error ? 'bg-red-50 text-red-600' :
                syncStore.lastSync ? 'bg-green-50 text-green-600' :
                'bg-gray-50 text-gray-600'
              ]"
            >
              {{ syncStore.isRunning ? 'Syncing' : syncStore.error ? 'Error' : syncStore.lastSync ? 'Synced' : 'Ready' }}
            </span>
          </div>

          <div class="grid grid-cols-2 gap-4 text-sm">
            <div>
              <p class="text-gray-500">Last Full Sync</p>
              <p class="font-medium text-gray-900">{{ formatDate(syncStore.lastSync) }}</p>
            </div>
            <div>
              <p class="text-gray-500">Status</p>
              <p class="font-medium text-gray-900">{{ syncStore.isRunning ? 'In Progress' : 'Idle' }}</p>
            </div>
          </div>

          <!-- Progress Bar -->
          <div v-if="syncStore.isRunning && syncStore.progress" class="mt-4">
            <div class="flex items-center justify-between text-sm mb-1">
              <span class="text-gray-500">{{ syncStore.progress.message }}</span>
              <span class="text-gray-900">{{ syncStore.progress.current }}/{{ syncStore.progress.total }}</span>
            </div>
            <div class="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
              <div
                class="h-full bg-accent transition-all duration-300"
                :style="{ width: `${syncStore.progress.total > 0 ? (syncStore.progress.current / syncStore.progress.total) * 100 : 0}%` }"
              />
            </div>
          </div>
        </div>

        <!-- Sync Phases -->
        <div class="bg-white border border-gray-200 rounded-xl p-6">
          <h2 class="font-semibold text-gray-900 mb-4">Sync Phases</h2>

          <div class="space-y-4">
            <div
              v-for="phase in ['emails', 'calendar', 'gaps', 'tasks']"
              :key="phase"
              class="flex items-center justify-between p-3 bg-gray-50 rounded-lg"
            >
              <div class="flex items-center gap-3">
                <span class="text-xl">{{ serviceIcons[phase === 'emails' ? 'gmail' : phase === 'calendar' ? 'google_calendar' : phase === 'tasks' ? 'google_tasks' : '🔗'] || '🔗' }}</span>
                <div>
                  <h3 class="font-medium text-gray-900 capitalize">{{ phase }}</h3>
                  <p class="text-sm text-gray-500">
                    {{ syncStore.progress?.phase === phase ? syncStore.progress.message : 'Ready' }}
                  </p>
                </div>
              </div>
              <div class="flex items-center gap-2">
                <span
                  :class="[
                    'w-2 h-2 rounded-full',
                    syncStore.progress?.phase === phase ? 'bg-blue-500 animate-pulse' : 'bg-gray-400'
                  ]"
                />
                <span class="text-sm text-gray-600 capitalize">
                  {{ syncStore.progress?.phase === phase ? 'Syncing' : 'Idle' }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- Sync Info -->
        <div class="bg-white border border-gray-200 rounded-xl p-6">
          <h2 class="font-semibold text-gray-900 mb-4">Sync Information</h2>

          <div class="text-center py-8 text-gray-500">
            <p>Last sync: {{ formatDate(syncStore.lastSync) }}</p>
            <p class="text-sm mt-2">Click "Sync Now" to refresh your data from connected services.</p>
          </div>
        </div>

        <!-- Error Messages -->
        <div v-if="syncStore.error" class="bg-red-50 border border-red-200 rounded-xl p-4">
          <div class="flex items-start gap-3">
            <svg class="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
            </svg>
            <div>
              <h3 class="font-medium text-red-800">Sync Error</h3>
              <p class="text-sm text-red-600 mt-1">{{ syncStore.error }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
