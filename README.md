# 企业级 Agentic RAG 知识库

> 基于 **LangChain 1.3 + LangGraph** 的企业知识问答模板，全栈使用**国产大模型**（阿里云百炼）。
> 一套可直接复用的 Agentic RAG 骨架：文档摄入、自主检索问答、企业级审计与管控。

`LangChain 1.3` · `LangGraph` · `FastAPI` · `Chroma` · `阿里云百炼` · `Python 3.12`

---

## 简介

这是一个**可复用的企业知识库模板**。与"先检索再回答"的传统 RAG 不同，它采用 **Agentic RAG**——把检索封装成工具，由 Agent 自主判断何时检索、检索什么；来源与拒答则由服务端真实工具状态决定。内置 PII 脱敏、长对话摘要、失败重试与自定义审计（敏感词转人工 + 问答落库），开箱即用、易于二次开发。

## 核心特性

- **🤖 Agentic RAG**：`create_agent` + retriever-as-tool，Agent 自主决定检索时机，而非固定流程。
- **🇨🇳 全国产模型**：LLM 与 Embedding 均经阿里云百炼 OpenAI 兼容接口调用，无需出海。
- **📚 可恢复摄入**：PDF / DOCX / TXT 使用 LangChain Loader，XLSX 使用 OpenPyXL 适配器；持久化 Job 由独立 Worker 租约领取，支持重试、取消、重建与崩溃恢复。
- **🧱 资源安全边界**：请求/并发/每日费用限制，MIME + magic 校验，压缩展开/PDF/XLSX/文本上限，隔离目录与独立解析进程。
- **🛡️ 企业级管控（中间件栈）**：PII 脱敏、对话摘要、模型重试，外加自定义审计中间件——敏感词命中标记转人工、每轮问答落库。
- **🔐 可信身份与租户隔离**：验证企业身份系统签发的 Bearer JWT，按 tenant/user/role 隔离关系数据、会话与向量检索。
- **🧠 持久化多轮记忆**：基于共享 SQLite Checkpointer，按可信 tenant/user/session 隔离，支持跨重启、会话租约、TTL、消息上限与清理。
- **👩‍💼 人工介入闭环**：敏感分类建立可领取、可完成的人工任务，状态变化写入不可变事件；工资、健康、法律数据按角色策略拒绝越权访问。
- **📌 可信溯源**：工具返回 `content + artifact`，API 只用真实 artifact 生成结构化来源；无证据强制拒答，模型自报引用无效。
- **🔍 可观测**：可选接入 LangSmith 链路追踪。
- **✅ 全 Mock 测试**：不消耗任何真实 API 即可跑通端到端测试。

## 架构图

```
                            ┌─────────────────────────────────────┐
        HTTP (curl/前端)     │              FastAPI                  │
   ─────────────────────────▶  documents · qa · admin · health     │
                            └───────┬───────────────────┬──────────┘
                                    │                   │
                  ┌─────────────────▼──────┐   ┌────────▼─────────────────────┐
                  │   文档摄入 Ingest        │   │   Agentic RAG (create_agent) │
                  │  Loader → Splitter →    │   │  ┌────────────────────────┐  │
                  │  Embedding → 向量入库     │   │  │  Middleware 栈          │  │
                  └───────┬─────────┬───────┘   │  │  PII / 摘要 / 重试 / 审计 │  │
                          │         │           │  └───────────┬────────────┘  │
                          │         │           │   tool: search_knowledge_base │
                          │         │           └────────┬──────────┬──────────┘
                          ▼         ▼                    ▼          │
                  ┌──────────┐  ┌────────────────────────────┐     │
                  │  SQLite  │  │      Chroma 向量库           │◀────┘
                  │ documents│  │   collection: enterprise_kb │
                  │chat_records  └────────────────────────────┘
                  └──────────┘
                          ▲                    ▲             ▲
                          │                    │             │
                  ┌───────┴────────────────────┴─────────────┴───────┐
                  │        阿里云百炼  (LLM + Embedding，OpenAI 兼容)   │
                  └──────────────────────────────────────────────────┘
```

## 快速开始

> ⚠️ **务必使用独立虚拟环境**。若本机默认 `python` 指向 Anaconda base，那里通常是旧版 LangChain 0.3.x，缺少 `create_agent`，本项目无法运行。

```powershell
# 1. 进入项目目录
cd 企业级AI知识问答系统

# 2. 确认 Python 版本必须为 3.12+，且不能是 Anaconda 3.9
python --version
# 若这里不是 3.12+，请安装 Python 3.12，并用其完整路径执行下一行，例如：
# & "C:\path\to\Python312\python.exe" -m venv .venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# 如果 PowerShell 禁止激活：Set-ExecutionPolicy -Scope Process Bypass

# 3. 安装依赖
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 4. 配置密钥并自检连通性
Copy-Item .env.example .env     # 仅首次执行，避免覆盖已有密钥
# 编辑 .env，填入真实 DASHSCOPE_API_KEY 和至少 32 字符的随机 AUTH_JWT_SECRET；
# 不用 LangSmith 时保持追踪为 false
python test_connection.py       # 验证 LLM / Embedding / Chroma 三项均通

# 5. 分别启动 API 与摄入 Worker（两个终端，均先激活 .venv）
uvicorn app.main:app --reload
python -m app.worker
#   打开 http://127.0.0.1:8000/docs 交互式 API 文档
```

macOS/Linux 请用 `python3.12 -m venv .venv`、`source .venv/bin/activate`，并将 `Copy-Item` 换成 `cp`。

容器化部署：`docker compose up -d --build`（已挂载 `storage` / `chroma_db` / `logs` 卷）。

> ⚠️ Compose 默认只监听 `127.0.0.1`。JWT 验证不等于完成全部生产加固；在 HARNESS 最终验收前仍禁止将 8000 端口直接暴露到局域网或公网。
>
> 生产环境请设置 `APP_ENV=production`，此时 `/docs`、`/redoc` 与 `/openapi.json` 默认关闭。

## 技术选型说明

| 组件 | 选型 | 理由 |
|---|---|---|
| Agent 框架 | LangChain **1.3** + LangGraph | 1.3 的 `create_agent` 是官方推荐写法；LangGraph 提供检查点与状态图运行时 |
| LLM / Embedding | 阿里云百炼（OpenAI 兼容） | 国产合规、低延迟；OpenAI 兼容接口意味着换模型零改码 |
| 向量库 | Chroma（`langchain-chroma`） | 轻量、本地可跑、零运维，适合模板与中小规模 |
| Web 框架 | FastAPI + Uvicorn | 原生 async、自动生成 OpenAPI 文档 |
| 关系存储 | SQLite + SQLAlchemy 2.0（async）| 模板免运维；接口与 PostgreSQL 一致，可平滑切换 |
| 配置 | pydantic-settings | `.env` 强类型校验，杜绝硬编码密钥 |
| 文档解析 | LangChain Loader + OpenPyXL | PDF/DOCX/TXT 使用生态 Loader；XLSX 采用轻量适配器，避免引入重型 OCR 依赖 |

## 项目结构

```
企业级AI知识问答系统/
├── app/
│   ├── main.py                 # FastAPI 入口、lifespan、路由注册
│   ├── config.py               # pydantic-settings 配置单例
│   ├── core/
│   │   ├── llm.py              # init_llm / init_embeddings（走百炼）
│   │   ├── vectorstore.py      # get_vectorstore（Chroma 单例）
│   │   ├── retriever_tool.py   # @tool search_knowledge_base
│   │   ├── limits.py           # 速率/并发限制与每日模型预算
│   │   ├── process_pool.py     # 可超时并终止的不可信解析进程
│   │   ├── checkpointer.py     # 持久化会话连接生命周期
│   │   └── database.py         # 异步引擎 / 会话 / Base / init_db
│   ├── agent/
│   │   ├── agent.py            # build_agent（create_agent 单例）
│   │   └── middleware.py       # EnterpriseAuditMiddleware + 自定义状态
│   ├── services/
│   │   ├── file_security.py    # MIME/magic/展开限制/扫描器接口
│   │   ├── ingest.py           # 隔离解析→Splitter→向量入库
│   │   ├── ingest_jobs.py      # Job 租约、重试、崩溃恢复与补偿
│   │   ├── conversations.py    # 会话租约、TTL、消息裁剪与清理
│   │   ├── audit.py            # 预登记、重试与 fail-closed 审计
│   │   ├── sensitive_policy.py # 版本化分类与角色访问策略
│   │   └── consistency.py      # SQLite/文件/Chroma 一致性巡检
│   ├── worker.py               # 独立摄入 Worker 入口
│   ├── models/                 # SQLAlchemy 模型（含 ingest_job）
│   ├── schemas/                # Pydantic 出入参
│   └── api/                    # 路由：documents / qa / admin
├── tests/                      # 全 Mock 测试（pytest）
├── test_connection.py          # 连通性自检脚本
├── requirements.txt            # 运行依赖
├── requirements-dev.txt        # 测试依赖
├── Dockerfile / docker-compose.yml
└── .env.example
```

## 环境变量说明

复制 `.env.example` 为 `.env` 后填写：

| 变量 | 必填 | 说明 |
|---|:--:|---|
| `DASHSCOPE_API_KEY` | ✅ | 百炼 API Key（[控制台获取](https://bailian.console.aliyun.com/)）|
| `DASHSCOPE_BASE_URL` | | 百炼 OpenAI 兼容地址，默认 `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `LLM_MODEL` | | 对话模型，默认 `qwen3.6-plus`；必须使用百炼控制台显示的精确模型 ID（区分大小写）|
| `EMBED_MODEL` | | 向量模型，默认 `text-embedding-v3` |
| `LLM_MAX_OUTPUT_TOKENS` | | 单次模型输出上限，默认 2048 |
| `AGENT_MAX_STEPS` | | 单次 Agent 图节点上限，默认 30 |
| `MAX_MODEL_CALLS_PER_REQUEST` | | 单请求模型调用上限，默认 4 |
| `MAX_RETRIEVAL_CALLS_PER_REQUEST` | | 单请求知识库检索上限，默认 3 |
| `LANGSMITH_API_KEY` | | LangSmith 密钥，留空则不上报 |
| `LANGCHAIN_TRACING_V2` | | 是否开启链路追踪，`true` / `false` |
| `LANGCHAIN_PROJECT` | | LangSmith 项目名，默认 `enterprise-kb` |
| `DATABASE_URL` | | 异步数据库连接串，默认 SQLite（`storage/app.db`）|
| `APP_ENV` | | `development` / `production`；生产模式关闭 API 文档路由 |
| `APP_HOST` / `APP_PORT` | | 服务监听地址 / 端口，默认 `127.0.0.1:8000` |
| `LOG_LEVEL` | | 日志级别，默认 `INFO` |
| `AUTH_JWT_SECRET` | ✅ | HS256 验签密钥，至少 32 个随机字符；不得使用示例值 |
| `AUTH_JWT_ISSUER` | | 可信签发方，默认 `enterprise-idp` |
| `AUTH_JWT_AUDIENCE` | | 本服务 audience，默认 `enterprise-kb` |
| `MAX_QUESTION_CHARS` / `MAX_SESSION_ID_CHARS` | | 问题/会话标识字符上限，默认 4000 / 64 |
| `QA_RATE_LIMIT_PER_MINUTE` / `QA_MAX_CONCURRENCY` | | 单身份 QA 每分钟/并发上限，默认 30 / 8 |
| `UPLOAD_RATE_LIMIT_PER_MINUTE` / `UPLOAD_MAX_CONCURRENCY` | | 单身份上传每分钟/并发上限，默认 10 / 2 |
| `ADMIN_RATE_LIMIT_PER_MINUTE` / `ADMIN_MAX_CONCURRENCY` | | 单身份管理请求每分钟/并发上限，默认 60 / 10 |
| `DAILY_USER_MODEL_CALLS` / `DAILY_TENANT_MODEL_CALLS` | | 用户/租户每日模型调用预留上限，默认 200 / 5000 |
| `DAILY_USER_TOKEN_BUDGET` / `DAILY_TENANT_TOKEN_BUDGET` | | 用户/租户每日 Token 预算，默认 500000 / 10000000 |
| `MAX_FILENAME_CHARS` / `MAX_FILE_SIZE_BYTES` | | 文件名字符/文件字节上限，默认 200 / 52428800 |
| `UPLOAD_CHUNK_BYTES` / `UPLOAD_WRITE_TIMEOUT_SECONDS` | | 流式写块大小/写入超时，默认 1048576 / 30 秒 |
| `FILE_VALIDATION_TIMEOUT_SECONDS` / `PARSER_TIMEOUT_SECONDS` | | 文件安全校验/解析超时，默认 30 / 120 秒 |
| `PARSER_WORKERS` | | 独立解析进程数，默认 2 |
| `INGEST_JOB_MAX_ATTEMPTS` / `INGEST_JOB_LEASE_SECONDS` | | 摄入最大尝试次数 / Worker 租约秒数，默认 3 / 300 |
| `INGEST_JOB_POLL_SECONDS` / `INGEST_JOB_RETRY_BASE_SECONDS` | | Worker 轮询间隔 / 指数退避基数，默认 2 / 30 秒 |
| `INGEST_WORKER_CONCURRENCY` | | 单 Worker 进程并发槽位，默认 1 |
| `CHECKPOINT_DB_PATH` | | LangGraph 持久化 checkpoint 文件，默认 `storage/checkpoints.db` |
| `CONVERSATION_TTL_DAYS` / `CONVERSATION_MAX_MESSAGES` | | 会话有效期 / checkpoint 最大消息数，默认 30 天 / 100 |
| `CONVERSATION_LEASE_SECONDS` / `CONVERSATION_CLEANUP_BATCH` | | 同会话跨 Worker 租约 / 单次清理上限，默认 300 秒 / 200 |
| `AUDIT_WRITE_RETRIES` | | 审计事务失败后的重试次数，默认 3；最终失败时响应 fail-closed |
| `SENSITIVE_RULES_PATH` | | 版本化敏感分类与访问规则文件，默认 `config/sensitive_rules.json` |
| `MAX_ARCHIVE_ENTRIES` | | Office 压缩包条目上限，默认 2000 |
| `MAX_ARCHIVE_UNCOMPRESSED_BYTES` / `MAX_ARCHIVE_COMPRESSION_RATIO` | | 展开字节/压缩比上限，默认 104857600 / 100 |
| `MAX_PDF_PAGES` | | PDF 页数上限，默认 500 |
| `MAX_XLSX_SHEETS` / `MAX_XLSX_CELLS` | | 工作表/单元格上限，默认 100 / 1000000 |
| `MAX_PARSED_CHARS` | | 单文档解析文本字符上限，默认 2000000 |
| `MALWARE_SCAN_REQUIRED` | | 是否要求外部恶意软件扫描器成功，生产接入后设为 `true` |

## 身份认证与租户模型

除 `/health` 外，业务接口都要求 `Authorization: Bearer <token>`。Token 必须由外部企业身份系统签发；本服务只验证、不提供 Token 签发接口。固定使用 HS256，并校验签名、`iss`、`aud`、`exp`、`iat` 及以下 claims：

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

- 文档和问答路由需要 `user` 角色；管理路由需要 `admin` 角色。
- `user_id`、`tenant_id` 和角色只取自已验签 claims，请求体中的同名字段不会改变身份。
- Agent thread ID 由服务端生成：`tenant_id:user_id:session_id`。
- 旧版本数据迁移到受控的 `legacy` 租户；只有持有该 tenant claim 的已签名 Token 才能访问。

## 可信证据与拒答

检索工具的 `content` 只供模型阅读，`artifact` 才是服务端认可的证据。每条 `sources` 都包含 `doc_id`、稳定的 `chunk_id`、`source`、`page/sheet_name`、`distance` 和 `relevance`。

- API 不从模型回答文本中解析来源。
- 模型未调用工具或工具无命中时，服务端强制 `refused=true`。
- 模型生成的来源标注会被清除，再由真实 artifact 重建展示引用。
- 文档片段使用 `UNTRUSTED_DOCUMENT_CONTENT` 边界传给模型；文档中的提示、角色或工具指令一律视为不可信数据。
- `refused`、`has_source` 与 evidence 均为结构化状态，管理统计直接读取数据库字段。

## 会话、审计与分类访问策略

- 每次问答使用 `tenant:user:session` 作为 checkpoint thread，并通过 `conversation_sessions` 租约串行化同一会话；不同 API Worker 共享 `CHECKPOINT_DB_PATH`。
- 会话超过 `CONVERSATION_TTL_DAYS` 后读取立即失效；启动时或执行 `python -m app.commands.cleanup_sessions` 会删除关系目录和 checkpoint。消息超过配置上限时只保留最新消息。
- 问答在调用 Agent 前先写 `pending` 审计；完成事务记录 tool/sources/trace/model/tokens/latency。写入会重试，最终失败返回 503，不向客户端交付未审计回答；`GET /admin/audits/pending` 可观测待补偿记录。
- `config/sensitive_rules.json` 使用版本号和正则分类，避免简单子串匹配。工资/健康/法律分类分别要求 `hr` / `legal` / `admin` 等可信 JWT 角色；无权访问返回 403，同时创建人工任务。
- 人工任务状态为 `pending → claimed → completed`，领取和完成均受租户与处理人约束，每次变化写入 `human_task_events`。

## 资源与上传安全

- 所有上传先进入 `storage/quarantine/{tenant}`；MIME、magic、结构、资源与恶意软件检查通过且解析成功后，才移动到 `storage/documents/{tenant}`。
- PDF、DOCX、XLSX、TXT 分别执行页数、压缩展开、工作表/单元格、UTF-8 与文本量校验；失败响应不会包含服务器绝对路径或内部堆栈。
- 上传 API 只保存文件，并在同一数据库事务中创建 `documents` 与 `ingest_jobs`；独立 Worker 使用超时租约领取任务，因此 API 或 Worker 重启不会丢任务。
- 文档解析在独立 `ProcessPoolExecutor` 中运行并受超时控制。文件字节 SHA-256 用作租户内幂等键，chunk 使用稳定 ID；向量或数据库提交失败时会补偿清理，避免错误标记为 `indexed`。
- `python -m app.commands.check_consistency` 可只读巡检 SQLite、文件与 Chroma 的缺失/孤儿记录；返回码 0 表示一致。
- `MalwareScanner` 是可替换接口。默认扫描器仅用于开发；生产接入 ClamAV/EDR 后调用 `configure_malware_scanner(...)` 并设置 `MALWARE_SCAN_REQUIRED=true`。
- 分钟速率与并发限制按 `tenant:user` 在单 API 进程内执行；当前 Docker 默认单进程。每日模型调用与 Token 预算写入 SQLite，可跨重启生效。
- Token 预算在模型调用前按“问题估算 + 每次最大输出 × 单请求最大模型次数”保守预留；即使模型供应商未返回 usage metadata，也不会低估费用上界。

## API 文档

完整交互文档见 `http://127.0.0.1:8000/docs`。常用接口：

**上传文档**（异步索引，仅 pdf/docx/xlsx/txt，≤50MB）
```bash
curl -X POST http://127.0.0.1:8000/documents/upload -H "Authorization: Bearer $TOKEN" -F "file=@手册.pdf"
```

**文档列表 / 详情**（查看索引状态与切片数）
```bash
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/documents
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/documents/1
```

**摄入任务管理 / 删除**
```bash
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/documents/1/jobs
curl -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/documents/1/retry
curl -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/documents/1/cancel
curl -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/documents/1/reindex
curl -X DELETE -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/documents/1
```

**提问**（同一 `session_id` 自动带多轮记忆）
```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/qa/ask -Method Post -Headers @{Authorization="Bearer $env:TOKEN"} -ContentType "application/json" -Body '{"question":"报销流程是什么？","session_id":"s1"}'
# 返回: {"answer":"...","sources":[{"doc_id":1,"chunk_id":"...","source":"手册.pdf","page":2,"sheet_name":null,"distance":0.2,"relevance":0.8333}],"refused":false,"need_human":false}
```

**会话历史**
```bash
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/qa/history/s1
```

**管理看板**（统计 / 拒答列表 / 转人工列表）
```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1:8000/admin/stats
curl -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1:8000/admin/refused
curl -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1:8000/admin/human
curl -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1:8000/admin/human-tasks?status=pending
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1:8000/admin/human-tasks/1/claim
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" -d '{"resolution":"已处理"}' http://127.0.0.1:8000/admin/human-tasks/1/complete
curl -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1:8000/admin/human-tasks/1/events
curl -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1:8000/admin/audits/pending
```

## 扩展指南

### 更换大模型 / 向量模型

百炼接口与 OpenAI 兼容，**换百炼内任意模型只改 `.env`**，无需动代码：

```dotenv
LLM_MODEL=qwen3.6-plus       # 换成百炼控制台中当前账号可用的精确模型 ID
EMBED_MODEL=text-embedding-v3
```

若要切换到**其它厂商**（如 OpenAI、智谱），只需在 `app/core/llm.py` 调整 `base_url` 与 `api_key` 来源；其余代码因面向 LangChain 抽象编程而无需改动。

### 更换向量库

检索逻辑全部依赖 `get_vectorstore()` 返回的 LangChain `VectorStore` 抽象。换 Chroma 为 PGVector / Milvus / Qdrant，**只改 `app/core/vectorstore.py` 一处**：

```python
# app/core/vectorstore.py
from langchain_postgres import PGVector

@lru_cache(maxsize=1)
def get_vectorstore():
    return PGVector(
        collection_name="enterprise_kb",
        embeddings=init_embeddings(),
        connection=settings.database_url,
    )
```

`retriever_tool.py`、`ingest.py`、Agent 均无需改动。

> 💡 距离阈值 `MAX_DISTANCE`（`retriever_tool.py`）与具体 embedding/度量强相关，更换模型或向量库后请按真实数据重新调优。

## 路线图

- [x] 项目骨架、配置、容器化
- [x] 文档摄入管道（多格式、异步索引）
- [x] Agentic RAG 核心（检索工具 + 中间件栈）
- [x] 问答 / 历史 / 管理接口
- [x] 全 Mock 自动化测试
- [x] 持久化 Checkpointer、会话 TTL/消息边界与跨 Worker 租约
- [x] 可靠审计、分类访问策略与人工任务状态流
- [ ] 流式输出（SSE / WebSocket）
- [x] 持久化摄入任务、崩溃恢复与三存储一致性
- [x] 文档删除与向量库同步清理
- [x] JWT 鉴权、角色授权与租户隔离
- [x] 结构化检索证据、稳定 chunk ID 与服务端强制拒答
- [x] 输入、上传、解析、并发与每日费用安全边界
- [ ] 检索增强：重排（Rerank）、混合检索、引用高亮
- [ ] 前端管理台

## 测试

```bash
pip install -r requirements-dev.txt
pytest
```

全程使用 Mock（假模型 / 确定性假向量 / 内存 Chroma / 临时库），**不消耗任何真实 API**。

---

> 本项目为学习与模板用途，欢迎基于它搭建你自己的企业知识库。
