<script setup lang="ts">
import { onMounted } from 'vue'
import { useContactsStore } from '@/stores/contacts'

const contactsStore = useContactsStore()

onMounted(() => {
  contactsStore.fetchContacts()
  contactsStore.fetchRelationshipGaps()
})

function formatDate(date: string | undefined) {
  if (!date) return 'Never'
  return new Date(date).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })
}

function getGapSeverity(days: number) {
  if (days > 90) return { label: 'Critical', color: 'bg-red-100 text-red-700' }
  if (days > 60) return { label: 'High', color: 'bg-orange-100 text-orange-700' }
  if (days > 30) return { label: 'Medium', color: 'bg-yellow-100 text-yellow-700' }
  return { label: 'Low', color: 'bg-green-100 text-green-700' }
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex-shrink-0 p-4 border-b border-gray-200">
      <h1 class="text-xl font-semibold text-gray-900">Relationship Gaps</h1>
      <p class="text-sm text-gray-500">
        {{ contactsStore.contactsWithGaps.length }} contacts need attention
      </p>
    </div>

    <!-- Content -->
    <div class="flex-1 overflow-y-auto p-4">
      <div v-if="contactsStore.loading" class="flex items-center justify-center h-32">
        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-accent"></div>
      </div>

      <div v-else-if="contactsStore.contactsWithGaps.length === 0" class="text-center py-12">
        <div class="w-16 h-16 mx-auto mb-4 bg-green-100 rounded-full flex items-center justify-center">
          <svg class="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
          </svg>
        </div>
        <p class="text-gray-900 font-medium">All caught up!</p>
        <p class="text-sm text-gray-500 mt-1">No relationship gaps detected</p>
      </div>

      <div v-else class="max-w-2xl mx-auto space-y-4">
        <!-- Summary Stats -->
        <div class="grid grid-cols-3 gap-4 mb-6">
          <div class="bg-red-50 border border-red-100 rounded-xl p-4 text-center">
            <p class="text-2xl font-bold text-red-700">
              {{ contactsStore.contactsWithGaps.filter(c => (c.relationshipGap || 0) > 90).length }}
            </p>
            <p class="text-sm text-red-600">Critical (90+ days)</p>
          </div>
          <div class="bg-orange-50 border border-orange-100 rounded-xl p-4 text-center">
            <p class="text-2xl font-bold text-orange-700">
              {{ contactsStore.contactsWithGaps.filter(c => (c.relationshipGap || 0) > 60 && (c.relationshipGap || 0) <= 90).length }}
            </p>
            <p class="text-sm text-orange-600">High (60-90 days)</p>
          </div>
          <div class="bg-yellow-50 border border-yellow-100 rounded-xl p-4 text-center">
            <p class="text-2xl font-bold text-yellow-700">
              {{ contactsStore.contactsWithGaps.filter(c => (c.relationshipGap || 0) > 30 && (c.relationshipGap || 0) <= 60).length }}
            </p>
            <p class="text-sm text-yellow-600">Medium (30-60 days)</p>
          </div>
        </div>

        <!-- Contact List -->
        <div class="bg-white border border-gray-200 rounded-xl divide-y divide-gray-100">
          <div
            v-for="contact in contactsStore.contactsWithGaps.sort((a, b) => (b.relationshipGap || 0) - (a.relationshipGap || 0))"
            :key="contact.id"
            class="p-4"
          >
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 bg-gray-200 rounded-full flex items-center justify-center">
                  <span class="text-sm font-medium text-gray-600">
                    {{ contact.name.charAt(0).toUpperCase() }}
                  </span>
                </div>
                <div>
                  <h3 class="font-medium text-gray-900">{{ contact.name }}</h3>
                  <p class="text-sm text-gray-500">{{ contact.email }}</p>
                </div>
              </div>
              <div class="flex items-center gap-3">
                <div class="text-right">
                  <span
                    :class="[
                      'inline-block px-2 py-1 rounded-full text-xs font-medium',
                      getGapSeverity(contact.relationshipGap || 0).color
                    ]"
                  >
                    {{ contact.relationshipGap }} days
                  </span>
                  <p class="text-xs text-gray-500 mt-1">
                    Last: {{ formatDate(contact.lastContact) }}
                  </p>
                </div>
                <div class="flex gap-2">
                  <button
                    class="p-2 text-gray-400 hover:text-accent hover:bg-accent/10 rounded-lg transition-colors"
                    title="Send email"
                  >
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
                    </svg>
                  </button>
                  <button
                    class="p-2 text-gray-400 hover:text-accent hover:bg-accent/10 rounded-lg transition-colors"
                    title="Schedule meeting"
                  >
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
                    </svg>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
