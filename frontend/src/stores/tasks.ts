import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Task } from '@/types'
import { tasksApi } from '@/services/api/tasks'

export const useTasksStore = defineStore('tasks', () => {
  const tasks = ref<Task[]>([])
  const currentTask = ref<Task | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const filterPerson = ref<string | null>(null)
  const filterStatus = ref<'all' | 'pending' | 'in_progress' | 'completed'>('all')

  const pendingTasks = computed(() =>
    tasks.value.filter(t => t.status === 'pending')
  )

  const inProgressTasks = computed(() =>
    tasks.value.filter(t => t.status === 'in_progress')
  )

  const completedTasks = computed(() =>
    tasks.value.filter(t => t.status === 'completed')
  )

  const tasksByPerson = computed(() => {
    const grouped: Record<string, Task[]> = {}
    tasks.value.forEach(task => {
      if (task.person) {
        if (!grouped[task.person]) grouped[task.person] = []
        grouped[task.person].push(task)
      }
    })
    return grouped
  })

  const filteredTasks = computed(() => {
    let result = tasks.value

    if (filterPerson.value) {
      result = result.filter(t => t.person === filterPerson.value)
    }

    if (filterStatus.value !== 'all') {
      result = result.filter(t => t.status === filterStatus.value)
    }

    return result.sort((a, b) => {
      // Sort by priority then by due date
      const priorityOrder = { high: 0, medium: 1, low: 2 }
      const priorityDiff = priorityOrder[a.priority] - priorityOrder[b.priority]
      if (priorityDiff !== 0) return priorityDiff

      if (a.dueDate && b.dueDate) {
        return new Date(a.dueDate).getTime() - new Date(b.dueDate).getTime()
      }
      if (a.dueDate) return -1
      if (b.dueDate) return 1
      return 0
    })
  })

  const overdueTasks = computed(() => {
    const now = new Date()
    return tasks.value.filter(t => {
      if (!t.dueDate || t.status === 'completed') return false
      return new Date(t.dueDate) < now
    })
  })

  async function fetchTasks() {
    loading.value = true
    error.value = null
    try {
      const data = await tasksApi.getTasks()
      tasks.value = data
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch tasks'
    } finally {
      loading.value = false
    }
  }

  async function createTask(task: Partial<Task>) {
    loading.value = true
    error.value = null
    try {
      const created = await tasksApi.createTask(task)
      tasks.value.push(created)
      return created
    } catch (err: any) {
      error.value = err.message || 'Failed to create task'
      return null
    } finally {
      loading.value = false
    }
  }

  async function updateTask(taskId: string, updates: Partial<Task>) {
    loading.value = true
    error.value = null
    try {
      const updated = await tasksApi.updateTask(taskId, updates)
      const idx = tasks.value.findIndex(t => t.id === taskId)
      if (idx >= 0) tasks.value[idx] = updated
      if (currentTask.value?.id === taskId) currentTask.value = updated
      return updated
    } catch (err: any) {
      error.value = err.message || 'Failed to update task'
      return null
    } finally {
      loading.value = false
    }
  }

  async function deleteTask(taskId: string) {
    loading.value = true
    error.value = null
    try {
      await tasksApi.deleteTask(taskId)
      tasks.value = tasks.value.filter(t => t.id !== taskId)
      if (currentTask.value?.id === taskId) currentTask.value = null
      return true
    } catch (err: any) {
      error.value = err.message || 'Failed to delete task'
      return false
    } finally {
      loading.value = false
    }
  }

  async function completeTask(taskId: string) {
    return updateTask(taskId, { status: 'completed', completedAt: new Date().toISOString() })
  }

  function setFilterPerson(person: string | null) {
    filterPerson.value = person
  }

  function setFilterStatus(status: 'all' | 'pending' | 'in_progress' | 'completed') {
    filterStatus.value = status
  }

  function selectTask(task: Task | null) {
    currentTask.value = task
  }

  return {
    tasks,
    currentTask,
    loading,
    error,
    filterPerson,
    filterStatus,
    pendingTasks,
    inProgressTasks,
    completedTasks,
    tasksByPerson,
    filteredTasks,
    overdueTasks,
    fetchTasks,
    createTask,
    updateTask,
    deleteTask,
    completeTask,
    setFilterPerson,
    setFilterStatus,
    selectTask
  }
})
