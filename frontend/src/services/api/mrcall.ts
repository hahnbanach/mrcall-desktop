import api from './index'
import type { MrCallAssistant } from '@/types'

export const mrcallService = {
  async getAssistants(): Promise<MrCallAssistant[]> {
    const { data } = await api.get('/api/mrcall/assistants')
    return data
  },

  async linkAssistant(mrcallId: string): Promise<void> {
    await api.post('/api/mrcall/link', { mrcall_id: mrcallId })
  },

  async unlinkAssistant(): Promise<void> {
    await api.delete('/api/mrcall/link')
  }
}
