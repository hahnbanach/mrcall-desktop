<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useEmailStore } from '@/stores/email'
import type { Draft } from '@/types'

const emailStore = useEmailStore()
const showEditModal = ref(false)
const editingDraft = ref<Draft | null>(null)

onMounted(() => {
  emailStore.fetchDrafts()
})

function formatDate(date: string) {
  return new Date(date).toLocaleDateString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function editDraft(draft: Draft) {
  editingDraft.value = { ...draft }
  showEditModal.value = true
}

async function saveDraft() {
  if (!editingDraft.value) return
  await emailStore.saveDraft(editingDraft.value)
  showEditModal.value = false
  editingDraft.value = null
}

async function sendDraft() {
  if (!editingDraft.value) return
  const success = await emailStore.sendEmail(
    editingDraft.value.to,
    editingDraft.value.subject,
    editingDraft.value.body,
    editingDraft.value.threadId
  )
  if (success) {
    await emailStore.deleteDraft(editingDraft.value.id)
    showEditModal.value = false
    editingDraft.value = null
  }
}

async function deleteDraft(id: string) {
  if (confirm('Are you sure you want to delete this draft?')) {
    await emailStore.deleteDraft(id)
  }
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex-shrink-0 p-4 border-b border-gray-200">
      <h1 class="text-xl font-semibold text-gray-900">Drafts</h1>
      <p class="text-sm text-gray-500">{{ emailStore.drafts.length }} drafts saved</p>
    </div>

    <!-- Drafts List -->
    <div class="flex-1 overflow-y-auto">
      <div v-if="emailStore.loading" class="flex items-center justify-center h-32">
        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-accent"></div>
      </div>

      <div v-else-if="emailStore.drafts.length === 0" class="text-center py-12">
        <div class="w-16 h-16 mx-auto mb-4 bg-gray-100 rounded-full flex items-center justify-center">
          <svg class="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
          </svg>
        </div>
        <p class="text-gray-500">No drafts</p>
        <p class="text-sm text-gray-400 mt-1">Drafts you save will appear here</p>
      </div>

      <div v-else class="divide-y divide-gray-100">
        <div
          v-for="draft in emailStore.drafts"
          :key="draft.id"
          @click="editDraft(draft)"
          class="p-4 hover:bg-gray-50 cursor-pointer transition-colors"
        >
          <div class="flex items-start gap-3">
            <div class="flex-shrink-0 mt-1">
              <div class="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center">
                <svg class="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                </svg>
              </div>
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center justify-between">
                <p class="text-sm text-gray-500 truncate">
                  To: {{ draft.to || '(no recipient)' }}
                </p>
                <span class="text-xs text-gray-400 flex-shrink-0 ml-2">
                  {{ formatDate(draft.updatedAt) }}
                </span>
              </div>
              <p class="font-medium text-gray-900 truncate">
                {{ draft.subject || '(no subject)' }}
              </p>
              <p class="text-sm text-gray-500 truncate">
                {{ draft.body || '(no content)' }}
              </p>
            </div>
            <button
              @click.stop="deleteDraft(draft.id)"
              class="flex-shrink-0 p-2 text-gray-400 hover:text-red-600 transition-colors"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Edit Modal -->
    <Teleport to="body">
      <div v-if="showEditModal && editingDraft" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/50" @click="showEditModal = false"></div>
        <div class="relative bg-white rounded-xl shadow-xl w-full max-w-2xl mx-4 max-h-[90vh] overflow-hidden">
          <div class="p-4 border-b border-gray-200 flex items-center justify-between">
            <h2 class="text-lg font-semibold">Edit Draft</h2>
            <button @click="showEditModal = false" class="text-gray-400 hover:text-gray-600">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </div>
          <div class="p-4 space-y-4 overflow-y-auto max-h-[60vh]">
            <input
              v-model="editingDraft.to"
              type="email"
              placeholder="To"
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
            />
            <input
              v-model="editingDraft.subject"
              type="text"
              placeholder="Subject"
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
            />
            <textarea
              v-model="editingDraft.body"
              rows="12"
              placeholder="Write your message..."
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50 resize-none"
            />
          </div>
          <div class="p-4 border-t border-gray-200 flex justify-between">
            <button
              @click="showEditModal = false"
              class="px-4 py-2 text-gray-600 hover:text-gray-900 transition-colors"
            >
              Cancel
            </button>
            <div class="flex gap-3">
              <button
                @click="saveDraft"
                :disabled="emailStore.loading"
                class="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
              >
                Save Draft
              </button>
              <button
                @click="sendDraft"
                :disabled="!editingDraft.to || !editingDraft.subject || emailStore.loading"
                class="px-6 py-2 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors disabled:opacity-50"
              >
                Send
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
