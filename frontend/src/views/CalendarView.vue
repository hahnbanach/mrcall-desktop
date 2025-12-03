<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useCalendarStore } from '@/stores/calendar'
import type { CalendarEvent } from '@/types'

const calendarStore = useCalendarStore()
const showCreateModal = ref(false)
const newEvent = ref({
  title: '',
  description: '',
  start: '',
  end: '',
  location: ''
})

onMounted(() => {
  calendarStore.fetchEvents()
})

const currentMonth = computed(() => {
  return calendarStore.selectedDate.toLocaleDateString([], { month: 'long', year: 'numeric' })
})

const daysInMonth = computed(() => {
  const date = calendarStore.selectedDate
  const year = date.getFullYear()
  const month = date.getMonth()
  const firstDay = new Date(year, month, 1)
  const lastDay = new Date(year, month + 1, 0)
  const startPadding = firstDay.getDay()

  const days = []

  // Previous month padding
  for (let i = startPadding - 1; i >= 0; i--) {
    const d = new Date(year, month, -i)
    days.push({ date: d, isCurrentMonth: false })
  }

  // Current month
  for (let i = 1; i <= lastDay.getDate(); i++) {
    days.push({ date: new Date(year, month, i), isCurrentMonth: true })
  }

  // Next month padding
  const remaining = 42 - days.length
  for (let i = 1; i <= remaining; i++) {
    days.push({ date: new Date(year, month + 1, i), isCurrentMonth: false })
  }

  return days
})

function getEventsForDate(date: Date) {
  const start = new Date(date)
  start.setHours(0, 0, 0, 0)
  const end = new Date(start)
  end.setDate(end.getDate() + 1)

  return calendarStore.events.filter(e => {
    const eventDate = new Date(e.start)
    return eventDate >= start && eventDate < end
  })
}

function isToday(date: Date) {
  const today = new Date()
  return date.toDateString() === today.toDateString()
}

function isSelected(date: Date) {
  return date.toDateString() === calendarStore.selectedDate.toDateString()
}

function prevMonth() {
  const d = new Date(calendarStore.selectedDate)
  d.setMonth(d.getMonth() - 1)
  calendarStore.setSelectedDate(d)
}

function nextMonth() {
  const d = new Date(calendarStore.selectedDate)
  d.setMonth(d.getMonth() + 1)
  calendarStore.setSelectedDate(d)
}

function selectDate(date: Date) {
  calendarStore.setSelectedDate(date)
}

async function createEvent() {
  const event = await calendarStore.createEvent(newEvent.value)
  if (event) {
    showCreateModal.value = false
    newEvent.value = { title: '', description: '', start: '', end: '', location: '' }
  }
}

function formatTime(date: string) {
  return new Date(date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex-shrink-0 p-4 border-b border-gray-200">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-4">
          <button @click="prevMonth" class="p-2 hover:bg-gray-100 rounded-lg transition-colors">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
            </svg>
          </button>
          <h1 class="text-xl font-semibold text-gray-900">{{ currentMonth }}</h1>
          <button @click="nextMonth" class="p-2 hover:bg-gray-100 rounded-lg transition-colors">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
            </svg>
          </button>
        </div>
        <button
          @click="showCreateModal = true"
          class="px-4 py-2 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors"
        >
          New Event
        </button>
      </div>
    </div>

    <!-- Calendar Grid -->
    <div class="flex-1 p-4 flex gap-4">
      <div class="flex-1">
        <!-- Day Headers -->
        <div class="grid grid-cols-7 gap-1 mb-2">
          <div
            v-for="day in ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']"
            :key="day"
            class="text-center text-sm font-medium text-gray-500 py-2"
          >
            {{ day }}
          </div>
        </div>

        <!-- Calendar Days -->
        <div class="grid grid-cols-7 gap-1">
          <div
            v-for="(day, i) in daysInMonth"
            :key="i"
            @click="selectDate(day.date)"
            :class="[
              'p-2 min-h-[80px] rounded-lg cursor-pointer transition-colors border',
              day.isCurrentMonth ? 'bg-white' : 'bg-gray-50',
              isSelected(day.date) ? 'border-accent' : 'border-transparent hover:border-gray-200'
            ]"
          >
            <div
              :class="[
                'text-sm font-medium mb-1',
                !day.isCurrentMonth && 'text-gray-400',
                isToday(day.date) && 'w-6 h-6 rounded-full bg-accent text-white flex items-center justify-center'
              ]"
            >
              {{ day.date.getDate() }}
            </div>
            <div class="space-y-1">
              <div
                v-for="event in getEventsForDate(day.date).slice(0, 2)"
                :key="event.id"
                class="text-xs px-1 py-0.5 rounded bg-accent/10 text-accent truncate"
              >
                {{ event.title }}
              </div>
              <div
                v-if="getEventsForDate(day.date).length > 2"
                class="text-xs text-gray-500"
              >
                +{{ getEventsForDate(day.date).length - 2 }} more
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Selected Day Events -->
      <div class="w-80 border-l border-gray-200 pl-4">
        <h2 class="font-semibold text-gray-900 mb-4">
          {{ calendarStore.selectedDate.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' }) }}
        </h2>

        <div v-if="calendarStore.eventsForSelectedDate.length === 0" class="text-center py-8">
          <p class="text-gray-500">No events scheduled</p>
        </div>

        <div v-else class="space-y-3">
          <div
            v-for="event in calendarStore.eventsForSelectedDate"
            :key="event.id"
            class="p-3 bg-gray-50 rounded-lg"
          >
            <h3 class="font-medium text-gray-900">{{ event.title }}</h3>
            <p class="text-sm text-gray-500">
              {{ formatTime(event.start) }} - {{ formatTime(event.end) }}
            </p>
            <p v-if="event.location" class="text-sm text-gray-500 flex items-center gap-1 mt-1">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"/>
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"/>
              </svg>
              {{ event.location }}
            </p>
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
            <h2 class="text-lg font-semibold">New Event</h2>
          </div>
          <div class="p-4 space-y-4">
            <input
              v-model="newEvent.title"
              type="text"
              placeholder="Event title"
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
            />
            <textarea
              v-model="newEvent.description"
              rows="2"
              placeholder="Description (optional)"
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50 resize-none"
            />
            <input
              v-model="newEvent.location"
              type="text"
              placeholder="Location (optional)"
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
            />
            <div class="flex gap-4">
              <div class="flex-1">
                <label class="block text-sm text-gray-600 mb-1">Start</label>
                <input
                  v-model="newEvent.start"
                  type="datetime-local"
                  class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
                />
              </div>
              <div class="flex-1">
                <label class="block text-sm text-gray-600 mb-1">End</label>
                <input
                  v-model="newEvent.end"
                  type="datetime-local"
                  class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
                />
              </div>
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
              @click="createEvent"
              :disabled="!newEvent.title || !newEvent.start || !newEvent.end || calendarStore.loading"
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
