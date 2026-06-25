// Vitest 全局测试初始化：引入 jest-dom 自定义断言（toBeInTheDocument 等），
// 并在每个用例后自动清理已挂载的 React 组件。
import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => {
  cleanup()
})
