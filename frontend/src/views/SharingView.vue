<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import type { ShareAuthorization } from '@/types'

const settingsStore = useSettingsStore()
const showAddModal = ref(false)
const newShare = ref({
  email: '',
  permissions: ['read'] as string[]
})

onMounted(() => {
  settingsStore.fetchShareAuthorizations()
})

function formatDate(date: string) {
  return new Date(date).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })
}

async function addAuthorization() {
  await settingsStore.addShareAuthorization(newShare.value)
  showAddModal.value = false
  newShare.value = { email: '', permissions: ['read'] }
}

async function revokeAuthorization(id: string) {
  if (confirm('Are you sure you want to revoke this authorization?')) {
    await settingsStore.revokeShareAuthorization(id)
  }
}

const permissionLabels: Record<string, string> = {
  read: 'View',
  write: 'Edit',
  delete: 'Delete',
  admin: 'Admin'
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex-shrink-0 p-4 border-b border-gray-200">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-semibold text-gray-900">Sharing & Permissions</h1>
          <p class="text-sm text-gray-500">Manage who can access your Zylch data</p>
        </div>
        <button
          @click="showAddModal = true"
          class="px-4 py-2 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors"
        >
          Add Person
        </button>
      </div>
    </div>

    <!-- Content -->
    <div class="flex-1 overflow-y-auto p-4">
      <div v-if="settingsStore.loading" class="flex items-center justify-center h-32">
        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-accent"></div>
      </div>

      <div v-else class="max-w-2xl mx-auto space-y-6">
        <!-- Active Authorizations -->
        <div class="bg-white border border-gray-200 rounded-xl p-6">
          <h2 class="font-semibold text-gray-900 mb-4">Authorized Users</h2>

          <div v-if="settingsStore.shareAuthorizations.length === 0" class="text-center py-8">
            <div class="w-16 h-16 mx-auto mb-4 bg-gray-100 rounded-full flex items-center justify-center">
              <svg class="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"/>
              </svg>
            </div>
            <p class="text-gray-500">No shared access</p>
            <p class="text-sm text-gray-400 mt-1">Add people to share your Zylch data</p>
          </div>

          <div v-else class="space-y-3">
            <div
              v-for="auth in settingsStore.shareAuthorizations"
              :key="auth.id"
              class="flex items-center justify-between p-4 bg-gray-50 rounded-lg"
            >
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 bg-accent/10 rounded-full flex items-center justify-center">
                  <span class="text-accent font-medium">
                    {{ auth.email.charAt(0).toUpperCase() }}
                  </span>
                </div>
                <div>
                  <p class="font-medium text-gray-900">{{ auth.email }}</p>
                  <div class="flex items-center gap-2 mt-1">
                    <span
                      v-for="perm in auth.permissions"
                      :key="perm"
                      class="text-xs px-2 py-0.5 bg-white border border-gray-200 rounded-full text-gray-600"
                    >
                      {{ permissionLabels[perm] || perm }}
                    </span>
                  </div>
                </div>
              </div>
              <div class="flex items-center gap-3">
                <span class="text-sm text-gray-500">
                  Added {{ formatDate(auth.createdAt) }}
                </span>
                <button
                  @click="revokeAuthorization(auth.id)"
                  class="text-red-600 hover:text-red-700 transition-colors"
                >
                  <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Sharing Info -->
        <div class="bg-blue-50 border border-blue-200 rounded-xl p-4">
          <div class="flex items-start gap-3">
            <svg class="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
            </svg>
            <div>
              <h3 class="font-medium text-blue-800">About Sharing</h3>
              <p class="text-sm text-blue-600 mt-1">
                Shared users can access your Zylch data based on the permissions you grant.
                You can revoke access at any time.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Add Modal -->
    <Teleport to="body">
      <div v-if="showAddModal" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/50" @click="showAddModal = false"></div>
        <div class="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4">
          <div class="p-4 border-b border-gray-200">
            <h2 class="text-lg font-semibold">Share Access</h2>
          </div>
          <div class="p-4 space-y-4">
            <div>
              <label class="block text-sm text-gray-600 mb-1">Email Address</label>
              <input
                v-model="newShare.email"
                type="email"
                placeholder="user@example.com"
                class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
              />
            </div>
            <div>
              <label class="block text-sm text-gray-600 mb-2">Permissions</label>
              <div class="space-y-2">
                <label class="flex items-center gap-2">
                  <input
                    type="checkbox"
                    value="read"
                    v-model="newShare.permissions"
                    class="rounded border-gray-300 text-accent focus:ring-accent"
                  />
                  <span class="text-gray-700">View data</span>
                </label>
                <label class="flex items-center gap-2">
                  <input
                    type="checkbox"
                    value="write"
                    v-model="newShare.permissions"
                    class="rounded border-gray-300 text-accent focus:ring-accent"
                  />
                  <span class="text-gray-700">Edit data</span>
                </label>
                <label class="flex items-center gap-2">
                  <input
                    type="checkbox"
                    value="admin"
                    v-model="newShare.permissions"
                    class="rounded border-gray-300 text-accent focus:ring-accent"
                  />
                  <span class="text-gray-700">Admin access</span>
                </label>
              </div>
            </div>
          </div>
          <div class="p-4 border-t border-gray-200 flex justify-end gap-3">
            <button
              @click="showAddModal = false"
              class="px-4 py-2 text-gray-600 hover:text-gray-900 transition-colors"
            >
              Cancel
            </button>
            <button
              @click="addAuthorization"
              :disabled="!newShare.email || newShare.permissions.length === 0 || settingsStore.loading"
              class="px-6 py-2 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors disabled:opacity-50"
            >
              Share
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
