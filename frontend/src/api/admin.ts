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

export async function getRecentRecords(limit = 50): Promise<AdminQARecord[]> {
  const { data } = await apiClient.get<AdminQARecord[]>('/admin/records', { params: { limit } })
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

export interface FeedbackStats {
  total_rated: number
  up_count: number
  down_count: number
  approval_rate: number
  recent_negatives: Array<{
    id: number
    user_id: string
    question: string
    comment: string | null
    created_at: string
  }>
}

export interface UsageReport {
  days: number
  total: number
  today: number
  refused_rate: number
  daily: Array<{ date: string; total: number; refused: number; human: number }>
  top_users: Array<{ user_id: string; count: number }>
  top_docs: Array<{ doc_name: string; cite_count: number }>
}

export async function getFeedbackStats(): Promise<FeedbackStats> {
  const { data } = await apiClient.get<FeedbackStats>('/admin/feedback-stats')
  return data
}

export async function getUsageReport(days = 7): Promise<UsageReport> {
  const { data } = await apiClient.get<UsageReport>('/admin/reports/usage', { params: { days } })
  return data
}
