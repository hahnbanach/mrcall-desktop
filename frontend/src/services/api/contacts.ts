import api from './index'
import type { Contact, RelationshipGap } from '@/types'

export const contactService = {
  async getContacts(): Promise<Contact[]> {
    const { data } = await api.get('/api/contacts')
    return data
  },

  async getContact(id: string): Promise<Contact> {
    const { data } = await api.get(`/api/contacts/${encodeURIComponent(id)}`)
    return data
  },

  async updateContact(id: string, updates: Partial<Contact>): Promise<Contact> {
    const { data } = await api.patch(`/api/contacts/${encodeURIComponent(id)}`, updates)
    return data
  },

  async enrichContact(email: string): Promise<Contact> {
    const { data } = await api.post(`/api/contacts/${encodeURIComponent(email)}/enrich`)
    return data
  },

  async getRelationshipGaps(): Promise<Contact[]> {
    const { data } = await api.get('/api/contacts/gaps')
    return data
  },

  async getGaps(): Promise<RelationshipGap[]> {
    const { data } = await api.get('/api/contacts/gaps')
    return data
  }
}

// Alias for stores that use contactsApi
export const contactsApi = contactService
