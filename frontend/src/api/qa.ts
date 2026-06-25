import { apiClient } from './client'
import { getToken, clearToken } from './auth'
import { navigateTo } from '@/lib/navigation'
import type { AskResponse, HistoryResponse, StreamDonePayload } from '@/types/api'

export async function askQuestion(question: string, sessionId: string): Promise<AskResponse> {
  const { data } = await apiClient.post<AskResponse>('/qa/ask', { question, session_id: sessionId })
  return data
}

export async function getHistory(sessionId: string): Promise<HistoryResponse> {
  const { data } = await apiClient.get<HistoryResponse>(`/qa/history/${sessionId}`)
  return data
}

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8765'

export interface StreamHandlers {
  onToken: (text: string) => void
  onDone: (payload: StreamDonePayload) => void
  onError: (err: Error) => void
  signal?: AbortSignal
}

// 解析单个 SSE 帧（多行 event:/data: ）；data 多行时按换行拼接。
function parseFrame(raw: string): { event: string; data: string } | null {
  let event = 'message'
  const dataLines: string[] = []
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).replace(/^ /, ''))
    }
  }
  if (dataLines.length === 0) return null
  return { event, data: dataLines.join('\n') }
}

/** 真流式提问：POST /qa/stream，逐帧解析 SSE 并回调。 */
export async function askQuestionStream(
  question: string,
  sessionId: string,
  handlers: StreamHandlers,
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}/qa/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${getToken() ?? ''}`,
      },
      body: JSON.stringify({ question, session_id: sessionId }),
      signal: handlers.signal,
    })
  } catch (err) {
    handlers.onError(err instanceof Error ? err : new Error('网络错误'))
    return
  }

  if (response.status === 401) {
    clearToken()
    navigateTo('/login')
    handlers.onError(new Error('登录已失效，请重新登录'))
    return
  }

  if (!response.ok || !response.body) {
    let detail = `请求失败（${response.status}）`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') detail = body.detail
      else if (typeof body?.detail?.message === 'string') detail = body.detail.message
    } catch {
      // 忽略非 JSON 错误体
    }
    handlers.onError(new Error(detail))
    return
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // 帧以空行分隔
      let sep: number
      while ((sep = buffer.indexOf('\n\n')) !== -1) {
        const rawFrame = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)
        const frame = parseFrame(rawFrame)
        if (!frame) continue
        if (frame.event === 'token') {
          try {
            const { text } = JSON.parse(frame.data) as { text: string }
            if (text) handlers.onToken(text)
          } catch {
            // 跳过无法解析的帧
          }
        } else if (frame.event === 'done') {
          try {
            handlers.onDone(JSON.parse(frame.data) as StreamDonePayload)
          } catch {
            handlers.onError(new Error('响应解析失败'))
          }
          return
        } else if (frame.event === 'error') {
          let detail = '问答服务暂不可用'
          try {
            const parsed = JSON.parse(frame.data) as { detail?: string }
            if (parsed?.detail) detail = parsed.detail
          } catch {
            // 保留默认文案
          }
          handlers.onError(new Error(detail))
          return
        }
      }
    }
  } catch (err) {
    handlers.onError(err instanceof Error ? err : new Error('流读取失败'))
  }
}
