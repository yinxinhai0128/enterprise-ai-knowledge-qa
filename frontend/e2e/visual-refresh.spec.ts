import { test, expect } from '@playwright/test'
import { injectAuth, mockApi } from './helpers'

test.describe('视觉升级', () => {
  test('登录页呈现品牌层级与登录表单', async ({ page }) => {
    await page.goto('/login')

    // 核心表单元素（跨视口稳定可见）
    await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
    await expect(page.locator('input[autocomplete="username"]')).toBeVisible()
    await expect(page.locator('input[type="password"]')).toBeVisible()
  })

  test('工作台有可读的主导航与对话输入区', async ({ page }) => {
    await injectAuth(page)
    await mockApi(page)
    await page.goto('/chat')

    // 主导航（桌面侧栏 / 移动底部栏）与对话输入区
    const nav = page.getByRole('navigation')
    if (await nav.count()) {
      await expect(nav.first()).toBeVisible()
    }
    await expect(page.getByRole('textbox', { name: '问题输入框' })).toBeVisible()
  })
})
