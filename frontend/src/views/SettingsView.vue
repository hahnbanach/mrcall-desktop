<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useAuthStore } from '@/stores/auth'
import api from '@/services/api'

const settingsStore = useSettingsStore()
const authStore = useAuthStore()

const activeTab = ref('assistant')

// Google OAuth state
const googleStatus = ref<{
  has_credentials: boolean
  email?: string
  valid?: boolean
  expired?: boolean
} | null>(null)
const googleLoading = ref(false)
const googleError = ref<string | null>(null)

// Anthropic API key state
const anthropicStatus = ref<{
  has_key: boolean
  key_preview?: string
} | null>(null)
const anthropicLoading = ref(false)
const anthropicError = ref<string | null>(null)
const anthropicSuccess = ref<string | null>(null)
const anthropicKeyInput = ref('')
const showAnthropicInput = ref(false)

const tabs = [
  { id: 'assistant', label: 'Assistant', icon: '🤖' },
  { id: 'privacy', label: 'Privacy', icon: '🔒' },
  { id: 'notifications', label: 'Notifications', icon: '🔔' },
  { id: 'integrations', label: 'Integrations', icon: '🔗' },
  { id: 'account', label: 'Account', icon: '👤' }
]

onMounted(() => {
  settingsStore.fetchAssistant()
  fetchGoogleStatus()
  fetchAnthropicStatus()
})

async function fetchGoogleStatus() {
  try {
    const response = await api.get('/api/auth/google/status')
    googleStatus.value = response.data
  } catch (error: any) {
    console.error('Failed to fetch Google status:', error)
    googleStatus.value = { has_credentials: false }
  }
}

async function connectGoogle() {
  googleLoading.value = true
  googleError.value = null
  try {
    const response = await api.get('/api/auth/google/authorize')
    const { auth_url } = response.data
    if (auth_url) {
      // Open Google OAuth in same window (will redirect back after auth)
      window.location.href = auth_url
    }
  } catch (error: any) {
    console.error('Failed to start Google OAuth:', error)
    googleError.value = error.response?.data?.detail || 'Failed to connect Google'
    googleLoading.value = false
  }
}

async function disconnectGoogle() {
  if (!confirm('Are you sure you want to disconnect Google? You will need to re-authorize to sync emails and calendar.')) {
    return
  }
  googleLoading.value = true
  googleError.value = null
  try {
    await api.post('/api/auth/google/revoke')
    googleStatus.value = { has_credentials: false }
  } catch (error: any) {
    console.error('Failed to disconnect Google:', error)
    googleError.value = error.response?.data?.detail || 'Failed to disconnect'
  } finally {
    googleLoading.value = false
  }
}

// Anthropic API key functions
async function fetchAnthropicStatus() {
  try {
    const response = await api.get('/api/auth/anthropic/status')
    anthropicStatus.value = response.data
  } catch (error: any) {
    console.error('Failed to fetch Anthropic status:', error)
    anthropicStatus.value = { has_key: false }
  }
}

async function saveAnthropicKey() {
  if (!anthropicKeyInput.value.trim()) {
    anthropicError.value = 'Please enter an API key'
    return
  }

  if (!anthropicKeyInput.value.startsWith('sk-ant-')) {
    anthropicError.value = 'Invalid API key format. Key should start with sk-ant-'
    return
  }

  anthropicLoading.value = true
  anthropicError.value = null
  anthropicSuccess.value = null

  try {
    await api.post('/api/auth/anthropic/key', { api_key: anthropicKeyInput.value })
    anthropicStatus.value = {
      has_key: true,
      key_preview: anthropicKeyInput.value.slice(0, 10) + '...' + anthropicKeyInput.value.slice(-4)
    }
    anthropicKeyInput.value = ''
    showAnthropicInput.value = false
    anthropicSuccess.value = 'API key saved successfully'
    setTimeout(() => { anthropicSuccess.value = null }, 3000)
  } catch (error: any) {
    console.error('Failed to save Anthropic key:', error)
    anthropicError.value = error.response?.data?.detail || 'Failed to save API key'
  } finally {
    anthropicLoading.value = false
  }
}

async function deleteAnthropicKey() {
  if (!confirm('Are you sure you want to remove your Anthropic API key? The assistant will stop working until you add a new key.')) {
    return
  }

  anthropicLoading.value = true
  anthropicError.value = null

  try {
    await api.delete('/api/auth/anthropic/key')
    anthropicStatus.value = { has_key: false }
    anthropicSuccess.value = 'API key removed'
    setTimeout(() => { anthropicSuccess.value = null }, 3000)
  } catch (error: any) {
    console.error('Failed to delete Anthropic key:', error)
    anthropicError.value = error.response?.data?.detail || 'Failed to remove API key'
  } finally {
    anthropicLoading.value = false
  }
}

async function updateSetting(key: string, value: any) {
  await settingsStore.updateAssistantSettings({ [key]: value })
}

async function handleLogout() {
  if (confirm('Are you sure you want to sign out?')) {
    await authStore.logout()
  }
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex-shrink-0 p-4 border-b border-gray-200">
      <h1 class="text-xl font-semibold text-gray-900">Settings</h1>
      <p class="text-sm text-gray-500">Manage your Zylch preferences</p>
    </div>

    <div class="flex-1 flex overflow-hidden">
      <!-- Sidebar -->
      <div class="w-56 border-r border-gray-200 p-4">
        <nav class="space-y-1">
          <button
            v-for="tab in tabs"
            :key="tab.id"
            @click="activeTab = tab.id"
            :class="[
              'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors',
              activeTab === tab.id
                ? 'bg-accent/10 text-accent'
                : 'text-gray-600 hover:bg-gray-100'
            ]"
          >
            <span>{{ tab.icon }}</span>
            {{ tab.label }}
          </button>
        </nav>
      </div>

      <!-- Content -->
      <div class="flex-1 overflow-y-auto p-6">
        <!-- Assistant Settings -->
        <div v-if="activeTab === 'assistant'" class="max-w-2xl space-y-6">
          <div>
            <h2 class="text-lg font-semibold text-gray-900 mb-4">Assistant Behavior</h2>

            <div class="space-y-4">
              <div class="flex items-center justify-between">
                <div>
                  <h3 class="font-medium text-gray-900">Tone</h3>
                  <p class="text-sm text-gray-500">How Zylch communicates with you</p>
                </div>
                <select
                  :value="settingsStore.assistant?.settings?.assistantTone || 'professional'"
                  @change="updateSetting('assistantTone', ($event.target as HTMLSelectElement).value)"
                  class="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
                >
                  <option value="casual">Casual</option>
                  <option value="professional">Professional</option>
                  <option value="formal">Formal</option>
                </select>
              </div>

              <div class="flex items-center justify-between">
                <div>
                  <h3 class="font-medium text-gray-900">Response Length</h3>
                  <p class="text-sm text-gray-500">Preferred length of assistant responses</p>
                </div>
                <select
                  :value="settingsStore.assistant?.settings?.responseLength || 'balanced'"
                  @change="updateSetting('responseLength', ($event.target as HTMLSelectElement).value)"
                  class="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
                >
                  <option value="concise">Concise</option>
                  <option value="balanced">Balanced</option>
                  <option value="detailed">Detailed</option>
                </select>
              </div>

              <div class="flex items-center justify-between">
                <div>
                  <h3 class="font-medium text-gray-900">Proactive Suggestions</h3>
                  <p class="text-sm text-gray-500">Allow Zylch to suggest actions</p>
                </div>
                <button
                  @click="updateSetting('proactiveSuggestions', !settingsStore.assistant?.settings?.proactiveSuggestions)"
                  :class="[
                    'relative w-12 h-6 rounded-full transition-colors',
                    settingsStore.assistant?.settings?.proactiveSuggestions ? 'bg-accent' : 'bg-gray-300'
                  ]"
                >
                  <span
                    :class="[
                      'absolute top-1 w-4 h-4 bg-white rounded-full transition-transform',
                      settingsStore.assistant?.settings?.proactiveSuggestions ? 'left-7' : 'left-1'
                    ]"
                  />
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Privacy Settings -->
        <div v-if="activeTab === 'privacy'" class="max-w-2xl space-y-6">
          <div>
            <h2 class="text-lg font-semibold text-gray-900 mb-4">Privacy & Data</h2>

            <div class="space-y-4">
              <div class="flex items-center justify-between">
                <div>
                  <h3 class="font-medium text-gray-900">Store Conversation History</h3>
                  <p class="text-sm text-gray-500">Keep chat history for context</p>
                </div>
                <button
                  @click="updateSetting('storeHistory', !settingsStore.assistant?.settings?.storeHistory)"
                  :class="[
                    'relative w-12 h-6 rounded-full transition-colors',
                    settingsStore.assistant?.settings?.storeHistory !== false ? 'bg-accent' : 'bg-gray-300'
                  ]"
                >
                  <span
                    :class="[
                      'absolute top-1 w-4 h-4 bg-white rounded-full transition-transform',
                      settingsStore.assistant?.settings?.storeHistory !== false ? 'left-7' : 'left-1'
                    ]"
                  />
                </button>
              </div>

              <div class="flex items-center justify-between">
                <div>
                  <h3 class="font-medium text-gray-900">Share Usage Analytics</h3>
                  <p class="text-sm text-gray-500">Help improve Zylch with anonymous data</p>
                </div>
                <button
                  @click="updateSetting('shareAnalytics', !settingsStore.assistant?.settings?.shareAnalytics)"
                  :class="[
                    'relative w-12 h-6 rounded-full transition-colors',
                    settingsStore.assistant?.settings?.shareAnalytics ? 'bg-accent' : 'bg-gray-300'
                  ]"
                >
                  <span
                    :class="[
                      'absolute top-1 w-4 h-4 bg-white rounded-full transition-transform',
                      settingsStore.assistant?.settings?.shareAnalytics ? 'left-7' : 'left-1'
                    ]"
                  />
                </button>
              </div>

              <div class="pt-4 border-t border-gray-200">
                <button
                  class="px-4 py-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                >
                  Clear All Data
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Notifications Settings -->
        <div v-if="activeTab === 'notifications'" class="max-w-2xl space-y-6">
          <div>
            <h2 class="text-lg font-semibold text-gray-900 mb-4">Notification Preferences</h2>

            <div class="space-y-4">
              <div class="flex items-center justify-between">
                <div>
                  <h3 class="font-medium text-gray-900">Email Notifications</h3>
                  <p class="text-sm text-gray-500">Receive notifications via email</p>
                </div>
                <button
                  @click="updateSetting('emailNotifications', !settingsStore.assistant?.settings?.emailNotifications)"
                  :class="[
                    'relative w-12 h-6 rounded-full transition-colors',
                    settingsStore.assistant?.settings?.emailNotifications ? 'bg-accent' : 'bg-gray-300'
                  ]"
                >
                  <span
                    :class="[
                      'absolute top-1 w-4 h-4 bg-white rounded-full transition-transform',
                      settingsStore.assistant?.settings?.emailNotifications ? 'left-7' : 'left-1'
                    ]"
                  />
                </button>
              </div>

              <div class="flex items-center justify-between">
                <div>
                  <h3 class="font-medium text-gray-900">Task Reminders</h3>
                  <p class="text-sm text-gray-500">Get reminded about upcoming tasks</p>
                </div>
                <button
                  @click="updateSetting('taskReminders', !settingsStore.assistant?.settings?.taskReminders)"
                  :class="[
                    'relative w-12 h-6 rounded-full transition-colors',
                    settingsStore.assistant?.settings?.taskReminders !== false ? 'bg-accent' : 'bg-gray-300'
                  ]"
                >
                  <span
                    :class="[
                      'absolute top-1 w-4 h-4 bg-white rounded-full transition-transform',
                      settingsStore.assistant?.settings?.taskReminders !== false ? 'left-7' : 'left-1'
                    ]"
                  />
                </button>
              </div>

              <div class="flex items-center justify-between">
                <div>
                  <h3 class="font-medium text-gray-900">Relationship Gap Alerts</h3>
                  <p class="text-sm text-gray-500">Alert when contacts need attention</p>
                </div>
                <button
                  @click="updateSetting('gapAlerts', !settingsStore.assistant?.settings?.gapAlerts)"
                  :class="[
                    'relative w-12 h-6 rounded-full transition-colors',
                    settingsStore.assistant?.settings?.gapAlerts ? 'bg-accent' : 'bg-gray-300'
                  ]"
                >
                  <span
                    :class="[
                      'absolute top-1 w-4 h-4 bg-white rounded-full transition-transform',
                      settingsStore.assistant?.settings?.gapAlerts ? 'left-7' : 'left-1'
                    ]"
                  />
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Integrations Settings -->
        <div v-if="activeTab === 'integrations'" class="max-w-2xl space-y-6">
          <div>
            <h2 class="text-lg font-semibold text-gray-900 mb-4">Connected Services</h2>

            <!-- Error messages -->
            <div v-if="googleError" class="mb-4 p-3 bg-red-50 text-red-700 rounded-lg text-sm">
              {{ googleError }}
            </div>
            <div v-if="anthropicError" class="mb-4 p-3 bg-red-50 text-red-700 rounded-lg text-sm">
              {{ anthropicError }}
            </div>
            <div v-if="anthropicSuccess" class="mb-4 p-3 bg-green-50 text-green-700 rounded-lg text-sm">
              {{ anthropicSuccess }}
            </div>

            <div class="space-y-4">
              <!-- Google Integration -->
              <div class="p-4 border border-gray-200 rounded-xl">
                <div class="flex items-center justify-between">
                  <div class="flex items-center gap-3">
                    <div class="w-10 h-10 bg-red-100 rounded-lg flex items-center justify-center">
                      <span class="text-red-600 text-lg">G</span>
                    </div>
                    <div>
                      <h3 class="font-medium text-gray-900">Google</h3>
                      <p class="text-sm text-gray-500">Gmail, Calendar, Tasks</p>
                    </div>
                  </div>

                  <!-- Loading state -->
                  <span v-if="googleLoading" class="text-sm text-gray-500">
                    Loading...
                  </span>

                  <!-- Connected state -->
                  <template v-else-if="googleStatus?.has_credentials">
                    <div class="flex items-center gap-2">
                      <span class="text-sm text-green-600 bg-green-50 px-3 py-1 rounded-full">Connected</span>
                      <button
                        @click="disconnectGoogle"
                        class="text-sm text-red-600 hover:underline"
                      >
                        Disconnect
                      </button>
                    </div>
                  </template>

                  <!-- Not connected state -->
                  <button
                    v-else
                    @click="connectGoogle"
                    class="text-sm text-white bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg transition-colors font-medium"
                  >
                    Connect Google
                  </button>
                </div>

                <!-- Show connected email if available -->
                <div v-if="googleStatus?.has_credentials && googleStatus?.email" class="mt-2 ml-13 text-sm text-gray-500">
                  Connected as: {{ googleStatus.email }}
                </div>

                <!-- Show warning if expired -->
                <div v-if="googleStatus?.expired" class="mt-2 ml-13 text-sm text-amber-600">
                  Token expired. Please reconnect.
                </div>
              </div>

              <!-- Microsoft Integration -->
              <div class="p-4 border border-gray-200 rounded-xl flex items-center justify-between">
                <div class="flex items-center gap-3">
                  <div class="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center">
                    <span class="text-blue-600 text-lg">M</span>
                  </div>
                  <div>
                    <h3 class="font-medium text-gray-900">Microsoft</h3>
                    <p class="text-sm text-gray-500">Outlook, Calendar</p>
                  </div>
                </div>
                <button class="text-sm text-accent hover:underline">Connect</button>
              </div>
            </div>
          </div>

          <!-- AI Provider Section -->
          <div>
            <h2 class="text-lg font-semibold text-gray-900 mb-4">AI Provider</h2>
            <p class="text-sm text-gray-500 mb-4">Configure your AI API key to power Zylch's assistant features.</p>

            <div class="space-y-4">
              <!-- Anthropic Integration -->
              <div class="p-4 border border-gray-200 rounded-xl">
                <div class="flex items-center justify-between">
                  <div class="flex items-center gap-3">
                    <div class="w-10 h-10 bg-orange-100 rounded-lg flex items-center justify-center">
                      <span class="text-orange-600 text-lg font-semibold">A</span>
                    </div>
                    <div>
                      <h3 class="font-medium text-gray-900">Anthropic Claude</h3>
                      <p class="text-sm text-gray-500">Powers the AI assistant</p>
                    </div>
                  </div>

                  <!-- Loading state -->
                  <span v-if="anthropicLoading" class="text-sm text-gray-500">
                    Loading...
                  </span>

                  <!-- Connected state -->
                  <template v-else-if="anthropicStatus?.has_key">
                    <div class="flex items-center gap-2">
                      <span class="text-sm text-green-600 bg-green-50 px-3 py-1 rounded-full">Connected</span>
                      <button
                        @click="deleteAnthropicKey"
                        class="text-sm text-red-600 hover:underline"
                      >
                        Remove
                      </button>
                    </div>
                  </template>

                  <!-- Not connected state -->
                  <button
                    v-else
                    @click="showAnthropicInput = true"
                    class="text-sm text-white bg-orange-600 hover:bg-orange-700 px-4 py-2 rounded-lg transition-colors font-medium"
                  >
                    Add API Key
                  </button>
                </div>

                <!-- Show key preview if connected -->
                <div v-if="anthropicStatus?.has_key && anthropicStatus?.key_preview" class="mt-2 ml-13 text-sm text-gray-500">
                  Key: {{ anthropicStatus.key_preview }}
                </div>

                <!-- API Key input form -->
                <div v-if="showAnthropicInput && !anthropicStatus?.has_key" class="mt-4 pt-4 border-t border-gray-100">
                  <label class="block text-sm font-medium text-gray-700 mb-2">
                    Anthropic API Key
                  </label>
                  <div class="flex gap-2">
                    <input
                      v-model="anthropicKeyInput"
                      type="password"
                      placeholder="sk-ant-..."
                      class="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500/50 focus:border-orange-500 text-sm"
                      @keyup.enter="saveAnthropicKey"
                    />
                    <button
                      @click="saveAnthropicKey"
                      :disabled="anthropicLoading"
                      class="px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 transition-colors text-sm font-medium disabled:opacity-50"
                    >
                      Save
                    </button>
                    <button
                      @click="showAnthropicInput = false; anthropicKeyInput = ''; anthropicError = null"
                      class="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors text-sm"
                    >
                      Cancel
                    </button>
                  </div>
                  <p class="mt-2 text-xs text-gray-500">
                    Get your API key from <a href="https://console.anthropic.com/settings/keys" target="_blank" class="text-orange-600 hover:underline">console.anthropic.com</a>
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Account Settings -->
        <div v-if="activeTab === 'account'" class="max-w-2xl space-y-6">
          <div>
            <h2 class="text-lg font-semibold text-gray-900 mb-4">Account</h2>

            <div class="p-4 bg-gray-50 rounded-xl mb-6">
              <div class="flex items-center gap-4">
                <div class="w-16 h-16 rounded-full bg-accent/10 flex items-center justify-center">
                  <span class="text-2xl text-accent">
                    {{ authStore.user?.name?.charAt(0) || '?' }}
                  </span>
                </div>
                <div>
                  <h3 class="font-semibold text-gray-900">{{ authStore.user?.name || 'User' }}</h3>
                  <p class="text-sm text-gray-500">{{ authStore.user?.email }}</p>
                </div>
              </div>
            </div>

            <div class="space-y-4">
              <button
                @click="handleLogout"
                class="w-full px-4 py-3 text-red-600 bg-red-50 rounded-lg hover:bg-red-100 transition-colors"
              >
                Sign Out
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
