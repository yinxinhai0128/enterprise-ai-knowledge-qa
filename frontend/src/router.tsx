import { lazy, Suspense } from 'react'
import { createBrowserRouter, Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '@/stores/auth'

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

function ProtectedRoute() {
  const { token } = useAuth()
  const location = useLocation()
  if (!token) return <Navigate to="/login" state={{ from: location }} replace />
  return <Outlet />
}

function AdminRoute() {
  const { token, isAdmin } = useAuth()
  const location = useLocation()
  if (!token) return <Navigate to="/login" state={{ from: location }} replace />
  if (!isAdmin) return <Navigate to="/chat" replace />
  return <Outlet />
}

function RootRedirect() {
  const { token } = useAuth()
  return <Navigate to={token ? '/chat' : '/login'} replace />
}

function wrap(Page: React.LazyExoticComponent<() => JSX.Element>) {
  return (
    <Suspense fallback={<PageLoader />}>
      <Page />
    </Suspense>
  )
}

export const router = createBrowserRouter([
  { path: '/login', element: wrap(LoginPage) },
  {
    element: <ProtectedRoute />,
    children: [
      { path: '/chat', element: wrap(ChatPage) },
    ],
  },
  {
    element: <AdminRoute />,
    children: [
      { path: '/documents', element: wrap(DocumentsPage) },
      { path: '/admin', element: wrap(AdminPage) },
    ],
  },
  { path: '/', element: <RootRedirect /> },
  { path: '*', element: <Navigate to="/" replace /> },
])
