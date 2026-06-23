# 可观测性、告警与恢复 Runbook

本文档对应 `config/alerts.yml`。日志、指标和探针不得包含 API Key、Token、完整问题、完整文档片段、租户 ID 或用户 ID。

## 监控入口

- `GET /health/live`：只检查 HTTP 进程是否存活，不访问数据库、向量库或模型。
- `GET /health/ready`：在单组件超时内检查 SQLite、Chroma collection 和运行中摄入任务租约；不调用 LLM/Embedding，不产生模型费用。
- `GET /metrics`：Prometheus 文本，仅导出低基数路由标签和全局聚合，不导出租户、用户、问题或文件名。
- `X-Request-ID`：客户端可传 1–64 位字母、数字、点、下划线或横线；非法值会被服务端 UUID 替换。错误响应同时返回稳定 `error_code` 和 `request_id`。

关键指标包括请求量/延迟、拒答/人工率、摄入失败/队列积压、模型 Token/估算费用、真实重试/超时以及指标采集错误。费用只有在 `.env` 配置供应商每百万 Token 单价后才有业务含义。

## readiness

告警：`APIReadinessFailed`，持续 2 分钟为 critical。

1. 查结构化日志中的 `event=readiness_failed`、`component`、`error_code` 和 `request_id`，不要要求或复制用户问题。
2. `READINESS_DATABASE_UNAVAILABLE` 转 SQLite 流程；`READINESS_VECTORSTORE_UNAVAILABLE` 转 Chroma 流程；`READINESS_WORKER_LEASE_STALE` 检查 Worker 与过期租约。
3. 不要通过把 `/health/live` 配成部署 readiness 来绕过故障。

## sqlite

1. 确认 `storage/` 可写、磁盘未满，API/Worker 使用同一挂载卷。
2. 在维护窗口停止 API 与 Worker，运行 `PRAGMA integrity_check`；禁止直接删除 `app.db` 或 `checkpoints.db`。
3. 完整性失败时执行下方恢复演练，从最近已验证备份恢复到空目录；验证为零异常后才能安排正式切换。

## vectorstore

1. 确认 `chroma_db/` 可读写且未被多个不兼容 Chroma 版本同时打开。
2. 运行 `python -m app.commands.check_consistency`，区分缺失向量、额外向量与孤儿向量。
3. 单文档问题优先使用已有 reindex 接口；库损坏才进入整库恢复。不得只恢复 Chroma 而遗漏同时间点的 SQLite 和文件。

## worker lease / queue backlog / ingest failure

1. 检查 Worker 是否运行、`enterprise_kb_ingest_queue_backlog` 与容器资源。
2. 过期租约由 `recover_stale_ingest_state` 回收；不要手工把 `running` 改成 `succeeded`。
3. 检查解析超时、格式限制和向量索引错误码。先处理根因，再使用 retry/reindex 接口。

## model-timeout / model-cost

1. `MODEL_TIMEOUT` 只记录异常类型和 request ID，不记录问题正文或供应商凭据。
2. 对照供应商状态、出口网络、单请求模型调用上限和每日预算；禁止为消除告警无限扩大重试次数或超时。
3. `enterprise_kb_model_retries_total` 是实际重试次数，`enterprise_kb_model_timeouts_total` 是每次超时失败次数。
4. 费用是按已审计 Token 与配置单价估算；账单核对仍以供应商为准。

## 备份

备份必须在 API/Worker 已停止、没有写入者的维护窗口执行。工具不读取或复制 `.env`，且拒绝覆盖已有备份目录。

```powershell
docker compose stop api worker
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
.\.venv\Scripts\python.exe scripts\backup_restore.py backup `
  --destination "backups\stage10_$stamp" --maintenance-confirmed
docker compose start api worker
```

备份包含 `storage/`、`chroma_db/`、SHA-256 清单，并对其中 SQLite 文件使用在线备份 API 生成快照。仍要求维护窗口，以保证 Chroma HNSW 文件与元数据处于同一时点。

## 恢复演练

恢复命令只允许写入空目标，绝不原地覆盖正式 `storage/` 或 `chroma_db/`。

```powershell
$drill = Join-Path $env:TEMP "enterprise_kb_restore_drill"
.\.venv\Scripts\python.exe scripts\backup_restore.py restore `
  --backup "backups\stage10_YYYYMMDD_HHMMSS" --target-root $drill
.\.venv\Scripts\python.exe scripts\backup_restore.py verify --root $drill
```

只有 verify 返回 `total_issues=0`，且所有 SQLite `integrity_check=ok`，才算演练通过。正式恢复必须另开变更窗口：停止写入、保留当前卷作为回滚副本、把已验证恢复副本切换到原挂载点、启动 API/Worker、再次检查 readiness 和一致性。任何一步失败立即回滚，禁止删除原卷。
