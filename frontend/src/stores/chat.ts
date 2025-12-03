import { defineStore } from 'pinia'
import { ref } from 'vue'
import { chatService } from '@/services/api'
import type { ChatMessage } from '@/types'

export const useChatStore = defineStore('chat', () => {
  // State
  const messages = ref<ChatMessage[]>([])
  const isStreaming = ref(false)
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const sessionId = ref<string | null>(null)

  // Actions
  async function sendMessage(content: string): Promise<void> {
    if (!content.trim()) return

    // Add user message immediately
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      timestamp: new Date().toISOString()
    }
    messages.value.push(userMessage)

    isLoading.value = true
    error.value = null

    try {
      const response = await chatService.sendMessage(content, sessionId.value)

      const assistantMessage: ChatMessage = {
        id: response.id || crypto.randomUUID(),
        role: 'assistant',
        content: response.content,
        timestamp: new Date().toISOString(),
        toolCalls: response.toolCalls
      }
      messages.value.push(assistantMessage)

      if (response.sessionId) {
        sessionId.value = response.sessionId
      }
    } catch (err: any) {
      error.value = err.message || 'Failed to send message'
      // Remove the user message on error
      messages.value.pop()
      throw err
    } finally {
      isLoading.value = false
    }
  }

  async function streamMessage(content: string, onChunk: (chunk: string) => void): Promise<void> {
    if (!content.trim()) return

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      timestamp: new Date().toISOString()
    }
    messages.value.push(userMessage)

    // Add placeholder for assistant message
    const assistantMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString()
    }
    messages.value.push(assistantMessage)

    isStreaming.value = true
    error.value = null

    try {
      await chatService.streamMessage(content, sessionId.value, (chunk) => {
        // Update the last message with new content
        const lastIdx = messages.value.length - 1
        messages.value[lastIdx].content += chunk
        onChunk(chunk)
      })
    } catch (err: any) {
      error.value = err.message || 'Failed to stream message'
      // Remove messages on error
      messages.value.pop()
      messages.value.pop()
      throw err
    } finally {
      isStreaming.value = false
    }
  }

  function clearMessages(): void {
    messages.value = []
    sessionId.value = null
  }

  function clearError(): void {
    error.value = null
  }

  return {
    // State
    messages,
    isStreaming,
    isLoading,
    error,
    sessionId,
    // Actions
    sendMessage,
    streamMessage,
    clearMessages,
    clearError
  }
})
