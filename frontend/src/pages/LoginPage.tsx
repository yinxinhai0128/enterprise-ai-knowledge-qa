import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bot, BookOpen, Lock, FlaskConical, ClipboardPaste } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useAuth } from '@/stores/auth'
import { toast } from '@/hooks/use-toast'

const FEATURES = [
  { icon: Bot, title: '智能问答', desc: '基于企业文档，拒绝幻觉，来源可溯' },
  { icon: BookOpen, title: '知识管理', desc: 'PDF / DOCX / XLSX 一键上传，自动索引' },
  { icon: Lock, title: '安全隔离', desc: '租户隔离，审计追踪，符合合规要求' },
]

export default function LoginPage() {
  const [token, setToken] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const auth = useAuth()
  const navigate = useNavigate()
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (auth.token) navigate('/chat', { replace: true })
  }, [auth.token, navigate])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const t = params.get('token')
    if (t) { setToken(t); window.history.replaceState({}, '', '/login') }
  }, [])

  function validate(t: string): string {
    const trimmed = t.trim()
    if (!trimmed) return '请输入访问令牌'
    if (!trimmed.startsWith('eyJ')) return '令牌格式不正确（应以 eyJ 开头）'
    return ''
  }

  function handleLogin() {
    const trimmed = token.trim()
    const err = validate(trimmed)
    if (err) { setError(err); return }
    setLoading(true)
    setError('')
    const ok = auth.login(trimmed)
    setLoading(false)
    if (!ok) {
      setError('令牌已过期或无效，请重新获取')
    } else {
      navigate('/chat', { replace: true })
    }
  }

  async function handlePaste() {
    try {
      const text = await navigator.clipboard.readText()
      setToken(text)
      setError('')
    } catch {
      toast({ variant: 'destructive', title: '无法读取剪贴板', description: '请手动粘贴令牌' })
    }
  }

  function handleDevHint() {
    toast({
      title: '开发模式：生成临时 Token',
      description: '在项目终端运行：python scripts/create_dev_token.py --roles user,admin --ttl-seconds 3600',
    })
  }

  const isDev = import.meta.env.DEV

  return (
    <div className="flex h-screen animate-fade-in">
      {/* Left — brand panel */}
      <div className="hidden md:flex w-1/2 flex-col justify-between p-10"
        style={{ background: 'linear-gradient(135deg, #1a3558 0%, #3B4FCC 100%)' }}>
        <div className="text-white">
          <div className="flex items-center gap-3 mb-16">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center"
              style={{ background: 'linear-gradient(135deg, rgba(255,255,255,0.25) 0%, rgba(255,255,255,0.1) 100%)' }}>
              <Bot className="w-6 h-6 text-white" />
            </div>
            <span className="text-xl font-bold tracking-wide">企知问答 EKQA</span>
          </div>
          <h2 className="text-3xl font-bold mb-4 leading-tight">
            让企业知识<br />触手可及
          </h2>
          <p className="text-blue-200 text-sm mb-12">
            Agentic RAG 驱动，每一条回答都有依据
          </p>
          <div className="space-y-6">
            {FEATURES.map(({ icon: Icon, title, desc }) => (
              <div key={title} className="flex items-start gap-4">
                <div className="w-10 h-10 rounded-full bg-white/15 flex items-center justify-center shrink-0">
                  <Icon className="w-5 h-5 text-white" />
                </div>
                <div>
                  <p className="text-white font-medium">{title}</p>
                  <p className="text-blue-200 text-sm mt-0.5">{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
        <p className="text-blue-300 text-xs">v1.0 · Enterprise Edition · Agentic RAG</p>
      </div>

      {/* Right — login form */}
      <div className="flex-1 flex flex-col items-center justify-center bg-gray-50 p-8">
        {/* Mobile logo */}
        <div className="flex md:hidden items-center gap-2 mb-8">
          <Bot className="w-6 h-6 text-brand" />
          <span className="font-bold text-lg" style={{ color: '#3B4FCC' }}>企知问答 EKQA</span>
        </div>

        <div className="w-full max-w-md">
          <h1 className="text-2xl font-bold text-gray-900 mb-1">欢迎回来</h1>
          <p className="text-gray-500 text-sm mb-8">请使用您的访问令牌登录</p>

          <div className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-sm font-medium text-gray-700">访问令牌</label>
                <button
                  type="button"
                  onClick={handlePaste}
                  className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700"
                >
                  <ClipboardPaste className="w-3 h-3" />
                  粘贴
                </button>
              </div>
              <Textarea
                ref={textareaRef}
                value={token}
                onChange={e => { setToken(e.target.value); setError('') }}
                placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
                className="font-mono text-xs resize-none h-20"
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleLogin() } }}
              />
              {error && <p className="text-red-500 text-xs mt-1">{error}</p>}
            </div>

            <Button
              className="w-full"
              style={{ backgroundColor: '#3B4FCC' }}
              onClick={handleLogin}
              disabled={loading}
            >
              {loading ? '验证中…' : '登录系统'}
            </Button>

            {isDev && (
              <>
                <div className="relative">
                  <div className="absolute inset-0 flex items-center">
                    <span className="w-full border-t border-gray-200" />
                  </div>
                  <div className="relative flex justify-center text-xs">
                    <span className="bg-gray-50 px-2 text-gray-400">或</span>
                  </div>
                </div>
                <Button
                  variant="outline"
                  className="w-full"
                  onClick={handleDevHint}
                >
                  <FlaskConical className="w-4 h-4" />
                  开发模式：如何获取 Token
                </Button>
              </>
            )}
          </div>

          <p className="text-center text-xs text-gray-400 mt-6">
            令牌由系统管理员颁发，有效期内使用
          </p>
        </div>
      </div>
    </div>
  )
}
