# 企业 AI 知识问答系统 — 生产交付 Harness

> 前置：安全加固 Harness（HARNESS.md）12 个阶段已全部 complete（2026-06-23）。
> 本 Harness 目标：将项目从"本地可运行"提升为"可交付他人在真实业务场景中使用"。
> 执行原则：同 HARNESS.md，每个阶段必须验收证据通过才进入下一阶段；多 Agent 并行阶段须各自独立验收。

---

## 1. 最终目标

完成后，任何有网络权限的员工可以：

1. 通过企业账号登录（对接现有 IdP 或账号密码）。
2. 用中文提问，得到基于真实公司文档的有来源回答。
3. 对回答质量打分（👍/👎），管理员可查看使用报表。
4. 管理员在 Web 界面管理知识库和敏感策略，无需 SSH。

完成标志：**P1~P5 全部 complete，且真实用户在真实服务器上可用**。

---

## 2. 阶段状态表

| 阶段 | 内容 | 依赖 | 状态 | 验收证据 |
|------|------|------|------|----------|
| P1 | 生产网络层：Nginx + HTTPS | 无 | pending | |
| P2 | 用户体验：回答反馈 + 会话搜索 | 无 | pending | |
| P3 | 管理员工具：使用量报表 + 知识库批量导入 | 无 | pending | |
| P4 | 企业认证对接 | 用户决策：选择 IdP 类型 | blocked | 等待：企业微信/钉钉/LDAP/账号密码 |
| P5 | 运营通知：人工审核 + 告警推送 | 用户决策：选择通知渠道 | blocked | 等待：企业微信机器人/钉钉/邮件 |

> P1/P2/P3 可多 Agent 并行执行，P4/P5 等用户决策后启动。

---

## 3. 执行铁律（继承自 HARNESS.md）

1. 不输出、不提交任何真实 Key、Token、Secret。
2. 测试必须强制关闭 LangSmith 和真实模型调用。
3. 每阶段完成后必须运行完整测试套件并记录结果。
4. 不通过删断言、跳测试制造"全绿"。
5. 修改数据库结构前必须备份。
6. 每阶段完成后更新本文档状态表与执行日志。

---

## 4. 阶段 P1：生产网络层

### 目标
让项目可以在公网安全访问：HTTPS 终止、静态资源服务、后端代理、安全响应头。

### 任务

- [ ] 新增 `nginx/nginx.conf`：
  - HTTPS 443 终止（证书路径通过环境变量注入）
  - HTTP 80 强制重定向到 443
  - `/api/` → 后端 8765
  - `/` → 前端静态文件（`frontend/dist/`）
  - 安全响应头：HSTS、X-Frame-Options、CSP、X-Content-Type-Options
  - 限流：`limit_req_zone` 防爆破
- [ ] 新增 `nginx/ssl/` 目录说明（证书需运维放置，不提交）
- [ ] 更新 `docker-compose.prod.yml`：
  - 新增 nginx 服务，80/443 对外，后端/Worker 仅内部通信
  - 所有服务加 `restart: unless-stopped`
  - 健康检查指向 nginx
- [ ] 新增 `scripts/build_frontend.sh`：`npm run build` 并输出到 `frontend/dist/`
- [ ] 更新 `.env.example`：新增 `SSL_CERT_PATH`、`SSL_KEY_PATH`、`DOMAIN`
- [ ] 更新 `docs/DEPLOYMENT.md`：加入 HTTPS/Nginx 部署步骤和证书申请指引

### 验收门

- [ ] `nginx -t` 配置语法通过（用 Docker 运行检查）
- [ ] `docker compose -f docker-compose.prod.yml config --quiet` 通过
- [ ] 本地用自签名证书测试：HTTPS 请求可到达后端，HTTP 跳转 HTTPS
- [ ] 安全响应头在响应中存在
- [ ] `pytest -q` 仍全绿（后端无回归）

---

## 5. 阶段 P2：用户体验完善

### 目标
让用户可以对回答打分，并能搜索历史会话。

### 子任务 P2-A：回答质量反馈

**后端：**
- [ ] 新增 `POST /qa/feedback` 端点：接收 `{record_id, rating: "up"|"down", comment?: str}`
- [ ] `chat_records` 表新增 `feedback_rating`（nullable varchar）、`feedback_comment`（nullable text）
- [ ] 只允许回答的提问者提交反馈，且只能提交一次（幂等：重复提交覆盖）
- [ ] 管理员可通过 `GET /admin/feedback-stats` 获取好评率、差评率、分类分布

**前端：**
- [ ] `AssistantBubble` 回答完成后显示 👍/👎 按钮（streaming 期间隐藏）
- [ ] 点击后调用 `/qa/feedback`，按钮变为已选中状态，不可重复点击
- [ ] 差评后可选填文字反馈（可折叠输入框，最多 200 字）
- [ ] 管理员页面新增"反馈统计"卡片：好评率、本周差评数、最近差评列表

### 子任务 P2-B：会话搜索

**后端：**
- [ ] 新增 `GET /qa/sessions/search?q=关键词` 端点：在 `chat_records.question` 中全文搜索（SQLite FTS5 或 LIKE）
- [ ] 结果按时间倒序，返回 session_id、首句问题、匹配问题、时间

**前端：**
- [ ] 左侧会话列表顶部添加搜索框（展开时显示，空时折叠）
- [ ] 输入关键词实时搜索（300ms 防抖），结果高亮关键词
- [ ] 点击搜索结果跳转到对应会话

### 验收门

- [ ] 提交反馈后刷新，按钮状态持久化（从数据库恢复）
- [ ] 非本人无法提交他人回答的反馈（403）
- [ ] 搜索"请假"能找到包含该词的历史会话
- [ ] `pytest -q` 新增反馈和搜索测试，全绿

---

## 6. 阶段 P3：管理员运营工具

### 目标
管理员无需 SSH 即可查看系统运行状况和管理知识库内容。

### 子任务 P3-A：使用量报表

**后端：**
- [ ] 新增 `GET /admin/reports/usage?days=7` 端点：
  - 每日问答量、拒答率、人工率、反馈好评率
  - Top 10 活跃用户（按问答数）
  - Top 5 最常被检索的文档（按 sources 出现次数）
  - 数据来源：`chat_records` + `usage_daily`

**前端（AdminPage）：**
- [ ] 新增"使用报表"标签页
- [ ] 折线图：过去 7 天每日问答量（用 recharts 或 CSS 手画简单图表）
- [ ] 关键指标卡：总问答数、今日、拒答率、好评率
- [ ] 热门文档 Top 5 列表
- [ ] 活跃用户 Top 10 列表（只显示 user_id 前 6 位 + `***`）

### 子任务 P3-B：知识库批量导入工具

- [ ] 新增 `scripts/bulk_import.py`：
  - 读取目录下所有 PDF/DOCX/XLSX/TXT 文件
  - 通过 API（带 admin token）批量上传
  - 显示进度、失败重试、最终汇总报告
  - 支持 `--dry-run` 预览
- [ ] 新增 `scripts/export_kb_report.py`：
  - 导出知识库现有文档列表（id、文件名、状态、切片数）为 CSV

### 验收门

- [ ] 有至少 5 条问答记录时，报表 API 返回正确数据
- [ ] 前端报表页面正常渲染，数值与 API 一致
- [ ] `bulk_import.py --dry-run` 扫描目录不上传
- [ ] `pytest -q` 新增报表 API 测试，全绿

---

## 7. 阶段 P4：企业认证对接（blocked — 等待决策）

### 需要用户决定

从以下选项选一个：

| 选项 | 适用场景 | 实现复杂度 |
|------|----------|-----------|
| A. 账号密码（内部自建） | 无现有 IdP，小团队 | 低 |
| B. 企业微信 OAuth | 已在用企业微信 | 中 |
| C. 钉钉 OAuth | 已在用钉钉 | 中 |
| D. LDAP/AD | 有企业目录服务 | 高 |

### 决策后实施

- [ ] 新增对应 OAuth/LDAP 认证中间件
- [ ] 登录页替换为对应企业登录入口
- [ ] 从 IdP claims 映射 `user_id`、`tenant_id`、`roles`
- [ ] 废弃 `create_dev_token.py`（或仅保留 development 模式）
- [ ] 更新 `.env.example` 和部署文档

---

## 8. 阶段 P5：运营通知（blocked — 等待决策）

### 需要用户决定

选择人工审核任务和系统告警的通知渠道：

| 选项 | 说明 |
|------|------|
| A. 企业微信机器人 | Webhook，5 分钟接入 |
| B. 钉钉机器人 | Webhook，5 分钟接入 |
| C. 邮件（SMTP） | 需 SMTP 配置 |

### 决策后实施

- [ ] 新增通知服务：`app/services/notification.py`
- [ ] `HumanTask` 创建时发送通知（含问题摘要、类别、审核链接）
- [ ] `/health/ready` 失败超过阈值时发送告警
- [ ] 通知失败不影响主流程（异步非阻塞）

---

## 9. 执行日志

> 新记录追加在此处，不覆盖历史。

### 2026-06-28 - Production Harness 创建

- 状态：pending
- 前置：安全加固 HARNESS.md 12 阶段已全部 complete（127 tests passed）。
- P1/P2/P3 无外部依赖，可多 Agent 并行立即开始。
- P4/P5 等用户选择 IdP 类型和通知渠道后启动。
- 下一步：派出 3 个并行 Agent 分别执行 P1、P2、P3。
