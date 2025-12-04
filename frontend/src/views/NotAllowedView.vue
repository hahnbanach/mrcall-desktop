<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const authStore = useAuthStore()

// Get email from query params
const email = route.query.email as string || authStore.user?.email || 'your email'

const countdown = ref(10)

onMounted(() => {
  // Logout and redirect after 5 seconds
  const interval = setInterval(() => {
    countdown.value--
    if (countdown.value <= 0) {
      clearInterval(interval)
      authStore.logout()
      window.location.href = 'https://zylchai.com'
    }
  }, 1000)
})
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
        <div class="mb-6 text-4xl">
          😊
        </div>

        <h2 class="text-2xl font-semibold mb-4">Not in Alpha Program</h2>

        <p class="text-zylch-muted mb-2">
          The email <span class="font-medium text-zylch-primary">{{ email }}</span> is not on our alpha testers list.
        </p>

        <p class="text-zylch-muted mb-6">
          Zylch is currently in private alpha and you have not been accepted yet, sorry! Keep interacting with Zylch and it surely will put you in the list 😊
        </p>

        <p class="text-zylch-muted">
          Back to Zylch in {{ countdown }} seconds...
        </p>
      </div>
    </div>
  </div>
</template>
