import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('@/hooks/use-toast', () => ({ toast: vi.fn() }))
vi.mock('@/lib/navigation', () => ({ navigateTo: vi.fn() }))

import { useAuthStore } from './auth'
import { toast } from '@/hooks/use-toast'
import { navigateTo } from '@/lib/navigation'

function b64url(obj: object): string {
  return btoa(JSON.stringify(obj)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}
function makeJwt(payload: object): string {
  return `eyJhbGciOiJIUzI1NiJ9.${b64url(payload)}.sig`
}
function payloadWithExp(expSec: number, roles: string[] = ['user', 'admin']) {
  return { sub: 'viewer', tenant_id: 'local-tenant', roles, iss: 'idp', aud: 'kb', iat: 0, exp: expSec }
}

const FUTURE = Math.floor(Date.now() / 1000) + 3600

beforeEach(() => {
  localStorage.clear()
  useAuthStore.getState().logout() // 复位单例状态 + 清定时器
  vi.clearAllMocks()
})
afterEach(() => {
  vi.useRealTimers()
})

describe('auth store · login', () => {
  it('合法 token：登录成功并派生 isAdmin', () => {
    const ok = useAuthStore.getState().login(makeJwt(payloadWithExp(FUTURE)))
    expect(ok).toBe(true)
    const s = useAuthStore.getState()
    expect(s.token).not.toBeNull()
    expect(s.userId).toBe('viewer')
    expect(s.tenantId).toBe('local-tenant')
    expect(s.isAdmin).toBe(true)
  })

  it('普通用户角色：isAdmin 为 false', () => {
    useAuthStore.getState().login(makeJwt(payloadWithExp(FUTURE, ['user'])))
    expect(useAuthStore.getState().isAdmin).toBe(false)
  })

  it('已过期 token：登录失败且不改状态', () => {
    const past = Math.floor(Date.now() / 1000) - 10
    const ok = useAuthStore.getState().login(makeJwt(payloadWithExp(past)))
    expect(ok).toBe(false)
    expect(useAuthStore.getState().token).toBeNull()
  })

  it('非法 token：登录失败', () => {
    expect(useAuthStore.getState().login('garbage')).toBe(false)
    expect(useAuthStore.getState().token).toBeNull()
  })
})

describe('auth store · logout / hydrate', () => {
  it('logout 清空状态与 localStorage', () => {
    useAuthStore.getState().login(makeJwt(payloadWithExp(FUTURE)))
    useAuthStore.getState().logout()
    const s = useAuthStore.getState()
    expect(s.token).toBeNull()
    expect(s.isAdmin).toBe(false)
    expect(localStorage.getItem('ekqa_token')).toBeNull()
  })

  it('hydrate 从 localStorage 恢复有效 token', () => {
    localStorage.setItem('ekqa_token', makeJwt(payloadWithExp(FUTURE)))
    useAuthStore.getState().hydrate()
    expect(useAuthStore.getState().userId).toBe('viewer')
  })

  it('hydrate 遇到过期 token：清除且不恢复', () => {
    localStorage.setItem('ekqa_token', makeJwt(payloadWithExp(Math.floor(Date.now() / 1000) - 5)))
    useAuthStore.getState().hydrate()
    expect(useAuthStore.getState().token).toBeNull()
    expect(localStorage.getItem('ekqa_token')).toBeNull()
  })
})

describe('auth store · 过期定时器', () => {
  it('到期前 5 分钟提醒，到期自动登出并跳登录', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2030-01-01T00:00:00Z'))
    const expSec = Math.floor(Date.now() / 1000) + 600 // 10 分钟后过期
    useAuthStore.getState().login(makeJwt(payloadWithExp(expSec)))
    expect(useAuthStore.getState().token).not.toBeNull()

    // 推进到「到期前 5 分钟」→ 触发提醒
    vi.advanceTimersByTime(5 * 60 * 1000 + 50)
    expect(toast).toHaveBeenCalled()

    // 推进到到期时刻 → 自动登出 + 跳登录
    vi.advanceTimersByTime(5 * 60 * 1000)
    expect(useAuthStore.getState().token).toBeNull()
    expect(navigateTo).toHaveBeenCalledWith('/login')
  })

  it('logout 后清除定时器，不再触发到期回调', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2030-01-01T00:00:00Z'))
    useAuthStore.getState().login(makeJwt(payloadWithExp(Math.floor(Date.now() / 1000) + 600)))
    useAuthStore.getState().logout()
    vi.clearAllMocks()
    vi.advanceTimersByTime(20 * 60 * 1000)
    expect(navigateTo).not.toHaveBeenCalled()
  })
})
