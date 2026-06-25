# 企业知识问答系统安全指南

## 概述

本指南描述企业级 AI 知识问答系统的安全边界、身份认证机制、输入防护策略和审计要求。
部署者在上线前必须完成本指南中标注 ⚠️ 的所有控制项。

> **重要说明**：本系统的安全设计遵循深度防御原则。JWT 验证、租户隔离、速率限制、
> 审计日志是系统内置的基础控制，但不能替代企业 IdP、TLS 反向代理、防火墙和恶意软件
> 扫描等外部安全控制。

---

## 一、JWT 认证体系

### 1.1 Token 格式

所有业务接口（`/health`、`/metrics` 除外）均要求 Bearer JWT：

```
Authorization: Bearer <JWT>
```

JWT 使用 HS256 对称签名，包含以下标准和自定义 claims：

```json
{
  "sub": "user-123",
  "tenant_id": "tenant-a",
  "roles": ["user"],
  "iss": "enterprise-idp",
  "aud": "enterprise-kb",
  "iat": 1735689600,
  "exp": 1735693200
}
```

### 1.2 验证步骤

服务端按顺序执行以下检查，任一失败返回 401：

1. 签名验证（使用 `AUTH_JWT_SECRET`）
2. `iss` 必须等于 `AUTH_JWT_ISSUER`
3. `aud` 必须包含 `AUTH_JWT_AUDIENCE`
4. `exp` 未过期（允许 60 秒时钟偏差）
5. `iat` 不超过当前时间 + 偏差
6. `tenant_id` 字段存在且非空
7. `sub` 字段存在且非空

### 1.3 角色定义

| 角色 | 权限 |
|------|------|
| `user` | 问答、查看自己上传的文档 |
| `uploader` | 上传文档、重建索引、删除文档 |
| `admin` | 全部权限 + 管理接口（审计、人工任务、统计） |

### 1.4 生产 Token 要求

- ⚠️ 生产环境必须由企业 IdP（Okta、Azure AD、Keycloak 等）签发 Token
- ⚠️ `AUTH_JWT_SECRET` 必须是 32 字节以上随机字符，不得使用示例值
- 开发工具 `scripts/create_dev_token.py` 仅用于本地测试，不得在生产使用

---

## 二、租户隔离

### 2.1 数据层隔离

所有 SQLite 查询强制带 `tenant_id` 过滤：

```python
# 所有文档查询示例
select(Document).where(
    Document.id == doc_id,
    Document.tenant_id == auth.tenant_id,   # 强制过滤
)
```

跨租户访问返回 404（不泄露资源是否存在）。

### 2.2 向量库隔离

Chroma 查询同样强制带 tenant 过滤：

```python
collection.query(
    query_embeddings=[query_vector],
    where={"tenant_id": tenant_id},   # 强制元数据过滤
    n_results=5,
)
```

### 2.3 文件存储隔离

上传文件按租户目录隔离：

```
storage/
├── quarantine/
│   ├── tenant-a/    # 隔离区（校验前）
│   └── tenant-b/
└── docs/
    ├── tenant-a/    # 通过校验后移入
    └── tenant-b/
```

### 2.4 会话隔离

LangGraph checkpoint 的 thread_id 格式：

```
{tenant_id}:{user_id}:{session_id}
```

任何对话历史的读写都通过此三元组隔离，不同租户的 session_id 即使相同也不冲突。

---

## 三、输入安全

### 3.1 问题长度限制

```python
MAX_QUESTION_CHARS = 4000   # 默认上限，可通过环境变量调整
MAX_SESSION_ID_CHARS = 64
```

超过上限返回 400，不传递给 LLM。

### 3.2 文件上传安全

#### 大小限制

```python
MAX_FILE_SIZE_BYTES = 52428800   # 50 MB
```

流式读取时实时计数，超过立即中断并删除临时文件。

#### MIME 类型白名单

支持的文件类型：

| 扩展名 | MIME 类型 |
|--------|-----------|
| `.pdf` | `application/pdf` |
| `.docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| `.txt` | `text/plain` |
| `.md` | `text/markdown` |
| `.xlsx` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |

#### Magic Bytes 验证

仅检查扩展名是不够的。文件内容必须通过 magic bytes 检查：

```python
# PDF 文件头
assert file_content[:4] == b'%PDF'

# Office Open XML（docx/xlsx）是 ZIP 格式
assert file_content[:2] == b'PK'
```

验证在独立的解析进程中执行，崩溃不影响主进程。

#### 压缩炸弹防护

对 Office 文件（ZIP 格式）的展开做限制：

```python
MAX_ARCHIVE_ENTRIES = 2000           # 最多 2000 个条目
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 104857600   # 展开后最多 100 MB
MAX_ARCHIVE_COMPRESSION_RATIO = 100  # 压缩比不超过 100:1
```

### 3.3 文件名安全

- 文件名长度上限 200 字符
- 自动剥离路径分隔符（防止路径穿越）
- 存储时替换为 `{uuid}_{sanitized_name}`

---

## 四、速率限制与预算控制

### 4.1 请求速率限制

| 操作类型 | 每分钟上限 | 最大并发 |
|----------|-----------|---------|
| 问答（QA） | 30 次/身份 | 8 |
| 文件上传 | 10 次/身份 | 2 |
| 管理操作 | 60 次/身份 | 10 |

超过限制返回 429，响应头包含 `Retry-After`。

### 4.2 每日模型预算

```python
DAILY_USER_MODEL_CALLS = 200        # 单用户每日模型调用上限
DAILY_TENANT_MODEL_CALLS = 5000     # 单租户每日模型调用上限
DAILY_USER_TOKEN_BUDGET = 500000    # 单用户每日 Token 预算
DAILY_TENANT_TOKEN_BUDGET = 10000000  # 单租户每日 Token 预算
```

超出预算时返回 429，错误码 `BUDGET_EXCEEDED`，不继续调用模型。

---

## 五、审计日志

### 5.1 每轮问答审计记录

每次问答至少记录：

| 字段 | 说明 |
|------|------|
| `trace_id` | 全局唯一追踪 ID（UUID4） |
| `tenant_id` | 租户标识 |
| `user_id` | 用户标识（来自 JWT sub） |
| `session_id` | 会话标识 |
| `question_hash` | 问题内容的 HMAC（不存储明文） |
| `model` | 使用的 LLM 模型 ID |
| `input_tokens` | 输入 Token 数 |
| `output_tokens` | 输出 Token 数 |
| `latency_ms` | 端到端延迟（毫秒） |
| `refused` | 是否触发拒答 |
| `sensitive_flag` | 是否命中敏感分类规则 |
| `created_at` | 记录时间（UTC） |

### 5.2 审计写入策略（Fail-Closed）

审计日志采用"审计前预登记"模式：

1. 问答开始前先写入一条 `status=started` 的审计记录
2. 如果预登记失败，整个问答请求拒绝（fail-closed）
3. 问答完成后更新为 `status=completed`
4. 异常时更新为 `status=failed`

`AUDIT_WRITE_RETRIES = 3`：写入失败最多重试 3 次，仍失败则请求失败。

### 5.3 敏感数据脱敏

LangSmith 追踪（如已开启）在发送前对以下内容做脱敏：
- 问题内容：仅保留 HMAC 和字符长度
- 文档 chunk 内容：仅保留长度
- 用户标识：HMAC 替换

---

## 六、数据治理

### 6.1 LangSmith 追踪控制

LangSmith 追踪默认完全关闭，开启需要同时满足：

```bash
LANGSMITH_API_KEY=<key>
LANGCHAIN_TRACING_V2=true
LANGSMITH_ORG_APPROVED=true           # 组织已审批
LANGSMITH_APPROVAL_REFERENCE=<单号>   # 审批工单或决策编号
LANGSMITH_REMOTE_POLICY_CONFIRMED=true  # 已在远端确认最小权限和保留策略
LANGSMITH_TRACING_SAMPLING_RATE=0.1  # 必须大于 0
LANGSMITH_REDACTION_SECRET=<32字符随机密钥>  # 脱敏用 HMAC 密钥
```

任一条件不满足，追踪自动降级为禁用。

### 6.2 数据保留

| 数据类型 | 默认保留期 | 配置项 |
|----------|-----------|--------|
| 对话会话 | 30 天 | `CONVERSATION_TTL_DAYS` |
| 审计日志 | 永久（不自动清理） | — |
| 上传文件 | 随文档删除 | — |
| LangSmith 追踪 | 14 天 | `LANGSMITH_RETENTION_DAYS` |

---

## 七、生产部署安全检查清单

### 必须完成（上线前）

- [ ] ⚠️ 设置 `AUTH_JWT_SECRET`（32+ 字符随机字符串）
- [ ] ⚠️ 对接企业 IdP，禁用 `create_dev_token.py`
- [ ] ⚠️ 配置 TLS 反向代理（Nginx/Caddy），禁止 HTTP 明文
- [ ] ⚠️ 设置 `APP_ENV=production`（关闭 `/docs`、`/redoc`）
- [ ] ⚠️ 集成外部恶意软件扫描器，设置 `MALWARE_SCAN_REQUIRED=true`
- [ ] ⚠️ 防火墙限制端口仅允许反向代理访问
- [ ] ⚠️ 禁止暴露 Chroma HTTP Server（CVE-2026-45829 尚无修复版）

### 建议完成

- [ ] 配置 Prometheus + Grafana 监控 `/metrics`
- [ ] 设置每日预算告警（`DAILY_TENANT_TOKEN_BUDGET` 的 80%）
- [ ] 定期轮换 `AUTH_JWT_SECRET`（建议每 90 天）
- [ ] 建立审计日志异地备份
