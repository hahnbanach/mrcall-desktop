<script setup lang="ts">
import { ref } from 'vue'
import AppSidebar from './AppSidebar.vue'
import AppHeader from './AppHeader.vue'

const sidebarOpen = ref(true)

function toggleSidebar() {
  sidebarOpen.value = !sidebarOpen.value
}
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <AppSidebar :open="sidebarOpen" @toggle="toggleSidebar" />

    <div
      class="transition-all duration-300"
      :class="sidebarOpen ? 'lg:pl-64' : 'lg:pl-20'"
    >
      <AppHeader @toggle-sidebar="toggleSidebar" />

      <main class="py-6 px-4 sm:px-6 lg:px-8">
        <slot />
      </main>
    </div>
  </div>
</template>
