import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { CalendarEvent } from '@/types'
import { calendarApi } from '@/services/api/calendar'

export const useCalendarStore = defineStore('calendar', () => {
  const events = ref<CalendarEvent[]>([])
  const currentEvent = ref<CalendarEvent | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const selectedDate = ref<Date>(new Date())
  const viewMode = ref<'day' | 'week' | 'month'>('week')

  const todayEvents = computed(() => {
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    const tomorrow = new Date(today)
    tomorrow.setDate(tomorrow.getDate() + 1)

    return events.value.filter(e => {
      const start = new Date(e.start)
      return start >= today && start < tomorrow
    })
  })

  const upcomingEvents = computed(() => {
    const now = new Date()
    return events.value
      .filter(e => new Date(e.start) > now)
      .sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime())
      .slice(0, 10)
  })

  const eventsForSelectedDate = computed(() => {
    const date = selectedDate.value
    const start = new Date(date)
    start.setHours(0, 0, 0, 0)
    const end = new Date(start)
    end.setDate(end.getDate() + 1)

    return events.value.filter(e => {
      const eventStart = new Date(e.start)
      return eventStart >= start && eventStart < end
    })
  })

  async function fetchEvents(timeMin?: string, timeMax?: string) {
    loading.value = true
    error.value = null
    try {
      const min = timeMin || new Date().toISOString()
      const max = timeMax || new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString()
      const data = await calendarApi.getEvents(min, max)
      events.value = data
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch calendar events'
    } finally {
      loading.value = false
    }
  }

  async function createEvent(event: Partial<CalendarEvent>) {
    loading.value = true
    error.value = null
    try {
      const created = await calendarApi.createEvent(event)
      events.value.push(created)
      return created
    } catch (err: any) {
      error.value = err.message || 'Failed to create event'
      return null
    } finally {
      loading.value = false
    }
  }

  async function updateEvent(eventId: string, updates: Partial<CalendarEvent>) {
    loading.value = true
    error.value = null
    try {
      const updated = await calendarApi.updateEvent(eventId, updates)
      const idx = events.value.findIndex(e => e.id === eventId)
      if (idx >= 0) events.value[idx] = updated
      if (currentEvent.value?.id === eventId) currentEvent.value = updated
      return updated
    } catch (err: any) {
      error.value = err.message || 'Failed to update event'
      return null
    } finally {
      loading.value = false
    }
  }

  async function deleteEvent(eventId: string) {
    loading.value = true
    error.value = null
    try {
      await calendarApi.deleteEvent(eventId)
      events.value = events.value.filter(e => e.id !== eventId)
      if (currentEvent.value?.id === eventId) currentEvent.value = null
      return true
    } catch (err: any) {
      error.value = err.message || 'Failed to delete event'
      return false
    } finally {
      loading.value = false
    }
  }

  function setSelectedDate(date: Date) {
    selectedDate.value = date
  }

  function setViewMode(mode: 'day' | 'week' | 'month') {
    viewMode.value = mode
  }

  function selectEvent(event: CalendarEvent | null) {
    currentEvent.value = event
  }

  return {
    events,
    currentEvent,
    loading,
    error,
    selectedDate,
    viewMode,
    todayEvents,
    upcomingEvents,
    eventsForSelectedDate,
    fetchEvents,
    createEvent,
    updateEvent,
    deleteEvent,
    setSelectedDate,
    setViewMode,
    selectEvent
  }
})
