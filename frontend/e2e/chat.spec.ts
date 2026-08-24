import { test, expect } from '@playwright/test'
import { injectAuth, mockApi } from './helpers'

test.describe('聊天界面', () => {

  // 等待历史加载与 DOM 稳定后再交互（避免 react-query 重挂载导致 detached）
  async function readyTextarea(page: import('@playwright/test').Page) {
    await page.waitForLoadState('domcontentloaded')
    const box = page.locator('textarea').last()
    await box.waitFor({ state: 'visible', timeout: 15_000 })
    await expect(box).toBeEnabled({ timeout: 15_000 })
    return box
  }

  test.beforeEach(async ({ page }) => {
    await injectAuth(page)
    await mockApi(page)
  })

  test('已登录访问首页 → 重定向到聊天界面', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveURL(/\/chat/, { timeout: 8_000 })
  })

  test('聊天页面有消息输入框和发送按钮', async ({ page }) => {
    await page.goto('/chat')
    // textarea 或带发送功能的 input
    await expect(page.locator('textarea').last()).toBeVisible({ timeout: 8_000 })
  })

  test('发送问题 → 显示回答内容', async ({ page }) => {
    await page.goto('/chat')
    const textarea = await readyTextarea(page)
    await textarea.fill('什么是 RAG？')

    // 点击发送按钮（找 button 中包含 Send/发送/箭头图标的）
    const sendBtn = page.getByRole('button', { name: '发送问题' })
    await sendBtn.click()

    // 等待回答文字出现
    await expect(page.getByText('根据', { exact: false })).toBeVisible({ timeout: 15_000 })
  })

  test('回答完成后显示来源卡片', async ({ page }) => {
    await page.goto('/chat')
    const textarea = await readyTextarea(page)
    await textarea.fill('请介绍企业知识库系统')
    await page.keyboard.press('Enter')

    // 等待"参考来源"出现
    await expect(page.getByText(/参考了/)).toBeVisible({ timeout: 15_000 })
  })

  test('展开来源卡片 → 显示原文引用片段', async ({ page }) => {
    await page.goto('/chat')
    await page.locator('textarea').last().fill('测试引用高亮')
    await page.keyboard.press('Enter')

    // 等待参考来源按钮出现并点击展开
    const sourceBtn = page.getByText(/参考了/).first()
    await expect(sourceBtn).toBeVisible({ timeout: 15_000 })
    await sourceBtn.click()

    // 展开后应显示引用片段（italic 斜体文字）
    await expect(page.getByText('这是被引用的原文片段', { exact: false })).toBeVisible({ timeout: 5_000 })
  })

  test('Enter 键可以发送消息', async ({ page }) => {
    await page.goto('/chat')
    const textarea = await readyTextarea(page)
    await textarea.fill('快捷键测试')
    await textarea.press('Enter')
    // 消息被发送（用户消息气泡中出现该文字）
    await expect(page.getByText('快捷键测试', { exact: true }).first()).toBeAttached({ timeout: 5_000 })
  })
})
