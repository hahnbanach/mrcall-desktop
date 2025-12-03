import api from './index'
import type { EmailThread, EmailMessage, Draft } from '@/types'

export const emailService = {
  async getThreads(maxResults = 50): Promise<EmailThread[]> {
    const { data } = await api.get('/api/emails/threads', { params: { max_results: maxResults } })
    return data
  },

  async getThread(threadId: string): Promise<EmailThread> {
    const { data } = await api.get(`/api/emails/threads/${threadId}`)
    return data
  },

  async getThreadMessages(threadId: string): Promise<EmailMessage[]> {
    const { data } = await api.get(`/api/emails/threads/${threadId}/messages`)
    return data
  },

  async searchEmails(query: string): Promise<EmailThread[]> {
    const { data } = await api.get('/api/emails/search', { params: { q: query } })
    return data
  },

  async send(params: { to: string; subject: string; body: string; threadId?: string }): Promise<void> {
    await api.post('/api/emails/send', params)
  },

  async getDrafts(): Promise<Draft[]> {
    const { data } = await api.get('/api/emails/drafts')
    return data
  },

  async saveDraft(draft: Partial<Draft>): Promise<Draft> {
    if (draft.id) {
      const { data } = await api.put(`/api/emails/drafts/${draft.id}`, draft)
      return data
    }
    const { data } = await api.post('/api/emails/drafts', draft)
    return data
  },

  async deleteDraft(id: string): Promise<void> {
    await api.delete(`/api/emails/drafts/${id}`)
  },

  async sendDraft(id: string): Promise<void> {
    await api.post(`/api/emails/drafts/${id}/send`)
  },

  async markAsRead(threadId: string): Promise<void> {
    await api.post(`/api/emails/threads/${threadId}/read`)
  },

  async archive(threadId: string): Promise<void> {
    await api.post(`/api/emails/threads/${threadId}/archive`)
  }
}

// Alias for stores that use emailApi
export const emailApi = emailService
