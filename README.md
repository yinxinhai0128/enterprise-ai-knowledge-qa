# 企业级 Agentic RAG 知识库

> 基于 **LangChain 1.3 + LangGraph** 的企业知识问答模板，全栈使用**国产大模型**（阿里云百炼）。
> 一套可直接复用的 Agentic RAG 骨架：文档摄入、自主检索问答、企业级审计与管控。

`LangChain 1.3` · `LangGraph` · `FastAPI` · `Chroma` · `阿里云百炼` · `Python 3.12`

---

## 简介

这是一个**可复用的企业知识库模板**。与"先检索再回答"的传统 RAG 不同，它采用 **Agentic RAG**——把检索封装成工具，由 Agent 自主判断何时检索、检索什么，并在回答中强制标注来源。内置 PII 脱敏、长对话摘要、失败重试与自定义审计（敏感词转人工 + 问答落库），开箱即用、易于二次开发。

## 核心特性

- **🤖 Agentic RAG**：`create_agent` + retriever-as-tool，Agent 自主决定检索时机，而非固定流程。
- **🇨🇳 全国产模型**：LLM 与 Embedding 均经阿里云百炼 OpenAI 兼容接口调用，无需出海。
- **📚 多格式摄入**：PDF / DOCX / TXT 使用 LangChain Loader，XLSX 使用兼容 `BaseLoader` 的 OpenPyXL 适配器；统一递归切分并异步入库。
- **🛡️ 企业级管控（中间件栈）**：PII 脱敏、对话摘要、模型重试，外加自定义审计中间件——敏感词命中标记转人工、每轮问答落库。
- **🔐 可信身份与租户隔离**：验证企业身份系统签发的 Bearer JWT，按 tenant/user/role 隔离关系数据、会话与向量检索。
- **🧠 多轮记忆**：基于 LangGraph Checkpointer，按 `session_id` 维护会话上下文。
- **📌 强制溯源**：回答按 `[来源:文件名 第X页]` 标注，无依据则明确拒答，杜绝编造。
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

# 5. 启动服务
uvicorn app.main:app --reload
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
│   │   └── database.py         # 异步引擎 / 会话 / Base / init_db
│   ├── agent/
│   │   ├── agent.py            # build_agent（create_agent 单例）
│   │   └── middleware.py       # EnterpriseAuditMiddleware + 自定义状态
│   ├── services/
│   │   └── ingest.py           # 文档摄入管道（Loader→Splitter→入库）
│   ├── models/                 # SQLAlchemy 模型（document / chat_record）
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

**提问**（同一 `session_id` 自动带多轮记忆）
```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/qa/ask -Method Post -Headers @{Authorization="Bearer $env:TOKEN"} -ContentType "application/json" -Body '{"question":"报销流程是什么？","session_id":"s1"}'
# 返回: {"answer":"...[来源:手册.pdf 第3页]","sources":["手册.pdf 第3页"],"refused":false,"need_human":false}
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
- [ ] Checkpointer 换持久化（`AsyncSqliteSaver`），会话记忆跨重启
- [ ] 流式输出（SSE / WebSocket）
- [ ] 文档删除与向量库同步清理
- [x] JWT 鉴权、角色授权与租户隔离
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
