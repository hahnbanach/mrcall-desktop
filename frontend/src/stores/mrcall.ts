import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { mrcallService } from '@/services/api'
import type { MrCallAssistant } from '@/types'

export const useMrCallStore = defineStore('mrcall', () => {
  // State
  const assistants = ref<MrCallAssistant[]>([])
  const linkedAssistant = ref<MrCallAssistant | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  // Getters
  const activeAssistants = computed(() => assistants.value.filter(a => a.status === 'active'))
  const isLinked = computed(() => !!linkedAssistant.value)

  // Actions
  async function fetchAssistants(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      assistants.value = await mrcallService.getAssistants()
      linkedAssistant.value = assistants.value.find(a => a.linkedZylchAssistant) || null
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch MrCall assistants'
    } finally {
      isLoading.value = false
    }
  }

  async function linkAssistant(mrcallId: string): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      await mrcallService.linkAssistant(mrcallId)
      await fetchAssistants()
    } catch (err: any) {
      error.value = err.message || 'Failed to link MrCall assistant'
      throw err
    } finally {
      isLoading.value = false
    }
  }

  async function unlinkAssistant(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      await mrcallService.unlinkAssistant()
      linkedAssistant.value = null
      await fetchAssistants()
    } catch (err: any) {
      error.value = err.message || 'Failed to unlink MrCall assistant'
      throw err
    } finally {
      isLoading.value = false
    }
  }

  function clearError(): void {
    error.value = null
  }

  return {
    // State
    assistants,
    linkedAssistant,
    isLoading,
    error,
    // Getters
    activeAssistants,
    isLinked,
    // Actions
    fetchAssistants,
    linkAssistant,
    unlinkAssistant,
    clearError
  }
})
