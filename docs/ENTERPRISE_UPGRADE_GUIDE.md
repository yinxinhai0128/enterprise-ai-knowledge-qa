# 企业级升级说明书

> **文档定位**：面向希望将本系统从"作品集演示版"升级为"真实企业内部产品"的团队。  
> 当前版本：v1.0（演示版）| 目标版本：v2.0（企业生产版）

---

## 一、当前版本现状

### 1.1 已实现能力

| 模块 | 技术实现 | 说明 |
|------|---------|------|
| 问答核心 | LangGraph Agentic RAG | Agent 自主决策检索，拒绝幻觉 |
| 文档解析 | PDF/DOCX/XLSX/TXT | 异步 Worker 队列处理 |
| 向量检索 | ChromaDB + text-embedding-v3 | 本地嵌入，L2 距离过滤 |
| 多轮对话 | SQLite Checkpointer | 按 session_id 隔离 |
| 多租户 | JWT tenant_id 字段 | 检索层过滤隔离 |
| 人工审核 | HumanTask 工作流 | 敏感问题转人工处理 |
| 前端 | React 18 + TypeScript | 4 页面，移动端适配 |
| 认证 | HS256 JWT（手动颁发） | 开发用，无真实身份系统 |

### 1.2 已知不足

| # | 问题 | 影响 | 严重程度 |
|---|------|------|---------|
| 1 | LLM 回答不稳定，同一问题时而回答时而拒答 | 用户体验差，不可预测 | 🔴 高 |
| 2 | 参考来源卡片为空，来源被 LLM 写入正文而非结构化返回 | 溯源功能失效 | 🔴 高 |
| 3 | Token 手动生成粘贴，无真实身份认证 | 无法实际分发给员工 | 🔴 高 |
| 4 | SQLite 单文件数据库，不支持高并发写入 | 多用户并发时数据异常 | 🟠 中 |
| 5 | ChromaDB 本地文件模式，无法集群扩展 | 文档量大时性能下降 | 🟠 中 |
| 6 | 文档存本地磁盘，服务器重置即丢失 | 数据安全风险 | 🟠 中 |
| 7 | 无 HTTPS，明文传输 Token 和文档内容 | 安全合规不达标 | 🟠 中 |
| 8 | 无流式输出，等待时用户无反馈（假打字机） | 体验不如 ChatGPT | 🟡 低 |
| 9 | 无用户管理界面，租户/角色需手工数据库操作 | 运维困难 | 🟡 低 |
| 10 | 无监控告警，服务异常无感知 | 运维盲区 | 🟡 低 |

---

## 二、核心问题修复方案

### 2.1 🔴 修复 LLM 回答不稳定

**根本原因**：当前使用纯 Agentic RAG，LLM 自主决策是否调用检索工具，存在随机性。

**解决方案**：改为"强制检索"模式（Naive RAG → 再套 Agent 判断）

```
当前流程：
问题 → Agent（自主决定）→ [可能调用检索] → 回答

改进流程：
问题 → 强制检索（Top-K 召回）→ Agent（基于检索结果判断）→ 回答
```

**代码位置**：`app/agent/agent.py` 的 `SYSTEM_PROMPT` + `app/core/retriever_tool.py`

**改动要点**：
```python
# 修改系统提示，强制要求先检索
SYSTEM_PROMPT = """
接收到任何问题后，你必须首先调用 search_knowledge_base 检索知识库。
即使你认为自己已知答案，也必须检索以确保回答基于企业文档。
...
"""
```

**预期效果**：回答一致性从 ~60% 提升至 ~95%

---

### 2.2 🔴 修复来源卡片为空

**根本原因**：LangChain Agent 的 artifact（tool 返回的结构化数据）未被正确透传到 API 响应的 `sources` 字段。

**解决方案**：在 QA 服务层从 Agent 的 tool 调用历史中提取 Evidence

```python
# app/services/qa.py（示意）
async def ask(question, session_id, ctx):
    result = await agent.ainvoke(...)
    
    # 从 tool_calls 历史提取 artifact
    sources = []
    for msg in result["messages"]:
        if hasattr(msg, "artifact") and msg.artifact:
            sources.extend(msg.artifact)
    
    return AskResponse(answer=result["output"], sources=sources, ...)
```

**代码位置**：`app/api/qa.py` 和 `app/services/qa.py`

---

### 2.3 🔴 接入真实身份认证

**方案选择**（按企业场景）：

| 场景 | 推荐方案 | 接入难度 |
|------|---------|---------|
| 钉钉企业 | 钉钉 OAuth2 + 扫码登录 | ⭐⭐ |
| 飞书企业 | 飞书开放平台 SSO | ⭐⭐ |
| 微信政务/企业微信 | 企业微信 OAuth | ⭐⭐ |
| 自建 LDAP/AD | python-ldap3 验证 | ⭐⭐⭐ |
| 通用 OIDC | Keycloak / Okta | ⭐⭐⭐ |

**实现思路（以钉钉为例）**：
```
用户点击"钉钉登录"
→ 跳转钉钉授权页（带 AppKey 和 redirect_uri）
→ 钉钉回调带 code
→ 后端用 code 换 access_token
→ 获取用户信息（userid、name、department）
→ 签发本系统 JWT（tenant_id = 企业 corpId）
→ 前端存 token，正常使用
```

**前端改动**：`LoginPage.tsx` 增加 OAuth 登录按钮，去掉手动 Token 输入框（或保留管理员入口）

---

## 三、企业生产环境改造

### 3.1 数据库升级：SQLite → PostgreSQL

**为什么换**：SQLite 不支持高并发写入，100+ 用户同时提问时会出现锁等待。

```bash
# 安装
pip install asyncpg

# .env 改动
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/ekqa
```

**代码改动**：`app/core/database.py` 修改连接字符串，Alembic 生成迁移脚本即可，ORM 层无需改动。

---

### 3.2 向量数据库升级：ChromaDB → Weaviate / Qdrant

**为什么换**：ChromaDB 本地模式不支持集群、不支持持久化备份、百万向量后性能下降。

| 选项 | 特点 | 推荐场景 |
|------|------|---------|
| **Qdrant** | 高性能，Docker 部署简单，API 稳定 | 首选 |
| **Weaviate** | 内置多模态，社区活跃 | 需要图片检索时 |
| **阿里云向量检索** | 全托管，无运维 | 已在用阿里云时 |

**代码改动**：`app/core/vectorstore.py` 替换 `langchain_chroma.Chroma` 为对应客户端，接口兼容 LangChain VectorStore 抽象层。

---

### 3.3 文档存储：本地磁盘 → 对象存储（OSS）

**为什么换**：本地存文件，服务器迁移/重置后文件丢失；多实例部署时文件不共享。

```python
# 上传文档时
import oss2
bucket.put_object(f"documents/{tenant_id}/{filename}", file_content)

# 解析文档时从 OSS 下载临时处理
```

**推荐**：阿里云 OSS（已有账号，与 DashScope 同账号，计费统一）

---

### 3.4 部署架构升级

**单机部署（10-50 人团队）**：
```
阿里云 ECS（2核4G）
├── nginx（反向代理 + HTTPS + 静态文件）
├── uvicorn（后端 API，supervisor 守护）
├── worker（文档处理，supervisor 守护）
└── PostgreSQL + Qdrant（本机或单独 RDS）
```

**集群部署（50-500 人团队）**：
```
负载均衡（SLB）
├── API 服务 × 3（ECS，无状态）
├── Worker 服务 × 2（处理文档队列）
├── RDS PostgreSQL（主从）
├── Qdrant 集群（3节点）
└── OSS（文档存储）
```

**Docker Compose 快速启动**（推荐先用这个）：
```yaml
# docker-compose.yml
services:
  api:
    build: .
    env_file: .env.production
    ports: ["8765:8765"]
  worker:
    build: .
    command: python -m app.worker
    env_file: .env.production
  frontend:
    build: ./frontend
    ports: ["80:80"]
  postgres:
    image: postgres:16
  qdrant:
    image: qdrant/qdrant
```

---

### 3.5 HTTPS 配置

```nginx
# nginx.conf
server {
    listen 443 ssl;
    server_name your-domain.com;
    
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    
    # 前端静态文件
    location / {
        root /var/www/ekqa/dist;
        try_files $uri /index.html;
    }
    
    # 后端 API 代理
    location /api/ {
        proxy_pass http://127.0.0.1:8765/;
        proxy_set_header Authorization $http_authorization;
    }
}
```

免费证书：`certbot --nginx -d your-domain.com`

---

## 四、功能增强路线图

### v1.1（1-2 周，体验优化）
- [ ] 修复 LLM 回答不稳定（强制检索模式）
- [ ] 修复来源卡片为空（artifact 透传）
- [ ] 前端 Markdown 完整渲染（标题/列表/代码块）
- [ ] 流式输出（后端 SSE，前端去掉假打字机）

### v1.5（2-4 周，企业化）
- [ ] 接入钉钉/飞书 OAuth 登录
- [ ] PostgreSQL 替换 SQLite
- [ ] 用户管理界面（邀请/禁用/角色分配）
- [ ] Docker Compose 一键部署
- [ ] HTTPS + 域名

### v2.0（1-2 月，生产就绪）
- [ ] Qdrant 替换 ChromaDB
- [ ] OSS 文档存储
- [ ] 监控告警（Prometheus + Grafana）
- [ ] 操作日志完整审计
- [ ] 文档版本管理（同名文件自动更新）
- [ ] 批量导入（文件夹上传/SharePoint 同步）
- [ ] 问答质量反馈（踩/赞 + 人工校正入训练集）

---

## 五、预估成本（阿里云，中小企业场景）

| 资源 | 规格 | 月费用（约） |
|------|------|------------|
| ECS 服务器 | 2核4G，50G SSD | ¥200-300 |
| RDS PostgreSQL | 1核2G | ¥150-200 |
| OSS 存储 | 100G + 请求费 | ¥20-50 |
| DashScope API | 按 Token 计费 | ¥50-500（按用量） |
| 域名 + SSL | 年费 | ¥50-100/年 |
| **合计** | | **¥420-1050/月** |

> DashScope 费用弹性最大，取决于使用频率和文档量。可设置每日限额（`app/config.py` 的 `max_model_calls_per_request`）控制成本。

---

## 六、安全合规清单

在正式给员工使用前，必须完成以下检查：

- [ ] **数据加密**：数据库字段加密（PII 字段），OSS 服务端加密
- [ ] **传输安全**：全站 HTTPS，HSTS 头
- [ ] **访问控制**：最小权限原则，API 接口鉴权全覆盖
- [ ] **审计日志**：所有问答记录留存（当前已有）≥ 90 天
- [ ] **敏感词过滤**：已有 PII 中间件，需根据企业需求补充行业敏感词库
- [ ] **数据隔离**：多租户严格隔离（当前通过 tenant_id 过滤，已实现）
- [ ] **备份恢复**：数据库每日备份，RTO < 4 小时
- [ ] **漏洞扫描**：依赖包定期更新（`pip audit` / `npm audit`）

---

*文档版本：v1.0 | 生成日期：2026-06-23*
