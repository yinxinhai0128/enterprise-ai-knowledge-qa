# 依赖、Chroma 与容器安全基线

基线日期：2026-06-22。该文档记录当前可验证事实、临时风险接受和迁移决策；它不是永久豁免。

## 可复现依赖与持续扫描

- `requirements.txt` 和 `requirements-dev.txt` 只使用精确顶层版本。
- `requirements.lock` 由 Python 3.12 + `pip-tools==7.5.3` 解析完整运行依赖，并包含 PyPI SHA-256 哈希。
- 生产镜像只执行 `python -m pip install --require-hashes --no-deps -r requirements.lock`。
- `pip-audit==2.10.1` 扫描完整锁文件；`scripts/dependency_audit.py` 对所有未登记或已过期漏洞 fail closed。
- Dependabot 每周检查 pip 和 Docker 更新。阶段 9 将把相同审计加入 CI；在此之前，发布和每周例行检查都必须手工执行：

```powershell
.\.venv\Scripts\python.exe scripts/dependency_audit.py
```

更新依赖时先改精确顶层版本，随后重新生成锁并完整回归：

```powershell
.\.venv\Scripts\python.exe -m piptools compile --resolver=backtracking --generate-hashes --allow-unsafe --output-file=requirements.lock requirements.txt
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
.\.venv\Scripts\python.exe scripts/dependency_audit.py
.\.venv\Scripts\python.exe -m pytest -q
```

风险接受必须位于 `security/accepted-vulnerabilities.json`，并同时限制 CVE、包、版本，记录 owner、理由、控制和到期日。禁止使用无期限或包级通配豁免。

## CVE-2026-45829

`pip-audit` 对 `chromadb==1.5.9` 报告 `CVE-2026-45829`（别名 `GHSA-f4j7-r4q5-qw2c`）：攻击者可在未认证的 Chroma HTTP API 上提交恶意模型仓库并启用 `trust_remote_code`，进而执行任意代码。扫描器没有给出修复版本；2026-06-22 从 PyPI 官方 JSON 核验的最新正式版仍是 1.5.9。

因此当前采用有期限的补偿控制：

1. 本项目只能通过 `langchain_chroma.Chroma(..., persist_directory=...)` 使用进程内持久化客户端。
2. 禁止执行 `chroma run`、`chromadb.HttpClient`，禁止部署 Chroma Server/Cloud 客户端。
3. Compose 只能包含 `api` 与 `worker`，不得出现 Chroma 服务或 Chroma 端口。
4. API 仅绑定 `127.0.0.1`；容器以 UID/GID 10001、只读根文件系统、零 capabilities、`no-new-privileges` 运行。
5. 风险接受于 2026-07-22 到期。每周检查 PyPI、上游公告和 `pip-audit`；一旦出现修复版，先备份 Chroma 数据，升级、重建索引并运行全部测试和一致性巡检，然后删除例外。

任何人若需要 HTTP Chroma，必须先停止发布并迁移到已修复版本或其它向量库；当前风险接受不覆盖该部署形态。

## 向量库迁移评估

| 方案 | 安全与运维收益 | 成本/风险 | 适用判断 |
|---|---|---|---|
| pgvector | 可与 PostgreSQL 复用备份、审计、TLS、角色/RLS 和事务；减少一种数据库 | 需迁移 SQLite 与向量数据，重新校准索引和距离阈值 | 首选演进方向；当业务库迁 PostgreSQL 时一并实施 |
| Qdrant | 原生向量检索、payload filter、API key/TLS、快照与集群能力清晰 | 新增独立服务、网络面和备份/升级职责 | 向量规模或过滤性能先成为瓶颈时优先 |
| Milvus | 大规模分布式吞吐和索引类型丰富 | 组件与运维复杂度最高，资源和故障面更大 | 当前单机中小规模不采用 |

推荐路径是 pgvector：先建立双写/离线导入工具，以稳定 `chunk_id` 校验条数与租户 metadata，再影子读取比较召回，最后切换并保留可回滚备份。无论选择哪种后端，都必须重新测试 tenant filter、删除一致性、备份恢复和真实 embedding 距离阈值。

## `langchain-community` 独立集成迁移跟踪

当前仍有两个依赖点：

- `app/services/ingest.py` 的 `PyPDFLoader`、`Docx2txtLoader`、`TextLoader`。
- 同文件的 `filter_complex_metadata` 工具函数。

Chroma 已使用独立包 `langchain-chroma`，文本切分已使用 `langchain-text-splitters`。上述 loaders/utility 在本阶段没有行为等价且已验证的独立替代，因此保留精确版本 `langchain-community==0.4.2`，不做猜测式迁移。每周依赖检查时同时检查 LangChain 的独立集成发布；迁移验收必须覆盖 PDF/DOCX/TXT 解析、metadata 清洗、恶意文件边界和索引一致性，完成后才可删除该依赖。

## 容器构建与扫描

基础镜像固定为 `python:3.12.12-slim-bookworm` 的不可变多架构摘要。Dockerfile 只复制运行时源码/config/锁文件，源码归 root 且 appuser 不可写；`.env`、测试、备份、正式数据和 Git 元数据不进入构建上下文。

发布前运行：

```powershell
.\scripts\scan_container.ps1
docker compose config --quiet
```

脚本验证 UID 与镜像内容/源码权限，并用本机 Trivy 或 Docker Scout 阻断仍存在的 Critical/High 镜像漏洞。Compose 的数据目录是唯一可写卷，`/tmp` 是受限 tmpfs；不得通过新增源码 bind mount 绕过只读边界。

在原生 Linux 主机首次部署前，运维必须预创建 `storage`、`chroma_db`、`logs` 并将其 owner 设为 `10001:10001`、权限设为最小可用范围；禁止为了省事给数据目录 `0777`。Docker Desktop 的文件共享语义不同，仍应以容器内实际写入检查为准。
