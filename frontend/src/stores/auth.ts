import { create } from 'zustand'
import { saveToken, getToken, clearToken, parseTokenPayload, isTokenExpired, type TokenPayload } from '@/api/auth'
import { toast } from '@/hooks/use-toast'
import { navigateTo } from '@/lib/navigation'

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

// 过期提醒提前量（毫秒）：到期前 5 分钟提示
const WARN_LEAD_MS = 5 * 60 * 1000

let warnTimer: ReturnType<typeof setTimeout> | null = null
let expiryTimer: ReturnType<typeof setTimeout> | null = null

function clearTimers() {
  if (warnTimer) { clearTimeout(warnTimer); warnTimer = null }
  if (expiryTimer) { clearTimeout(expiryTimer); expiryTimer = null }
}

/** 根据 token 的 exp 安排"即将过期提醒"和"到期自动登出" */
function scheduleExpiry(payload: TokenPayload, onExpire: () => void) {
  clearTimers()
  const msUntilExp = payload.exp * 1000 - Date.now()
  if (msUntilExp <= 0) return

  if (msUntilExp > WARN_LEAD_MS) {
    warnTimer = setTimeout(() => {
      toast({ title: '登录即将过期', description: '将在 5 分钟后失效，请及时保存操作' })
    }, msUntilExp - WARN_LEAD_MS)
  }

  expiryTimer = setTimeout(() => {
    onExpire()
    toast({ variant: 'destructive', title: '登录已过期', description: '请重新登录' })
    navigateTo('/login')
  }, msUntilExp)
}

export const useAuthStore = create<AuthState>((set, get) => ({
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
    scheduleExpiry(payload, () => get().logout())
    return true
  },

  logout: () => {
    clearTimers()
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
    scheduleExpiry(payload, () => get().logout())
  },
}))

export const useAuth = () => useAuthStore()
