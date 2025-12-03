<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useTasksStore } from '@/stores/tasks'
import type { Task } from '@/types'

const tasksStore = useTasksStore()
const showCreateModal = ref(false)
const newTask = ref({
  title: '',
  description: '',
  priority: 'medium' as 'low' | 'medium' | 'high',
  person: '',
  dueDate: ''
})

onMounted(() => {
  tasksStore.fetchTasks()
})

async function createTask() {
  const task = await tasksStore.createTask({
    ...newTask.value,
    status: 'pending'
  })
  if (task) {
    showCreateModal.value = false
    newTask.value = { title: '', description: '', priority: 'medium', person: '', dueDate: '' }
  }
}

async function toggleComplete(task: Task) {
  if (task.status === 'completed') {
    await tasksStore.updateTask(task.id, { status: 'pending', completedAt: undefined })
  } else {
    await tasksStore.completeTask(task.id)
  }
}

function formatDueDate(date: string) {
  const d = new Date(date)
  const now = new Date()
  const diff = d.getTime() - now.getTime()
  const days = Math.ceil(diff / (1000 * 60 * 60 * 24))

  if (days < 0) return `${Math.abs(days)} days overdue`
  if (days === 0) return 'Due today'
  if (days === 1) return 'Due tomorrow'
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

const priorityColors = {
  high: 'text-red-600 bg-red-50',
  medium: 'text-yellow-600 bg-yellow-50',
  low: 'text-green-600 bg-green-50'
}

const statusFilters = [
  { value: 'all', label: 'All' },
  { value: 'pending', label: 'Pending' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'completed', label: 'Completed' }
] as const
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex-shrink-0 p-4 border-b border-gray-200">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-semibold text-gray-900">Tasks</h1>
          <p class="text-sm text-gray-500">
            {{ tasksStore.pendingTasks.length }} pending, {{ tasksStore.overdueTasks.length }} overdue
          </p>
        </div>
        <button
          @click="showCreateModal = true"
          class="px-4 py-2 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors"
        >
          New Task
        </button>
      </div>

      <!-- Filters -->
      <div class="mt-4 flex gap-2 flex-wrap">
        <button
          v-for="filter in statusFilters"
          :key="filter.value"
          @click="tasksStore.setFilterStatus(filter.value)"
          :class="[
            'px-3 py-1 text-sm rounded-full transition-colors',
            tasksStore.filterStatus === filter.value
              ? 'bg-accent text-white'
              : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          ]"
        >
          {{ filter.label }}
        </button>
      </div>
    </div>

    <!-- Task List -->
    <div class="flex-1 overflow-y-auto p-4">
      <div v-if="tasksStore.loading" class="flex items-center justify-center h-32">
        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-accent"></div>
      </div>

      <div v-else-if="tasksStore.filteredTasks.length === 0" class="text-center py-12">
        <div class="w-16 h-16 mx-auto mb-4 bg-gray-100 rounded-full flex items-center justify-center">
          <svg class="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
          </svg>
        </div>
        <p class="text-gray-500">No tasks found</p>
      </div>

      <div v-else class="space-y-3">
        <div
          v-for="task in tasksStore.filteredTasks"
          :key="task.id"
          class="bg-white border border-gray-200 rounded-xl p-4 hover:shadow-md transition-shadow"
        >
          <div class="flex items-start gap-3">
            <button
              @click="toggleComplete(task)"
              :class="[
                'flex-shrink-0 w-6 h-6 rounded-full border-2 flex items-center justify-center transition-colors',
                task.status === 'completed'
                  ? 'bg-accent border-accent'
                  : 'border-gray-300 hover:border-accent'
              ]"
            >
              <svg
                v-if="task.status === 'completed'"
                class="w-4 h-4 text-white"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
              </svg>
            </button>
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-1">
                <h3
                  :class="[
                    'font-medium',
                    task.status === 'completed' ? 'text-gray-400 line-through' : 'text-gray-900'
                  ]"
                >
                  {{ task.title }}
                </h3>
                <span
                  :class="['text-xs px-2 py-0.5 rounded-full', priorityColors[task.priority]]"
                >
                  {{ task.priority }}
                </span>
              </div>
              <p v-if="task.description" class="text-sm text-gray-500 mb-2">
                {{ task.description }}
              </p>
              <div class="flex items-center gap-4 text-sm text-gray-500">
                <span v-if="task.person" class="flex items-center gap-1">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
                  </svg>
                  {{ task.person }}
                </span>
                <span
                  v-if="task.dueDate"
                  :class="[
                    'flex items-center gap-1',
                    new Date(task.dueDate) < new Date() && task.status !== 'completed' ? 'text-red-600' : ''
                  ]"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
                  </svg>
                  {{ formatDueDate(task.dueDate) }}
                </span>
              </div>
            </div>
            <button
              @click="tasksStore.deleteTask(task.id)"
              class="flex-shrink-0 text-gray-400 hover:text-red-600 transition-colors"
            >
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Create Modal -->
    <Teleport to="body">
      <div v-if="showCreateModal" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/50" @click="showCreateModal = false"></div>
        <div class="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4">
          <div class="p-4 border-b border-gray-200">
            <h2 class="text-lg font-semibold">New Task</h2>
          </div>
          <div class="p-4 space-y-4">
            <input
              v-model="newTask.title"
              type="text"
              placeholder="Task title"
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
            />
            <textarea
              v-model="newTask.description"
              rows="3"
              placeholder="Description (optional)"
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50 resize-none"
            />
            <input
              v-model="newTask.person"
              type="text"
              placeholder="Assign to person (optional)"
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
            />
            <div class="flex gap-4">
              <div class="flex-1">
                <label class="block text-sm text-gray-600 mb-1">Priority</label>
                <select
                  v-model="newTask.priority"
                  class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
                >
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
              </div>
              <div class="flex-1">
                <label class="block text-sm text-gray-600 mb-1">Due date</label>
                <input
                  v-model="newTask.dueDate"
                  type="date"
                  class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent/50"
                />
              </div>
            </div>
          </div>
          <div class="p-4 border-t border-gray-200 flex justify-end gap-3">
            <button
              @click="showCreateModal = false"
              class="px-4 py-2 text-gray-600 hover:text-gray-900 transition-colors"
            >
              Cancel
            </button>
            <button
              @click="createTask"
              :disabled="!newTask.title || tasksStore.loading"
              class="px-6 py-2 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors disabled:opacity-50"
            >
              Create
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
