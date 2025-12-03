<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    // Get token from URL query params (backend redirects with ?token=xxx)
    const token = route.query.token as string
    const errorParam = route.query.error as string

    if (errorParam) {
      error.value = errorParam
      return
    }

    if (!token) {
      error.value = 'No authentication token received'
      return
    }

    // Handle the callback with the token
    const success = await authStore.handleCallback(token)

    if (success) {
      // Get redirect URL from query or default to dashboard
      const redirect = route.query.redirect as string || '/'
      router.push(redirect)
    } else {
      error.value = authStore.error || 'Authentication failed'
    }
  } catch (err: any) {
    error.value = err.message || 'Authentication failed'
  }
})
</script>

<template>
  <div class="min-h-screen flex flex-col items-center justify-center bg-white">
    <div v-if="!error" class="text-center">
      <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-zylch-accent mx-auto mb-4"></div>
      <p class="text-zylch-muted">Completing sign in...</p>
    </div>

    <div v-else class="text-center">
      <div class="text-red-500 mb-4">
        <svg class="h-12 w-12 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
      </div>
      <p class="text-red-600 mb-4">{{ error }}</p>
      <router-link to="/login" class="text-zylch-accent hover:underline">
        Back to Login
      </router-link>
    </div>
  </div>
</template>
