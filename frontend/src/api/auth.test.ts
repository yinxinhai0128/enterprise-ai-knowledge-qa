import { describe, it, expect, beforeEach } from 'vitest'
import { parseTokenPayload, isTokenExpired, saveToken, getToken, clearToken } from './auth'

// 构造 base64url 编码的伪 JWT（仅用于解析逻辑测试，不验签）。
function b64url(obj: object): string {
  return btoa(JSON.stringify(obj))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
}
function makeJwt(payload: object): string {
  return `eyJhbGciOiJIUzI1NiJ9.${b64url(payload)}.sig`
}

const basePayload = {
  sub: 'viewer',
  tenant_id: 'local-tenant',
  roles: ['user', 'admin'],
  iss: 'enterprise-idp',
  aud: 'enterprise-kb',
  iat: 1700000000,
  exp: 1900000000,
}

describe('parseTokenPayload', () => {
  it('解析合法 token 的 payload', () => {
    const payload = parseTokenPayload(makeJwt(basePayload))
    expect(payload).not.toBeNull()
    expect(payload?.sub).toBe('viewer')
    expect(payload?.tenant_id).toBe('local-tenant')
    expect(payload?.roles).toEqual(['user', 'admin'])
    expect(payload?.exp).toBe(1900000000)
  })

  it('段数不为 3 时返回 null', () => {
    expect(parseTokenPayload('only.two')).toBeNull()
    expect(parseTokenPayload('no-dots-at-all')).toBeNull()
  })

  it('中间段非合法 base64/JSON 时返回 null（不抛异常）', () => {
    expect(parseTokenPayload('aaa.!!!not-base64!!!.bbb')).toBeNull()
  })

  it('处理无 padding 的 base64url', () => {
    // 长度故意构造成需要补 padding 的情况
    const payload = parseTokenPayload(makeJwt({ sub: 'a', roles: [] }))
    expect(payload?.sub).toBe('a')
  })
})

describe('isTokenExpired', () => {
  it('exp 在未来 → 未过期', () => {
    expect(isTokenExpired({ ...basePayload, exp: Math.floor(Date.now() / 1000) + 3600 })).toBe(false)
  })

  it('exp 在过去 → 已过期', () => {
    expect(isTokenExpired({ ...basePayload, exp: Math.floor(Date.now() / 1000) - 1 })).toBe(true)
  })
})

describe('token localStorage 读写', () => {
  beforeEach(() => localStorage.clear())

  it('save / get / clear 往返', () => {
    expect(getToken()).toBeNull()
    saveToken('abc.def.ghi')
    expect(getToken()).toBe('abc.def.ghi')
    clearToken()
    expect(getToken()).toBeNull()
  })
})
