import { create } from 'zustand'
import { saveToken, getToken, clearToken, parseTokenPayload, isTokenExpired } from '@/api/auth'

interface AuthState {
  token: string | null
  userId: string | null
  tenantId: string | null
  roles: string[]
  isAdmin: boolean

  login: (token: string) => boolean
  logout: () => void
  hydrate: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  userId: null,
  tenantId: null,
  roles: [],
  isAdmin: false,

  login: (token: string) => {
    const payload = parseTokenPayload(token)
    if (!payload) return false
    if (isTokenExpired(payload)) return false
    saveToken(token)
    set({
      token,
      userId: payload.sub,
      tenantId: payload.tenant_id,
      roles: payload.roles,
      isAdmin: payload.roles.includes('admin'),
    })
    return true
  },

  logout: () => {
    clearToken()
    set({ token: null, userId: null, tenantId: null, roles: [], isAdmin: false })
  },

  hydrate: () => {
    const token = getToken()
    if (!token) return
    const payload = parseTokenPayload(token)
    if (!payload || isTokenExpired(payload)) {
      clearToken()
      return
    }
    set({
      token,
      userId: payload.sub,
      tenantId: payload.tenant_id,
      roles: payload.roles,
      isAdmin: payload.roles.includes('admin'),
    })
  },
}))

export const useAuth = () => useAuthStore()
