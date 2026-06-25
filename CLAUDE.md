# 企业级 AI 知识问答系统 — Claude Code 协作规范

> 本文件被 Claude Code 和所有子 Agent 自动加载。
> 任何长流程改动必须遵守本规范，不得绕过。

---

## 项目快照

| 项目 | 值 |
|------|---|
| 后端 | FastAPI 0.138 + LangGraph 1.2.6 + LangChain 1.3（Agentic RAG） |
| 数据库 | SQLite（业务/检查点）+ ChromaDB 1.5.9（向量） |
| 前端 | React 18 + TypeScript + Vite 8 + Tailwind CSS v3 + shadcn/ui |
| 认证 | HS256 JWT，`AUTH_JWT_SECRET`≥32字符，严禁信任请求体 user_id |
| 端口 | 后端 8765，前端 5173 |
| 测试 | 后端 119 tests（pytest）；前端 35 tests（vitest） |
| CI | GitHub Actions：quality（lint/mypy/pytest/audit）+ frontend（tsc/vitest/build）+ docker-build |
| 生产基线 | HARNESS.md 阶段 0-12 全部 complete，阶段 12 验收报告在 `docs/audit/stage12-acceptance-2026-06-23.md` |

---

## 多 Agent 并行 Harness

### 角色分工（铁律）

```
主控（Controller）= 主线程
  ├─ 制定契约/规范
  ├─ 派发 → 执行 Agent（worktree 隔离）
  ├─ 派发 → 检查 Agent（独立 worktree，不共享执行上下文）
  ├─ 路由反馈 → 执行 Agent 修复
  └─ 合并 → commit/push → 向用户汇报

主控不写业务实现代码，不做权威验收（避免自改自查）。
```

### 启动检查清单

执行 Agent 开始前必须：
1. 读取相关文件（禁止凭记忆写 API）
2. 确认 `.venv` 是 Python 3.12+（`.\\.venv\\Scripts\\python.exe --version`）
3. 数据库结构变更前先备份（`Copy-Item storage storage_backup -Recurse`）

### 并行任务调度示例

```python
# 主控在同一条消息中同时发出，真正并行：
Agent(isolation="worktree", description="后端实现-执行", prompt=EXECUTOR_PROMPT)
Agent(isolation="worktree", description="前端实现-执行", prompt=EXECUTOR_PROMPT)
# 两个 Agent 完成后再派发：
Agent(isolation="worktree", description="集成验收-检查", prompt=CHECKER_PROMPT)
```

---

## 开发守则

### 安全红线（任何 Agent 不得违反）

- 禁止在聊天/日志/代码注释中打印真实 Key、Token、JWT Secret
- 禁止信任请求体中的 `user_id`；身份只取自已验签 JWT claims
- 禁止跳过 `--no-verify`、`--no-gpg-sign` 提交钩子
- 禁止在生产模式下暴露 `/docs`、`/redoc`、`/openapi.json`（未鉴权）
- 禁止启动/暴露 Chroma HTTP Server（CVE-2026-45829，例外到期 2026-07-22）

### 测试守则

- 测试强制关闭 LangSmith：`LANGSMITH_TRACING=false`、`LANGCHAIN_TRACING_V2=false`
- 测试不得使用真实 API Key；LLM/Embedding/Vectorstore 全部 mock
- 测试结束后 `kb_test_*` 临时目录计数必须为零（`scripts/check_test_cleanup.py`）
- 新增功能必须同时新增测试，不允许只写实现

### 代码守则

- 先读文件再写，禁止凭旧版 LangChain/LangGraph 记忆写 API
- 不添加超出任务要求的功能、重构或抽象
- `EvidenceSource.sources` 只能来自真实检索 artifact，禁止正则解析模型输出
- 审计写入故障：fail-closed（503），不能静默失败

---

## 常用命令

```powershell
# 后端测试
.\.venv\Scripts\python.exe -m pytest -q

# 后端 lint/type
.\.venv\Scripts\python.exe -m ruff check app tests scripts
.\.venv\Scripts\python.exe -m mypy

# 后端一致性巡检
.\.venv\Scripts\python.exe -m app.commands.check_consistency

# 前端测试
cd frontend && npm test

# 前端类型+构建
npx tsc --noEmit && npm run build

# 启动开发环境（一键）
.\start.ps1

# 生成开发 Token（仅 development 模式）
.\.venv\Scripts\python.exe scripts\create_dev_token.py --user dev --roles user admin
```

---

## 已知约束与经验教训

| 问题 | 根因 | 解法 |
|------|------|------|
| 浏览器翻译崩溃 | Edge 内置翻译修改 DOM 文字节点，React `removeChild` 崩溃 | `index.html` 加 `translate="no"` + ErrorBoundary |
| SSE disconnect 租约泄漏 | Starlette `generator.finally` 在断连时不执行 | `asyncio.ensure_future` 分离清理 + `asyncio.shield` 保护 DB 写 |
| 认证水合竞态 | Zustand `hydrate()` 在 `useEffect` 里，第一渲染 ProtectedRoute 看到 null | Zustand store 同步初始化（`buildAuthFields(getToken())` 在创建时调用） |
| 多轮拒答 | Agent 第 2 轮跳过 `search_knowledge_base` | system prompt 强制每轮必须检索 |
| AdminPage Rules of Hooks | `navigate`/`toast` 在 render 期间调用 | 移到 `useEffect` + `enabled` gate |
| Windows Docker Engine | Docker Desktop 可能处于 `starting` 状态 | 重启 Windows 恢复；CI 使用 GitHub Actions 干净环境 |
| 源卡片空白 + 引用重复 | `invalidateQueries` 重取历史覆盖了带 sources 的本地消息 | `hydratedSessionRef` 防二次水合 + 移除 invalidate |

---

## 待优化方向（已完成基础，可按需执行）

以下方向均可作为下一个 Harness 任务启动：

- **引用高亮**：`EvidenceSource` 加 `snippet` 字段（检索时截取 200 字符），SourceCard 展示原文片段
- **Playwright E2E**：login → chat → upload → answer with sources 完整流程自动化
- **知识库测试数据**：GitHub 项目 README 批量导入，丰富演示内容
- **检索质量**：HyDE（假设文档向量化）、cross-encoder 重排、相关性分数校准
- **性能**：`aiosqlite` 异步 DB、Redis 会话缓存、答案 embedding 缓存
- **多租户管理**：租户注册/管理 API + 前端管理页
- **企业 SSO**：OIDC/SAML IdP 对接适配层（现有 AuthContext 抽象已预留）
- **导出功能**：对话历史 PDF/Markdown 导出
- **批量上传**：支持同时上传多文件，后端 Job 并行处理

---

## 版本记录

| 日期 | 里程碑 |
|------|--------|
| 2026-06-22 | HARNESS 阶段 0-7 完成（安全基线→数据治理） |
| 2026-06-23 | HARNESS 阶段 8-12 完成；119 tests；生产候选验收通过 |
| 2026-06-24 | 前端 SSE 真流式输出上线；35 前端测试通过；推送 GitHub |
| 2026-06-25 | CLAUDE.md 建立；Multi-Agent Parallel Harness 技能创建 |
