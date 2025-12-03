import api from './index'
import type { Task } from '@/types'

export const taskService = {
  async getTasks(): Promise<Task[]> {
    const { data } = await api.get('/api/tasks')
    return data
  },

  async getTask(contactEmail: string): Promise<Task> {
    const { data } = await api.get(`/api/tasks/${encodeURIComponent(contactEmail)}`)
    return data
  },

  async createTask(task: Partial<Task>): Promise<Task> {
    const { data } = await api.post('/api/tasks', task)
    return data
  },

  async updateTask(id: string, updates: Partial<Task>): Promise<Task> {
    const { data } = await api.patch(`/api/tasks/${id}`, updates)
    return data
  },

  async deleteTask(id: string): Promise<void> {
    await api.delete(`/api/tasks/${id}`)
  },

  async updateTaskStatus(contactEmail: string, status: Task['status']): Promise<Task> {
    const { data } = await api.patch(`/api/tasks/${encodeURIComponent(contactEmail)}`, { status })
    return data
  },

  async rebuildTasks(forceRebuild = false): Promise<Task[]> {
    const { data } = await api.post('/api/tasks/rebuild', { force_rebuild: forceRebuild })
    return data
  }
}

// Alias for stores that use tasksApi
export const tasksApi = taskService
