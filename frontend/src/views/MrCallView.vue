<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useMrCallStore } from '@/stores/mrcall'

const mrcallStore = useMrCallStore()
const showSetupModal = ref(false)
const setupForm = ref({
  phoneNumber: '',
  voiceType: 'professional',
  greeting: ''
})

onMounted(() => {
  mrcallStore.fetchStatus()
  mrcallStore.fetchCallHistory()
})

function formatDate(date: string) {
  return new Date(date).toLocaleString()
}

function formatDuration(seconds: number) {
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

async function handleSetup() {
  await mrcallStore.configure(setupForm.value)
  showSetupModal.value = false
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex-shrink-0 p-4 border-b border-gray-200">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-semibold text-gray-900">MrCall Integration</h1>
          <p class="text-sm text-gray-500">AI-powered phone assistant</p>
        </div>
        <button
          @click="showSetupModal = true"
          class="px-4 py-2 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors"
        >
          Configure
        </button>
      </div>
    </div>

    <!-- Content -->
    <div class="flex-1 overflow-y-auto p-4">
      <div v-if="mrcallStore.loading" class="flex items-center justify-center h-32">
        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-accent"></div>
      </div>

      <div v-else class="max-w-2xl mx-auto space-y-6">
        <!-- Status Card -->
        <div class="bg-white border border-gray-200 rounded-xl p-6">
          <div class="flex items-center justify-between mb-4">
            <h2 class="font-semibold text-gray-900">Assistant Status</h2>
            <span
              :class="[
                'px-3 py-1 rounded-full text-sm',
                mrcallStore.assistant?.enabled ? 'bg-green-50 text-green-600' : 'bg-gray-100 text-gray-500'
              ]"
            >
              {{ mrcallStore.assistant?.enabled ? 'Active' : 'Inactive' }}
            </span>
          </div>

          <div v-if="mrcallStore.assistant" class="space-y-3">
            <div class="flex items-center gap-3 p-3 bg-gray-50 rounded-lg">
              <div class="w-10 h-10 bg-accent/10 rounded-full flex items-center justify-center">
                <svg class="w-5 h-5 text-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"/>
                </svg>
              </div>
              <div>
                <p class="text-sm text-gray-500">Phone Number</p>
                <p class="font-medium text-gray-900">{{ mrcallStore.assistant.phoneNumber || 'Not configured' }}</p>
              </div>
            </div>

            <div class="grid grid-cols-2 gap-3">
              <div class="p-3 bg-gray-50 rounded-lg">
                <p class="text-sm text-gray-500">Voice Type</p>
                <p class="font-medium text-gray-900 capitalize">{{ mrcallStore.assistant.voiceType || 'Default' }}</p>
              </div>
              <div class="p-3 bg-gray-50 rounded-lg">
                <p class="text-sm text-gray-500">Total Calls</p>
                <p class="font-medium text-gray-900">{{ mrcallStore.assistant.totalCalls || 0 }}</p>
              </div>
            </div>
          </div>

          <div v-else class="text-center py-8">
            <div class="w-16 h-16 mx-auto mb-4 bg-gray-100 rounded-full flex items-center justify-center">
              <svg class="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"/>
              </svg>
            </div>
            <p class="text-gray-500">MrCall not configured</p>
            <p class="text-sm text-gray-400 mt-1">Set up your AI phone assistant</p>
            <button
              @click="showSetupModal = true"
              class="mt-4 px-4 py-2 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors"
            >
              Get Started
            </button>
          </div>
        </div>

        <!-- Call History -->
        <div class="bg-white border border-gray-200 rounded-xl p-6">
          <h2 class="font-semibold text-gray-900 mb-4">Recent Calls</h2>

          <div v-if="mrcallStore.callHistory.length === 0" class="text-center py-8 text-gray-500">
            No call history yet
          </div>

          <div v-else class="space-y-3">
            <div
              v-for="call in mrcallStore.callHistory"
              :key="call.id"
              class="flex items-center gap-4 p-3 bg-gray-50 rounded-lg"
            >
              <div
                :class="[
                  'w-10 h-10 rounded-full flex items-center justify-center',
                  call.direction === 'incoming' ? 'bg-blue-100' : 'bg-green-100'
                ]"
              >
                <svg
                  :class="[
                    'w-5 h-5',
                    call.direction === 'incoming' ? 'text-blue-600' : 'text-green-600'
                  ]"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    v-if="call.direction === 'incoming'"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"
                  />
                  <path
                    v-else
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"
                  />
                </svg>
              </div>
              <div class="flex-1 min-w-0">
                <p class="font-medium text-gray-900">{{ call.callerNumber || 'Unknown' }}</p>
                <p class="text-sm text-gray-500">{{ formatDate(call.timestamp) }}</p>
              </div>
              <div class="text-right">
                <p class="text-sm text-gray-900">{{ formatDuration(call.duration || 0) }}</p>
                <p class="text-xs text-gray-500 capitalize">{{ call.status }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Setup Modal -->
    <Teleport to="body">
      <div v-if="showSetupModal" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/50" @click="showSetupModal = false"></div>
        <div class="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4">
          <div class="p-4 border-b border-gray-200">
            <h2 class="text-lg font-semibold">Configure MrCall</h2>
          </div>
          <div class="p-4 space-y-4">
            <div>
              <label class="block text-sm text-gray-600 mb-1">Phone Number</label>
              <input
                v-model="setupForm.phoneNumber"
                type="tel"
                placeholder="+1 (555) 123-4567"
                class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
              />
            </div>
            <div>
              <label class="block text-sm text-gray-600 mb-1">Voice Type</label>
              <select
                v-model="setupForm.voiceType"
                class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
              >
                <option value="professional">Professional</option>
                <option value="friendly">Friendly</option>
                <option value="formal">Formal</option>
              </select>
            </div>
            <div>
              <label class="block text-sm text-gray-600 mb-1">Custom Greeting (optional)</label>
              <textarea
                v-model="setupForm.greeting"
                rows="2"
                placeholder="Hello, you've reached..."
                class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50 resize-none"
              />
            </div>
          </div>
          <div class="p-4 border-t border-gray-200 flex justify-end gap-3">
            <button
              @click="showSetupModal = false"
              class="px-4 py-2 text-gray-600 hover:text-gray-900 transition-colors"
            >
              Cancel
            </button>
            <button
              @click="handleSetup"
              :disabled="!setupForm.phoneNumber || mrcallStore.loading"
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
