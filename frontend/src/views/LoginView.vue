<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const isLoading = ref(false)
const error = ref<string | null>(null)

async function loginWithGoogle() {
  isLoading.value = true
  error.value = null
  try {
    await authStore.loginWithGoogle()
    const redirect = route.query.redirect as string || '/'
    router.push(redirect)
  } catch (err: any) {
    error.value = err.message || 'Failed to login'
  } finally {
    isLoading.value = false
  }
}

async function loginWithMicrosoft() {
  isLoading.value = true
  error.value = null
  try {
    await authStore.loginWithMicrosoft()
    const redirect = route.query.redirect as string || '/'
    router.push(redirect)
  } catch (err: any) {
    error.value = err.message || 'Failed to login'
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="min-h-screen flex flex-col items-center justify-center bg-white px-4">
    <!-- Logo -->
    <div class="mb-8">
      <img src="/logo/zylch-horizontal.svg" alt="Zylch" class="h-12" />
    </div>

    <!-- Tagline -->
    <p class="text-zylch-muted text-lg mb-8">
      Your AI assistant for business communication
    </p>

    <!-- Login Card -->
    <div class="w-full max-w-md">
      <div class="bg-white rounded-zylch shadow-zylch-lg p-8">
        <h2 class="text-2xl font-semibold text-center mb-6">Sign in to Zylch</h2>

        <!-- Error Message -->
        <div
          v-if="error"
          class="mb-4 p-4 bg-red-50 border border-red-200 rounded-zylch-sm text-red-600 text-sm"
        >
          {{ error }}
        </div>

        <!-- Login Buttons -->
        <div class="space-y-4">
          <button
            @click="loginWithGoogle"
            :disabled="isLoading"
            class="w-full flex items-center justify-center px-4 py-3 border border-gray-200 rounded-zylch-sm text-gray-700 font-medium hover:bg-gray-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <svg class="w-5 h-5 mr-3" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
            </svg>
            {{ isLoading ? 'Signing in...' : 'Continue with Google' }}
          </button>

          <button
            @click="loginWithMicrosoft"
            :disabled="isLoading"
            class="w-full flex items-center justify-center px-4 py-3 border border-gray-200 rounded-zylch-sm text-gray-700 font-medium hover:bg-gray-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <svg class="w-5 h-5 mr-3" viewBox="0 0 24 24">
              <path fill="#F25022" d="M1 1h10v10H1z"/>
              <path fill="#00A4EF" d="M1 13h10v10H1z"/>
              <path fill="#7FBA00" d="M13 1h10v10H13z"/>
              <path fill="#FFB900" d="M13 13h10v10H13z"/>
            </svg>
            {{ isLoading ? 'Signing in...' : 'Continue with Microsoft' }}
          </button>
        </div>

        <!-- Privacy Note -->
        <p class="mt-6 text-center text-sm text-zylch-muted">
          By signing in, you agree to our
          <a href="/privacy" class="text-zylch-accent hover:underline">Privacy Policy</a>
          and
          <a href="/terms" class="text-zylch-accent hover:underline">Terms of Service</a>
        </p>
      </div>
    </div>

    <!-- Footer -->
    <footer class="mt-8 text-sm text-zylch-muted">
      <a href="https://zylch.ai" class="hover:text-zylch-primary">Learn more about Zylch</a>
    </footer>
  </div>
</template>
