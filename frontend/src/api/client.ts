import axios from 'axios'
import { getToken } from './auth'
import { toast } from '@/hooks/use-toast'
import { navigateTo } from '@/lib/navigation'
import { useAuthStore } from '@/stores/auth'

export const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8765'

export const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 60000,
})

apiClient.interceptors.request.use(config => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

apiClient.interceptors.response.use(
  response => response,
  error => {
    if (!error.response) {
      toast({ variant: 'destructive', title: '网络错误', description: '无法连接到服务器，请检查网络' })
      return Promise.reject(error)
    }

    const { status, data, headers } = error.response

    if (status === 401) {
      // 同时重置 Zustand 状态（clearToken 只清 localStorage，不会触发 UI 更新）
      useAuthStore.getState().logout()
      navigateTo('/login')
      return Promise.reject(error)
    }

    if (status === 429) {
      const retryAfter = headers['retry-after'] ?? headers['Retry-After']
      const msg = retryAfter ? `请等待 ${retryAfter} 秒后重试` : '请求过于频繁，请稍候'
      toast({ variant: 'destructive', title: '请求受限', description: msg })
      return Promise.reject(error)
    }

    const detail = data?.detail
    const message = typeof detail === 'string' ? detail : (detail?.message ?? '操作失败，请重试')
    if (status !== 404) {
      toast({ variant: 'destructive', title: `错误 ${status}`, description: message })
    }

    return Promise.reject(error)
  }
)
