import api from './index'
import type { CalendarEvent } from '@/types'

interface GetEventsParams {
  startDate?: Date
  endDate?: Date
}

export const calendarService = {
  async getEvents(timeMin?: string, timeMax?: string): Promise<CalendarEvent[]> {
    const { data } = await api.get('/api/calendar/events', {
      params: { time_min: timeMin, time_max: timeMax }
    })
    return data
  },

  async getEvent(id: string): Promise<CalendarEvent> {
    const { data } = await api.get(`/api/calendar/events/${id}`)
    return data
  },

  async createEvent(event: Partial<CalendarEvent>): Promise<CalendarEvent> {
    const { data } = await api.post('/api/calendar/events', event)
    return data
  },

  async updateEvent(id: string, event: Partial<CalendarEvent>): Promise<CalendarEvent> {
    const { data } = await api.put(`/api/calendar/events/${id}`, event)
    return data
  },

  async deleteEvent(id: string): Promise<void> {
    await api.delete(`/api/calendar/events/${id}`)
  }
}

// Alias for stores that use calendarApi
export const calendarApi = calendarService
