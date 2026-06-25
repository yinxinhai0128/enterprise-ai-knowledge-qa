import { test, expect } from '@playwright/test'
import { injectAuth } from './helpers'

test.describe('认证流程', () => {
  test('未登录访问首页 → 重定向到 /login', async ({ page }) => {
    // 确保没有 token
    await page.addInitScript(() => localStorage.clear())
    await page.goto('/')
    await expect(page).toHaveURL(/\/login/, { timeout: 8_000 })
  })

  test('未登录访问 /chat → 重定向到 /login', async ({ page }) => {
    await page.addInitScript(() => localStorage.clear())
    await page.goto('/chat')
    await expect(page).toHaveURL(/\/login/, { timeout: 8_000 })
  })

  test('未登录访问 /documents → 重定向到 /login', async ({ page }) => {
    await page.addInitScript(() => localStorage.clear())
    await page.goto('/documents')
    await expect(page).toHaveURL(/\/login/, { timeout: 8_000 })
  })

  test('登录页面有 token 输入区域', async ({ page }) => {
    await page.goto('/login')
    // 登录页用 <textarea> 让用户粘贴 JWT Token
    const tokenField = page.locator('textarea').first()
    await expect(tokenField).toBeVisible({ timeout: 5_000 })
  })

  test('已登录访问 /login → 重定向到 /chat 或首页', async ({ page }) => {
    await injectAuth(page)
    await page.goto('/login')
    // 已登录时应跳走（重定向到 / 或 /chat）
    await expect(page).not.toHaveURL(/\/login/, { timeout: 8_000 })
  })
})
