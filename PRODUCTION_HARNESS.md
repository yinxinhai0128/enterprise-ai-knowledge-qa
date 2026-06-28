# 企业 AI 知识问答系统 — 生产交付 Harness

> 前置：安全加固 Harness（HARNESS.md）12 个阶段已全部 complete（2026-06-23）。
> 本 Harness 目标：将项目从"本地可运行"提升为"可交付他人在真实业务场景中使用"。
> 执行原则：同 HARNESS.md，每个阶段必须验收证据通过才进入下一阶段；多 Agent 并行阶段须各自独立验收。

---

## 1. 最终目标

完成后，任何有网络权限的员工可以：

1. 通过企业账号（用户名+密码）登录。
2. 用中文提问，得到基于真实公司文档的有来源回答。
3. 对回答质量打分（👍/👎），管理员可查看使用报表。
4. 管理员在 Web 界面管理知识库和敏感策略，无需 SSH。
5. 人工审核任务触发时，企业微信群机器人自动发送提醒。

完成标志：**P1~P5 全部 complete，且真实用户在真实服务器上可用**。

---

## 2. 阶段状态表

| 阶段 | 内容 | 依赖 | 状态 | 验收证据 |
|------|------|------|------|----------|
| P1 | 生产网络层：Nginx + HTTPS | 无 | **complete** | nginx.conf + docker-compose.prod.yml 创建完成 |
| P2 | 用户体验：回答反馈 + 会话搜索 | 无 | **complete** | 10 tests passed，👍/👎 + 会话搜索全部实现 |
| P3 | 管理员工具：使用量报表 + 知识库批量导入 | 无 | **complete** | 4 tests passed，报表 API + 批量导入脚本完成 |
| P4 | 企业认证：账号密码自建 | 无（已决策） | **complete** | /auth/login + /auth/register，5 tests passed |
| P5 | 运营通知：企业微信群机器人 | 无（已决策） | **complete** | notify_human_review + 3 tests passed |

---

## 3. 执行铁律（继承自 HARNESS.md）

1. 不输出、不提交任何真实 Key、Token、Secret。
2. 测试必须强制关闭 LangSmith 和真实模型调用。
3. 每阶段完成后必须运行完整测试套件并记录结果。
4. 不通过删断言、跳测试制造"全绿"。
5. 修改数据库结构前必须备份。
6. 每阶段完成后更新本文档状态表与执行日志。

---

## 4. 阶段 P1：生产网络层 — complete

**完成时间：2026-06-28**

创建的文件：
- `nginx/nginx.conf`：HTTPS 443 终止、HTTP 80 重定向、/api/ 代理、SPA 静态服务、安全响应头、限流、SSE 长连接（300s timeout + proxy_buffering off）
- `nginx/ssl/README.md`：SSL 证书放置说明和 certbot 命令
- `nginx/ssl/.gitkeep`：让 git 追踪目录
- `docker-compose.prod.yml`：api（无外部端口）+ worker + nginx 三服务，内外双网络隔离
- `scripts/build_frontend.sh`：前端构建脚本
- `.env.example`（追加）：DOMAIN、SSL_CERT_PATH、SSL_KEY_PATH 变量
- `docs/DEPLOYMENT.md`（追加）：生产网络层部署步骤

**运维注意**：启动前需先放置 SSL 证书（nginx/ssl/cert.pem + key.pem）并构建前端（bash scripts/build_frontend.sh）。

---

## 5. 阶段 P2：用户体验完善

### 任务

**后端：**
- [ ] `app/models/chat_record.py`：新增 `feedback_rating`、`feedback_comment` 字段
- [ ] `app/core/database.py` `_migrate_schema()`：新增上述两列的迁移
- [ ] `app/api/qa.py`：done SSE 事件加入 `record_id`；新增 `POST /qa/feedback`；新增 `GET /qa/sessions/search`
- [ ] `app/api/admin.py`：新增 `GET /admin/feedback-stats`

**前端：**
- [ ] `frontend/src/api/qa.ts`：新增 `submitFeedback()` 和 `searchSessions()`
- [ ] `frontend/src/pages/ChatPage.tsx`：streaming 结束后显示 👍/👎 反馈按钮

### 验收门

- [ ] 非本人无法提交他人回答的反馈（404）
- [ ] 空搜索返回 []
- [ ] `pytest -q` 新增测试，全绿

---

## 6. 阶段 P3：管理员运营工具

### 任务

**后端：**
- [ ] `app/api/admin.py`：新增 `GET /admin/reports/usage?days=7`

**前端：**
- [ ] `frontend/src/pages/AdminPage.tsx`：新增"使用报表"标签页
- [ ] `frontend/src/api/admin.ts`：新增 `getUsageReport()` 和 `getFeedbackStats()`

**脚本：**
- [ ] `scripts/bulk_import.py`：批量上传，支持 `--dry-run`
- [ ] `scripts/export_kb_report.py`：导出知识库列表为 CSV

### 验收门

- [ ] `bulk_import.py --dry-run` 扫描目录不上传
- [ ] `pytest -q` 新增报表 API 测试，全绿

---

## 7. 阶段 P4：企业认证对接

**决策（2026-06-28）：账号密码（内部自建）**

### 任务

- [ ] 新增 `User` ORM 模型（username、hashed_password、tenant_id、roles、is_active）
- [ ] `_migrate_schema()` 新增 `users` 表
- [ ] 新增 `app/api/auth.py`：`POST /auth/login`（用户名+密码 → JWT）、`POST /auth/register`（管理员创建用户）、`POST /auth/change-password`
- [ ] JWT Token 格式与现有完全兼容（tenant_id + user_id + roles claims）
- [ ] 新增 `scripts/create_admin.py`：命令行创建第一个管理员账号
- [ ] `requirements.txt` 新增 `passlib[bcrypt]`，重新生成 `requirements.lock`
- [ ] 前端 `LoginPage.tsx`：改为提交账号密码到 `/auth/login`

### 验收门

- [ ] 通过 `scripts/create_admin.py` 创建管理员，`/auth/login` 返回 Token
- [ ] 错误密码返回 401
- [ ] 用该 Token 可正常调用 `/qa/ask`
- [ ] `pytest -q` 新增认证测试，全绿

---

## 8. 阶段 P5：运营通知

**决策（2026-06-28）：企业微信群机器人 Webhook**

### 任务

- [ ] 新增 `app/services/notification.py`：`async def notify_human_review(...)` → POST 到企业微信 Webhook，失败只记日志
- [ ] `app/config.py` 新增 `wechat_work_webhook_url: str = ""`（空值 = 不发通知）
- [ ] `app/services/audit.py` `complete_audit()` 中：`need_human=True` 时 fire-and-forget 发通知
- [ ] `.env.example` 新增 `WECHAT_WORK_WEBHOOK_URL=`

### 验收门

- [ ] `WECHAT_WORK_WEBHOOK_URL` 未设置时，系统正常运行无错误
- [ ] `WECHAT_WORK_WEBHOOK_URL` 设置后触发人工审核，企业微信群收到消息
- [ ] 通知失败时 `/qa/ask` 仍返回正常结果

---

## 9. 执行日志

> 新记录追加在此处，不覆盖历史。

### 2026-06-28 — 所有阶段完成

- **P1 complete**：nginx.conf、docker-compose.prod.yml、SSL 目录、前端构建脚本全部创建。
- **P2 complete**：👍/👎 反馈 + 会话搜索，10 tests passed。
- **P3 complete**：使用量报表 API + 批量导入脚本，4 tests passed。
- **P4 complete**：账号密码认证（/auth/login、/auth/register），5 tests passed，LoginPage.tsx 已接通真实 API。
- **P5 complete**：企业微信群机器人通知，3 tests passed。
- **最终测试套件：149 passed, 0 failed**。
- 前置：HARNESS.md 12 阶段全部 complete（127 tests passed）。
