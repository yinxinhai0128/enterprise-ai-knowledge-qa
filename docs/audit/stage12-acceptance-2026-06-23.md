# 阶段 12 最终生产候选验收报告

- 验收日期：2026-06-23（Asia/Shanghai）
- 验收实现提交：`622b7fc`
- 分支：`hardening/production-readiness`
- 应用版本：`0.1.0`
- 测试运行时：CPython 3.12.6
- 镜像运行时：CPython 3.12.13
- 最终镜像：`enterprise-kb-api:rc`
- 镜像摘要：`sha256:c62ebe18115338b6510db250d161e7100d9518e13d12bf69c6f855155d5eff85`
- 迁移版本：`schema@622b7fc`（`init_db` 幂等迁移）；备份清单 `schema_version=1`

## 结论

HARNESS 阶段 12 的自动化、安全、可靠性和真实环境验收门全部通过，当前代码可作为生产候选版本。这里的“生产候选”不替代企业 IdP、恶意软件扫描器、容量压测、反向代理/防火墙、远端权限审批及持续风险复审。

## 自动化与数据证据

| 验收项 | 结果与证据 |
|---|---|
| 编译与测试 | `compileall` 通过；`pytest -v` 为 119 passed、1 个已跟踪的 `langchain-community` 迁移警告 |
| 静态质量 | Ruff 全绿；Mypy 对 42 个源码文件 0 issues；`pip check` 无损坏依赖 |
| 依赖风险 | 120 个哈希锁定依赖；1 个 Chroma 风险命中有效例外；unaccepted=0 |
| 镜像风险 | 4 个 Critical/High 全部命中截至 2026-07-22 的精确例外；unaccepted=0 |
| 秘密与残留 | 秘密候选 0；`kb_test_*` 与阶段 12 临时验收目录残留均为 0 |
| 空库迁移 | 连续执行两次成功；`integrity_check=ok`；38 个 schema 对象 |
| 已有库迁移 | 阶段 10 备份恢复副本连续迁移两次；原有 6 行保留；与空库 38 个 schema 对象同名 |
| 恢复与一致性 | 恢复清单校验通过；SQLite/文件/向量六类异常及 `total_issues` 均为 0；正式一致性巡检也为 0 |
| Docker | 最终镜像以 10001:10001、只读根文件系统、无外网临时容器启动；health=`healthy`、readiness=200 |
| 暴露面 | Compose 仅含 API/Worker，API 只绑定 loopback，无 Chroma HTTP 服务 |

已有库验收首次发现 ORM `index=True` 不会为旧表补建 5 个索引，已将这些索引纳入显式幂等迁移；修复后空库与已有库对象集合一致。

## 安全验收映射

- `tests/test_auth.py`、`tests/test_api.py`：匿名业务路由 401、普通用户管理路由 403、跨用户/跨租户不可访问。
- `tests/test_agent.py`：来源只接受真实 tool artifact；模型伪造来源无效；文档提示词注入不能改变系统策略。
- `tests/test_limits.py`、`tests/test_ingest.py`、`tests/test_concurrency.py`：超长输入、频率/并发、预算、MIME/magic、恶意压缩包及解析资源边界均受限。
- `tests/test_tracing.py`：LangSmith 关闭时 SDK/HTTP 零调用；测试开启路径的最终载荷不含假敏感原文。真实 LangSmith 未执行，因为没有本次明确授权，实际 E2E 强制关闭追踪。
- `tests/test_container_security.py` 与最终 Compose/容器检查：Chroma HTTP Server 不存在，镜像不含 `.env`、tests、backups 或 Git 元数据。

## 可靠性验收映射

- `tests/test_ingest_jobs.py`：向量写入前后崩溃、DB 提交失败补偿、租约恢复、重试/取消/重建、稳定 chunk ID 与不重复向量。
- `tests/test_ingest.py`：文件、关系库与向量三层删除。
- `tests/test_persistence.py`：Checkpointer 跨重启恢复、共享会话、租约、TTL 和消息裁剪。
- `tests/test_backup_restore.py` 与阶段 10 备份副本复演：清单哈希、SQLite 完整性和三存储一致性通过。

真实 E2E 首次暴露 API/Worker 长期复用同一嵌入式 Chroma 目录会触发 `chromadb.errors.InternalError`。修复后所有向量操作通过跨进程文件锁串行化，并在每次操作后关闭客户端，避免复用旧状态。

## 真实环境验收

使用专用临时身份 `stage12-user` / `stage12-tenant` 和合成文件 `docs/samples/stage12-non-sensitive.txt`，在独立临时 SQLite、Chroma、文件与日志目录执行真实百炼调用：

1. 上传并由独立 Worker 完成真实 Embedding，文档达到 `indexed`；
2. 真实 Agent 调用检索工具并回答，API 返回 1 个与上传文档匹配的可信来源；
3. 会话历史持久化；
4. 删除后文档 404，文件、数据库、向量一致性为 0 异常；
5. LangSmith 强制关闭；未使用真实企业数据，未触碰正式数据。

本地验收客户端显式设置 `trust_env=False`，防止系统 HTTP 代理劫持 loopback 请求。Token 仅通过进程环境传递，验收输出不包含 Key、Token 或响应正文。

## 仍需持续治理

- 4 个风险例外必须在 2026-07-22 前复审；上游发布修复后立即升级并删除例外。
- `langchain-community` 已进入 sunset，按供应链文档迁移到独立集成包。
- 嵌入式 Chroma 与 SQLite 仅支持当前单机部署边界；多主机扩展前迁移到受支持的服务型向量库和 PostgreSQL。
- 上线方仍须完成企业 IdP、恶意软件扫描器、容量/故障压测、TLS 反向代理、防火墙和备份保留策略。
- LangSmith 只有在组织明确授权、远端权限/驻留/保留策略确认后才可执行真实验收与启用。
