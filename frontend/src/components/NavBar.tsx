import { useNavigate, useLocation } from 'react-router-dom'
import { MessageSquare, FileText, Settings, LogOut } from 'lucide-react'
import { useAuth } from '@/stores/auth'
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from '@/components/ui/tooltip'
import { toast } from '@/hooks/use-toast'

const NAV_ITEMS = [
  { icon: MessageSquare, label: '智能问答', path: '/chat' },
  { icon: FileText, label: '知识库文档', path: '/documents' },
]

export function NavBar() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const auth = useAuth()

  function handleLogout() {
    auth.logout()
    navigate('/login')
    toast({ title: '已退出登录' })
  }

  const initials = auth.userId ? auth.userId.slice(0, 2).toUpperCase() : '??'

  const allItems = [
    ...NAV_ITEMS,
    ...(auth.isAdmin ? [{ icon: Settings, label: '管理员面板', path: '/admin' }] : []),
  ]

  return (
    <TooltipProvider delayDuration={200}>
      {/* Desktop: left sidebar */}
      <nav
        className="hidden md:flex flex-col items-center py-4 h-full shrink-0"
        style={{ width: 60, background: '#1e3a5f' }}
      >
        <div className="w-9 h-9 rounded-lg bg-white/20 flex items-center justify-center mb-6">
          <span className="text-white text-xs font-bold">EK</span>
        </div>

        <div className="flex-1 flex flex-col items-center gap-2 w-full px-2">
          {allItems.map(({ icon: Icon, label, path }) => {
            const active = pathname.startsWith(path)
            return (
              <Tooltip key={path}>
                <TooltipTrigger asChild>
                  <button
                    onClick={() => navigate(path)}
                    className={`w-10 h-10 rounded-xl flex items-center justify-center transition-colors ${
                      active ? 'bg-white/25 text-white' : 'text-white/60 hover:bg-white/10 hover:text-white'
                    }`}
                  >
                    <Icon className="w-5 h-5" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="right">{label}</TooltipContent>
              </Tooltip>
            )
          })}
        </div>

        <div className="flex flex-col items-center gap-2">
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="w-8 h-8 rounded-full flex items-center justify-center cursor-default"
                style={{ backgroundColor: '#3B4FCC' }}>
                <span className="text-white text-xs font-semibold">{initials}</span>
              </div>
            </TooltipTrigger>
            <TooltipContent side="right">{auth.userId ?? '用户'}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={handleLogout}
                className="w-8 h-8 rounded-xl flex items-center justify-center text-white/50 hover:text-white hover:bg-white/10 transition-colors"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="right">退出登录</TooltipContent>
          </Tooltip>
        </div>
      </nav>

      {/* Mobile: bottom navigation bar */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 flex items-center justify-around h-14 bg-white border-t border-gray-200">
        {allItems.map(({ icon: Icon, label, path }) => {
          const active = pathname.startsWith(path)
          return (
            <button
              key={path}
              onClick={() => navigate(path)}
              className={`flex flex-col items-center gap-0.5 px-4 py-1 rounded-lg transition-colors ${
                active ? 'text-[#3B4FCC]' : 'text-gray-400'
              }`}
            >
              <Icon className="w-5 h-5" />
              <span className="text-[10px]">{label}</span>
            </button>
          )
        })}
        <button
          onClick={handleLogout}
          className="flex flex-col items-center gap-0.5 px-4 py-1 rounded-lg text-gray-400"
        >
          <LogOut className="w-5 h-5" />
          <span className="text-[10px]">退出</span>
        </button>
      </nav>
    </TooltipProvider>
  )
}
