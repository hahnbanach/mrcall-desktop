import axios, { type AxiosInstance, type AxiosError } from 'axios'
import { useAuthStore } from '@/stores/auth'

// Create axios instance - Zylch backend runs on port 8000
const api: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// Request interceptor for auth
api.interceptors.request.use(
  (config) => {
    const authStore = useAuthStore()
    if (authStore.token) {
      config.headers.Authorization = `Bearer ${authStore.token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    if (error.response?.status === 401) {
      const authStore = useAuthStore()
      // Try to refresh token
      const newToken = await authStore.refreshToken()
      if (newToken && error.config) {
        error.config.headers.Authorization = `Bearer ${newToken}`
        return api.request(error.config)
      }
      // If refresh fails, logout
      await authStore.logout()
    }
    return Promise.reject(error)
  }
)

export default api

// Export all services
export { emailService } from './email'
export { calendarService } from './calendar'
export { taskService } from './tasks'
export { contactService } from './contacts'
export { memoryService } from './memory'
export { chatService } from './chat'
export { syncService } from './sync'
export { settingsService, triggerService, cacheService, sharingService } from './settings'
export { mrcallService } from './mrcall'
