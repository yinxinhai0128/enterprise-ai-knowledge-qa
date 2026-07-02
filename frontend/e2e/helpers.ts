import type { Page } from '@playwright/test'

const TOKEN_KEY = 'ekqa_token'

// 在 Node.js 环境中构造 base64url（Playwright test runner 跑在 Node.js）
function b64url(obj: object): string {
  return Buffer.from(JSON.stringify(obj))
    .toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
}

// 构造一个 exp 在 1 小时后的假 JWT（格式合法，但签名无效）
// auth store 的 parseTokenPayload / isTokenExpired 只看格式和 exp 字段
const FAKE_TOKEN = [
  b64url({ alg: 'HS256', typ: 'JWT' }),
  b64url({
    sub: 'e2e-test-user',
    tenant_id: 'e2e-tenant',
    roles: ['user', 'admin'],
    iss: 'e2e-idp',
    aud: 'kb',
    iat: Math.floor(Date.now() / 1000),
    exp: Math.floor(Date.now() / 1000) + 3600,
  }),
  'e2e-fake-signature',
].join('.')

/** 注入假 Token 到 localStorage，模拟已登录状态（addInitScript 在页面 JS 执行前运行） */
export async function injectAuth(page: Page): Promise<void> {
  await page.addInitScript(
    ({ key, token }: { key: string; token: string }) => {
      localStorage.setItem(key, token)
    },
    { key: TOKEN_KEY, token: FAKE_TOKEN },
  )
}

// 后端 API 基础 URL（与 frontend/src/api/client.ts 的默认值一致）
const API_BASE = 'http://127.0.0.1:8765'

/** 拦截所有 API 请求并返回测试用假数据 */
export async function mockApi(page: Page): Promise<void> {
  // 文档列表（GET /documents 和 POST /documents/upload）
  await page.route(`${API_BASE}/documents*`, (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 1,
            tenant_id: 'e2e-tenant',
            uploaded_by: 'e2e-test-user',
            filename: 'ai-knowledge-guide.md',
            status: 'indexed',
            chunk_count: 8,
            error_msg: null,
            created_at: new Date().toISOString(),
          },
        ]),
      })
    } else {
      route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({ id: 2, filename: 'test-upload.txt', status: 'pending' }),
      })
    }
  })

  // 流式问答 POST /qa/stream
  await page.route(`${API_BASE}/qa/stream`, (route) => {
    const sseBody =
      'event: token\ndata: {"text":"根据"}\n\n' +
      'event: token\ndata: {"text":"知识库内容，"}\n\n' +
      'event: token\ndata: {"text":"这是测试回答。"}\n\n' +
      'event: done\ndata: ' +
      JSON.stringify({
        answer: '根据知识库内容，这是测试回答。',
        sources: [
          {
            doc_id: 1,
            chunk_id: 'e2e-tenant:1:0:abc12345',
            source: 'ai-knowledge-guide.md',
            page: null,
            sheet_name: null,
            distance: 0.3,
            relevance: 0.77,
            snippet: '这是被引用的原文片段，用于展示引用高亮功能是否正常工作。',
          },
        ],
        refused: false,
        need_human: false,
        human_task_id: null,
      }) +
      '\n\n'
    route.fulfill({
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'X-Request-ID': 'e2e-req-001',
      },
      body: sseBody,
    })
  })

  // 非流式问答（兜底）POST /qa/ask
  await page.route(`${API_BASE}/qa/ask`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        answer: '根据知识库内容，这是测试回答。',
        sources: [],
        refused: false,
        need_human: false,
        human_task_id: null,
      }),
    })
  })

  // 会话历史 GET /qa/history/:session_id
  await page.route(`${API_BASE}/qa/history/**`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ session_id: 'e2e-sess', messages: [] }),
    })
  })

  // 用户列表
  await page.route(`${API_BASE}/admin/users`, (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 1,
            username: 'e2e-test-user',
            tenant_id: 'e2e-tenant',
            roles: ['user', 'admin'],
            is_active: true,
            created_at: new Date().toISOString(),
          },
        ]),
      })
    } else {
      route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 2,
          username: 'new-user',
          tenant_id: 'e2e-tenant',
          roles: ['user'],
          is_active: true,
          created_at: new Date().toISOString(),
        }),
      })
    }
  })

  // 管理统计（其余 admin 路由兜底）
  await page.route(`${API_BASE}/admin/**`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        documents: { total: 1, indexed: 1, failed: 0 },
        qa: { total: 0, refused_rate: 0, human_rate: 0 },
      }),
    })
  })

  // 健康检查
  await page.route(`${API_BASE}/health/**`, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"ok"}' })
  })
}
