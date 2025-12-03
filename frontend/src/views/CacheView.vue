<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'

const settingsStore = useSettingsStore()
const clearing = ref(false)

onMounted(() => {
  settingsStore.fetchCacheStats()
})

function formatBytes(bytes: number) {
  if (bytes === 0) return '0 Bytes'
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

async function clearCache(type?: string) {
  if (!confirm(`Are you sure you want to clear ${type || 'all'} cache?`)) return
  clearing.value = true
  await settingsStore.clearCache(type)
  await settingsStore.fetchCacheStats()
  clearing.value = false
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex-shrink-0 p-4 border-b border-gray-200">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-semibold text-gray-900">Cache Management</h1>
          <p class="text-sm text-gray-500">Manage cached data and storage</p>
        </div>
        <button
          @click="clearCache()"
          :disabled="clearing"
          class="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50"
        >
          {{ clearing ? 'Clearing...' : 'Clear All Cache' }}
        </button>
      </div>
    </div>

    <!-- Cache Stats -->
    <div class="flex-1 overflow-y-auto p-4">
      <div v-if="settingsStore.loading" class="flex items-center justify-center h-32">
        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-accent"></div>
      </div>

      <div v-else class="max-w-2xl mx-auto space-y-6">
        <!-- Overview -->
        <div class="bg-white border border-gray-200 rounded-xl p-6">
          <h2 class="font-semibold text-gray-900 mb-4">Storage Overview</h2>
          <div class="grid grid-cols-3 gap-4">
            <div class="text-center p-4 bg-gray-50 rounded-lg">
              <p class="text-2xl font-bold text-gray-900">
                {{ formatBytes(settingsStore.cacheStats.totalSize || 0) }}
              </p>
              <p class="text-sm text-gray-500">Total Size</p>
            </div>
            <div class="text-center p-4 bg-gray-50 rounded-lg">
              <p class="text-2xl font-bold text-gray-900">
                {{ settingsStore.cacheStats.itemCount || 0 }}
              </p>
              <p class="text-sm text-gray-500">Items Cached</p>
            </div>
            <div class="text-center p-4 bg-gray-50 rounded-lg">
              <p class="text-2xl font-bold text-gray-900">
                {{ settingsStore.cacheStats.hitRate ? Math.round(settingsStore.cacheStats.hitRate * 100) : 0 }}%
              </p>
              <p class="text-sm text-gray-500">Hit Rate</p>
            </div>
          </div>
        </div>

        <!-- Cache Types -->
        <div class="bg-white border border-gray-200 rounded-xl p-6">
          <h2 class="font-semibold text-gray-900 mb-4">Cache Categories</h2>

          <div class="space-y-4">
            <div class="flex items-center justify-between p-4 bg-gray-50 rounded-lg">
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center">
                  <svg class="w-5 h-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
                  </svg>
                </div>
                <div>
                  <h3 class="font-medium text-gray-900">Email Cache</h3>
                  <p class="text-sm text-gray-500">
                    {{ settingsStore.cacheStats.emailCount || 0 }} threads •
                    {{ formatBytes(settingsStore.cacheStats.emailSize || 0) }}
                  </p>
                </div>
              </div>
              <button
                @click="clearCache('email')"
                :disabled="clearing"
                class="text-sm text-red-600 hover:text-red-700 transition-colors disabled:opacity-50"
              >
                Clear
              </button>
            </div>

            <div class="flex items-center justify-between p-4 bg-gray-50 rounded-lg">
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center">
                  <svg class="w-5 h-5 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
                  </svg>
                </div>
                <div>
                  <h3 class="font-medium text-gray-900">Calendar Cache</h3>
                  <p class="text-sm text-gray-500">
                    {{ settingsStore.cacheStats.calendarCount || 0 }} events •
                    {{ formatBytes(settingsStore.cacheStats.calendarSize || 0) }}
                  </p>
                </div>
              </div>
              <button
                @click="clearCache('calendar')"
                :disabled="clearing"
                class="text-sm text-red-600 hover:text-red-700 transition-colors disabled:opacity-50"
              >
                Clear
              </button>
            </div>

            <div class="flex items-center justify-between p-4 bg-gray-50 rounded-lg">
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 bg-purple-100 rounded-lg flex items-center justify-center">
                  <svg class="w-5 h-5 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/>
                  </svg>
                </div>
                <div>
                  <h3 class="font-medium text-gray-900">Chat History</h3>
                  <p class="text-sm text-gray-500">
                    {{ settingsStore.cacheStats.chatCount || 0 }} messages •
                    {{ formatBytes(settingsStore.cacheStats.chatSize || 0) }}
                  </p>
                </div>
              </div>
              <button
                @click="clearCache('chat')"
                :disabled="clearing"
                class="text-sm text-red-600 hover:text-red-700 transition-colors disabled:opacity-50"
              >
                Clear
              </button>
            </div>

            <div class="flex items-center justify-between p-4 bg-gray-50 rounded-lg">
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 bg-yellow-100 rounded-lg flex items-center justify-center">
                  <svg class="w-5 h-5 text-yellow-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
                  </svg>
                </div>
                <div>
                  <h3 class="font-medium text-gray-900">Memory Data</h3>
                  <p class="text-sm text-gray-500">
                    {{ settingsStore.cacheStats.memoryCount || 0 }} entries •
                    {{ formatBytes(settingsStore.cacheStats.memorySize || 0) }}
                  </p>
                </div>
              </div>
              <button
                @click="clearCache('memory')"
                :disabled="clearing"
                class="text-sm text-red-600 hover:text-red-700 transition-colors disabled:opacity-50"
              >
                Clear
              </button>
            </div>
          </div>
        </div>

        <!-- Cache Settings -->
        <div class="bg-white border border-gray-200 rounded-xl p-6">
          <h2 class="font-semibold text-gray-900 mb-4">Cache Settings</h2>

          <div class="space-y-4">
            <div class="flex items-center justify-between">
              <div>
                <h3 class="font-medium text-gray-900">Auto-clear on logout</h3>
                <p class="text-sm text-gray-500">Clear cache when signing out</p>
              </div>
              <button
                @click="settingsStore.updateSettings({ autoClearCache: !settingsStore.settings.autoClearCache })"
                :class="[
                  'relative w-12 h-6 rounded-full transition-colors',
                  settingsStore.settings.autoClearCache ? 'bg-accent' : 'bg-gray-300'
                ]"
              >
                <span
                  :class="[
                    'absolute top-1 w-4 h-4 bg-white rounded-full transition-transform',
                    settingsStore.settings.autoClearCache ? 'left-7' : 'left-1'
                  ]"
                />
              </button>
            </div>

            <div class="flex items-center justify-between">
              <div>
                <h3 class="font-medium text-gray-900">Cache Retention</h3>
                <p class="text-sm text-gray-500">How long to keep cached data</p>
              </div>
              <select
                :value="settingsStore.settings.cacheRetention || '7d'"
                @change="settingsStore.updateSettings({ cacheRetention: ($event.target as HTMLSelectElement).value })"
                class="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
              >
                <option value="1d">1 Day</option>
                <option value="7d">7 Days</option>
                <option value="30d">30 Days</option>
                <option value="forever">Forever</option>
              </select>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
