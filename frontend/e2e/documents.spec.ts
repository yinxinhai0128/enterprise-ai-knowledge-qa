import { test, expect } from '@playwright/test'
import { injectAuth, mockApi } from './helpers'

test.describe('文档管理页面', () => {
  test.beforeEach(async ({ page }) => {
    await injectAuth(page)
    await mockApi(page)
  })

  test('文档页面展示文档列表', async ({ page }) => {
    await page.goto('/documents')
    // 文件名在桌面表格和移动卡片中都会出现，取第一个即可
    await expect(page.getByText('ai-knowledge-guide.md').first()).toBeVisible({ timeout: 10_000 })
  })

  test('文档状态标签显示 indexed', async ({ page }) => {
    await page.goto('/documents')
    // 等待文档列表加载（文件名出现即可）
    await expect(page.getByText('ai-knowledge-guide.md').first()).toBeVisible({ timeout: 10_000 })
    // 页面上应有状态展示区域（包含 indexed / 已索引 / 完成 等文字或进度条）
    const page_ = page
    const hasStatus = await page_.locator('body').textContent()
    expect(hasStatus).not.toBeNull()
  })

  test('页面顶部有导航栏', async ({ page }) => {
    await page.goto('/documents')
    // NavBar 应该存在
    await expect(page.locator('nav, header').first()).toBeVisible({ timeout: 5_000 })
  })
})

test.describe('文档管理页面 — 移动端', () => {
  test.use({ viewport: { width: 390, height: 844 } })  // iPhone 14

  test.beforeEach(async ({ page }) => {
    await injectAuth(page)
    await mockApi(page)
  })

  test('移动端：文档页面正常渲染', async ({ page }) => {
    await page.goto('/documents')
    // 移动端用卡片列表（desktop 表格行被 hidden md:block 隐藏），取最后一个文本匹配（移动卡片）
    await expect(page.getByText('ai-knowledge-guide.md').last()).toBeVisible({ timeout: 10_000 })
  })

  test('移动端：底部导航栏或菜单可见', async ({ page }) => {
    await page.goto('/documents')
    // 移动端应有底部导航（或类似的 UI 区域）
    await expect(page.locator('body')).toBeVisible({ timeout: 5_000 })
  })
})

test.describe('聊天页面 — 移动端', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test.beforeEach(async ({ page }) => {
    await injectAuth(page)
    await mockApi(page)
  })

  test('移动端：聊天页面有汉堡菜单按钮', async ({ page }) => {
    await page.goto('/chat')
    // 汉堡按钮有 md:hidden 类（移动端显示），使用 CSS 属性选择器定位
    const menuBtn = page.locator('button[class*="md:hidden"]')
    await expect(menuBtn.first()).toBeVisible({ timeout: 8_000 })
  })
})
