import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    clearMocks: true,
    restoreMocks: true,
    // 排除 Playwright E2E 测试和配置文件（由 playwright test 单独运行）
    exclude: ['**/node_modules/**', '**/e2e/**', '**/playwright.config.*'],
  },
})
