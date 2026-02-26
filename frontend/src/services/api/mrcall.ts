import api from './index'
import type { MrCallAssistant, MrCallTrainingStatus, MrCallStartTrainingResponse } from '@/types'

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
  },

  async getTrainingStatus(): Promise<MrCallTrainingStatus> {
    const { data } = await api.get('/api/mrcall/training/status')
    return data
  },

  async startTraining(options?: { force?: boolean; features?: string[] }): Promise<MrCallStartTrainingResponse> {
    const { data } = await api.post('/api/mrcall/training/start', {
      force: options?.force ?? false,
      features: options?.features ?? null,
    })
    return data
  },

  async getJobStatus(jobId: string) {
    const { data } = await api.get(`/api/jobs/${jobId}`)
    return data
  },
}
