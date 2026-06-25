// 模块级导航助手：让 axios 拦截器等 React 组件外的代码也能触发 SPA 导航，
// 避免使用 window.location.href 造成整页刷新（丢失状态、白屏）。

type NavFn = (path: string) => void

let navigateFn: NavFn | null = null

/** App 启动时注入 React Router 的 navigate */
export function setNavigator(fn: NavFn): void {
  navigateFn = fn
}

/** 任意位置调用：优先走 SPA 导航，未注册时降级为整页跳转 */
export function navigateTo(path: string): void {
  if (navigateFn) navigateFn(path)
  else window.location.href = path
}
