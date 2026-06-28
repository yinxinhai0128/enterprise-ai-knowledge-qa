// 模块级导航助手：让非 React 代码（axios 拦截器等）也能触发 SPA 导航。
// 导入 router 单例直接调用 navigate，避免 window.location.href 整页刷新。
import { router } from '@/router'

export function navigateTo(path: string): void {
  router.navigate(path)
}
