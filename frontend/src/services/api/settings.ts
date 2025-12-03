import api from './index'
import type { Assistant, AssistantSettings, Trigger, CacheStats, ShareAuthorization } from '@/types'

export const settingsService = {
  async getAssistant(): Promise<Assistant> {
    const { data } = await api.get('/api/assistant')
    return data
  },

  async updateAssistantSettings(settings: Partial<AssistantSettings>): Promise<void> {
    await api.patch('/api/assistant/settings', settings)
  }
}

export const triggerService = {
  async getTriggers(): Promise<Trigger[]> {
    const { data } = await api.get('/api/triggers')
    return data
  },

  async addTrigger(trigger: Partial<Trigger>): Promise<Trigger> {
    const { data } = await api.post('/api/triggers', trigger)
    return data
  },

  async removeTrigger(id: string): Promise<void> {
    await api.delete(`/api/triggers/${id}`)
  },

  async checkTriggers(): Promise<{ triggered: Trigger[] }> {
    const { data } = await api.post('/api/triggers/check')
    return data
  }
}

export const cacheService = {
  async getStats(): Promise<CacheStats> {
    const { data } = await api.get('/api/cache/stats')
    return data
  },

  async clearCache(type: 'emails' | 'calendar' | 'gaps' | 'tasks' | 'all'): Promise<void> {
    await api.delete(`/api/cache/${type}`)
  }
}

export const sharingService = {
  async getAuthorizations(): Promise<ShareAuthorization[]> {
    const { data } = await api.get('/api/sharing')
    return data
  },

  async share(email: string, permissions: string[]): Promise<ShareAuthorization> {
    const { data } = await api.post('/api/sharing', { email, permissions })
    return data
  },

  async revoke(id: string): Promise<void> {
    await api.delete(`/api/sharing/${id}`)
  }
}
