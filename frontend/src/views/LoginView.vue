<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const isLoading = ref(false)
const error = ref<string | null>(null)

async function signIn() {
  isLoading.value = true
  error.value = null
  try {
    // Default to Google, but Firebase will show provider selection
    await authStore.loginWithGoogle()
    const redirect = route.query.redirect as string || '/'
    router.push(redirect)
  } catch (err: any) {
    error.value = err.message || 'Failed to sign in'
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="min-h-screen flex flex-col items-center justify-center bg-gradient-to-b from-white to-gray-50 px-4">
    <!-- Logo -->
    <div class="mb-6">
      <img src="/logo/zylch-horizontal.svg" alt="Zylch" class="h-16" />
    </div>

    <!-- Tagline -->
    <p class="text-gray-500 text-lg mb-12 text-center max-w-md">
      Your AI-powered email assistant for smarter business communication
    </p>

    <!-- Error Message -->
    <div
      v-if="error"
      class="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-600 text-sm max-w-sm w-full text-center"
    >
      {{ error }}
    </div>

    <!-- Single Sign In Button -->
    <button
      @click="signIn"
      :disabled="isLoading"
      class="px-8 py-4 bg-accent text-white font-semibold rounded-xl shadow-lg hover:bg-accent/90 hover:shadow-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed text-lg"
    >
      {{ isLoading ? 'Signing in...' : 'Sign in to Zylch' }}
    </button>

    <!-- Privacy Note -->
    <p class="mt-8 text-center text-sm text-gray-400 max-w-xs">
      By signing in, you agree to our
      <a href="/privacy" class="text-accent hover:underline">Privacy Policy</a>
      and
      <a href="/terms" class="text-accent hover:underline">Terms of Service</a>
    </p>

    <!-- Footer -->
    <footer class="absolute bottom-8 text-sm text-gray-400">
      <a href="https://zylch.ai" class="hover:text-gray-600">Learn more about Zylch</a>
    </footer>
  </div>
</template>
