import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Contact } from '@/types'
import { contactsApi } from '@/services/api/contacts'

export const useContactsStore = defineStore('contacts', () => {
  const contacts = ref<Contact[]>([])
  const currentContact = ref<Contact | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const searchQuery = ref('')

  const filteredContacts = computed(() => {
    if (!searchQuery.value) return contacts.value
    const query = searchQuery.value.toLowerCase()
    return contacts.value.filter(c =>
      c.name.toLowerCase().includes(query) ||
      c.email.toLowerCase().includes(query) ||
      c.company?.toLowerCase().includes(query)
    )
  })

  const contactsWithGaps = computed(() =>
    contacts.value.filter(c => c.relationshipGap && c.relationshipGap > 30)
  )

  const sortedByLastContact = computed(() =>
    [...contacts.value].sort((a, b) => {
      if (!a.lastContact && !b.lastContact) return 0
      if (!a.lastContact) return 1
      if (!b.lastContact) return -1
      return new Date(b.lastContact).getTime() - new Date(a.lastContact).getTime()
    })
  )

  const contactsByCompany = computed(() => {
    const grouped: Record<string, Contact[]> = {}
    contacts.value.forEach(contact => {
      const company = contact.company || 'No Company'
      if (!grouped[company]) grouped[company] = []
      grouped[company].push(contact)
    })
    return grouped
  })

  async function fetchContacts() {
    loading.value = true
    error.value = null
    try {
      const data = await contactsApi.getContacts()
      contacts.value = data
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch contacts'
    } finally {
      loading.value = false
    }
  }

  async function fetchContact(contactId: string) {
    loading.value = true
    error.value = null
    try {
      const data = await contactsApi.getContact(contactId)
      currentContact.value = data
      const idx = contacts.value.findIndex(c => c.id === contactId)
      if (idx >= 0) contacts.value[idx] = data
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch contact'
    } finally {
      loading.value = false
    }
  }

  async function fetchRelationshipGaps() {
    loading.value = true
    error.value = null
    try {
      const data = await contactsApi.getRelationshipGaps()
      // Update contacts with gap data
      data.forEach((gap: Contact) => {
        const idx = contacts.value.findIndex(c => c.id === gap.id)
        if (idx >= 0) {
          contacts.value[idx] = { ...contacts.value[idx], ...gap }
        }
      })
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch relationship gaps'
    } finally {
      loading.value = false
    }
  }

  async function updateContact(contactId: string, updates: Partial<Contact>) {
    loading.value = true
    error.value = null
    try {
      const updated = await contactsApi.updateContact(contactId, updates)
      const idx = contacts.value.findIndex(c => c.id === contactId)
      if (idx >= 0) contacts.value[idx] = updated
      if (currentContact.value?.id === contactId) currentContact.value = updated
      return updated
    } catch (err: any) {
      error.value = err.message || 'Failed to update contact'
      return null
    } finally {
      loading.value = false
    }
  }

  function setSearchQuery(query: string) {
    searchQuery.value = query
  }

  function selectContact(contact: Contact | null) {
    currentContact.value = contact
  }

  return {
    contacts,
    currentContact,
    loading,
    error,
    searchQuery,
    filteredContacts,
    contactsWithGaps,
    sortedByLastContact,
    contactsByCompany,
    fetchContacts,
    fetchContact,
    fetchRelationshipGaps,
    updateContact,
    setSearchQuery,
    selectContact
  }
})
