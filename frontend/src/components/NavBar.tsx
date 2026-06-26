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
      {/* Desktop: left icon rail */}
      <nav
        className="hidden md:flex flex-col items-center py-4 h-full shrink-0"
        style={{ width: 60, background: 'linear-gradient(180deg, #1a3558 0%, #1e3a5f 100%)' }}
      >
        {/* Logo */}
        <div className="w-9 h-9 rounded-xl flex items-center justify-center mb-7 shadow-sm"
          style={{ background: 'linear-gradient(135deg, #4F6EF7 0%, #3B4FCC 100%)' }}>
          <span className="text-white text-xs font-bold tracking-wide">EK</span>
        </div>

        {/* Nav items */}
        <div className="flex-1 flex flex-col items-center gap-1.5 w-full px-2">
          {allItems.map(({ icon: Icon, label, path }) => {
            const active = pathname.startsWith(path)
            return (
              <Tooltip key={path}>
                <TooltipTrigger asChild>
                  <button
                    onClick={() => navigate(path)}
                    className={`w-10 h-10 rounded-xl flex items-center justify-center transition-all ${
                      active
                        ? 'bg-white/20 text-white shadow-inner ring-1 ring-white/10'
                        : 'text-white/50 hover:bg-white/10 hover:text-white'
                    }`}
                  >
                    <Icon className="w-5 h-5" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="right" className="font-medium">{label}</TooltipContent>
              </Tooltip>
            )
          })}
        </div>

        {/* Bottom: avatar + logout */}
        <div className="flex flex-col items-center gap-2 pb-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <div
                className="w-8 h-8 rounded-full flex items-center justify-center cursor-default ring-2 ring-white/10"
                style={{ background: 'linear-gradient(135deg, #5B72F5 0%, #3B4FCC 100%)' }}
              >
                <span className="text-white text-xs font-semibold">{initials}</span>
              </div>
            </TooltipTrigger>
            <TooltipContent side="right">{auth.userId ?? '用户'}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={handleLogout}
                className="w-8 h-8 rounded-xl flex items-center justify-center text-white/40 hover:text-white hover:bg-white/10 transition-colors"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="right">退出登录</TooltipContent>
          </Tooltip>
        </div>
      </nav>

      {/* Mobile: bottom navigation bar */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 flex items-center justify-around h-14 bg-white border-t border-gray-100 shadow-lg">
        {allItems.map(({ icon: Icon, label, path }) => {
          const active = pathname.startsWith(path)
          return (
            <button
              key={path}
              onClick={() => navigate(path)}
              className={`flex flex-col items-center gap-0.5 px-4 py-1.5 rounded-xl transition-colors ${
                active ? 'text-[#3B4FCC]' : 'text-gray-400 hover:text-gray-600'
              }`}
            >
              <Icon className={`w-5 h-5 ${active ? 'stroke-[2.2px]' : ''}`} />
              <span className="text-[10px] font-medium">{label}</span>
            </button>
          )
        })}
        <button
          onClick={handleLogout}
          className="flex flex-col items-center gap-0.5 px-4 py-1.5 rounded-xl text-gray-400 hover:text-gray-600 transition-colors"
        >
          <LogOut className="w-5 h-5" />
          <span className="text-[10px] font-medium">退出</span>
        </button>
      </nav>
    </TooltipProvider>
  )
}
