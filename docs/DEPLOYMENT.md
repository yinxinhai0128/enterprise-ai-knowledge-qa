# 安全部署与配置手册

> 当前状态：阶段 11 文档化完成前的生产候选，尚未通过 HARNESS 阶段 12 最终验收。不得把本手册理解为公网直接暴露许可或生产可用性承诺。

## 1. 三套配置

| 项目 | development | test | production |
|---|---|---|---|
| `APP_ENV` | `development` | 测试进程环境覆盖 | `production` |
| 监听 | 默认 `127.0.0.1:8000` | ASGITransport，不监听端口 | 容器内 `0.0.0.0:8000`，宿主只绑定 `127.0.0.1`，由 TLS 反向代理接入 |
| API 文档 | 开启 | 可生成 schema | 关闭 `/docs`、`/redoc`、`/openapi.json` |
| 身份 | 企业 IdP Token；可用本地 development Token 工具 | 假 JWT Secret 和测试 Token | 只允许企业 IdP；Secret Manager 注入，不把秘密写入镜像或 Git |
| 模型 | 百炼真实 Key，可执行人工连通性自检 | 假模型/假向量，禁止外网 | 经审批的百炼 Key、精确模型 ID、费用阈值 |
| LangSmith | 默认关闭 | 强制关闭且网络守卫拦截 | 默认关闭；只有治理门全部通过才允许采样 |
| 数据 | 本地 `storage/`、`chroma_db/` | 每次运行独立 `kb_test_*` | 独立持久卷、维护窗口备份、访问控制和监控 |
| 文件扫描 | 默认扫描器仅供开发 | 测试替身 | 必须接入实际 MalwareScanner，并设 `MALWARE_SCAN_REQUIRED=true` |

`.env.example` 是配置字段模板，不是生产 Secret 分发机制。开发可复制为 `.env`；生产应由编排器或 Secret Manager 注入等价环境变量。

## 2. 运行前检查

1. CPython 3.12+，不得使用带旧 LangChain 的 Anaconda base。
2. 运行依赖必须通过 `python -m pip install --require-hashes -r requirements.lock` 安装。
3. `DASHSCOPE_API_KEY` 已轮换且仅授予所需模型；`LLM_MODEL=qwen3.6-plus` 和 `EMBED_MODEL=text-embedding-v3` 必须是当前账号可用的精确 ID。
4. `AUTH_JWT_SECRET` 至少 32 个随机字符；生产值不得等于示例值。
5. `LANGCHAIN_TRACING_V2=false`，除非已完成 `LANGSMITH_DATA_GOVERNANCE.md` 的全部审批门。
6. 生产必须有 TLS 反向代理、防火墙、备份、告警接收人和实际恶意软件扫描器；8000 不直接暴露到局域网或公网。
7. 不启动 Chroma HTTP Server；只使用本进程嵌入式持久化集合。

## 3. 源码启动

PowerShell：

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements.lock
Copy-Item .env.example .env  # 仅首次；已有 .env 时禁止覆盖
# 编辑 .env：填真实 Key、随机 JWT Secret，并保持 APP_HOST=127.0.0.1
python test_connection.py
uvicorn app.main:app
```

第二个已激活虚拟环境的终端启动 Worker：

```powershell
python -m app.worker
```

检查 `GET http://127.0.0.1:8000/health/live` 和 `/health/ready` 均为 200。`test_connection.py` 会产生真实 LLM/Embedding 调用，只用于人工连通性验收，不属于自动化测试。

## 4. Token 获取

服务只验证 Token，不提供登录或生产 Token 签发接口。生产 Token 必须从企业 IdP/OIDC 网关取得，并包含：

- `sub`：用户 ID；
- `tenant_id`：租户 ID；
- `roles`：至少一个角色；业务接口为 `user`，管理接口为 `admin`；
- 与配置相同的 `iss`、`aud`，以及有效的 `iat`、`exp`；
- HS256 签名。

本地 `APP_ENV=development` 时可签发最长 1 小时的短期 Token：

```powershell
$env:TOKEN = python scripts\create_dev_token.py --roles user --ttl-seconds 900
$env:ADMIN_TOKEN = python scripts\create_dev_token.py --roles admin --ttl-seconds 900
```

该工具在 `test`/`production` 环境硬失败，不显示签名 Secret。Token 本身是凭据，不得粘贴到工单、日志或聊天。

## 5. Docker Compose

```powershell
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Compose 同时运行 API 和 Worker，挂载 `storage/`、`chroma_db/`、`logs/`，使用 UID/GID 10001、只读根文件系统、移除 capabilities，并把宿主端口限制为 `127.0.0.1`。API healthcheck 使用 `/health/ready`；Worker 在 API ready 后启动。

生产入口应为：`客户端 → 企业 TLS 网关/WAF → 身份系统签发 Token → API 本机/私网端口`。反向代理必须限制上传体积、设置连接超时并保留 `X-Request-ID`，但不能替代应用 JWT、租户过滤或文件校验。

## 6. API 与访问要求

| 方法 | 路径 | 访问要求 |
|---|---|---|
| GET | `/health`, `/health/live`, `/health/ready`, `/metrics` | 无 JWT；仅暴露聚合/健康信息，仍应受网络边界保护 |
| POST | `/documents/upload` | `user` |
| GET | `/documents`, `/documents/{doc_id}`, `/documents/{doc_id}/jobs` | `user` |
| POST | `/documents/{doc_id}/retry`, `/documents/{doc_id}/cancel`, `/documents/{doc_id}/reindex` | `user` |
| DELETE | `/documents/{doc_id}` | `user` |
| POST | `/qa/ask` | `user` |
| POST | `/qa/stream` | `user` |
| GET | `/qa/history/{session_id}` | `user` |
| POST | `/qa/feedback` | `user` |
| GET | `/qa/sessions/search` | `user` |
| POST | `/auth/login`, `/auth/register`, `/auth/change-password` | 见各端点说明 |
| GET | `/admin/stats`, `/admin/refused`, `/admin/human`, `/admin/human-tasks`, `/admin/audits/pending`, `/admin/consistency`, `/admin/feedback-stats`, `/admin/records` | `admin` |
| POST | `/admin/human-tasks/{task_id}/claim`, `/admin/human-tasks/{task_id}/complete` | `admin` |
| GET | `/admin/human-tasks/{task_id}/events`, `/admin/reports/usage` | `admin` |

所有业务数据查询同时带来自已验签 Token 的 `tenant_id`。客户端提交的 `user_id` 或 `tenant_id` 不构成身份。

## 7. 数据库迁移与升级

当前没有 Alembic。启动时 `init_db()` 执行 `Base.metadata.create_all` 和有限的幂等列/索引迁移，因此不支持无停机复杂 schema 变更。

升级步骤：

1. 阅读发布差异并确认目标版本支持当前 Python、SQLite、Chroma 格式。
2. 停止 API/Worker 写入并执行同时间点 `storage/` + `chroma_db/` 备份。
3. 在恢复副本上启动目标版本并运行 `python -m app.commands.check_consistency`。
4. 只有 SQLite integrity、迁移和三存储一致性全绿才能安排正式切换。
5. 复杂迁移必须先引入版本化迁移工具，禁止继续在 `_migrate_schema` 中堆叠不可逆 DDL。

## 8. 备份恢复

维护窗口命令、恢复到空目录、SHA-256 清单、SQLite integrity、一致性验证和回滚步骤见 [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md)。备份必须覆盖同一时间点的：

- `storage/app.db`、`storage/checkpoints.db` 和文档文件；
- `chroma_db/` 的 SQLite 元数据及 HNSW 文件；
- 与该版本对应的配置模板、镜像/提交号和敏感规则版本（不把 `.env` 放入数据备份）。

## 9. Key 轮换

- **DashScope**：创建新 Key → 在 Secret Manager 更新并滚动重启 API/Worker → 运行人工连通性与 readiness → 确认调用使用新 Key → 吊销旧 Key。
- **JWT HS256**：当前不支持 `kid` 或双 Key 重叠验证。需维护窗口协调 IdP 与服务切换，旧 Token 会立即失效；高可用生产部署前应迁移到支持 JWKS/非对称签名与重叠轮换的验证方式。
- **LangSmith**：先关闭追踪，轮换 API Key 与独立 HMAC Secret，完成远端权限/保留策略复核后重新审批启用。
- Key 泄漏时先吊销再调查；不得把旧/新值写入日志、Git、备份清单或工单。

## 10. LangSmith 数据治理

外部追踪不是运行前提。默认关闭，组织审批、数据驻留、供应商协议、远端权限、保留期、采样率、工作区和脱敏 Secret 任一缺失都会拒绝外发。完整清单见 [LANGSMITH_DATA_GOVERNANCE.md](LANGSMITH_DATA_GOVERNANCE.md)。

## 11. 已知限制与容量边界

- SQLite 与嵌入式 Chroma 适合单机/中小规模，不是多节点高可用数据库；写并发和容量必须用目标硬件压测后确定。
- 分钟速率和并发限制是 API 进程内状态；每日调用/Token 预算才持久化。多 API 进程前需引入共享限流器。
- 单文件默认 50 MiB；PDF 500 页；XLSX 100 工作表/1,000,000 单元格；Office 展开 100 MiB/2000 条目/压缩比 100；解析文本 2,000,000 字符。
- 默认 API QA 并发 8、上传并发 2、解析进程 2、Worker 并发 1；这些是保护上限，不是吞吐承诺。
- 不提供 OCR、扫描 PDF 识别、混合检索、rerank、SSE/WebSocket 或前端管理台。
- 默认 MalwareScanner 不是生产扫描器；实际适配器未部署前不得把文件上传能力视为生产就绪。
- JWT 目前是单一共享 HS256 Secret，没有 JWKS、撤销列表或重叠轮换。
- 数据库迁移没有 Alembic；备份需要短暂停写以保证 Chroma 与文件同时间点。
- `/metrics` 含进程内计数，进程重启会归零；持久业务总量来自 SQLite。监控端必须处理 counter reset。
- `chromadb==1.5.9` 的风险接受有到期日，且严禁暴露 Chroma HTTP Server；见供应链安全文档。
- LangSmith 即使获批也只能看到脱敏 HMAC/长度，不是完整内容调试工具。

## 12. 发布前证据

执行测试、依赖审计、容器构建、恢复演练和威胁模型复核。阶段 12 全部门通过前，只能称”生产候选整改中”，不能声称已生产可用。

## 13. 生产网络层（Nginx + HTTPS）部署

### 前置条件

- Docker ≥ 24、Docker Compose ≥ 2（`docker compose version` 确认）
- 已解析到服务器 IP 的域名
- 服务器 80 和 443 端口对外开放（防火墙/安全组放行）
- 前端已完成构建（`frontend/dist/` 存在）

### 1. 配置 .env

```bash
cp .env.example .env
```

必填项清单：

| 变量 | 说明 |
|---|---|
| `DASHSCOPE_API_KEY` | 阿里云百炼 API Key |
| `AUTH_JWT_SECRET` | HS256 密钥，至少 32 个随机字符，不得使用示例值 |
| `APP_ENV` | 改为 `production` |
| `DOMAIN` | 实际域名，例如 `kb.example.com` |

### 2. 申请 SSL 证书

```bash
# 在服务器上安装 certbot
apt install certbot

# 确保 80 端口未被占用后申请（standalone 模式）
certbot certonly --standalone -d your-domain.com

# 将证书复制到项目目录
cp /etc/letsencrypt/live/your-domain.com/fullchain.pem nginx/ssl/cert.pem
cp /etc/letsencrypt/live/your-domain.com/privkey.pem nginx/ssl/key.pem
chmod 600 nginx/ssl/key.pem
```

开发/测试环境可使用自签名证书：

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/ssl/key.pem \
  -out nginx/ssl/cert.pem \
  -subj “/CN=localhost”
```

### 3. 构建前端

```bash
bash scripts/build_frontend.sh
```

构建产物输出到 `frontend/dist/`，Nginx 容器以只读方式挂载。

### 4. 启动生产环境

```bash
docker compose -f docker-compose.prod.yml up -d
```

首次启动会拉取 `nginx:1.27-alpine` 镜像并构建 API 镜像。

### 5. 验证服务状态

```bash
# 检查所有容器健康状态
docker compose -f docker-compose.prod.yml ps

# 查看各服务日志
docker compose -f docker-compose.prod.yml logs nginx
docker compose -f docker-compose.prod.yml logs api
docker compose -f docker-compose.prod.yml logs worker
```

所有容器 Status 应显示 `healthy`。可通过 `https://your-domain.com/api/health/ready` 验证后端健康检查。

### 6. 常见问题

**证书路径错误**：Nginx 容器启动失败时，先确认 `nginx/ssl/cert.pem` 和 `nginx/ssl/key.pem` 均存在，再执行 `docker compose -f docker-compose.prod.yml logs nginx` 查看具体错误。

**80/443 端口被占用**：执行 `ss -tlnp | grep -E ':80|:443'`（Linux）确认端口占用进程，停止冲突服务后重新启动。

**前端 404**：确认 `frontend/dist/index.html` 存在；若构建产物缺失，重新运行 `bash scripts/build_frontend.sh`。

**API 502 Bad Gateway**：API 容器可能尚未通过 healthcheck，等待约 20 秒后刷新；或执行 `docker compose -f docker-compose.prod.yml logs api` 查看启动错误。

**查看 Nginx 访问/错误日志**：

```bash
docker exec enterprise-kb-nginx cat /var/log/nginx/error.log
docker exec enterprise-kb-nginx cat /var/log/nginx/access.log
```
