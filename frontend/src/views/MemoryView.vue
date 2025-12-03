<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useMemoryStore } from '@/stores/memory'
import type { Memory } from '@/types'

const memoryStore = useMemoryStore()
const showCreateModal = ref(false)
const showEditModal = ref(false)
const selectedMemory = ref<Memory | null>(null)
const newMemory = ref({
  key: '',
  value: '',
  category: 'preference'
})

onMounted(() => {
  memoryStore.fetchMemories()
})

const categories = ['preference', 'fact', 'behavior', 'relationship', 'context']

const groupedMemories = computed(() => {
  const grouped: Record<string, Memory[]> = {}
  memoryStore.memories.forEach(m => {
    const cat = m.category || 'other'
    if (!grouped[cat]) grouped[cat] = []
    grouped[cat].push(m)
  })
  return grouped
})

async function createMemory() {
  const memory = await memoryStore.addMemory(newMemory.value)
  if (memory) {
    showCreateModal.value = false
    newMemory.value = { key: '', value: '', category: 'preference' }
  }
}

function editMemory(memory: Memory) {
  selectedMemory.value = { ...memory }
  showEditModal.value = true
}

async function updateMemory() {
  if (!selectedMemory.value) return
  await memoryStore.updateMemory(selectedMemory.value.id, {
    value: selectedMemory.value.value,
    category: selectedMemory.value.category
  })
  showEditModal.value = false
  selectedMemory.value = null
}

async function deleteMemory(id: string) {
  if (confirm('Are you sure you want to delete this memory?')) {
    await memoryStore.deleteMemory(id)
  }
}

function formatDate(date: string) {
  return new Date(date).toLocaleDateString([], {
    month: 'short',
    day: 'numeric',
    year: 'numeric'
  })
}

const categoryIcons: Record<string, string> = {
  preference: '⚙️',
  fact: '📌',
  behavior: '🎯',
  relationship: '👥',
  context: '📝'
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex-shrink-0 p-4 border-b border-gray-200">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-semibold text-gray-900">Memory</h1>
          <p class="text-sm text-gray-500">{{ memoryStore.memories.length }} memories stored</p>
        </div>
        <button
          @click="showCreateModal = true"
          class="px-4 py-2 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors"
        >
          Add Memory
        </button>
      </div>

      <!-- Search -->
      <div class="mt-4">
        <input
          type="text"
          :value="memoryStore.searchQuery"
          @input="memoryStore.setSearchQuery(($event.target as HTMLInputElement).value)"
          placeholder="Search memories..."
          class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
        />
      </div>
    </div>

    <!-- Memory List -->
    <div class="flex-1 overflow-y-auto p-4">
      <div v-if="memoryStore.loading" class="flex items-center justify-center h-32">
        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-accent"></div>
      </div>

      <div v-else-if="memoryStore.filteredMemories.length === 0" class="text-center py-12">
        <div class="w-16 h-16 mx-auto mb-4 bg-gray-100 rounded-full flex items-center justify-center">
          <svg class="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
          </svg>
        </div>
        <p class="text-gray-500">No memories found</p>
        <p class="text-sm text-gray-400 mt-1">Add memories to help Zylch remember important information</p>
      </div>

      <div v-else class="space-y-6">
        <div v-for="(memories, category) in groupedMemories" :key="category">
          <h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3 flex items-center gap-2">
            <span>{{ categoryIcons[category] || '📄' }}</span>
            {{ category }}
          </h2>
          <div class="space-y-2">
            <div
              v-for="memory in memories"
              :key="memory.id"
              class="bg-white border border-gray-200 rounded-xl p-4 hover:shadow-md transition-shadow"
            >
              <div class="flex items-start justify-between">
                <div class="flex-1 min-w-0">
                  <h3 class="font-medium text-gray-900">{{ memory.key }}</h3>
                  <p class="text-gray-600 mt-1">{{ memory.value }}</p>
                  <p class="text-xs text-gray-400 mt-2">
                    Updated {{ formatDate(memory.updatedAt || memory.createdAt) }}
                  </p>
                </div>
                <div class="flex items-center gap-2 ml-4">
                  <button
                    @click="editMemory(memory)"
                    class="p-2 text-gray-400 hover:text-accent transition-colors"
                  >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
                    </svg>
                  </button>
                  <button
                    @click="deleteMemory(memory.id)"
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
      </div>
    </div>

    <!-- Create Modal -->
    <Teleport to="body">
      <div v-if="showCreateModal" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/50" @click="showCreateModal = false"></div>
        <div class="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4">
          <div class="p-4 border-b border-gray-200">
            <h2 class="text-lg font-semibold">Add Memory</h2>
          </div>
          <div class="p-4 space-y-4">
            <input
              v-model="newMemory.key"
              type="text"
              placeholder="Memory key (e.g., 'Favorite color')"
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
            />
            <textarea
              v-model="newMemory.value"
              rows="3"
              placeholder="Memory value (e.g., 'Blue')"
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50 resize-none"
            />
            <select
              v-model="newMemory.category"
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
            >
              <option v-for="cat in categories" :key="cat" :value="cat">
                {{ categoryIcons[cat] }} {{ cat.charAt(0).toUpperCase() + cat.slice(1) }}
              </option>
            </select>
          </div>
          <div class="p-4 border-t border-gray-200 flex justify-end gap-3">
            <button
              @click="showCreateModal = false"
              class="px-4 py-2 text-gray-600 hover:text-gray-900 transition-colors"
            >
              Cancel
            </button>
            <button
              @click="createMemory"
              :disabled="!newMemory.key || !newMemory.value || memoryStore.loading"
              class="px-6 py-2 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors disabled:opacity-50"
            >
              Add
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Edit Modal -->
    <Teleport to="body">
      <div v-if="showEditModal && selectedMemory" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/50" @click="showEditModal = false"></div>
        <div class="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4">
          <div class="p-4 border-b border-gray-200">
            <h2 class="text-lg font-semibold">Edit Memory</h2>
          </div>
          <div class="p-4 space-y-4">
            <div>
              <label class="block text-sm text-gray-600 mb-1">Key</label>
              <input
                :value="selectedMemory.key"
                type="text"
                disabled
                class="w-full px-4 py-2 border border-gray-200 rounded-lg bg-gray-50 text-gray-500"
              />
            </div>
            <textarea
              v-model="selectedMemory.value"
              rows="3"
              placeholder="Memory value"
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50 resize-none"
            />
            <select
              v-model="selectedMemory.category"
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
            >
              <option v-for="cat in categories" :key="cat" :value="cat">
                {{ categoryIcons[cat] }} {{ cat.charAt(0).toUpperCase() + cat.slice(1) }}
              </option>
            </select>
          </div>
          <div class="p-4 border-t border-gray-200 flex justify-end gap-3">
            <button
              @click="showEditModal = false"
              class="px-4 py-2 text-gray-600 hover:text-gray-900 transition-colors"
            >
              Cancel
            </button>
            <button
              @click="updateMemory"
              :disabled="!selectedMemory.value || memoryStore.loading"
              class="px-6 py-2 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors disabled:opacity-50"
            >
              Save
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
