import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Send, Square, Plus, ChevronDown, ChevronUp, FileText, AlertTriangle, UserCheck, Bot, RefreshCw, Menu, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Progress } from '@/components/ui/progress'
import { NavBar } from '@/components/NavBar'
import { SimpleMarkdown } from '@/components/SimpleMarkdown'
import { stripCitationBlock } from '@/lib/answer'
import { askQuestionStream, getHistory } from '@/api/qa'
import type { AskResponse, SourceItem } from '@/types/api'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

// Session storage
interface Session {
  id: string
  firstQuestion: string
  createdAt: string
}

function getSessions(): Session[] {
  try { return JSON.parse(localStorage.getItem('ekqa_sessions') ?? '[]') } catch { return [] }
}

function saveSessions(sessions: Session[]) {
  localStorage.setItem('ekqa_sessions', JSON.stringify(sessions.slice(0, 50)))
}

function newSessionId(): string {
  return `sess_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`
}

// Typewriter hook
function useTypewriter(text: string, enabled: boolean) {
  const [displayed, setDisplayed] = useState('')
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (!enabled || !text) { setDisplayed(text); setDone(true); return }
    setDisplayed('')
    setDone(false)
    let i = 0
    const speed = text.length > 500 ? 10 : 20
    const step = text.length > 500 ? 4 : 2
    const id = setInterval(() => {
      i = Math.min(i + step, text.length)
      setDisplayed(text.slice(0, i))
      if (i >= text.length) { clearInterval(id); setDone(true) }
    }, speed)
    return () => clearInterval(id)
  }, [text, enabled])

  return { displayed, done }
}

// Source card
function SourceCard({ sources }: { sources: SourceItem[] }) {
  const [open, setOpen] = useState(false)
  if (!sources.length) return null
  return (
    <div className="mt-2 border border-gray-100 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs text-gray-500 hover:bg-gray-50 transition-colors"
      >
        <span className="flex items-center gap-1.5">
          <FileText className="w-3.5 h-3.5" />
          {sources.length} 个参考来源
        </span>
        {open ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
      </button>
      {open && (
        <div className="border-t border-gray-100 divide-y divide-gray-50">
          {sources.map((s, i) => (
            <div key={i} className="px-3 py-2">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium text-gray-700 truncate max-w-[200px]" title={s.source}>
                  {s.source}
                </span>
                {s.page != null && (
                  <span className="text-xs text-gray-400 ml-2 shrink-0">第 {s.page} 页</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <Progress value={Math.round(s.relevance * 100)} className="h-1 flex-1" />
                <span className="text-xs text-gray-400 shrink-0">{Math.round(s.relevance * 100)}%</span>
              </div>
              {s.snippet && (
                <p className="mt-1.5 text-xs text-gray-500 italic line-clamp-2 leading-relaxed">
                  「{s.snippet}」
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// Message bubble
interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  response?: AskResponse
  error?: boolean
  isNew?: boolean
  // 流式消息：内容逐字到达，不走打字机；streaming=true 表示尚未收到 done。
  streaming?: boolean
}

function AssistantBubble({ msg, onRetry }: { msg: Message; onRetry?: () => void }) {
  // 流式消息内容本身就是逐字到达的，禁用打字机；done 取决于是否已收到 response。
  const isStream = msg.isNew === true && (msg.streaming === true || msg.response !== undefined)
  const typewriter = useTypewriter(msg.content, msg.isNew === true && !isStream)
  const displayed = isStream ? msg.content : typewriter.displayed
  const done = isStream ? msg.streaming !== true : typewriter.done

  return (
    <div className="flex gap-3 max-w-[85%]">
      <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-1"
        style={{ backgroundColor: '#3B4FCC' }}>
        <Bot className="w-4 h-4 text-white" />
      </div>
      <div className="flex-1">
        <div className={`rounded-2xl rounded-tl-sm border px-4 py-3 text-sm leading-relaxed ${
          msg.error ? 'border-red-200 bg-red-50 text-red-700' : 'border-gray-100 bg-white text-gray-800'
        }`}>
          {msg.error ? (
            <div className="flex items-center gap-2">
              <span>{msg.content}</span>
              {onRetry && (
                <button onClick={onRetry} className="flex items-center gap-1 text-xs text-red-500 hover:text-red-700">
                  <RefreshCw className="w-3 h-3" /> 重试
                </button>
              )}
            </div>
          ) : (
            <span>
              <SimpleMarkdown text={displayed} />
              {msg.streaming && (
                <span className="inline-block w-0.5 h-4 bg-gray-400 animate-pulse ml-0.5 align-middle rounded-sm" />
              )}
            </span>
          )}
        </div>
        {done && msg.response && !msg.error && (
          <div className="mt-1 animate-fade-in">
            {msg.response.refused && (
              <div className="flex items-center gap-1.5 text-xs text-orange-600 mt-1">
                <AlertTriangle className="w-3.5 h-3.5" />
                未在知识库中找到相关资料
              </div>
            )}
            {msg.response.need_human && (
              <div className="flex items-center gap-1.5 text-xs text-yellow-600 mt-1">
                <UserCheck className="w-3.5 h-3.5" />
                已转交人工处理{msg.response.human_task_id ? ` #${msg.response.human_task_id}` : ''}
              </div>
            )}
            {msg.response.sources.length > 0 && <SourceCard sources={msg.response.sources} />}
          </div>
        )}
      </div>
    </div>
  )
}

function LoadingBubble() {
  return (
    <div className="flex gap-3 max-w-[85%]">
      <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0"
        style={{ backgroundColor: '#3B4FCC' }}>
        <Bot className="w-4 h-4 text-white" />
      </div>
      <div className="border border-gray-100 bg-white rounded-2xl rounded-tl-sm px-4 py-3">
        <div className="flex gap-1 items-center h-5">
          {[0, 1, 2].map(i => (
            <span key={i} className="w-1.5 h-1.5 rounded-full bg-gray-300 animate-bounce"
              style={{ animationDelay: `${i * 0.15}s` }} />
          ))}
        </div>
      </div>
    </div>
  )
}

export default function ChatPage() {
  const [sessions, setSessions] = useState<Session[]>(getSessions)
  const [currentSessionId, setCurrentSessionId] = useState<string>(() => {
    const s = getSessions()
    return s.length > 0 ? s[0].id : newSessionId()
  })
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  // 记录已用历史填充过的会话，避免发送后历史刷新覆盖本地富消息（含结构化来源）
  const hydratedSessionRef = useRef<string | null>(null)

  // Load history when session changes
  const { data: history, isLoading: historyLoading } = useQuery({
    queryKey: ['history', currentSessionId],
    queryFn: () => getHistory(currentSessionId),
    enabled: !!currentSessionId,
    retry: false,
  })

  useEffect(() => {
    if (!history) return
    // 每个会话只在首次进入时用历史填充一次；之后本地消息（带来源卡片）为准
    if (hydratedSessionRef.current === currentSessionId) return
    hydratedSessionRef.current = currentSessionId
    const mapped: Message[] = history.messages
      .filter(m => m.role === 'user' || m.role === 'assistant')
      .map((m, i) => ({
        id: String(i),
        role: m.role as 'user' | 'assistant',
        content: m.content,
      }))
    setMessages(mapped)
  }, [history, currentSessionId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  const handleSend = useCallback(async () => {
    const q = input.trim()
    if (!q || isLoading) return
    setInput('')
    setIsLoading(true)

    const userMsg: Message = { id: `u_${Date.now()}`, role: 'user', content: q }
    // 流式占位 assistant 消息：稳定 id，token 增量按 id 累加，done 时挂 response。
    const aiId = `a_${Date.now()}`
    setMessages(prev => [
      ...prev,
      userMsg,
      { id: aiId, role: 'assistant', content: '', isNew: true, streaming: true },
    ])

    // Update session list
    const existing = sessions.find(s => s.id === currentSessionId)
    if (!existing) {
      const newSession: Session = { id: currentSessionId, firstQuestion: q.slice(0, 30), createdAt: new Date().toISOString() }
      const updated = [newSession, ...sessions]
      setSessions(updated)
      saveSessions(updated)
    }

    const abort = new AbortController()
    abortRef.current = abort
    await askQuestionStream(q, currentSessionId, {
      signal: abort.signal,
      onToken: (text: string) => {
        setMessages(prev =>
          prev.map(m => (m.id === aiId ? { ...m, content: m.content + text } : m)),
        )
      },
      onDone: payload => {
        const resp: AskResponse = {
          answer: payload.answer,
          sources: payload.sources,
          refused: payload.refused,
          need_human: payload.need_human,
          human_task_id: payload.human_task_id,
        }
        setMessages(prev =>
          prev.map(m =>
            m.id === aiId
              ? {
                  ...m,
                  // 有结构化来源时剥离正文引用块，交给来源卡片展示，避免重复
                  content:
                    payload.sources.length > 0
                      ? stripCitationBlock(payload.answer)
                      : payload.answer,
                  response: resp,
                  streaming: false,
                }
              : m,
          ),
        )
      },
      onError: () => {
        setMessages(prev =>
          prev.map(m =>
            m.id === aiId
              ? {
                  id: m.id,
                  role: 'assistant',
                  content: '请求失败，请检查网络连接后重试',
                  error: true,
                }
              : m,
          ),
        )
      },
    })

    abortRef.current = null
    setIsLoading(false)
    textareaRef.current?.focus()
  }, [input, isLoading, currentSessionId, sessions])

  const handleStop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  function handleNewSession() {
    const id = newSessionId()
    setCurrentSessionId(id)
    setMessages([])
    setInput('')
  }

  function handleSelectSession(id: string) {
    if (id === currentSessionId) return
    setCurrentSessionId(id)
    setMessages([])
    setDrawerOpen(false)
  }

  const currentSession = sessions.find(s => s.id === currentSessionId)

  const SessionList = () => (
    <>
      <div className="p-3">
        <Button className="w-full text-sm" style={{ backgroundColor: '#3B4FCC' }} onClick={() => { handleNewSession(); setDrawerOpen(false) }}>
          <Plus className="w-4 h-4" /> 新对话
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-2 scrollbar-thin">
        {sessions.length === 0 && (
          <p className="text-xs text-gray-400 text-center py-8">暂无会话记录</p>
        )}
        {sessions.map(s => (
          <button
            key={s.id}
            onClick={() => handleSelectSession(s.id)}
            className={`w-full text-left px-3 py-2.5 rounded-lg mb-1 transition-colors ${
              s.id === currentSessionId
                ? 'bg-white border-l-[3px] shadow-sm'
                : 'hover:bg-white/60'
            }`}
            style={s.id === currentSessionId ? { borderLeftColor: '#3B4FCC' } : undefined}
          >
            <p className="text-sm text-gray-700 font-medium truncate">{s.firstQuestion || '新对话'}</p>
            <p className="text-xs text-gray-400 mt-0.5">{dayjs(s.createdAt).fromNow()}</p>
          </button>
        ))}
      </div>
      <div className="px-4 py-2 border-t border-gray-200">
        <p className="text-xs text-gray-400">{sessions.length} 个会话</p>
      </div>
    </>
  )

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <NavBar />

      {/* Mobile drawer overlay */}
      {drawerOpen && (
        <div className="md:hidden fixed inset-0 z-40 flex">
          <div className="absolute inset-0 bg-black/40" onClick={() => setDrawerOpen(false)} />
          <div className="relative z-10 w-72 flex flex-col bg-[#F0F4F8] shadow-xl">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
              <span className="text-sm font-medium text-gray-700">会话记录</span>
              <button onClick={() => setDrawerOpen(false)} className="text-gray-400 hover:text-gray-600">
                <X className="w-4 h-4" />
              </button>
            </div>
            <SessionList />
          </div>
        </div>
      )}

      {/* Desktop sidebar */}
      <div className="hidden md:flex w-60 flex-col bg-[#F0F4F8] border-r border-gray-200">
        <SessionList />
      </div>

      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="h-14 flex items-center px-4 md:px-6 border-b border-gray-200 bg-white gap-3">
          <button
            className="md:hidden p-1 rounded-lg text-gray-500 hover:bg-gray-100"
            onClick={() => setDrawerOpen(true)}
          >
            <Menu className="w-5 h-5" />
          </button>
          <span className="font-medium text-gray-800 truncate">
            {currentSession?.firstQuestion ? `${currentSession.firstQuestion}…` : '新对话'}
          </span>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-4 scrollbar-thin">
          {historyLoading && (
            <div className="space-y-4">
              {[0, 1].map(i => (
                <div key={i} className={`flex gap-3 ${i % 2 ? 'justify-end' : ''}`}>
                  {i % 2 === 0 && <Skeleton className="w-8 h-8 rounded-full shrink-0" />}
                  <Skeleton className="h-16 w-64 rounded-2xl" />
                </div>
              ))}
            </div>
          )}

          {!historyLoading && messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center pb-12">
              <div className="w-16 h-16 rounded-2xl flex items-center justify-center mb-4"
                style={{ backgroundColor: '#EEF2FF' }}>
                <Bot className="w-8 h-8" style={{ color: '#3B4FCC' }} />
              </div>
              <h3 className="text-lg font-medium text-gray-700 mb-2">企业知识问答助手</h3>
              <p className="text-sm text-gray-400 max-w-sm">
                请输入问题，我将从知识库中为您查找答案，并标注来源文档
              </p>
            </div>
          )}

          {messages.map((msg, idx) => (
            <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              {msg.role === 'user' ? (
                <div className="max-w-[75%] rounded-2xl rounded-tr-sm px-4 py-3 text-sm text-white"
                  style={{ backgroundColor: '#3B4FCC' }}>
                  {msg.content}
                </div>
              ) : (
                <AssistantBubble
                  msg={msg}
                  onRetry={msg.error ? () => {
                    // find last user message before this
                    const userMsg = [...messages].slice(0, idx).reverse().find(m => m.role === 'user')
                    if (userMsg) { setInput(userMsg.content); textareaRef.current?.focus() }
                  } : undefined}
                />
              )}
            </div>
          ))}

          {isLoading && !messages.some(m => m.streaming && m.content.length > 0) && (
            <div className="flex justify-start">
              <LoadingBubble />
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div className="border-t border-gray-200 bg-white px-4 md:px-6 py-4 md:pb-4 pb-20">
          <div className="flex gap-3 items-end">
            <div className="flex-1 relative">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
                }}
                placeholder="输入您的问题… (Enter 发送，Shift+Enter 换行)"
                maxLength={4000}
                rows={2}
                disabled={isLoading}
                className="w-full resize-none rounded-xl border border-gray-200 px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:border-transparent disabled:opacity-50 scrollbar-thin"
                style={{ maxHeight: 120, '--tw-ring-color': '#3B4FCC' } as React.CSSProperties}
              />
              <span className="absolute bottom-2 right-3 text-xs text-gray-300 pointer-events-none">
                {input.length}/4000
              </span>
            </div>
            {isLoading ? (
              <Button
                onClick={handleStop}
                className="h-10 w-10 p-0 rounded-xl bg-red-500 hover:bg-red-600"
                title="停止生成"
              >
                <Square className="w-4 h-4" />
              </Button>
            ) : (
              <Button
                onClick={handleSend}
                disabled={!input.trim()}
                className="h-10 w-10 p-0 rounded-xl"
                style={{ backgroundColor: '#3B4FCC' }}
              >
                <Send className="w-4 h-4" />
              </Button>
            )}
          </div>
          <p className="text-xs text-gray-300 mt-1.5">Enter 发送 · Shift+Enter 换行</p>
        </div>
      </div>
    </div>
  )
}
