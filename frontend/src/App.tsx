import { useEffect, Component, type ReactNode } from 'react'
import { RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from '@/components/ui/toaster'
import { useAuth } from '@/stores/auth'
import { router } from '@/router'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 5000 },
  },
})

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

function AuthHydrator() {
  const { hydrate } = useAuth()
  useEffect(() => { hydrate() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
        <AuthHydrator />
        <Toaster />
      </QueryClientProvider>
    </ErrorBoundary>
  )
}
