import { useEffect, Component, type ReactNode } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation, Outlet } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from '@/components/ui/toaster'
import { useAuth } from '@/stores/auth'
import LoginPage from '@/pages/LoginPage'
import ChatPage from '@/pages/ChatPage'
import DocumentsPage from '@/pages/DocumentsPage'
import AdminPage from '@/pages/AdminPage'

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
            className="px-4 py-2 rounded-lg text-white text-sm"
            style={{ backgroundColor: '#3B4FCC' }}
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

  useEffect(() => {
    auth.hydrate()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
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
