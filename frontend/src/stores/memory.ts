import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { memoryService } from '@/services/api'
import type { Memory, MemoryStats } from '@/types'

export const useMemoryStore = defineStore('memory', () => {
  // State
  const memories = ref<Memory[]>([])
  const stats = ref<MemoryStats | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const typeFilter = ref<'all' | 'personal' | 'global'>('all')

  // Getters
  const filteredMemories = computed(() => {
    if (typeFilter.value === 'all') return memories.value
    return memories.value.filter(m => m.type === typeFilter.value)
  })

  const personalMemories = computed(() => memories.value.filter(m => m.type === 'personal'))
  const globalMemories = computed(() => memories.value.filter(m => m.type === 'global'))

  // Actions
  async function fetchMemories(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      memories.value = await memoryService.getMemories()
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch memories'
    } finally {
      isLoading.value = false
    }
  }

  async function fetchStats(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      stats.value = await memoryService.getStats()
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch memory stats'
    } finally {
      isLoading.value = false
    }
  }

  async function addMemory(memory: Partial<Memory>): Promise<Memory> {
    isLoading.value = true
    error.value = null
    try {
      const newMemory = await memoryService.addMemory(memory)
      memories.value.unshift(newMemory)
      return newMemory
    } catch (err: any) {
      error.value = err.message || 'Failed to add memory'
      throw err
    } finally {
      isLoading.value = false
    }
  }

  async function removeMemory(id: string): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      await memoryService.removeMemory(id)
      memories.value = memories.value.filter(m => m.id !== id)
    } catch (err: any) {
      error.value = err.message || 'Failed to remove memory'
      throw err
    } finally {
      isLoading.value = false
    }
  }

  async function buildMemory(days?: number, contact?: string): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      await memoryService.buildMemory({ days, contact })
      await fetchMemories()
      await fetchStats()
    } catch (err: any) {
      error.value = err.message || 'Failed to build memory'
      throw err
    } finally {
      isLoading.value = false
    }
  }

  function setTypeFilter(type: typeof typeFilter.value): void {
    typeFilter.value = type
  }

  function clearError(): void {
    error.value = null
  }

  return {
    // State
    memories,
    stats,
    isLoading,
    error,
    typeFilter,
    // Getters
    filteredMemories,
    personalMemories,
    globalMemories,
    // Actions
    fetchMemories,
    fetchStats,
    addMemory,
    removeMemory,
    buildMemory,
    setTypeFilter,
    clearError
  }
})
