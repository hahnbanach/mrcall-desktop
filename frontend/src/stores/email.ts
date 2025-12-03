import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { EmailThread, Draft } from '@/types'
import { emailApi } from '@/services/api/email'

export const useEmailStore = defineStore('email', () => {
  const threads = ref<EmailThread[]>([])
  const currentThread = ref<EmailThread | null>(null)
  const drafts = ref<Draft[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const searchQuery = ref('')

  const unreadCount = computed(() =>
    threads.value.filter(t => t.unread).length
  )

  const filteredThreads = computed(() => {
    if (!searchQuery.value) return threads.value
    const query = searchQuery.value.toLowerCase()
    return threads.value.filter(t =>
      t.subject.toLowerCase().includes(query) ||
      t.participants.some(p => p.toLowerCase().includes(query)) ||
      t.snippet.toLowerCase().includes(query)
    )
  })

  async function fetchThreads(maxResults = 50) {
    loading.value = true
    error.value = null
    try {
      const data = await emailApi.getThreads(maxResults)
      threads.value = data
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch email threads'
    } finally {
      loading.value = false
    }
  }

  async function fetchThread(threadId: string) {
    loading.value = true
    error.value = null
    try {
      const data = await emailApi.getThread(threadId)
      currentThread.value = data
      // Update in list
      const idx = threads.value.findIndex(t => t.id === threadId)
      if (idx >= 0) threads.value[idx] = data
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch email thread'
    } finally {
      loading.value = false
    }
  }

  async function sendEmail(to: string, subject: string, body: string, threadId?: string) {
    loading.value = true
    error.value = null
    try {
      await emailApi.send({ to, subject, body, threadId })
      if (threadId) await fetchThread(threadId)
      return true
    } catch (err: any) {
      error.value = err.message || 'Failed to send email'
      return false
    } finally {
      loading.value = false
    }
  }

  async function fetchDrafts() {
    loading.value = true
    error.value = null
    try {
      const data = await emailApi.getDrafts()
      drafts.value = data
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch drafts'
    } finally {
      loading.value = false
    }
  }

  async function saveDraft(draft: Partial<Draft>) {
    loading.value = true
    error.value = null
    try {
      const saved = await emailApi.saveDraft(draft)
      const idx = drafts.value.findIndex(d => d.id === saved.id)
      if (idx >= 0) {
        drafts.value[idx] = saved
      } else {
        drafts.value.push(saved)
      }
      return saved
    } catch (err: any) {
      error.value = err.message || 'Failed to save draft'
      return null
    } finally {
      loading.value = false
    }
  }

  async function deleteDraft(draftId: string) {
    loading.value = true
    error.value = null
    try {
      await emailApi.deleteDraft(draftId)
      drafts.value = drafts.value.filter(d => d.id !== draftId)
      return true
    } catch (err: any) {
      error.value = err.message || 'Failed to delete draft'
      return false
    } finally {
      loading.value = false
    }
  }

  async function markAsRead(threadId: string) {
    try {
      await emailApi.markAsRead(threadId)
      const thread = threads.value.find(t => t.id === threadId)
      if (thread) thread.unread = false
    } catch (err: any) {
      error.value = err.message || 'Failed to mark as read'
    }
  }

  async function archiveThread(threadId: string) {
    try {
      await emailApi.archive(threadId)
      threads.value = threads.value.filter(t => t.id !== threadId)
      if (currentThread.value?.id === threadId) {
        currentThread.value = null
      }
    } catch (err: any) {
      error.value = err.message || 'Failed to archive thread'
    }
  }

  function setSearchQuery(query: string) {
    searchQuery.value = query
  }

  return {
    threads,
    currentThread,
    drafts,
    loading,
    error,
    searchQuery,
    unreadCount,
    filteredThreads,
    fetchThreads,
    fetchThread,
    sendEmail,
    fetchDrafts,
    saveDraft,
    deleteDraft,
    markAsRead,
    archiveThread,
    setSearchQuery
  }
})
