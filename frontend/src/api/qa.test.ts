import { describe, it, expect, vi, beforeEach } from 'vitest'
import { parseFrame, askQuestionStream } from './qa'
import { saveToken } from './auth'
import type { StreamDonePayload } from '@/types/api'

vi.mock('@/lib/navigation', () => ({ navigateTo: vi.fn() }))
import { navigateTo } from '@/lib/navigation'

// 用 chunk 文本构造一个 Response 替身：body.getReader().read() 逐块吐字节。
function mockResponse(opts: {
  status?: number
  chunks?: string[]
  jsonBody?: unknown
}): Response {
  const { status = 200, chunks = [], jsonBody } = opts
  const encoder = new TextEncoder()
  const queue = chunks.map((c) => encoder.encode(c))
  let i = 0
  return {
    status,
    ok: status >= 200 && status < 300,
    body: chunks.length
      ? {
          getReader() {
            return {
              read: async () =>
                i < queue.length
                  ? { done: false, value: queue[i++] }
                  : { done: true, value: undefined },
            }
          },
        }
      : null,
    json: async () => jsonBody,
  } as unknown as Response
}

describe('parseFrame', () => {
  it('解析 event + data', () => {
    expect(parseFrame('event: token\ndata: {"text":"hi"}')).toEqual({
      event: 'token',
      data: '{"text":"hi"}',
    })
  })

  it('data 多行按换行拼接', () => {
    expect(parseFrame('event: done\ndata: line1\ndata: line2')).toEqual({
      event: 'done',
      data: 'line1\nline2',
    })
  })

  it('无 data 行返回 null', () => {
    expect(parseFrame('event: ping')).toBeNull()
  })

  it('缺省 event 名为 message', () => {
    expect(parseFrame('data: hello')).toEqual({ event: 'message', data: 'hello' })
  })
})

describe('askQuestionStream', () => {
  beforeEach(() => {
    localStorage.clear()
    saveToken('h.payload.sig')
    vi.stubGlobal('fetch', vi.fn())
  })

  it('happy path：逐 token 回调，done 带结构化来源', async () => {
    const sse =
      'event: token\ndata: {"text":"根据"}\n\n' +
      'event: token\ndata: {"text":"知识库"}\n\n' +
      'event: done\ndata: {"answer":"根据知识库……","sources":[{"source":"a.txt","relevance":0.71}],"refused":false,"need_human":false,"human_task_id":null}\n\n'
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue(mockResponse({ chunks: [sse] }))

    const tokens: string[] = []
    let done: StreamDonePayload | undefined
    const onError = vi.fn()
    await askQuestionStream('q', 'sess1', {
      onToken: (t) => tokens.push(t),
      onDone: (p) => { done = p },
      onError,
    })

    expect(tokens).toEqual(['根据', '知识库'])
    expect(done?.refused).toBe(false)
    expect(done?.sources).toHaveLength(1)
    expect(done?.sources[0].source).toBe('a.txt')
    expect(onError).not.toHaveBeenCalled()
  })

  it('跨 chunk 切断的帧也能正确拼接解析', async () => {
    // 把一个 token 帧从中间劈成两块投喂
    const chunks = [
      'event: token\ndata: {"text":"上', // 半个帧
      '半"}\n\nevent: done\ndata: {"answer":"x","sources":[],"refused":true,"need_human":false,"human_task_id":null}\n\n',
    ]
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue(mockResponse({ chunks }))

    const tokens: string[] = []
    let done: StreamDonePayload | undefined
    await askQuestionStream('q', 'sess1', {
      onToken: (t) => tokens.push(t),
      onDone: (p) => { done = p },
      onError: vi.fn(),
    })

    expect(tokens).toEqual(['上半'])
    expect(done?.refused).toBe(true)
  })

  it('error 事件 → onError 带后端 detail', async () => {
    const sse = 'event: error\ndata: {"detail":"审计写入失败，请稍后重试","error_code":"audit_write_failed"}\n\n'
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue(mockResponse({ chunks: [sse] }))

    const onError = vi.fn()
    const onDone = vi.fn()
    await askQuestionStream('q', 'sess1', { onToken: vi.fn(), onDone, onError })

    expect(onDone).not.toHaveBeenCalled()
    expect(onError).toHaveBeenCalledOnce()
    expect(onError.mock.calls[0][0].message).toBe('审计写入失败，请稍后重试')
  })

  it('401 → 清 token、跳登录、回调 onError', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue(mockResponse({ status: 401 }))

    const onError = vi.fn()
    await askQuestionStream('q', 'sess1', { onToken: vi.fn(), onDone: vi.fn(), onError })

    expect(localStorage.getItem('ekqa_token')).toBeNull()
    expect(navigateTo).toHaveBeenCalledWith('/login')
    expect(onError).toHaveBeenCalledOnce()
  })

  it('非 2xx 错误体 → onError 提取 detail', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockResponse({ status: 500, jsonBody: { detail: '问答服务暂不可用' } }),
    )

    const onError = vi.fn()
    await askQuestionStream('q', 'sess1', { onToken: vi.fn(), onDone: vi.fn(), onError })

    expect(onError.mock.calls[0][0].message).toBe('问答服务暂不可用')
  })

  it('fetch 抛错（网络错误）→ onError', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('boom'))

    const onError = vi.fn()
    await askQuestionStream('q', 'sess1', { onToken: vi.fn(), onDone: vi.fn(), onError })

    expect(onError).toHaveBeenCalledOnce()
  })
})
