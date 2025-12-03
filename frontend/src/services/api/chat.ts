import api from './index'
import type { ChatMessage, ToolCall } from '@/types'

interface ChatResponse {
  id: string
  content: string
  sessionId?: string
  toolCalls?: ToolCall[]
}

export const chatService = {
  async sendMessage(message: string, sessionId?: string | null): Promise<ChatResponse> {
    const { data } = await api.post('/api/chat', {
      message,
      session_id: sessionId
    })
    return data
  },

  async streamMessage(
    message: string,
    sessionId: string | null,
    onChunk: (chunk: string) => void
  ): Promise<void> {
    const response = await fetch(`${import.meta.env.VITE_API_URL || 'http://localhost:9000'}/api/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${localStorage.getItem('token')}`
      },
      body: JSON.stringify({
        message,
        session_id: sessionId
      })
    })

    if (!response.ok) {
      throw new Error('Failed to stream message')
    }

    const reader = response.body?.getReader()
    if (!reader) throw new Error('No reader available')

    const decoder = new TextDecoder()
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      const chunk = decoder.decode(value)
      onChunk(chunk)
    }
  },

  async getHistory(sessionId: string): Promise<ChatMessage[]> {
    const { data } = await api.get(`/api/chat/history/${sessionId}`)
    return data
  },

  async clearHistory(sessionId: string): Promise<void> {
    await api.delete(`/api/chat/history/${sessionId}`)
  }
}
