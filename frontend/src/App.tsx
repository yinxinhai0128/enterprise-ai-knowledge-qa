import { lazy, Suspense, useEffect, Component, type ReactNode } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation, useNavigate, Outlet } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from '@/components/ui/toaster'
import { useAuth } from '@/stores/auth'
import { setNavigator } from '@/lib/navigation'

const LoginPage = lazy(() => import('@/pages/LoginPage'))
const ChatPage = lazy(() => import('@/pages/ChatPage'))
const DocumentsPage = lazy(() => import('@/pages/DocumentsPage'))
const AdminPage = lazy(() => import('@/pages/AdminPage'))

function PageLoader() {
  return (
    <div className="flex h-screen items-center justify-center bg-gray-50">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 rounded-full border-2 border-[#3B4FCC] border-t-transparent animate-spin" />
        <span className="text-xs text-gray-400">加载中…</span>
      </div>
    </div>
  )
}

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null }
  static getDerivedStateFromError(error: Error) { return { error } }
  render() {
    if (this.state.error) {
      return (
        <div className="flex flex-col items-center justify-center h-screen text-center p-8">
          <p className="text-lg font-medium text-gray-700 mb-2">页面遇到问题</p>
          <p className="text-sm text-gray-400 mb-6">可能是浏览器扩展干扰了页面，请刷新重试</p>
          <button
            onClick={() => { this.setState({ error: null }); window.location.reload() }}
            className="px-4 py-2 rounded-xl text-white text-sm"
            style={{ background: 'linear-gradient(135deg, #5B72F5 0%, #3B4FCC 100%)' }}
          >
            刷新页面
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 5000 },
  },
})

function ProtectedRoute() {
  const auth = useAuth()
  const location = useLocation()
  if (!auth.token) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }
  return <Outlet />
}

function AppRoutes() {
  const auth = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    setNavigator(navigate)
  }, [navigate])

  useEffect(() => {
    auth.hydrate()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Suspense fallback={<PageLoader />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/admin" element={<AdminPage />} />
        </Route>
        <Route path="/" element={<Navigate to={auth.token ? '/chat' : '/login'} replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AppRoutes />
          <Toaster />
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}
