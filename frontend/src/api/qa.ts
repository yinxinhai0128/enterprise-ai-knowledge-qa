import { apiClient } from './client'
import type { AskResponse, HistoryResponse } from '@/types/api'

export async function askQuestion(question: string, sessionId: string): Promise<AskResponse> {
  const { data } = await apiClient.post<AskResponse>('/qa/ask', { question, session_id: sessionId })
  return data
}

export async function getHistory(sessionId: string): Promise<HistoryResponse> {
  const { data } = await apiClient.get<HistoryResponse>(`/qa/history/${sessionId}`)
  return data
}
