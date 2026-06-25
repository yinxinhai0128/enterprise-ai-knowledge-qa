# API 参考手册

## 概述

企业知识问答系统提供 RESTful HTTP API，基于 FastAPI 构建，支持 OpenAPI 3.1 规范。
开发环境可通过 `http://127.0.0.1:8000/docs` 访问交互式文档（Swagger UI）。

> ⚠️ 生产环境设置 `APP_ENV=production` 后，`/docs`、`/redoc`、`/openapi.json`
> 默认关闭，防止接口信息泄露。

---

## 认证

除健康检查和指标接口外，所有接口均需要 Bearer JWT 认证：

```http
Authorization: Bearer <JWT>
```

Token 要求：
- HS256 签名，使用 `AUTH_JWT_SECRET` 验签
- 包含 `sub`、`tenant_id`、`roles`、`iss`、`aud`、`exp` claims
- 开发环境使用 `scripts/create_dev_token.py` 生成，生产环境由企业 IdP 签发

Token 获取（开发环境）：

```powershell
# 生成 user 角色 Token（有效期 15 分钟）
$env:TOKEN = python scripts\create_dev_token.py --roles user --ttl-seconds 900

# 生成 admin 角色 Token（有效期 1 小时）
$env:TOKEN = python scripts\create_dev_token.py --roles user,admin --ttl-seconds 3600
```

---

## 问答接口

### POST /api/qa/ask

同步问答接口，返回完整回答（非流式）。

**请求**

```http
POST /api/qa/ask
Authorization: Bearer <JWT>
Content-Type: application/json
```

```json
{
  "question": "企业知识库支持哪些文件格式？",
  "session_id": "session-abc123"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `question` | string | ✅ | 问题内容，最多 `MAX_QUESTION_CHARS` 字符（默认 4000） |
| `session_id` | string | ✅ | 会话标识，最多 64 字符，同一会话内保持对话历史 |

**响应 200 OK**

```json
{
  "answer": "本系统支持 PDF、DOCX、TXT、Markdown 和 XLSX 文件格式。",
  "refused": false,
  "sources": [
    {
      "doc_id": 42,
      "filename": "技术规范.pdf",
      "chunk_index": 3,
      "relevance_score": 0.82,
      "excerpt": "支持的文件格式包括：PDF、DOCX、TXT..."
    }
  ],
  "trace_id": "550e8400-e29b-41d4-a716-446655440000",
  "input_tokens": 1024,
  "output_tokens": 128,
  "latency_ms": 3200
}
```

**错误码**

| HTTP 状态 | 错误详情 | 说明 |
|-----------|---------|------|
| 400 | `QUESTION_TOO_LONG` | 问题超过字符上限 |
| 401 | `UNAUTHORIZED` | Token 无效或过期 |
| 429 | `RATE_LIMIT_EXCEEDED` | 超过每分钟请求上限 |
| 429 | `BUDGET_EXCEEDED` | 超过每日模型调用/Token 预算 |
| 503 | `AUDIT_NOT_STARTED` | 审计预登记失败（fail-closed） |
| 503 | `CONVERSATION_BUSY` | 同一会话正在处理另一请求 |

---

## 文档接口

### POST /api/documents/upload

上传文档并触发异步索引。

**请求**

```http
POST /api/documents/upload
Authorization: Bearer <JWT>
Content-Type: multipart/form-data
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `file` | file | 上传的文件（PDF/DOCX/TXT/MD/XLSX） |

**响应 201 Created**

```json
{
  "id": 42,
  "filename": "技术规范.pdf",
  "status": "uploading",
  "created_at": "2026-06-23T10:00:00Z",
  "updated_at": "2026-06-23T10:00:00Z"
}
```

文档状态流转：

```
uploading → parsing → indexed
                    ↘ failed
```

重复上传相同内容的文件，响应头会包含 `X-Idempotent-Replay: true`，返回已有文档记录。

**错误码**

| HTTP 状态 | 说明 |
|-----------|------|
| 400 | 文件类型不支持或文件名非法 |
| 408 | 文件上传或安全校验超时 |
| 413 | 文件超过 50 MB 上限 |
| 429 | 超过上传速率限制 |
| 507 | 服务器存储空间不足 |

### GET /api/documents

获取当前租户的文档列表，按创建时间倒序。

**响应 200 OK**

```json
[
  {
    "id": 42,
    "filename": "技术规范.pdf",
    "status": "indexed",
    "created_at": "2026-06-23T10:00:00Z",
    "updated_at": "2026-06-23T10:05:00Z"
  }
]
```

### GET /api/documents/{doc_id}

获取单个文档详情。

### GET /api/documents/{doc_id}/jobs

获取文档的摄入任务历史，包括重试记录。

### POST /api/documents/{doc_id}/retry

重新触发失败的摄入任务（仅限 `failed` 状态的文档）。

### POST /api/documents/{doc_id}/reindex

强制重新索引已索引的文档（全量重新解析和向量化）。

### POST /api/documents/{doc_id}/cancel

取消正在处理的摄入任务。

### DELETE /api/documents/{doc_id}

删除文档及其所有数据（SQLite 记录、原始文件、向量 chunk）。

---

## 会话接口

### GET /api/qa/history/{session_id}

获取指定会话的对话历史。

**响应 200 OK**

```json
{
  "session_id": "session-abc123",
  "messages": [
    {
      "role": "user",
      "content": "企业知识库支持哪些文件格式？",
      "created_at": "2026-06-23T10:00:00Z"
    },
    {
      "role": "assistant",
      "content": "本系统支持 PDF、DOCX、TXT、Markdown 和 XLSX 文件格式。",
      "sources": [...],
      "created_at": "2026-06-23T10:00:03Z"
    }
  ]
}
```

---

## 管理接口（需要 admin 角色）

### GET /api/admin/stats

获取系统统计信息（文档数、问答数、Token 消耗等）。

### GET /api/admin/audit

查询审计日志，支持时间范围和用户过滤。

### GET /api/admin/human-tasks

获取需要人工审核的任务列表（触发敏感分类的问答）。

### POST /api/admin/human-tasks/{task_id}/complete

标记人工任务为已完成。

---

## 健康检查接口

### GET /health/live

存活探针，检查进程是否运行。

**响应 200 OK**

```json
{"status": "alive"}
```

### GET /health/ready

就绪探针，检查所有依赖组件是否就绪。

**响应 200 OK**（就绪）

```json
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "vectorstore": "ok",
    "worker_lease": "ok"
  }
}
```

**响应 503 Service Unavailable**（未就绪）

```json
{
  "status": "not_ready",
  "checks": {
    "database": "ok",
    "vectorstore": "error: connection timeout",
    "worker_lease": "ok"
  }
}
```

---

## 指标接口

### GET /metrics

Prometheus 格式的指标端点，可对接 Grafana。

主要指标：

| 指标名 | 类型 | 说明 |
|--------|------|------|
| `qa_requests_total` | Counter | 问答请求总数（按状态分类） |
| `qa_latency_seconds` | Histogram | 问答延迟分布 |
| `qa_tokens_total` | Counter | 模型 Token 消耗总数 |
| `document_uploads_total` | Counter | 文档上传总数（按状态分类） |
| `document_ingest_duration_seconds` | Histogram | 文档摄入耗时分布 |
| `active_sessions` | Gauge | 当前活跃会话数 |
| `budget_exceeded_total` | Counter | 预算超出次数（按类型分类） |

---

## 常见错误排查

### 401 Unauthorized

1. 检查 Token 是否过期（JWT 的 `exp` claim）
2. 检查 `AUTH_JWT_SECRET` 是否与签发 Token 时一致
3. 检查 `iss` 和 `aud` claims 是否匹配服务器配置

### 503 AUDIT_NOT_STARTED

审计系统预登记失败导致请求被拒绝（fail-closed 机制）。
检查：数据库连接是否正常、磁盘空间是否充足。

### 503 CONVERSATION_BUSY

同一 `session_id` 正在处理另一个请求。等待当前请求完成或使用新的 `session_id`。
并发超出 `QA_MAX_CONCURRENCY` 时也会触发。

### 文档状态停在 `uploading`

Worker 进程可能未启动。检查：`python -m app.worker` 是否在运行。
也可能是 Worker 崩溃，查看 `logs/worker.log`。
