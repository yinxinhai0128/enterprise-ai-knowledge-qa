# 部署指南

## 概述

本指南覆盖企业知识问答系统的本地开发部署、Docker 容器化部署和生产加固要求。
请根据目标环境选择对应章节。

---

## 一、环境要求

### 必需组件

| 组件 | 最低版本 | 说明 |
|------|---------|------|
| Python | 3.12+ | 不支持 3.9/3.10/3.11；Anaconda base 通常是旧版，需单独安装 |
| Node.js | 20+ | 仅前端需要；纯后端部署可跳过 |
| pip | 23+ | 用于安装依赖 |
| Git | 任意 | 拉取代码 |

### 可选组件

| 组件 | 说明 |
|------|------|
| Docker + Docker Compose | 容器化部署 |
| ClamAV | 恶意软件扫描（生产推荐） |
| Nginx/Caddy | TLS 反向代理（生产必须） |
| Prometheus + Grafana | 监控可视化 |

### 硬件建议

| 规模 | CPU | 内存 | 磁盘 |
|------|-----|------|------|
| 开发/演示 | 2 核 | 4 GB | 20 GB |
| 小型生产（< 1 万文档） | 4 核 | 8 GB | 100 GB SSD |
| 中型生产（< 10 万文档） | 8 核 | 16 GB | 500 GB SSD |

---

## 二、配置文件

### .env 文件

复制 `.env.example` 为 `.env` 并填写关键变量：

```bash
# 必填
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxx          # 阿里云百炼 API Key
AUTH_JWT_SECRET=<至少32字符的随机字符串>    # JWT 签名密钥

# 建议修改
LLM_MODEL=qwen3.6-plus                     # 对话模型 ID（百炼控制台确认）
EMBED_MODEL=text-embedding-v3              # 向量模型 ID

# 开发环境
APP_ENV=development                        # 生产改为 production
APP_HOST=127.0.0.1                        # 生产部署改为 0.0.0.0（配合反向代理）
APP_PORT=8000

# 追踪（默认关闭）
LANGCHAIN_TRACING_V2=false
```

### 生成随机密钥

```powershell
# Windows PowerShell
-join ((65..90) + (97..122) + (48..57) | Get-Random -Count 48 | ForEach-Object {[char]$_})
```

```bash
# macOS/Linux
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

---

## 三、本地开发部署

### Windows（推荐 PowerShell）

```powershell
# 1. 进入项目目录
cd 企业级AI知识问答系统

# 2. 确认 Python 版本（必须是 3.12+，不能是 Anaconda 3.9）
python --version

# 3. 创建虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# 若提示执行策略限制：
# Set-ExecutionPolicy -Scope Process Bypass

# 4. 安装依赖（使用哈希锁定的精确版本）
python -m pip install --require-hashes -r requirements.lock

# 5. 配置密钥（仅首次）
Copy-Item .env.example .env
# 编辑 .env 填入 DASHSCOPE_API_KEY 和 AUTH_JWT_SECRET

# 6. 一键启动（推荐）
.\start.ps1
```

`start.ps1` 会同时启动：
- API 服务（`uvicorn app.main:app --reload`）
- 摄入 Worker（`python -m app.worker`）
- 前端开发服务器（`npm run dev`，如已安装 Node.js）

### 手动启动（分步）

```powershell
# 终端 1：API 服务
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 终端 2：摄入 Worker（必须与 API 同时运行）
python -m app.worker

# 终端 3：前端（可选）
cd frontend
npm install
npm run dev   # http://localhost:5173
```

### macOS / Linux

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --require-hashes -r requirements.lock
cp .env.example .env
# 编辑 .env
uvicorn app.main:app --reload &
python -m app.worker &
```

---

## 四、获取 Token

### 开发环境（本地测试）

```powershell
# user 角色 Token（有效期 15 分钟）
$env:TOKEN = python scripts\create_dev_token.py --roles user --ttl-seconds 900

# user + admin 角色 Token（用于登录前端管理界面，有效期 1 小时）
$env:TOKEN = python scripts\create_dev_token.py --roles user,admin --ttl-seconds 3600

# 测试 API 是否正常
Invoke-RestMethod -Uri http://127.0.0.1:8000/health/ready
curl -H "Authorization: Bearer $env:TOKEN" http://127.0.0.1:8000/api/documents
```

### 生产环境

⚠️ 生产环境 **禁止使用** `create_dev_token.py`。必须对接企业身份系统：

- **Azure Active Directory**：配置 App Registration，使用 OIDC/OAuth2 流程
- **Okta**：配置 API Services Application，使用 Client Credentials
- **Keycloak**：配置 Realm + Client，使用 JWT Bearer

企业 IdP 签发的 Token 必须包含 `tenant_id`、`roles` 等自定义 claims。
具体对接方式见 `docs/ENTERPRISE_UPGRADE_GUIDE.md`。

---

## 五、Docker 部署

### 基本启动

```bash
# 构建并启动所有服务（API + Worker）
docker compose up -d --build

# 查看日志
docker compose logs -f

# 停止
docker compose down
```

### 数据持久化

Docker Compose 挂载三个卷：

```yaml
volumes:
  - ./storage:/app/storage       # 上传文件、SQLite 数据库
  - ./chroma_db:/app/chroma_db  # 向量数据库
  - ./logs:/app/logs             # 日志文件
```

首次启动前确保这些目录存在：

```bash
mkdir -p storage chroma_db logs
```

### 容器安全说明

- 容器以 UID/GID 10001（非 root）运行
- 根文件系统为只读，源码由 root 拥有不可修改
- 默认只监听 `127.0.0.1`，不直接暴露到局域网

---

## 六、生产加固

### 6.1 必须完成的配置

```bash
# .env 生产配置
APP_ENV=production               # 关闭 /docs、/redoc、/openapi.json
APP_HOST=127.0.0.1              # 配合反向代理，不直接暴露
MALWARE_SCAN_REQUIRED=true      # 强制外部恶意软件扫描
```

### 6.2 TLS 反向代理（Nginx 示例）

```nginx
server {
    listen 443 ssl;
    server_name kb.your-company.com;

    ssl_certificate /etc/ssl/certs/kb.crt;
    ssl_certificate_key /etc/ssl/private/kb.key;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# 强制重定向 HTTP 到 HTTPS
server {
    listen 80;
    server_name kb.your-company.com;
    return 301 https://$server_name$request_uri;
}
```

### 6.3 防火墙规则

```bash
# 仅允许反向代理访问后端端口（Linux ufw 示例）
ufw allow 443/tcp              # 对外开放 HTTPS
ufw deny 8000/tcp              # 禁止外部直接访问后端
ufw deny 5173/tcp              # 禁止外部直接访问前端开发服务器
```

---

## 七、备份与恢复

### 7.1 需要备份的数据

| 数据 | 位置 | 备份频率 |
|------|------|---------|
| SQLite 数据库 | `storage/app.db` | 每日 |
| LangGraph 检查点 | `storage/checkpoints.db` | 每日 |
| 上传文件 | `storage/quarantine/` 和 `storage/docs/` | 每日 |
| 向量数据库 | `chroma_db/` | 每周（可从文件重建） |
| 配置 | `.env` | 每次变更 |

### 7.2 备份脚本

```powershell
# 使用内置备份脚本
python scripts\backup_restore.py backup --output backup-2026-06-23.tar.gz
```

### 7.3 恢复流程

```powershell
# 停止服务
docker compose down   # 或 Ctrl+C 停止手动启动的进程

# 恢复数据
python scripts\backup_restore.py restore --input backup-2026-06-23.tar.gz

# 重启服务
docker compose up -d
```

---

## 八、监控与告警

### 8.1 Prometheus 接入

Prometheus `scrape_configs` 配置：

```yaml
scrape_configs:
  - job_name: 'enterprise-kb'
    static_configs:
      - targets: ['127.0.0.1:8000']
    metrics_path: /metrics
    scrape_interval: 30s
```

### 8.2 关键告警规则

```yaml
groups:
  - name: enterprise-kb
    rules:
      - alert: BudgetExceeded
        expr: increase(budget_exceeded_total[5m]) > 0
        annotations:
          summary: "预算超出告警"

      - alert: IngestWorkerDown
        expr: absent(up{job="enterprise-kb"}) == 1
        for: 2m
        annotations:
          summary: "摄入 Worker 可能宕机"

      - alert: HighErrorRate
        expr: rate(qa_requests_total{status="error"}[5m]) > 0.1
        annotations:
          summary: "问答错误率过高"
```

### 8.3 日志聚合

日志输出到 `logs/` 目录，格式为 JSON（生产）或彩色文本（开发）：

```bash
# 实时查看 API 日志
tail -f logs/app.log | python -m json.tool

# 查看 Worker 日志
tail -f logs/worker.log
```
