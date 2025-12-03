import api from './index'
import type { SyncStatus } from '@/types'

export const syncService = {
  async getStatus(): Promise<SyncStatus> {
    const { data } = await api.get('/api/sync/status')
    return data
  },

  async startSync(days?: number): Promise<void> {
    await api.post('/api/sync/start', { days })
  }
}
