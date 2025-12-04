<script setup lang="ts">
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const authStore = useAuthStore()

// Get email from query params
const email = route.query.email as string || authStore.user?.email || 'your email'

async function logout() {
  await authStore.logout()
}
</script>

<template>
  <div class="min-h-screen flex flex-col items-center justify-center bg-white px-4">
    <!-- Logo -->
    <div class="mb-8">
      <img src="/logo/zylch-horizontal.svg" alt="Zylch" class="h-12" />
    </div>

    <!-- Not Allowed Card -->
    <div class="w-full max-w-md">
      <div class="bg-white rounded-zylch shadow-zylch-lg p-8 text-center">
        <!-- Icon -->
        <div class="mb-6">
          <svg class="h-16 w-16 mx-auto text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
        </div>

        <h2 class="text-2xl font-semibold mb-4">Not in Alpha Program</h2>

        <p class="text-zylch-muted mb-2">
          The email <span class="font-medium text-zylch-primary">{{ email }}</span> is not on our alpha testers list.
        </p>

        <p class="text-zylch-muted mb-6">
          Zylch is currently in private alpha. If you'd like to join, please contact us to request access.
        </p>

        <!-- Actions -->
        <div class="space-y-3">
          <a
            href="mailto:alpha@zylch.ai?subject=Alpha%20Access%20Request"
            class="block w-full px-4 py-3 bg-zylch-accent text-white rounded-zylch-sm font-medium hover:bg-zylch-accent/90 transition-colors"
          >
            Request Alpha Access
          </a>

          <button
            @click="logout"
            class="w-full px-4 py-3 border border-gray-200 rounded-zylch-sm text-gray-700 font-medium hover:bg-gray-50 transition-colors"
          >
            Sign in with Different Account
          </button>
        </div>
      </div>
    </div>

    <!-- Footer -->
    <footer class="mt-8 text-sm text-zylch-muted">
      <a href="https://zylch.ai" class="hover:text-zylch-primary">Learn more about Zylch</a>
    </footer>
  </div>
</template>
