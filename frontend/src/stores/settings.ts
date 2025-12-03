import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { settingsService, triggerService, cacheService, sharingService } from '@/services/api'
import type { Assistant, AssistantSettings, Trigger, CacheStats, ShareAuthorization } from '@/types'

export const useSettingsStore = defineStore('settings', () => {
  // State
  const assistant = ref<Assistant | null>(null)
  const triggers = ref<Trigger[]>([])
  const cacheStats = ref<CacheStats | null>(null)
  const shareAuthorizations = ref<ShareAuthorization[]>([])
  const model = ref<'haiku' | 'sonnet' | 'opus' | 'auto'>('auto')
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  // Getters
  const activeTriggers = computed(() => triggers.value.filter(t => t.isActive))

  // Actions
  async function fetchAssistant(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      assistant.value = await settingsService.getAssistant()
      if (assistant.value?.settings.model) {
        model.value = assistant.value.settings.model
      }
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch assistant'
    } finally {
      isLoading.value = false
    }
  }

  async function updateAssistantSettings(settings: Partial<AssistantSettings>): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      await settingsService.updateAssistantSettings(settings)
      if (assistant.value) {
        assistant.value.settings = { ...assistant.value.settings, ...settings }
      }
      if (settings.model) model.value = settings.model
    } catch (err: any) {
      error.value = err.message || 'Failed to update settings'
      throw err
    } finally {
      isLoading.value = false
    }
  }

  // Trigger Management
  async function fetchTriggers(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      triggers.value = await triggerService.getTriggers()
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch triggers'
    } finally {
      isLoading.value = false
    }
  }

  async function addTrigger(trigger: Partial<Trigger>): Promise<Trigger> {
    isLoading.value = true
    error.value = null
    try {
      const newTrigger = await triggerService.addTrigger(trigger)
      triggers.value.push(newTrigger)
      return newTrigger
    } catch (err: any) {
      error.value = err.message || 'Failed to add trigger'
      throw err
    } finally {
      isLoading.value = false
    }
  }

  async function removeTrigger(id: string): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      await triggerService.removeTrigger(id)
      triggers.value = triggers.value.filter(t => t.id !== id)
    } catch (err: any) {
      error.value = err.message || 'Failed to remove trigger'
      throw err
    } finally {
      isLoading.value = false
    }
  }

  // Cache Management
  async function fetchCacheStats(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      cacheStats.value = await cacheService.getStats()
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch cache stats'
    } finally {
      isLoading.value = false
    }
  }

  async function clearCache(type: 'emails' | 'calendar' | 'gaps' | 'tasks' | 'all'): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      await cacheService.clearCache(type)
      await fetchCacheStats()
    } catch (err: any) {
      error.value = err.message || 'Failed to clear cache'
      throw err
    } finally {
      isLoading.value = false
    }
  }

  // Sharing Management
  async function fetchShareAuthorizations(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      shareAuthorizations.value = await sharingService.getAuthorizations()
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch share authorizations'
    } finally {
      isLoading.value = false
    }
  }

  async function shareWithRecipient(email: string, permissions: string[]): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      const auth = await sharingService.share(email, permissions)
      shareAuthorizations.value.push(auth)
    } catch (err: any) {
      error.value = err.message || 'Failed to share'
      throw err
    } finally {
      isLoading.value = false
    }
  }

  async function revokeShare(id: string): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      await sharingService.revoke(id)
      shareAuthorizations.value = shareAuthorizations.value.filter(a => a.id !== id)
    } catch (err: any) {
      error.value = err.message || 'Failed to revoke share'
      throw err
    } finally {
      isLoading.value = false
    }
  }

  function setModel(newModel: typeof model.value): void {
    model.value = newModel
    if (assistant.value) {
      updateAssistantSettings({ model: newModel })
    }
  }

  function clearError(): void {
    error.value = null
  }

  return {
    // State
    assistant,
    triggers,
    cacheStats,
    shareAuthorizations,
    model,
    isLoading,
    error,
    // Getters
    activeTriggers,
    // Actions
    fetchAssistant,
    updateAssistantSettings,
    fetchTriggers,
    addTrigger,
    removeTrigger,
    fetchCacheStats,
    clearCache,
    fetchShareAuthorizations,
    shareWithRecipient,
    revokeShare,
    setModel,
    clearError
  }
})
