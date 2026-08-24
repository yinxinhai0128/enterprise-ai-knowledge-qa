import { test, expect } from '@playwright/test'
import { injectAuth, mockApi } from './helpers'

test.describe('视觉升级', () => {
  test('登录页呈现可信知识工作台的品牌层级', async ({ page }) => {
    await page.goto('/login')

    await expect(page.getByText('企知问答 EKQA').first()).toBeVisible()
    await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
    await expect(page.locator('input[autocomplete="username"]')).toBeVisible()
    await expect(page.locator('input[type="password"]')).toBeVisible()
  })

  test('桌面工作台有可读的主导航与对话输入区', async ({ page }) => {
    await injectAuth(page)
    await mockApi(page)
    await page.goto('/chat')

    await expect(page.getByRole('navigation').or(page.getByText('EKE2')).first()).toBeVisible()
    await expect(page.getByRole('textbox', { name: '问题输入框' })).toBeVisible()
  })
})
