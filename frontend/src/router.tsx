import { Suspense, type ComponentType } from 'react'
import { createBrowserRouter, Navigate } from 'react-router-dom'
import LoginPage from '@/pages/LoginPage'
import {
  AdminPage,
  AdminRoute,
  ChatPage,
  DocumentsPage,
  PageLoader,
  ProtectedRoute,
  RootRedirect,
} from '@/routerComponents'

function wrap(Page: ComponentType) {
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
