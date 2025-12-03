<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import type { Trigger } from '@/types'

const settingsStore = useSettingsStore()
const showCreateModal = ref(false)
const newTrigger = ref({
  type: 'custom',
  condition: '',
  action: '',
  isActive: true
})

onMounted(() => {
  settingsStore.fetchTriggers()
})

async function createTrigger() {
  const trigger = await settingsStore.addTrigger(newTrigger.value)
  if (trigger) {
    showCreateModal.value = false
    newTrigger.value = { type: 'custom', condition: '', action: '', isActive: true }
  }
}

async function toggleTrigger(_trigger: Trigger) {
  // Toggle functionality would need to be added to the store
  // For now, this is a placeholder
}

async function deleteTrigger(id: string) {
  if (confirm('Are you sure you want to delete this trigger?')) {
    await settingsStore.removeTrigger(id)
  }
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex-shrink-0 p-4 border-b border-gray-200">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-semibold text-gray-900">Triggered Instructions</h1>
          <p class="text-sm text-gray-500">Automate actions based on conditions</p>
        </div>
        <button
          @click="showCreateModal = true"
          class="px-4 py-2 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors"
        >
          New Trigger
        </button>
      </div>
    </div>

    <!-- Triggers List -->
    <div class="flex-1 overflow-y-auto p-4">
      <div v-if="settingsStore.isLoading" class="flex items-center justify-center h-32">
        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-accent"></div>
      </div>

      <div v-else-if="settingsStore.triggers.length === 0" class="text-center py-12">
        <div class="w-16 h-16 mx-auto mb-4 bg-gray-100 rounded-full flex items-center justify-center">
          <svg class="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
          </svg>
        </div>
        <p class="text-gray-500">No triggers configured</p>
        <p class="text-sm text-gray-400 mt-1">Create triggers to automate your workflow</p>
      </div>

      <div v-else class="max-w-2xl mx-auto space-y-4">
        <div
          v-for="trigger in settingsStore.triggers"
          :key="trigger.id"
          class="bg-white border border-gray-200 rounded-xl p-4"
        >
          <div class="flex items-start justify-between">
            <div class="flex-1">
              <div class="flex items-center gap-3 mb-2">
                <h3 class="font-medium text-gray-900">{{ trigger.type }}</h3>
                <span
                  :class="[
                    'text-xs px-2 py-0.5 rounded-full',
                    trigger.isActive ? 'bg-green-50 text-green-600' : 'bg-gray-100 text-gray-500'
                  ]"
                >
                  {{ trigger.isActive ? 'Active' : 'Disabled' }}
                </span>
              </div>
              <div class="space-y-1 text-sm">
                <p class="text-gray-500">
                  <span class="font-medium text-gray-700">When:</span> {{ trigger.condition }}
                </p>
                <p class="text-gray-500">
                  <span class="font-medium text-gray-700">Then:</span> {{ trigger.action }}
                </p>
              </div>
            </div>
            <div class="flex items-center gap-2 ml-4">
              <button
                @click="toggleTrigger(trigger)"
                :class="[
                  'relative w-10 h-5 rounded-full transition-colors',
                  trigger.isActive ? 'bg-accent' : 'bg-gray-300'
                ]"
              >
                <span
                  :class="[
                    'absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform',
                    trigger.isActive ? 'left-5' : 'left-0.5'
                  ]"
                />
              </button>
              <button
                @click="deleteTrigger(trigger.id)"
                class="p-2 text-gray-400 hover:text-red-600 transition-colors"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Create Modal -->
    <Teleport to="body">
      <div v-if="showCreateModal" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/50" @click="showCreateModal = false"></div>
        <div class="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4">
          <div class="p-4 border-b border-gray-200">
            <h2 class="text-lg font-semibold">New Trigger</h2>
          </div>
          <div class="p-4 space-y-4">
            <input
              v-model="newTrigger.type"
              type="text"
              placeholder="Trigger type"
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
            />
            <div>
              <label class="block text-sm text-gray-600 mb-1">When (condition)</label>
              <input
                v-model="newTrigger.condition"
                type="text"
                placeholder="e.g., Email from VIP contact"
                class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
              />
            </div>
            <div>
              <label class="block text-sm text-gray-600 mb-1">Then (action)</label>
              <input
                v-model="newTrigger.action"
                type="text"
                placeholder="e.g., Mark as high priority"
                class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
              />
            </div>
          </div>
          <div class="p-4 border-t border-gray-200 flex justify-end gap-3">
            <button
              @click="showCreateModal = false"
              class="px-4 py-2 text-gray-600 hover:text-gray-900 transition-colors"
            >
              Cancel
            </button>
            <button
              @click="createTrigger"
              :disabled="!newTrigger.type || !newTrigger.condition || !newTrigger.action"
              class="px-6 py-2 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors disabled:opacity-50"
            >
              Create
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
