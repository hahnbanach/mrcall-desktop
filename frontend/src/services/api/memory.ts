import api from './index'
import type { Memory, MemoryStats } from '@/types'

interface BuildMemoryParams {
  days?: number
  contact?: string
}

export const memoryService = {
  async getMemories(): Promise<Memory[]> {
    const { data } = await api.get('/api/memory')
    return data
  },

  async getStats(): Promise<MemoryStats> {
    const { data } = await api.get('/api/memory/stats')
    return data
  },

  async addMemory(memory: Partial<Memory>): Promise<Memory> {
    const { data } = await api.post('/api/memory', memory)
    return data
  },

  async removeMemory(id: string): Promise<void> {
    await api.delete(`/api/memory/${id}`)
  },

  async buildMemory(params: BuildMemoryParams): Promise<void> {
    await api.post('/api/memory/build', params)
  }
}
