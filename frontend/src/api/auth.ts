const TOKEN_KEY = 'ekqa_token'

export interface TokenPayload {
  sub: string
  tenant_id: string
  roles: string[]
  exp: number
  iss?: string
  aud?: string
}

export function saveToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export function parseTokenPayload(token: string): TokenPayload | null {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    const payload = parts[1]
    // Pad base64 if needed
    const padded = payload + '=='.slice(0, (4 - (payload.length % 4)) % 4)
    const decoded = atob(padded.replace(/-/g, '+').replace(/_/g, '/'))
    return JSON.parse(decoded) as TokenPayload
  } catch {
    return null
  }
}

export function isTokenExpired(payload: TokenPayload): boolean {
  return Date.now() / 1000 > payload.exp
}
