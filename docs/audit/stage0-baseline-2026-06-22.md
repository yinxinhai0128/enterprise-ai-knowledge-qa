# 阶段 0 基线记录（2026-06-22）

## 环境

- Workspace: `D:\企业级AI知识问答系统`
- Python: `3.12.6`
- Git: `2.54.0.windows.1`
- Docker: `29.4.3`
- Docker Compose: `5.1.3`

## 核心依赖

| 包 | 版本 |
|---|---:|
| langchain | 1.3.10 |
| langchain-core | 1.4.8 |
| langchain-community | 0.4.2 |
| langchain-openai | 1.3.2 |
| langgraph | 1.2.6 |
| langchain-chroma | 1.1.0 |
| chromadb | 1.5.9 |
| fastapi | 0.138.0 |
| sqlalchemy | 2.0.51 |
| pydantic | 2.13.4 |
| pytest | 9.1.1 |

## 验证结果

- Python 编译：通过。
- Pytest：`14 passed`，仅有 `langchain-community` sunset 警告。
- Pip 依赖闭包：`No broken requirements found`。
- 百炼 LLM：通过，模型 `qwen3.6-plus`。
- Embedding：通过，模型 `text-embedding-v3`，维度 1024。
- Chroma 读写：通过。
- Docker Compose 配置：通过；受限执行环境无法读取用户 Docker config，但不影响 Compose 解析。
- 秘密扫描：`.env` 之外已知真实 Key 前缀命中数为 0。
- 通用启发式扫描的 3 个命中均为 `.env.example` 占位符或源码变量引用。

## 数据基线

- SQLite `integrity_check`: `ok`。
- Documents: 1。
- Document chunks: 1。
- Chat records: 4。
- Chroma vectors: 1。
- Chroma chunks by document: `{2: 1}`。
- 文件、数据库与 Chroma metadata 当前一致，无缺失和孤儿。

## 备份

- 路径：`backups/stage0_20260622_125445/`
- 正式 DB SHA-256：`3220833788992936A1AD719434740939B2A6C2BF0EEC43D4CA2B94B942E32203`
- 备份 DB SHA-256：`3220833788992936A1AD719434740939B2A6C2BF0EEC43D4CA2B94B942E32203`
- 正式与备份 SQLite 均 `integrity_check=ok`。
- Chroma 正式与备份文件数、总字节数一致。

## 安全状态

- `.env` 同时被 Git 与 Docker 忽略。
- `storage/`、`chroma_db/`、`logs/`、`.venv/`、`backups/` 被 Git 忽略。
- `.claude/settings.local.json` 被 Git 忽略。
- Key 仅验证存在且非占位符，未在本记录中保存内容或指纹。
- 百炼历史暴露 Key 是否已在控制台吊销，仍需账户所有者确认。

## 已知风险（留待后续阶段）

- 未实现认证、授权和租户隔离。
- `chromadb==1.5.9` 命中 `CVE-2026-45829`，当前补偿控制是不得暴露 Chroma HTTP Server。
- LangSmith 当前在真实 `.env` 中启用，数据治理在阶段 7 处理。
- 依赖尚未锁定，留待阶段 8。
