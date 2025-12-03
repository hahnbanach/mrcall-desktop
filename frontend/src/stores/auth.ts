import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import type { User } from '@/types'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const token = ref<string | null>(null)
  const loading = ref(true)
  const error = ref<string | null>(null)

  const isAuthenticated = computed(() => !!user.value && !!token.value)
  const userName = computed(() => user.value?.name || 'User')
  const isLoading = computed(() => loading.value)

  /**
   * Initialize auth state from localStorage
   */
  async function initAuth(): Promise<void> {
    loading.value = true
    try {
      const storedToken = localStorage.getItem('zylch_token')
      if (storedToken) {
        token.value = storedToken
        // Verify token is still valid by fetching session
        await fetchSession()
      }
    } catch (err) {
      // Token invalid, clear it
      token.value = null
      user.value = null
      localStorage.removeItem('zylch_token')
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
  async function handleCallback(urlToken: string): Promise<boolean> {
    loading.value = true
    error.value = null

    try {
      token.value = urlToken
      localStorage.setItem('zylch_token', urlToken)

      // Fetch user session
      await fetchSession()
      return true
    } catch (err: any) {
      error.value = err.message || 'Failed to complete authentication'
      token.value = null
      localStorage.removeItem('zylch_token')
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * Logout user
   */
  async function logout(): Promise<void> {
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
      localStorage.removeItem('zylch_token')
    }
  }

  /**
   * Refresh token
   */
  async function refreshToken(): Promise<string | null> {
    if (!token.value) return null

    try {
      const response = await axios.post(`${API_URL}/api/auth/refresh`, {}, {
        headers: { Authorization: `Bearer ${token.value}` }
      })

      if (response.data.token) {
        token.value = response.data.token
        localStorage.setItem('zylch_token', response.data.token)
        return response.data.token
      }
      return token.value
    } catch (err: any) {
      error.value = err.message || 'Failed to refresh token'
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
    refreshToken
  }
})
