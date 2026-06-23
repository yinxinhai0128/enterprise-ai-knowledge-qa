import { apiClient } from './client'
import type { AdminStats, AdminQARecord, HumanTaskOut } from '@/types/api'

export async function getStats(): Promise<AdminStats> {
  const { data } = await apiClient.get<AdminStats>('/admin/stats')
  return data
}

export async function getRefused(): Promise<AdminQARecord[]> {
  const { data } = await apiClient.get<AdminQARecord[]>('/admin/refused')
  return data
}

export async function getHumanTasks(status?: string): Promise<HumanTaskOut[]> {
  const { data } = await apiClient.get<HumanTaskOut[]>('/admin/human-tasks', {
    params: status ? { status } : undefined,
  })
  return data
}

export async function claimTask(id: number): Promise<HumanTaskOut> {
  const { data } = await apiClient.post<HumanTaskOut>(`/admin/human-tasks/${id}/claim`)
  return data
}

export async function completeTask(id: number, resolution: string): Promise<HumanTaskOut> {
  const { data } = await apiClient.post<HumanTaskOut>(`/admin/human-tasks/${id}/complete`, { resolution })
  return data
}
