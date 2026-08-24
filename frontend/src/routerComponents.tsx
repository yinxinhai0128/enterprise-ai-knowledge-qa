import { lazy } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '@/stores/auth'

export const ChatPage = lazy(() => import('@/pages/ChatPage'))
export const DocumentsPage = lazy(() => import('@/pages/DocumentsPage'))
export const AdminPage = lazy(() => import('@/pages/AdminPage'))

export function PageLoader() {
  return (
    <div className="flex h-screen items-center justify-center bg-gray-50">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 rounded-full border-2 border-[#3B4FCC] border-t-transparent animate-spin" />
        <span className="text-xs text-gray-400">加载中...</span>
      </div>
    </div>
  )
}

export function ProtectedRoute() {
  const { token } = useAuth()
  const location = useLocation()
  if (!token) return <Navigate to="/login" state={{ from: location }} replace />
  return <Outlet />
}

export function AdminRoute() {
  const { token, isAdmin } = useAuth()
  const location = useLocation()
  if (!token) return <Navigate to="/login" state={{ from: location }} replace />
  if (!isAdmin) return <Navigate to="/chat" replace />
  return <Outlet />
}

export function RootRedirect() {
  const { token } = useAuth()
  return <Navigate to={token ? '/chat' : '/login'} replace />
}
