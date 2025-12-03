<script setup lang="ts">
import { ref, onMounted, nextTick, watch } from 'vue'
import { useChatStore } from '@/stores/chat'

const chatStore = useChatStore()
const inputMessage = ref('')
const messagesContainer = ref<HTMLElement | null>(null)

onMounted(() => {
  // Chat history loads from the store's messages
})

watch(() => chatStore.messages.length, () => {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
})

async function handleSubmit() {
  const message = inputMessage.value.trim()
  if (!message || chatStore.isLoading) return

  inputMessage.value = ''
  await chatStore.sendMessage(message)
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSubmit()
  }
}

function formatTime(timestamp: string) {
  return new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Chat Header -->
    <div class="flex-shrink-0 p-4 border-b border-gray-200">
      <h1 class="text-xl font-semibold text-gray-900">Chat with Zylch</h1>
      <p class="text-sm text-gray-500">Your AI-powered personal assistant</p>
    </div>

    <!-- Messages Container -->
    <div
      ref="messagesContainer"
      class="flex-1 overflow-y-auto p-4 space-y-4"
    >
      <div v-if="chatStore.messages.length === 0" class="flex items-center justify-center h-full">
        <div class="text-center">
          <div class="w-16 h-16 mx-auto mb-4 bg-accent/10 rounded-full flex items-center justify-center">
            <svg class="w-8 h-8 text-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/>
            </svg>
          </div>
          <h3 class="text-lg font-medium text-gray-900 mb-2">Start a conversation</h3>
          <p class="text-gray-500 max-w-sm">
            Ask me to help with emails, schedule meetings, manage tasks, or anything else!
          </p>
        </div>
      </div>

      <div
        v-for="message in chatStore.messages"
        :key="message.id"
        :class="[
          'flex',
          message.role === 'user' ? 'justify-end' : 'justify-start'
        ]"
      >
        <div
          :class="[
            'max-w-[75%] rounded-2xl px-4 py-3',
            message.role === 'user'
              ? 'bg-accent text-white'
              : 'bg-gray-100 text-gray-900'
          ]"
        >
          <p class="whitespace-pre-wrap">{{ message.content }}</p>
          <p
            :class="[
              'text-xs mt-1',
              message.role === 'user' ? 'text-white/70' : 'text-gray-400'
            ]"
          >
            {{ formatTime(message.timestamp) }}
          </p>
        </div>
      </div>

      <!-- Streaming indicator -->
      <div v-if="chatStore.isStreaming" class="flex justify-start">
        <div class="bg-gray-100 rounded-2xl px-4 py-3">
          <div class="flex space-x-2">
            <div class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 0ms"></div>
            <div class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 150ms"></div>
            <div class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 300ms"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Input Area -->
    <div class="flex-shrink-0 p-4 border-t border-gray-200">
      <form @submit.prevent="handleSubmit" class="flex items-end gap-3">
        <div class="flex-1">
          <textarea
            v-model="inputMessage"
            @keydown="handleKeydown"
            rows="1"
            class="w-full px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent resize-none"
            placeholder="Type your message..."
            :disabled="chatStore.isLoading"
          />
        </div>
        <button
          type="submit"
          :disabled="!inputMessage.trim() || chatStore.isLoading"
          class="px-6 py-3 bg-accent text-white rounded-xl hover:bg-accent/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
          </svg>
        </button>
      </form>
    </div>
  </div>
</template>
