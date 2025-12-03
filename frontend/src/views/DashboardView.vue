<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { AppLayout } from '@/components/layout'
import { useTasksStore } from '@/stores/tasks'
import { useCalendarStore } from '@/stores/calendar'
import { useContactsStore } from '@/stores/contacts'
import { useSyncStore } from '@/stores/sync'
import { useAuthStore } from '@/stores/auth'
import {
  ClipboardDocumentListIcon,
  CalendarIcon,
  ExclamationTriangleIcon,
  ArrowPathIcon,
  EnvelopeIcon,
  UserGroupIcon
} from '@heroicons/vue/24/outline'
import { formatDistanceToNow } from 'date-fns'

const authStore = useAuthStore()
const taskStore = useTasksStore()
const calendarStore = useCalendarStore()
const contactStore = useContactsStore()
const syncStore = useSyncStore()

onMounted(async () => {
  await Promise.all([
    taskStore.fetchTasks(),
    calendarStore.fetchEvents(),
    contactStore.fetchRelationshipGaps(),
    syncStore.fetchStatus()
  ])
})

const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
})

const lastSyncText = computed(() => {
  if (!syncStore.lastSync) return 'Never synced'
  return formatDistanceToNow(new Date(syncStore.lastSync), { addSuffix: true })
})
</script>

<template>
  <AppLayout>
    <div class="space-y-6">
      <!-- Welcome Header -->
      <div class="bg-gradient-to-r from-zylch-accent to-indigo-500 rounded-zylch p-6 text-white">
        <h2 class="text-2xl font-semibold">{{ greeting }}, {{ authStore.userName }}!</h2>
        <p class="mt-1 text-white/80">Here's what's happening with your communications today.</p>
        <p class="mt-2 text-sm text-white/60">Last synced {{ lastSyncText }}</p>
      </div>

      <!-- Stats Grid -->
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <!-- Urgent Tasks -->
        <router-link to="/tasks?filter=urgent" class="card hover:shadow-zylch-lg transition-shadow">
          <div class="flex items-center">
            <div class="p-3 bg-red-100 rounded-lg">
              <ClipboardDocumentListIcon class="h-6 w-6 text-red-600" />
            </div>
            <div class="ml-4">
              <p class="text-sm text-zylch-muted">Urgent Tasks</p>
              <p class="text-2xl font-semibold text-red-600">{{ taskStore.overdueTasks.length }}</p>
            </div>
          </div>
        </router-link>

        <!-- Open Tasks -->
        <router-link to="/tasks?filter=open" class="card hover:shadow-zylch-lg transition-shadow">
          <div class="flex items-center">
            <div class="p-3 bg-yellow-100 rounded-lg">
              <ClipboardDocumentListIcon class="h-6 w-6 text-yellow-600" />
            </div>
            <div class="ml-4">
              <p class="text-sm text-zylch-muted">Open Tasks</p>
              <p class="text-2xl font-semibold">{{ taskStore.pendingTasks.length }}</p>
            </div>
          </div>
        </router-link>

        <!-- Today's Events -->
        <router-link to="/calendar" class="card hover:shadow-zylch-lg transition-shadow">
          <div class="flex items-center">
            <div class="p-3 bg-blue-100 rounded-lg">
              <CalendarIcon class="h-6 w-6 text-blue-600" />
            </div>
            <div class="ml-4">
              <p class="text-sm text-zylch-muted">Today's Events</p>
              <p class="text-2xl font-semibold">{{ calendarStore.todayEvents.length }}</p>
            </div>
          </div>
        </router-link>

        <!-- Relationship Gaps -->
        <router-link to="/gaps" class="card hover:shadow-zylch-lg transition-shadow">
          <div class="flex items-center">
            <div class="p-3 bg-orange-100 rounded-lg">
              <ExclamationTriangleIcon class="h-6 w-6 text-orange-600" />
            </div>
            <div class="ml-4">
              <p class="text-sm text-zylch-muted">Relationship Gaps</p>
              <p class="text-2xl font-semibold">{{ contactStore.contactsWithGaps.length }}</p>
            </div>
          </div>
        </router-link>
      </div>

      <!-- Main Content Grid -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- Urgent Tasks List -->
        <div class="card">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-lg font-semibold">Urgent Tasks</h3>
            <router-link to="/tasks" class="text-sm text-zylch-accent hover:underline">
              View all
            </router-link>
          </div>

          <div v-if="taskStore.overdueTasks.length === 0" class="text-center py-8 text-zylch-muted">
            No urgent tasks. Great job!
          </div>

          <div v-else class="space-y-3">
            <router-link
              v-for="task in taskStore.overdueTasks.slice(0, 5)"
              :key="task.id"
              :to="`/tasks?id=${task.id}`"
              class="block p-3 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors"
            >
              <div class="flex items-center justify-between">
                <div>
                  <p class="font-medium">{{ task.title || 'Task' }}</p>
                  <p class="text-sm text-zylch-muted truncate">{{ task.description }}</p>
                </div>
                <span
                  class="px-2 py-1 text-xs font-medium rounded-full"
                  :class="task.priority === 'high' ? 'bg-red-100 text-red-700' : 'bg-orange-100 text-orange-700'"
                >
                  {{ task.priority }}
                </span>
              </div>
            </router-link>
          </div>
        </div>

        <!-- Upcoming Events -->
        <div class="card">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-lg font-semibold">Upcoming Events</h3>
            <router-link to="/calendar" class="text-sm text-zylch-accent hover:underline">
              View calendar
            </router-link>
          </div>

          <div v-if="calendarStore.upcomingEvents.length === 0" class="text-center py-8 text-zylch-muted">
            No upcoming events
          </div>

          <div v-else class="space-y-3">
            <div
              v-for="event in calendarStore.upcomingEvents"
              :key="event.id"
              class="p-3 bg-gray-50 rounded-lg"
            >
              <div class="flex items-start justify-between">
                <div>
                  <p class="font-medium">{{ event.summary }}</p>
                  <p class="text-sm text-zylch-muted">
                    {{ new Date(event.start).toLocaleString() }}
                  </p>
                </div>
                <a
                  v-if="event.meetLink"
                  :href="event.meetLink"
                  target="_blank"
                  class="px-2 py-1 text-xs font-medium bg-green-100 text-green-700 rounded-full hover:bg-green-200"
                >
                  Join Meet
                </a>
              </div>
            </div>
          </div>
        </div>

        <!-- Relationship Gaps -->
        <div class="card lg:col-span-2">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-lg font-semibold">Relationship Gaps</h3>
            <router-link to="/gaps" class="text-sm text-zylch-accent hover:underline">
              View all gaps
            </router-link>
          </div>

          <div v-if="contactStore.contactsWithGaps.length === 0" class="text-center py-8 text-zylch-muted">
            No relationship gaps detected
          </div>

          <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <div
              v-for="contact in contactStore.contactsWithGaps.slice(0, 6)"
              :key="contact.email"
              class="p-4 border border-orange-200 bg-orange-50 rounded-lg"
            >
              <div class="flex items-center justify-between mb-2">
                <p class="font-medium">{{ contact.name }}</p>
                <span class="text-xs text-orange-600">{{ contact.relationshipGap }} days</span>
              </div>
              <p class="text-sm text-zylch-muted">Consider reaching out</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>
