import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { mrcallService } from '@/services/api'
import type { MrCallAssistant, MrCallTrainingStatus } from '@/types'

export const useMrCallStore = defineStore('mrcall', () => {
  // State
  const assistants = ref<MrCallAssistant[]>([])
  const linkedAssistant = ref<MrCallAssistant | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  // Training state
  const trainingStatus = ref<MrCallTrainingStatus | null>(null)
  const isTrainingLoading = ref(false)
  const trainingError = ref<string | null>(null)
  const trainingJobId = ref<string | null>(null)
  let trainingPollInterval: ReturnType<typeof setInterval> | null = null

  // Getters
  const activeAssistants = computed(() => assistants.value.filter(a => a.status === 'active'))
  const isLinked = computed(() => !!linkedAssistant.value)

  // Actions
  async function fetchAssistants(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      assistants.value = await mrcallService.getAssistants()
      linkedAssistant.value = assistants.value.find(a => a.linkedZylchAssistant) || null
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch MrCall assistants'
    } finally {
      isLoading.value = false
    }
  }

  async function linkAssistant(mrcallId: string): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      await mrcallService.linkAssistant(mrcallId)
      await fetchAssistants()
    } catch (err: any) {
      error.value = err.message || 'Failed to link MrCall assistant'
      throw err
    } finally {
      isLoading.value = false
    }
  }

  async function unlinkAssistant(): Promise<void> {
    isLoading.value = true
    error.value = null
    try {
      await mrcallService.unlinkAssistant()
      linkedAssistant.value = null
      await fetchAssistants()
    } catch (err: any) {
      error.value = err.message || 'Failed to unlink MrCall assistant'
      throw err
    } finally {
      isLoading.value = false
    }
  }

  async function fetchTrainingStatus(): Promise<void> {
    isTrainingLoading.value = true
    trainingError.value = null
    try {
      trainingStatus.value = await mrcallService.getTrainingStatus()
    } catch (err: any) {
      // 400 means not linked — not an error for the user
      if (err.response?.status === 400) {
        trainingStatus.value = null
      } else {
        trainingError.value = err.response?.data?.detail || err.message || 'Failed to fetch training status'
      }
    } finally {
      isTrainingLoading.value = false
    }
  }

  async function startTraining(options?: { force?: boolean; features?: string[] }): Promise<void> {
    trainingError.value = null
    try {
      const response = await mrcallService.startTraining(options)
      trainingJobId.value = response.job_id

      // Update status to in_progress immediately
      if (trainingStatus.value) {
        trainingStatus.value = {
          ...trainingStatus.value,
          status: 'in_progress',
          job_id: response.job_id,
          job_progress_pct: 0,
        }
      }

      // Start polling for job completion
      if (response.job_id) {
        _startPolling(response.job_id)
      }
    } catch (err: any) {
      if (err.response?.status === 409) {
        // Already in progress — start polling
        const existingJobId = err.response?.data?.detail?.match(/job ([a-f0-9-]+)/)?.[1]
        if (existingJobId) {
          _startPolling(existingJobId)
        }
      } else {
        trainingError.value = err.response?.data?.detail || err.message || 'Failed to start training'
      }
    }
  }

  function _startPolling(jobId: string) {
    _stopPolling()
    trainingPollInterval = setInterval(async () => {
      try {
        const job = await mrcallService.getJobStatus(jobId)

        if (trainingStatus.value) {
          trainingStatus.value.job_progress_pct = job.progress_pct
        }

        if (job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled') {
          _stopPolling()
          trainingJobId.value = null

          if (job.status === 'failed') {
            trainingError.value = job.last_error || 'Training failed'
          }

          // Refresh the actual training status
          await fetchTrainingStatus()
        }
      } catch {
        // Polling error — ignore, will retry
      }
    }, 3000)
  }

  function _stopPolling() {
    if (trainingPollInterval) {
      clearInterval(trainingPollInterval)
      trainingPollInterval = null
    }
  }

  function clearError(): void {
    error.value = null
    trainingError.value = null
  }

  return {
    // State
    assistants,
    linkedAssistant,
    isLoading,
    error,
    trainingStatus,
    isTrainingLoading,
    trainingError,
    trainingJobId,
    // Getters
    activeAssistants,
    isLinked,
    // Actions
    fetchAssistants,
    linkAssistant,
    unlinkAssistant,
    fetchTrainingStatus,
    startTraining,
    clearError,
  }
})
