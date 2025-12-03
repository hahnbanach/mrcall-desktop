<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useEmailStore } from '@/stores/email'

const router = useRouter()
const emailStore = useEmailStore()
const showComposeModal = ref(false)
const composeForm = ref({ to: '', subject: '', body: '' })

onMounted(() => {
  emailStore.fetchThreads()
})

function openThread(threadId: string) {
  router.push(`/emails/${threadId}`)
}

function formatDate(date: string) {
  const d = new Date(date)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))

  if (days === 0) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } else if (days === 1) {
    return 'Yesterday'
  } else if (days < 7) {
    return d.toLocaleDateString([], { weekday: 'short' })
  } else {
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
  }
}

async function handleSendEmail() {
  const success = await emailStore.sendEmail(
    composeForm.value.to,
    composeForm.value.subject,
    composeForm.value.body
  )
  if (success) {
    showComposeModal.value = false
    composeForm.value = { to: '', subject: '', body: '' }
  }
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex-shrink-0 p-4 border-b border-gray-200">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-semibold text-gray-900">Emails</h1>
          <p class="text-sm text-gray-500">{{ emailStore.unreadCount }} unread</p>
        </div>
        <button
          @click="showComposeModal = true"
          class="px-4 py-2 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors"
        >
          Compose
        </button>
      </div>

      <!-- Search -->
      <div class="mt-4">
        <input
          type="text"
          :value="emailStore.searchQuery"
          @input="emailStore.setSearchQuery(($event.target as HTMLInputElement).value)"
          placeholder="Search emails..."
          class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
        />
      </div>
    </div>

    <!-- Email List -->
    <div class="flex-1 overflow-y-auto">
      <div v-if="emailStore.loading" class="flex items-center justify-center h-32">
        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-accent"></div>
      </div>

      <div v-else-if="emailStore.filteredThreads.length === 0" class="p-8 text-center">
        <p class="text-gray-500">No emails found</p>
      </div>

      <div v-else class="divide-y divide-gray-100">
        <div
          v-for="thread in emailStore.filteredThreads"
          :key="thread.id"
          @click="openThread(thread.id)"
          class="p-4 hover:bg-gray-50 cursor-pointer transition-colors"
          :class="{ 'bg-blue-50/50': thread.unread }"
        >
          <div class="flex items-start gap-3">
            <div class="flex-shrink-0">
              <div
                class="w-10 h-10 rounded-full bg-gray-200 flex items-center justify-center"
                :class="{ 'bg-accent/10': thread.unread }"
              >
                <span class="text-sm font-medium" :class="thread.unread ? 'text-accent' : 'text-gray-600'">
                  {{ thread.participants[0]?.charAt(0).toUpperCase() || '?' }}
                </span>
              </div>
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center justify-between">
                <p
                  class="text-sm truncate"
                  :class="thread.unread ? 'font-semibold text-gray-900' : 'text-gray-700'"
                >
                  {{ thread.participants.join(', ') }}
                </p>
                <span class="text-xs text-gray-500 flex-shrink-0 ml-2">
                  {{ formatDate(thread.lastMessageAt) }}
                </span>
              </div>
              <p
                class="text-sm truncate"
                :class="thread.unread ? 'font-medium text-gray-900' : 'text-gray-700'"
              >
                {{ thread.subject }}
              </p>
              <p class="text-sm text-gray-500 truncate">{{ thread.snippet }}</p>
            </div>
            <div v-if="thread.unread" class="flex-shrink-0">
              <div class="w-2 h-2 rounded-full bg-accent"></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Compose Modal -->
    <Teleport to="body">
      <div v-if="showComposeModal" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/50" @click="showComposeModal = false"></div>
        <div class="relative bg-white rounded-xl shadow-xl w-full max-w-2xl mx-4 max-h-[90vh] overflow-hidden">
          <div class="p-4 border-b border-gray-200 flex items-center justify-between">
            <h2 class="text-lg font-semibold">New Message</h2>
            <button @click="showComposeModal = false" class="text-gray-400 hover:text-gray-600">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </div>
          <div class="p-4 space-y-4">
            <input
              v-model="composeForm.to"
              type="email"
              placeholder="To"
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
            />
            <input
              v-model="composeForm.subject"
              type="text"
              placeholder="Subject"
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
            />
            <textarea
              v-model="composeForm.body"
              rows="10"
              placeholder="Write your message..."
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50 resize-none"
            />
          </div>
          <div class="p-4 border-t border-gray-200 flex justify-end gap-3">
            <button
              @click="showComposeModal = false"
              class="px-4 py-2 text-gray-600 hover:text-gray-900 transition-colors"
            >
              Cancel
            </button>
            <button
              @click="handleSendEmail"
              :disabled="!composeForm.to || !composeForm.subject || emailStore.loading"
              class="px-6 py-2 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors disabled:opacity-50"
            >
              Send
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
