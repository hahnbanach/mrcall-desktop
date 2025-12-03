<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'

const settingsStore = useSettingsStore()
const clearing = ref(false)

// Computed properties for aggregated stats
const totalSize = computed(() => {
  const stats = settingsStore.cacheStats
  if (!stats) return 0
  return (stats.emails?.sizeBytes || 0) +
         (stats.calendar?.sizeBytes || 0) +
         (stats.gaps?.sizeBytes || 0) +
         (stats.tasks?.sizeBytes || 0)
})

const totalCount = computed(() => {
  const stats = settingsStore.cacheStats
  if (!stats) return 0
  return (stats.emails?.count || 0) +
         (stats.calendar?.count || 0) +
         (stats.gaps?.count || 0) +
         (stats.tasks?.count || 0)
})

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

async function clearCache(type?: 'emails' | 'calendar' | 'gaps' | 'tasks' | 'all') {
  if (!confirm(`Are you sure you want to clear ${type || 'all'} cache?`)) return
  clearing.value = true
  await settingsStore.clearCache(type || 'all')
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
      <div v-if="settingsStore.isLoading" class="flex items-center justify-center h-32">
        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-accent"></div>
      </div>

      <div v-else class="max-w-2xl mx-auto space-y-6">
        <!-- Overview -->
        <div class="bg-white border border-gray-200 rounded-xl p-6">
          <h2 class="font-semibold text-gray-900 mb-4">Storage Overview</h2>
          <div class="grid grid-cols-3 gap-4">
            <div class="text-center p-4 bg-gray-50 rounded-lg">
              <p class="text-2xl font-bold text-gray-900">
                {{ formatBytes(totalSize) }}
              </p>
              <p class="text-sm text-gray-500">Total Size</p>
            </div>
            <div class="text-center p-4 bg-gray-50 rounded-lg">
              <p class="text-2xl font-bold text-gray-900">
                {{ totalCount }}
              </p>
              <p class="text-sm text-gray-500">Items Cached</p>
            </div>
            <div class="text-center p-4 bg-gray-50 rounded-lg">
              <p class="text-2xl font-bold text-gray-900">
                N/A
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
                    {{ settingsStore.cacheStats?.emails?.count || 0 }} threads •
                    {{ formatBytes(settingsStore.cacheStats?.emails?.sizeBytes || 0) }}
                  </p>
                </div>
              </div>
              <button
                @click="clearCache('emails')"
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
                    {{ settingsStore.cacheStats?.calendar?.count || 0 }} events •
                    {{ formatBytes(settingsStore.cacheStats?.calendar?.sizeBytes || 0) }}
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
                  <h3 class="font-medium text-gray-900">Gap Analysis</h3>
                  <p class="text-sm text-gray-500">
                    {{ settingsStore.cacheStats?.gaps?.count || 0 }} entries •
                    {{ formatBytes(settingsStore.cacheStats?.gaps?.sizeBytes || 0) }}
                  </p>
                </div>
              </div>
              <button
                @click="clearCache('gaps')"
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
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>
                  </svg>
                </div>
                <div>
                  <h3 class="font-medium text-gray-900">Tasks Cache</h3>
                  <p class="text-sm text-gray-500">
                    {{ settingsStore.cacheStats?.tasks?.count || 0 }} entries •
                    {{ formatBytes(settingsStore.cacheStats?.tasks?.sizeBytes || 0) }}
                  </p>
                </div>
              </div>
              <button
                @click="clearCache('tasks')"
                :disabled="clearing"
                class="text-sm text-red-600 hover:text-red-700 transition-colors disabled:opacity-50"
              >
                Clear
              </button>
            </div>
          </div>
        </div>

        <!-- Cache Info -->
        <div class="bg-white border border-gray-200 rounded-xl p-6">
          <h2 class="font-semibold text-gray-900 mb-4">Cache Information</h2>
          <p class="text-sm text-gray-500">
            Cache data is stored locally to improve performance. Clear individual categories or all cache data using the buttons above.
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
