import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Send, Square, Plus, ChevronDown, ChevronUp, FileText, AlertTriangle, UserCheck, Bot, RefreshCw, Menu, X, MessageSquare } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
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

const SUGGESTIONS = [
  '请假申请需要提前几天提交？',
  '差旅报销需要哪些材料？',
  '如何申请加班补贴？',
  '试用期转正需要满足哪些条件？',
]

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

// Typewriter hook (for history messages loaded from backend)
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
    <div className="mt-3">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 transition-colors"
      >
        <FileText className="w-3.5 h-3.5" />
        <span>参考了 {sources.length} 份文档</span>
        {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
      </button>
      {open && (
        <div className="mt-2 space-y-1.5 pl-1">
          {sources.map((s, i) => (
            <div key={i} className="rounded-xl bg-gray-50 border border-gray-100 px-3 py-2.5">
              <div className="flex items-center gap-2 mb-1">
                <FileText className="w-3 h-3 text-gray-400 shrink-0" />
                <span className="text-xs font-medium text-gray-700 truncate flex-1" title={s.source}>
                  {s.source}
                </span>
                {s.page != null && (
                  <span className="text-[10px] text-gray-400 shrink-0">第 {s.page} 页</span>
                )}
                <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-md shrink-0"
                  style={{ backgroundColor: '#EEF2FF', color: '#3B4FCC' }}>
                  {Math.round(s.relevance * 100)}%
                </span>
              </div>
              {s.snippet && (
                <p className="text-[11px] text-gray-500 italic line-clamp-2 leading-relaxed pl-5">
                  {s.snippet}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// Message types
interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  response?: AskResponse
  error?: boolean
  isNew?: boolean
  streaming?: boolean
}

function AssistantBubble({ msg, onRetry }: { msg: Message; onRetry?: () => void }) {
  const isStream = msg.isNew === true && (msg.streaming === true || msg.response !== undefined)
  const typewriter = useTypewriter(msg.content, msg.isNew === true && !isStream)
  const displayed = isStream ? msg.content : typewriter.displayed
  const done = isStream ? msg.streaming !== true : typewriter.done

  return (
    <div className="flex gap-3 max-w-[86%]">
      <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-1 shadow-sm"
        style={{ background: 'linear-gradient(135deg, #4F6EF7 0%, #3B4FCC 100%)' }}>
        <Bot className="w-4 h-4 text-white" />
      </div>
      <div className="flex-1 min-w-0">
        <div className={`rounded-2xl rounded-tl-sm px-4 py-3 text-sm leading-relaxed shadow-sm ${
          msg.error
            ? 'bg-red-50 border border-red-200 text-red-700'
            : 'bg-white text-gray-800'
        }`}>
          {msg.error ? (
            <div className="flex items-center gap-2">
              <span>{msg.content}</span>
              {onRetry && (
                <button onClick={onRetry} className="flex items-center gap-1 text-xs text-red-500 hover:text-red-700 shrink-0">
                  <RefreshCw className="w-3 h-3" /> 重试
                </button>
              )}
            </div>
          ) : (
            <span>
              <SimpleMarkdown text={displayed} />
              {msg.streaming && (
                <span className="inline-block w-0.5 h-4 bg-blue-400 animate-pulse ml-0.5 align-middle rounded-sm" />
              )}
            </span>
          )}
        </div>
        {done && msg.response && !msg.error && (
          <div className="mt-1 animate-fade-in">
            {msg.response.refused && (
              <div className="flex items-center gap-1.5 text-xs text-orange-500 mt-1 pl-1">
                <AlertTriangle className="w-3.5 h-3.5" />
                未在知识库中找到相关资料
              </div>
            )}
            {msg.response.need_human && (
              <div className="flex items-center gap-1.5 text-xs text-yellow-600 mt-1 pl-1">
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
    <div className="flex gap-3 max-w-[86%]">
      <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 shadow-sm"
        style={{ background: 'linear-gradient(135deg, #4F6EF7 0%, #3B4FCC 100%)' }}>
        <Bot className="w-4 h-4 text-white" />
      </div>
      <div className="bg-white rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
        <div className="flex gap-1.5 items-center h-5">
          {[0, 1, 2].map(i => (
            <span key={i}
              className="w-2 h-2 rounded-full animate-bounce"
              style={{ backgroundColor: '#C7D2FE', animationDelay: `${i * 0.18}s` }}
            />
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
  const hydratedSessionRef = useRef<string | null>(null)

  const mountedRef = useRef(true)
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      abortRef.current?.abort()
    }
  }, [])

  const { data: history, isLoading: historyLoading } = useQuery({
    queryKey: ['history', currentSessionId],
    queryFn: () => getHistory(currentSessionId),
    enabled: !!currentSessionId,
    retry: false,
  })

  useEffect(() => {
    if (!history) return
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

  const handleSend = useCallback(async (override?: string) => {
    const q = (override ?? input).trim()
    if (!q || isLoading) return
    setInput('')
    setIsLoading(true)

    const userMsg: Message = { id: `u_${Date.now()}`, role: 'user', content: q }
    const aiId = `a_${Date.now()}`
    setMessages(prev => [
      ...prev,
      userMsg,
      { id: aiId, role: 'assistant', content: '', isNew: true, streaming: true },
    ])

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
        if (!mountedRef.current) return
        setMessages(prev =>
          prev.map(m => (m.id === aiId ? { ...m, content: m.content + text } : m)),
        )
      },
      onDone: payload => {
        if (!mountedRef.current) return
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
        if (!mountedRef.current) return
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
    if (!mountedRef.current) return
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
        <button
          onClick={() => { handleNewSession(); setDrawerOpen(false) }}
          className="w-full flex items-center justify-center gap-2 py-2 rounded-xl text-sm font-medium text-white transition-all hover:opacity-90 active:scale-[0.98]"
          style={{ background: 'linear-gradient(135deg, #4F6EF7 0%, #3B4FCC 100%)' }}
        >
          <Plus className="w-4 h-4" /> 新对话
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-2 scrollbar-thin">
        {sessions.length === 0 && (
          <p className="text-xs text-gray-400 text-center py-8">暂无会话记录</p>
        )}
        {sessions.map(s => (
          <button
            key={s.id}
            onClick={() => handleSelectSession(s.id)}
            className={`w-full text-left px-3 py-2.5 rounded-xl mb-1 transition-all ${
              s.id === currentSessionId
                ? 'bg-white shadow-sm border-l-[3px]'
                : 'hover:bg-white/70 border-l-[3px] border-transparent'
            }`}
            style={s.id === currentSessionId ? { borderLeftColor: '#3B4FCC' } : undefined}
          >
            <div className="flex items-start gap-2">
              <MessageSquare className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${s.id === currentSessionId ? 'text-[#3B4FCC]' : 'text-gray-400'}`} />
              <div className="min-w-0">
                <p className="text-sm text-gray-700 font-medium truncate leading-snug">{s.firstQuestion || '新对话'}</p>
                <p className="text-xs text-gray-400 mt-0.5">{dayjs(s.createdAt).fromNow()}</p>
              </div>
            </div>
          </button>
        ))}
      </div>
      <div className="px-4 py-2.5 border-t border-gray-200/60">
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
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setDrawerOpen(false)} />
          <div className="relative z-10 w-72 flex flex-col bg-[#F0F4F8] shadow-2xl">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
              <span className="text-sm font-medium text-gray-700">会话记录</span>
              <button onClick={() => setDrawerOpen(false)} className="text-gray-400 hover:text-gray-600 p-1">
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
        <div className="h-14 flex items-center px-4 md:px-6 border-b border-gray-100 bg-white gap-3 shadow-sm">
          <button
            className="md:hidden p-1.5 rounded-lg text-gray-500 hover:bg-gray-100 transition-colors"
            onClick={() => setDrawerOpen(true)}
          >
            <Menu className="w-5 h-5" />
          </button>
          <span className="font-medium text-gray-700 truncate text-sm">
            {currentSession?.firstQuestion ? `${currentSession.firstQuestion}…` : '新对话'}
          </span>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6 space-y-5 scrollbar-thin">
          {historyLoading && (
            <div className="space-y-5">
              {[0, 1].map(i => (
                <div key={i} className={`flex gap-3 ${i % 2 ? 'justify-end' : ''}`}>
                  {i % 2 === 0 && <Skeleton className="w-8 h-8 rounded-full shrink-0" />}
                  <Skeleton className="h-16 w-64 rounded-2xl" />
                </div>
              ))}
            </div>
          )}

          {!historyLoading && messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center pb-8">
              <div className="w-16 h-16 rounded-2xl flex items-center justify-center mb-5 shadow-md"
                style={{ background: 'linear-gradient(135deg, #EEF2FF 0%, #C7D2FE 100%)' }}>
                <Bot className="w-8 h-8" style={{ color: '#3B4FCC' }} />
              </div>
              <h3 className="text-lg font-semibold text-gray-800 mb-2">企业知识问答助手</h3>
              <p className="text-sm text-gray-400 max-w-xs mb-8 leading-relaxed">
                请输入问题，我将从知识库中为您查找答案，并标注来源文档
              </p>
              <div className="flex flex-wrap justify-center gap-2 max-w-md">
                {SUGGESTIONS.map(s => (
                  <button
                    key={s}
                    onClick={() => handleSend(s)}
                    className="px-4 py-2 rounded-full border border-gray-200 bg-white text-sm text-gray-600 hover:border-blue-300 hover:text-[#3B4FCC] hover:bg-[#EEF2FF] hover:shadow-sm transition-all"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, idx) => (
            <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              {msg.role === 'user' ? (
                <div
                  className="max-w-[75%] rounded-2xl rounded-tr-sm px-4 py-3 text-sm text-white shadow-sm leading-relaxed"
                  style={{ background: 'linear-gradient(135deg, #5B72F5 0%, #3B4FCC 100%)' }}
                >
                  {msg.content}
                </div>
              ) : (
                <AssistantBubble
                  msg={msg}
                  onRetry={msg.error ? () => {
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
        <div className="bg-white border-t border-gray-100 px-4 md:px-8 py-4 pb-5 md:pb-5 pb-20">
          <div className="max-w-3xl mx-auto">
            <div className={`relative rounded-2xl border shadow-sm transition-all ${
              isLoading
                ? 'border-gray-100 bg-gray-50/80'
                : 'border-gray-200 bg-white focus-within:border-blue-300 focus-within:shadow-md'
            }`}>
              <textarea
                ref={textareaRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
                }}
                placeholder="输入您的问题…"
                maxLength={4000}
                rows={2}
                disabled={isLoading}
                className="w-full resize-none bg-transparent px-4 pt-3.5 pb-2 text-sm text-gray-800 placeholder-gray-400 focus:outline-none disabled:opacity-60 scrollbar-thin"
                style={{ maxHeight: 160 }}
              />
              <div className="flex items-center justify-between px-3 pb-2.5">
                <span className="text-xs text-gray-300 select-none">
                  {input.length > 0 ? `${input.length} / 4000` : 'Enter 发送 · Shift+Enter 换行'}
                </span>
                {isLoading ? (
                  <button
                    onClick={handleStop}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-red-500 hover:bg-red-600 text-white text-xs font-medium transition-colors"
                  >
                    <Square className="w-3.5 h-3.5" /> 停止
                  </button>
                ) : (
                  <button
                    onClick={() => handleSend()}
                    disabled={!input.trim()}
                    className="w-8 h-8 rounded-xl flex items-center justify-center text-white transition-all disabled:opacity-30 disabled:cursor-not-allowed hover:opacity-90 active:scale-95"
                    style={{ background: input.trim() ? 'linear-gradient(135deg, #5B72F5 0%, #3B4FCC 100%)' : '#D1D5DB' }}
                  >
                    <Send className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
