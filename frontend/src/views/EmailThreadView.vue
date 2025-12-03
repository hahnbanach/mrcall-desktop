<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useEmailStore } from '@/stores/email'

const route = useRoute()
const router = useRouter()
const emailStore = useEmailStore()

const replyMode = ref(false)
const replyBody = ref('')

const threadId = computed(() => route.params.id as string)

onMounted(async () => {
  await emailStore.fetchThread(threadId.value)
  await emailStore.markAsRead(threadId.value)
})

function formatDate(date: string) {
  return new Date(date).toLocaleString([], {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

async function handleReply() {
  if (!replyBody.value.trim() || !emailStore.currentThread) return

  const lastMessage = emailStore.currentThread.messages[emailStore.currentThread.messages.length - 1]
  const success = await emailStore.sendEmail(
    lastMessage.from,
    `Re: ${emailStore.currentThread.subject}`,
    replyBody.value,
    threadId.value
  )

  if (success) {
    replyBody.value = ''
    replyMode.value = false
  }
}

async function handleArchive() {
  await emailStore.archiveThread(threadId.value)
  router.push('/emails')
}

function goBack() {
  router.push('/emails')
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex-shrink-0 p-4 border-b border-gray-200">
      <div class="flex items-center gap-4">
        <button
          @click="goBack"
          class="p-2 hover:bg-gray-100 rounded-lg transition-colors"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
          </svg>
        </button>
        <div class="flex-1 min-w-0">
          <h1 class="text-lg font-semibold text-gray-900 truncate">
            {{ emailStore.currentThread?.subject || 'Loading...' }}
          </h1>
          <p class="text-sm text-gray-500">
            {{ emailStore.currentThread?.messages?.length || 0 }} messages
          </p>
        </div>
        <div class="flex items-center gap-2">
          <button
            @click="replyMode = true"
            class="px-4 py-2 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors"
          >
            Reply
          </button>
          <button
            @click="handleArchive"
            class="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
            title="Archive"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4"/>
            </svg>
          </button>
        </div>
      </div>
    </div>

    <!-- Messages -->
    <div class="flex-1 overflow-y-auto p-4">
      <div v-if="emailStore.loading" class="flex items-center justify-center h-32">
        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-accent"></div>
      </div>

      <div v-else-if="!emailStore.currentThread" class="text-center py-12">
        <p class="text-gray-500">Thread not found</p>
      </div>

      <div v-else class="max-w-3xl mx-auto space-y-4">
        <div
          v-for="message in emailStore.currentThread.messages"
          :key="message.id"
          class="bg-white border border-gray-200 rounded-xl overflow-hidden"
        >
          <!-- Message Header -->
          <div class="p-4 bg-gray-50 border-b border-gray-100">
            <div class="flex items-start justify-between">
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-full bg-accent/10 flex items-center justify-center">
                  <span class="text-accent font-medium">
                    {{ message.from.charAt(0).toUpperCase() }}
                  </span>
                </div>
                <div>
                  <p class="font-medium text-gray-900">{{ message.from }}</p>
                  <p class="text-sm text-gray-500">To: {{ message.to }}</p>
                </div>
              </div>
              <span class="text-sm text-gray-500">
                {{ formatDate(message.date) }}
              </span>
            </div>
          </div>

          <!-- Message Body -->
          <div class="p-4">
            <div class="prose prose-sm max-w-none text-gray-700 whitespace-pre-wrap">
              {{ message.body }}
            </div>
          </div>

          <!-- Attachments -->
          <div v-if="message.attachments?.length" class="px-4 pb-4">
            <div class="flex flex-wrap gap-2">
              <div
                v-for="attachment in message.attachments"
                :key="attachment.id"
                class="flex items-center gap-2 px-3 py-2 bg-gray-100 rounded-lg text-sm"
              >
                <svg class="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"/>
                </svg>
                <span class="text-gray-700">{{ attachment.filename }}</span>
                <span class="text-gray-400 text-xs">({{ attachment.size }})</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Reply Box -->
        <div v-if="replyMode" class="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div class="p-4 bg-gray-50 border-b border-gray-100">
            <p class="font-medium text-gray-900">Reply</p>
          </div>
          <div class="p-4">
            <textarea
              v-model="replyBody"
              rows="6"
              placeholder="Write your reply..."
              class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50 resize-none"
              autofocus
            />
          </div>
          <div class="px-4 pb-4 flex justify-end gap-3">
            <button
              @click="replyMode = false"
              class="px-4 py-2 text-gray-600 hover:text-gray-900 transition-colors"
            >
              Cancel
            </button>
            <button
              @click="handleReply"
              :disabled="!replyBody.trim() || emailStore.loading"
              class="px-6 py-2 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors disabled:opacity-50"
            >
              Send
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
