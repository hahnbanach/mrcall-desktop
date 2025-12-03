<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useContactsStore } from '@/stores/contacts'
import type { Contact } from '@/types'

const contactsStore = useContactsStore()
const selectedContact = ref<Contact | null>(null)

onMounted(() => {
  contactsStore.fetchContacts()
})

function formatDate(date: string | null | undefined) {
  if (!date) return 'Never'
  return new Date(date).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })
}

function getGapColor(days: number | undefined) {
  if (!days) return 'text-gray-500'
  if (days > 60) return 'text-red-600'
  if (days > 30) return 'text-yellow-600'
  return 'text-green-600'
}
</script>

<template>
  <div class="h-full flex">
    <!-- Contact List -->
    <div class="w-80 border-r border-gray-200 flex flex-col">
      <div class="p-4 border-b border-gray-200">
        <h1 class="text-xl font-semibold text-gray-900">Contacts</h1>
        <div class="mt-3">
          <input
            type="text"
            :value="contactsStore.searchQuery"
            @input="contactsStore.setSearchQuery(($event.target as HTMLInputElement).value)"
            placeholder="Search contacts..."
            class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
          />
        </div>
      </div>

      <div class="flex-1 overflow-y-auto">
        <div v-if="contactsStore.loading" class="flex items-center justify-center h-32">
          <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-accent"></div>
        </div>

        <div v-else-if="contactsStore.filteredContacts.length === 0" class="p-8 text-center">
          <p class="text-gray-500">No contacts found</p>
        </div>

        <div v-else class="divide-y divide-gray-100">
          <div
            v-for="contact in contactsStore.filteredContacts"
            :key="contact.id"
            @click="selectedContact = contact"
            :class="[
              'p-4 cursor-pointer transition-colors',
              selectedContact?.id === contact.id ? 'bg-accent/5' : 'hover:bg-gray-50'
            ]"
          >
            <div class="flex items-center gap-3">
              <div class="w-10 h-10 rounded-full bg-gray-200 flex items-center justify-center">
                <span class="text-sm font-medium text-gray-600">
                  {{ contact.name.charAt(0).toUpperCase() }}
                </span>
              </div>
              <div class="flex-1 min-w-0">
                <p class="font-medium text-gray-900 truncate">{{ contact.name }}</p>
                <p class="text-sm text-gray-500 truncate">{{ contact.email }}</p>
              </div>
              <div
                v-if="contact.relationshipGap && contact.relationshipGap > 30"
                class="flex-shrink-0"
              >
                <span
                  :class="['text-xs px-2 py-1 rounded-full', getGapColor(contact.relationshipGap)]"
                  :style="{ backgroundColor: contact.relationshipGap > 60 ? 'rgb(254 242 242)' : contact.relationshipGap > 30 ? 'rgb(254 249 195)' : 'rgb(220 252 231)' }"
                >
                  {{ contact.relationshipGap }}d
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Contact Detail -->
    <div class="flex-1 overflow-y-auto">
      <div v-if="!selectedContact" class="h-full flex items-center justify-center">
        <div class="text-center">
          <div class="w-16 h-16 mx-auto mb-4 bg-gray-100 rounded-full flex items-center justify-center">
            <svg class="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
            </svg>
          </div>
          <p class="text-gray-500">Select a contact to view details</p>
        </div>
      </div>

      <div v-else class="p-6">
        <div class="max-w-2xl">
          <!-- Header -->
          <div class="flex items-start gap-4 mb-6">
            <div class="w-20 h-20 rounded-full bg-accent/10 flex items-center justify-center">
              <span class="text-3xl text-accent">
                {{ selectedContact.name.charAt(0).toUpperCase() }}
              </span>
            </div>
            <div>
              <h2 class="text-2xl font-semibold text-gray-900">{{ selectedContact.name }}</h2>
              <p class="text-gray-500">{{ selectedContact.email }}</p>
              <p v-if="selectedContact.company" class="text-gray-500">{{ selectedContact.company }}</p>
            </div>
          </div>

          <!-- Info Cards -->
          <div class="grid grid-cols-2 gap-4 mb-6">
            <div class="p-4 bg-gray-50 rounded-xl">
              <p class="text-sm text-gray-500">Last Contact</p>
              <p class="font-medium text-gray-900">{{ formatDate(selectedContact.lastContact) }}</p>
            </div>
            <div class="p-4 bg-gray-50 rounded-xl">
              <p class="text-sm text-gray-500">Relationship Gap</p>
              <p :class="['font-medium', getGapColor(selectedContact.relationshipGap)]">
                {{ selectedContact.relationshipGap ? `${selectedContact.relationshipGap} days` : 'N/A' }}
              </p>
            </div>
          </div>

          <!-- Notes -->
          <div v-if="selectedContact.notes" class="mb-6">
            <h3 class="font-semibold text-gray-900 mb-2">Notes</h3>
            <p class="text-gray-600 bg-gray-50 p-4 rounded-xl">{{ selectedContact.notes }}</p>
          </div>

          <!-- Actions -->
          <div class="flex gap-3">
            <button class="px-4 py-2 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors">
              Send Email
            </button>
            <button class="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors">
              Schedule Meeting
            </button>
            <button class="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors">
              Create Task
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
