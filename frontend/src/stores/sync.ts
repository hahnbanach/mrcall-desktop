import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { syncService } from '@/services/api'
import type { SyncStatus, SyncProgress } from '@/types'

export const useSyncStore = defineStore('sync', () => {
  // State
  const status = ref<SyncStatus>({
    isRunning: false,
    lastSync: null,
    progress: null,
    error: null
  })
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  // Getters
  const isRunning = computed(() => status.value.isRunning)
  const progress = computed(() => status.value.progress)
  const lastSync = computed(() => status.value.lastSync)

  // Actions
  async function fetchStatus(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      status.value = await syncService.getStatus()
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch sync status'
    } finally {
      isLoading.value = false
    }
  }

  async function startSync(days?: number): Promise<void> {
    isLoading.value = true
    error.value = null
    status.value.isRunning = true
    status.value.error = null

    try {
      await syncService.startSync(days)
    } catch (err: any) {
      error.value = err.message || 'Failed to start sync'
      status.value.isRunning = false
      throw err
    } finally {
      isLoading.value = false
    }
  }

  function updateProgress(progress: SyncProgress): void {
    status.value.progress = progress
  }

  function syncCompleted(): void {
    status.value.isRunning = false
    status.value.progress = null
    status.value.lastSync = new Date().toISOString()
  }

  function syncError(errorMessage: string): void {
    status.value.isRunning = false
    status.value.error = errorMessage
    error.value = errorMessage
  }

  function clearError(): void {
    error.value = null
    status.value.error = null
  }

  return {
    // State
    status,
    isLoading,
    error,
    // Getters
    isRunning,
    progress,
    lastSync,
    // Actions
    fetchStatus,
    startSync,
    updateProgress,
    syncCompleted,
    syncError,
    clearError
  }
})
