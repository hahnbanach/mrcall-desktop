import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import type { User } from '@/types'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const REFRESH_THRESHOLD_MS = 5 * 60 * 1000 // Refresh when < 5 minutes left

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const token = ref<string | null>(null)
  const refreshToken = ref<string | null>(null)
  const loading = ref(true)
  const error = ref<string | null>(null)
  let refreshTimer: ReturnType<typeof setTimeout> | null = null

  const isAuthenticated = computed(() => !!user.value && !!token.value)
  const userName = computed(() => user.value?.name || 'User')
  const isLoading = computed(() => loading.value)

  /**
   * Parse JWT to get expiration time
   */
  function getTokenExpiry(jwt: string): number | null {
    try {
      const payload = JSON.parse(atob(jwt.split('.')[1]))
      return payload.exp ? payload.exp * 1000 : null // Convert to ms
    } catch {
      return null
    }
  }

  /**
   * Schedule auto-refresh before token expires
   */
  function scheduleRefresh(): void {
    if (refreshTimer) {
      clearTimeout(refreshTimer)
      refreshTimer = null
    }

    if (!token.value) return

    const expiry = getTokenExpiry(token.value)
    if (!expiry) return

    const now = Date.now()
    const timeUntilRefresh = expiry - now - REFRESH_THRESHOLD_MS

    if (timeUntilRefresh <= 0) {
      // Token already expired or about to expire, refresh now
      doRefreshToken()
    } else {
      // Schedule refresh
      refreshTimer = setTimeout(() => {
        doRefreshToken()
      }, timeUntilRefresh)
      console.log(`Token refresh scheduled in ${Math.round(timeUntilRefresh / 1000 / 60)} minutes`)
    }
  }

  /**
   * Initialize auth state from localStorage
   */
  async function initAuth(): Promise<void> {
    loading.value = true
    try {
      const storedToken = localStorage.getItem('zylch_token')
      const storedRefreshToken = localStorage.getItem('zylch_refresh_token')

      if (storedRefreshToken) {
        refreshToken.value = storedRefreshToken
      }

      if (storedToken) {
        token.value = storedToken

        // Check if token is expired
        const expiry = getTokenExpiry(storedToken)
        if (expiry && expiry < Date.now()) {
          // Token expired, try to refresh
          if (refreshToken.value) {
            await doRefreshToken()
          } else {
            throw new Error('Token expired')
          }
        } else {
          // Verify token is still valid by fetching session
          await fetchSession()
          // Schedule auto-refresh
          scheduleRefresh()
        }
      }
    } catch (err) {
      // Token invalid, clear it
      token.value = null
      refreshToken.value = null
      user.value = null
      localStorage.removeItem('zylch_token')
      localStorage.removeItem('zylch_refresh_token')
    } finally {
      loading.value = false
    }
  }

  /**
   * Fetch current session from backend
   */
  async function fetchSession(): Promise<void> {
    if (!token.value) return

    const response = await axios.get(`${API_URL}/api/auth/session`, {
      headers: { Authorization: `Bearer ${token.value}` }
    })

    if (response.data.user) {
      user.value = {
        id: response.data.user.uid || response.data.user.id,
        email: response.data.user.email || '',
        name: response.data.user.display_name || response.data.user.name || '',
        picture: response.data.user.photo_url || response.data.user.picture,
        provider: response.data.user.provider || 'google'
      }
    }
  }

  /**
   * Redirect to backend OAuth login page (Google)
   */
  function loginWithGoogle(): void {
    const callbackUrl = `${window.location.origin}/auth/callback`
    window.location.href = `${API_URL}/api/auth/oauth/initiate?callback_url=${encodeURIComponent(callbackUrl)}&provider=google`
  }

  /**
   * Redirect to backend OAuth login page (Microsoft)
   */
  function loginWithMicrosoft(): void {
    const callbackUrl = `${window.location.origin}/auth/callback`
    window.location.href = `${API_URL}/api/auth/oauth/initiate?callback_url=${encodeURIComponent(callbackUrl)}&provider=microsoft`
  }

  /**
   * Handle OAuth callback - extract token from URL and store it
   */
  async function handleCallback(urlToken: string, urlRefreshToken?: string): Promise<boolean> {
    loading.value = true
    error.value = null

    try {
      token.value = urlToken
      localStorage.setItem('zylch_token', urlToken)

      // Store refresh token if provided
      if (urlRefreshToken) {
        refreshToken.value = urlRefreshToken
        localStorage.setItem('zylch_refresh_token', urlRefreshToken)
      }

      // Fetch user session
      await fetchSession()

      // Schedule auto-refresh
      scheduleRefresh()

      return true
    } catch (err: any) {
      error.value = err.message || 'Failed to complete authentication'
      token.value = null
      refreshToken.value = null
      localStorage.removeItem('zylch_token')
      localStorage.removeItem('zylch_refresh_token')
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * Logout user
   */
  async function logout(): Promise<void> {
    // Clear refresh timer
    if (refreshTimer) {
      clearTimeout(refreshTimer)
      refreshTimer = null
    }

    try {
      if (token.value) {
        await axios.post(`${API_URL}/api/auth/logout`, {}, {
          headers: { Authorization: `Bearer ${token.value}` }
        })
      }
    } catch (err) {
      // Ignore logout errors
    } finally {
      user.value = null
      token.value = null
      refreshToken.value = null
      localStorage.removeItem('zylch_token')
      localStorage.removeItem('zylch_refresh_token')
    }
  }

  /**
   * Refresh the ID token using Firebase refresh token
   */
  async function doRefreshToken(): Promise<string | null> {
    if (!refreshToken.value) {
      console.warn('No refresh token available')
      return null
    }

    try {
      // Call Firebase's token refresh endpoint
      const FIREBASE_API_KEY = import.meta.env.VITE_FIREBASE_API_KEY
      const response = await axios.post(
        `https://securetoken.googleapis.com/v1/token?key=${FIREBASE_API_KEY}`,
        {
          grant_type: 'refresh_token',
          refresh_token: refreshToken.value
        }
      )

      if (response.data.id_token) {
        token.value = response.data.id_token
        localStorage.setItem('zylch_token', response.data.id_token)

        // Update refresh token if a new one was provided
        if (response.data.refresh_token) {
          refreshToken.value = response.data.refresh_token
          localStorage.setItem('zylch_refresh_token', response.data.refresh_token)
        }

        // Schedule next refresh
        scheduleRefresh()

        console.log('Token refreshed successfully')
        return response.data.id_token
      }
      return null
    } catch (err: any) {
      console.error('Token refresh failed:', err)
      error.value = 'Session expired. Please login again.'
      // Clear invalid tokens
      token.value = null
      refreshToken.value = null
      user.value = null
      localStorage.removeItem('zylch_token')
      localStorage.removeItem('zylch_refresh_token')
      return null
    }
  }

  return {
    user,
    token,
    loading,
    error,
    isAuthenticated,
    isLoading,
    userName,
    initAuth,
    loginWithGoogle,
    loginWithMicrosoft,
    handleCallback,
    logout,
    refreshToken: doRefreshToken
  }
})
