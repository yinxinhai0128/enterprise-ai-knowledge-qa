# 企业级 AI 知识库生产化整改 Harness

> 用途：供 Codex、Claude Code 或人工工程师执行长流程整改。
> 原则：按阶段推进；每个阶段必须有验证证据，验收未通过不得进入下一阶段。
> 当前基线：功能链路已跑通，但尚未满足企业生产环境的安全、可信、可靠性要求。

---

## 1. 最终目标

把当前项目从“可运行的 Agentic RAG 模板”提升为具备以下能力的生产候选版本：

- 所有业务数据受认证、授权和租户隔离保护。
- 回答来源只能来自真实检索结果，模型无法伪造引用。
- 文档摄入可恢复、可重试、可删除、可审计，并具备幂等性。
- 多轮会话持久化，重启和多进程环境下保持一致。
- 企业数据不会未经治理上传到外部可观测平台。
- 输入、文件解析、模型调用均有资源和费用边界。
- 数据库、向量库、文件存储之间具备一致性检查和补偿机制。
- 依赖、镜像、迁移、测试和 CI 均可复现。

完成标志不是“代码写完”，而是第 12 阶段的全部验收门通过。

---

## 2. 当前已确认基线

执行前不得假设以下结果仍然成立，必须重新运行并记录：

- Python 3.12.6。
- `pytest` 当前为 14 项通过。
- LLM、Embedding、Chroma 连通性为 3/3。
- SQLite `integrity_check=ok`。
- 当前文档、SQLite 记录、Chroma chunk 一致。
- Docker Compose 配置可解析。
- `.env` 已被 `.gitignore` 和 `.dockerignore` 排除。
- 当前无 Git 仓库。
- 当前 `chromadb==1.5.9` 命中 `CVE-2026-45829`，但项目未暴露 Chroma HTTP Server。
- 当前真实 `.env` 开启 LangSmith 追踪。

---

## 3. 执行铁律

### 3.1 环境与数据

1. 只使用现有 `.venv`，运行前确认：

   ```powershell
   .\.venv\Scripts\python.exe --version
   ```

   必须为 Python 3.12+，禁止使用 Anaconda base。

2. 不得打印、提交、复制或在聊天中展示任何真实 Key、Token、JWT Secret。
3. 不得用真实企业文档执行自动化测试。
4. 测试必须强制关闭 LangSmith 和真实模型调用。
5. 修改数据库结构前必须备份：

   ```powershell
   Copy-Item storage storage_backup -Recurse
   Copy-Item chroma_db chroma_db_backup -Recurse
   ```

6. 不得执行 `git reset --hard`、覆盖 `.env`、删除正式 `storage/` 或 `chroma_db/`。
7. 所有新增配置必须同时更新 `.env.example` 与 README，示例值不得包含秘密。

### 3.2 代码与验证

1. 一次只执行一个阶段。
2. 先读相关文件，再修改；禁止凭旧版 LangChain 记忆写 API。
3. 每次修改后至少执行：

   ```powershell
   .\.venv\Scripts\python.exe -m compileall -q app tests
   .\.venv\Scripts\python.exe -m pytest -q
   .\.venv\Scripts\python.exe -m pip check
   ```

4. 不得通过删除断言、跳过测试、扩大阈值到无限大来制造“全绿”。
5. 失败必须记录根因、修复和回归证据。
6. 每个阶段完成后更新本文档的状态表与执行日志。

### 3.3 长流程恢复

如果执行中断，恢复时按以下顺序：

1. 读取“阶段状态表”。
2. 读取“执行日志”最近一条记录。
3. 检查工作区变更和当前测试结果。
4. 从首个 `in_progress` 或 `blocked` 阶段继续，禁止从头重做。
5. 同一阻塞连续出现三次，标记 `blocked`，写清缺少的外部条件，再继续不依赖该条件的任务。

---

## 4. 阶段状态表

状态只允许：`pending`、`in_progress`、`blocked`、`complete`。

| 阶段 | 内容 | 状态 | 验收证据 |
|---|---|---|---|
| 0 | 安全基线、备份与版本控制 | complete | 基线提交 `678638d`；备份/秘密扫描/测试/连接验收通过；旧 Key 已吊销 |
| 1 | 紧急暴露面收敛 | complete | Compose 仅绑定本机；生产文档端点 404；16 tests passed |
| 2 | 身份认证、授权与租户隔离 | complete | JWT/角色/tenant-user 隔离；25 tests passed；正式数据迁移完整 |
| 3 | 可信检索、结构化来源与拒答 | complete | artifact 驱动来源/拒答；稳定 chunk ID；29 tests passed |
| 4 | 输入、上传与解析安全 | complete | 资源/费用/文件/解析边界；54 tests passed |
| 5 | 持久化摄入任务与数据一致性 | complete | 验收通过 |
| 6 | 会话、审计与人工介入持久化 | complete | 验收通过 |
| 7 | LangSmith 与数据治理 | pending | |
| 8 | 依赖、Chroma CVE 与容器加固 | pending | |
| 9 | 测试体系与 CI | pending | |
| 10 | 可观测性、运维与恢复 | pending | |
| 11 | README、威胁模型和部署文档 | pending | |
| 12 | 最终生产候选验收 | pending | |

---

## 5. 阶段 0：安全基线、备份与版本控制

### 目标

建立可回滚、可审计的整改起点。

### 任务

- [x] 确认百炼与 LangSmith 旧 Key 已轮换；不得记录 Key 内容。
- [x] 扫描 `.env` 之外的秘密模式，结果必须为零。
- [x] 备份 `storage/` 和 `chroma_db/`。
- [x] 删除或合并误建的 `enterprise-kb/requirements.txt`，只保留唯一依赖入口。
- [x] 初始化 Git 仓库。
- [x] 确认 `.env`、运行数据、日志、虚拟环境均被忽略。
- [x] 建立整改分支，例如 `hardening/production-readiness`。
- [x] 保存基线测试、依赖版本、数据库与 Chroma 统计。

### 验收门

- [x] `git status` 不出现 `.env`、`storage/`、`chroma_db/`、`logs/`。
- [x] 源码和示例文件无真实密钥。
- [x] 基线测试全绿。
- [x] 备份可读取，SQLite 备份 `integrity_check=ok`。

---

## 6. 阶段 1：紧急暴露面收敛

### 目标

在完整鉴权上线前，防止服务被局域网或公网匿名访问。

### 任务

- [x] Compose 默认只绑定 `127.0.0.1:8000:8000`。
- [x] 新增 `APP_ENV=development|production`。
- [x] 生产环境默认关闭 `/docs`、`/redoc` 和 `/openapi.json`，或纳入管理员认证。
- [x] `/health` 仅返回最小存活信息，不暴露版本和内部组件。
- [x] 增加安全响应头。
- [x] README 明确：鉴权未完成前禁止对外开放。

### 验收门

- [x] 未配置鉴权时，Docker 端口不能从非本机访问。
- [x] 生产模式下文档端点不可匿名访问。
- [x] Compose 配置解析通过。

---

## 7. 阶段 2：身份认证、授权与租户隔离

### 目标

用户身份必须由服务端可信认证结果产生，禁止信任请求体中的 `user_id`。

### 默认决策

采用可替换的 `AuthContext` 抽象。若尚无企业 OIDC，先实现受配置控制的 JWT 验证层；不得创建无保护的“签发任意管理员 Token”接口。

### 任务

- [x] 新增 `AuthContext(user_id, tenant_id, roles)`。
- [x] 从 Bearer Token 的受验证 claims 获取身份。
- [x] 删除 `AskRequest.user_id`，或忽略并最终移除该字段。
- [x] 普通用户路由要求 `user` 角色。
- [x] `/admin/*` 要求 `admin` 角色。
- [x] 文档记录增加 `tenant_id`、`uploaded_by`。
- [x] 聊天记录增加 `tenant_id`、`user_id`。
- [x] thread ID 改为服务端生成的 `tenant:user:session`。
- [x] 文档列表、详情、检索、历史均强制 tenant/user 过滤。
- [x] 禁止跨用户读取历史，禁止跨租户检索向量。
- [x] 使用常量时间比较密钥或标准 JWT 库，禁止自行实现密码学。

### 必测场景

- [x] 无 Token：401。
- [x] 普通用户访问管理接口：403。
- [x] 用户 A 读取用户 B 会话：403/404。
- [x] 租户 A 无法检索租户 B 文档。
- [x] 伪造请求体 `user_id` 不改变服务端身份。

### 验收门

- [x] OpenAPI 存在安全方案。
- [x] 所有非健康检查端点均受保护。
- [x] 跨租户、跨用户自动化测试全绿。

---

## 8. 阶段 3：可信检索、结构化来源与拒答

### 目标

来源、拒答和是否检索必须由服务端真实状态产生，不能由模型文本决定。

### 任务

- [x] 检索工具返回 `content + artifact`，artifact 至少包含：
  - `doc_id`
  - `chunk_id`
  - `source`
  - `page/sheet_name`
  - `distance/relevance`
- [x] 使用稳定的 chunk ID，而非 Chroma 自动随机 ID。
- [x] Agent state 增加 `retrieved_evidence`。
- [x] API 的 `sources` 从真实 tool artifact 生成，禁止正则解析最终回答。
- [x] `has_source` 由真实证据决定。
- [x] `refused` 作为结构化状态/数据库字段保存，不再依赖中文话术匹配。
- [x] 若模型生成引用不在真实 evidence 中，删除该引用并记录告警。
- [x] 对知识库事实型回答，若没有成功检索证据，则强制拒答或进入受控重试。
- [x] 在 system prompt 中声明文档内容是不可信数据，禁止执行文档内指令。
- [x] 增加文档提示词注入测试。

### 必测场景

- [x] 假模型直接输出 `[来源:fake.txt]`，API 必须拒绝该来源。
- [x] 模型没有调用工具但尝试回答内部制度，必须拒答。
- [x] 工具真实命中后，sources 与 artifact 完全一致。
- [x] 无结果时 `refused=true`，且数据库统计准确。
- [x] 文档中包含“忽略系统提示”时，不改变 Agent 行为。

### 验收门

- [x] 不再存在以 `[来源:` 子串作为真实性依据的代码。
- [x] `test_agent` 包含真实 fake tool-calling 回环，而非只脚本化最终回答。

---

## 9. 阶段 4：输入、上传与解析安全

### 目标

为费用、内存、CPU、磁盘和解析器建立明确边界。

### 任务

- [x] 为 `question`、`session_id`、文件名、用户可控 metadata 增加最大长度。
- [x] 对 `/qa/ask`、上传和管理接口增加限流与并发限制。
- [x] 限制单用户/租户每日模型调用量和 Token 成本。
- [x] 文件名安全规范化并限制长度，超长返回 400，而不是 500。
- [x] 不只检查扩展名，同时验证 MIME 和 magic bytes。
- [x] 增加压缩后展开大小、PDF 页数、工作表数、单元格数和文本总量限制。
- [x] 上传文件进入隔离目录，解析成功前不得视为可信。
- [x] 为恶意软件扫描预留接口。
- [x] 解析任务与 API 进程隔离，至少放入独立 Worker。
- [x] 对同步磁盘写入和解析设置超时。

### 必测场景

- [x] 300 字符文件名返回 400。
- [x] 百万字符问题返回 422/413。
- [x] 扩展名伪造被拒绝。
- [x] 空文件、超 50MB、超页数、超单元格均有明确错误。
- [x] 并发上传不会阻塞问答健康检查。

### 验收门

- [x] 所有资源限制均来自配置并有默认安全值。
- [x] 解析错误不泄露服务器绝对路径或内部堆栈。

---

## 10. 阶段 5：持久化摄入任务与数据一致性

### 目标

替换易丢失的 `BackgroundTasks`，实现可恢复的摄入工作流。

### 默认决策

优先采用数据库持久化 `ingest_jobs` + 独立 Worker；如果项目已有 Redis 基础设施，可改用成熟队列，但必须保留数据库状态与幂等键。

### 任务

- [x] 新增 `ingest_jobs` 表：状态、attempt、next_retry_at、lease、error。
- [x] 文档上传只负责落盘、建记录、创建 Job。
- [x] Worker 领取 Job，具备超时租约和崩溃恢复。
- [x] 应用启动时修复长期停留在 `uploading/parsing` 的记录。
- [x] 文件保存时计算 SHA-256，建立租户内幂等键。
- [x] 为每个 chunk 生成稳定 ID：`tenant:doc_id:chunk_index:content_hash`。
- [x] Chroma 写入失败时不得标记 indexed。
- [x] DB 更新失败时执行向量补偿删除或记录 reconciliation job。
- [x] 新增重试、取消和重新索引接口。
- [x] 新增文档删除：数据库、文件、向量同步清理。
- [x] 新增一致性巡检命令。

### 必测场景

- [x] Worker 在向量写入前/后崩溃均可恢复。
- [x] 重复上传不会产生重复 chunk。
- [x] 删除文档后三个存储层均无残留。
- [x] 同一 Job 多次执行结果一致。

### 验收门

- [x] API 重启不会丢失摄入任务。
- [x] 一致性巡检结果为零缺失、零孤儿。

---

## 11. 阶段 6：会话、审计与人工介入持久化

### 目标

让多轮记忆、审计和人工介入跨重启、跨进程可靠工作。

### 任务

- [x] 将 `InMemorySaver` 替换为持久化 Checkpointer。
- [x] thread/checkpoint 按 tenant/user 隔离。
- [x] 为会话设置生命周期、最大消息数和清理任务。
- [x] 审计表增加：user、tenant、refused、tool_used、sources、trace_id、model、tokens、latency。
- [x] 审计写入不得静默失败；明确选择 fail-closed、outbox 或告警策略。
- [x] `need_human` 不只返回布尔值，建立人工队列表、状态流转和处理人。
- [x] 敏感词规则可配置、可版本化，并避免简单子串误报。
- [x] 对工资、健康、法律等数据建立访问策略，而不是只标记。

### 验收门

- [x] 重启后同一用户会话可恢复。
- [x] 多 Worker 下会话一致。
- [x] 审计写入故障可观测且可补偿。
- [x] 人工任务可查询、领取、完成、审计。

---

## 12. 阶段 7：LangSmith 与数据治理

### 目标

外部追踪必须显式授权、最小化数据并可审计。

### 任务

- [ ] 生产默认 `LANGCHAIN_TRACING_V2=false`。
- [ ] 追踪开启必须经过环境和组织策略批准。
- [ ] 记录会发送哪些输入、输出、文档片段和 metadata。
- [ ] 对用户问题和工具结果实施追踪前脱敏。
- [ ] 工具结果默认不发送完整文档内容，必要时只发送 hash/doc_id。
- [ ] 设置采样率、项目权限和保留周期。
- [ ] 测试环境强制关闭追踪并断言不会产生网络请求。
- [ ] 将数据驻留、供应商协议和删除流程写入文档。

### 验收门

- [ ] 使用假敏感数据验证 LangSmith 中不可见原文。
- [ ] 关闭追踪时不创建任何 LangSmith run。

---

## 13. 阶段 8：依赖、Chroma CVE 与容器加固

### 目标

实现可复现、可审计、最小权限的供应链和运行环境。

### 任务

- [ ] 生成锁文件或精确版本约束，禁止只有无上限的 `>=`。
- [ ] 引入持续依赖漏洞扫描。
- [ ] 记录 `CVE-2026-45829` 补偿控制：不得启动/暴露 Chroma HTTP Server。
- [ ] 监控 Chroma 修复版本；修复发布后升级并回归。
- [ ] 评估迁移 PGVector/Qdrant/Milvus 的成本与安全收益。
- [ ] 跟踪 `langchain-community` 独立集成迁移。
- [ ] `.dockerignore` 排除 tests、`.claude`、`requirements-dev.txt`、重复目录和开发文件。
- [ ] Docker 镜像中源码由 root 拥有，仅数据目录交给 appuser 写入。
- [ ] 增加只读根文件系统、drop capabilities、`no-new-privileges`、资源限制。
- [ ] 固定基础镜像版本/摘要，并执行镜像漏洞扫描。
- [ ] 容器不包含 `.env`、备份、测试数据和 Git 元数据。

### 验收门

- [ ] 依赖扫描无未接受的 Critical/High 风险。
- [ ] 镜像以非 root 运行且不能修改应用源码。
- [ ] Compose 不暴露 Chroma 服务。

---

## 14. 阶段 9：测试体系与 CI

### 目标

测试必须覆盖真实安全边界和 Agent 行为，而不只是最终字符串。

### 任务

- [ ] 修复测试临时目录未清理问题，显式 dispose 数据库引擎。
- [ ] 增加 PDF、DOCX、XLSX、UTF-8 TXT 实际解析样本。
- [ ] 增加上传大小、长文件名、伪造 MIME、空文件测试。
- [ ] 增加认证、角色、跨用户、跨租户测试。
- [ ] 增加真实 fake tool-call 回环和伪造来源测试。
- [ ] 增加 prompt injection、PII、人工介入测试。
- [ ] 增加任务重启、重试、幂等、删除、一致性测试。
- [ ] 增加管理接口和拒答率准确性测试。
- [ ] 增加并发上传和并发问答测试。
- [ ] 增加 `ruff`、类型检查、依赖扫描、秘密扫描。
- [ ] 新增 CI，至少运行 lint、type-check、pytest、dependency audit、Docker build。
- [ ] CI 禁止使用真实 API Key。

### 验收门

- [ ] 所有测试全绿且无真实外部调用。
- [ ] 测试结束后无 `kb_test_*` 临时目录残留。
- [ ] CI 在干净环境中通过。

---

## 15. 阶段 10：可观测性、运维与恢复

### 目标

系统故障可发现、可定位、可恢复。

### 任务

- [ ] 区分 `/health/live` 与 `/health/ready`。
- [ ] readiness 检查 SQLite、向量库、Worker 租约，不直接消耗模型费用。
- [ ] 增加 request_id、结构化日志和错误码。
- [ ] 日志禁止出现 Key、Token、完整敏感问题和完整文档片段。
- [ ] 增加请求量、延迟、拒答率、人工率、摄入失败率、队列积压指标。
- [ ] 增加模型 Token、费用、重试次数和超时指标。
- [ ] 编写 SQLite、Chroma、文件备份与恢复脚本。
- [ ] 验证从备份恢复后的一致性。
- [ ] 建立告警阈值和故障处理 Runbook。

### 验收门

- [ ] 模拟数据库不可用、向量库不可用、模型超时均能产生清晰告警。
- [ ] 恢复演练通过，数据一致性巡检为零异常。

---

## 16. 阶段 11：README、威胁模型和部署文档

### 目标

新开发者和运维人员能在不依赖口头知识的情况下安全运行系统。

### 任务

- [ ] README 快速开始在干净 Python 3.12 环境实跑。
- [ ] 明确开发、测试、生产三套配置。
- [ ] 增加认证和 Token 获取说明。
- [ ] 增加租户模型、数据流和信任边界图。
- [ ] 增加威胁模型：匿名访问、越权、提示词注入、恶意文件、数据外传、费用攻击。
- [ ] 增加数据库迁移、备份恢复、Key 轮换说明。
- [ ] 增加 LangSmith 数据治理说明。
- [ ] 增加已知限制和容量边界。
- [ ] 删除“企业级生产可用”等未经验收的表述，直到第 12 阶段通过。

### 验收门

- [ ] 新用户只按 README 即可安全启动。
- [ ] 不存在与实际代码不一致的 API、模型名和配置。

---

## 17. 阶段 12：最终生产候选验收

### 自动化验收

```powershell
.\.venv\Scripts\python.exe -m compileall -q app tests
.\.venv\Scripts\python.exe -m pytest -v
.\.venv\Scripts\python.exe -m pip check
docker compose config --quiet
```

- [ ] lint/type-check 全绿。
- [ ] 依赖与镜像漏洞扫描无未接受的 Critical/High。
- [ ] 秘密扫描结果为零。
- [ ] 数据库迁移可在空库和已有库执行。
- [ ] SQLite、文件、向量一致性为零异常。
- [ ] Docker 镜像构建和健康检查通过。

### 安全验收

- [ ] 匿名访问所有业务路由均为 401。
- [ ] 普通用户访问管理路由为 403。
- [ ] 跨用户、跨租户访问不可行。
- [ ] 模型伪造来源不会被 API 接受。
- [ ] 文档提示词注入不能改变系统策略。
- [ ] 超长输入、恶意文件和高频请求被限制。
- [ ] Chroma HTTP Server 不可访问。
- [ ] LangSmith 关闭时零上报；开启时敏感数据已脱敏。

### 可靠性验收

- [ ] API/Worker 在摄入各阶段崩溃后任务可恢复。
- [ ] 多次重试不产生重复向量。
- [ ] 删除文档后文件、数据库、向量均清理。
- [ ] 重启后会话可恢复。
- [ ] 备份恢复演练通过。

### 真实环境验收

- [ ] 使用专用测试账号和非敏感样本文档完成端到端流程。
- [ ] LangSmith 验收只在明确授权时执行。
- [ ] 记录版本、提交号、镜像摘要、迁移版本和验收日期。

只有上述项目全部完成，阶段 12 才可标记 `complete`。

---

## 18. 每阶段执行报告模板

每完成或阻塞一个阶段，在执行日志中追加：

```markdown
### YYYY-MM-DD HH:mm - 阶段 N：名称

- 状态：complete / blocked
- 修改文件：
  - path/to/file.py
- 数据迁移：无 / 迁移版本
- 验证命令：
  - command
- 验证结果：
  - 14 passed
- 安全影响：
- 已知遗留：
- 下一步：
```

---

## 19. 执行日志

> 新记录追加在此处，不覆盖历史记录。

### 2026-06-22 - Harness 创建

- 状态：pending
- 基于全面排查结果拆解 13 个阶段。
- 尚未执行生产化整改。
- 下一步：执行阶段 0，先备份、秘密扫描并初始化版本控制。

### 2026-06-22 - 阶段 0 开始

- 状态：in_progress
- 前置检查：Python 3.12.6；8000 端口空闲；Git 身份已配置。
- 安全约束：不输出密钥、不覆盖 `.env`、不修改正式运行数据。
- 下一步：建立备份、执行秘密扫描并初始化 Git 基线。

### 2026-06-22 - 阶段 0 本地任务完成

- 状态：in_progress
- 修改文件：`.gitignore`、`.dockerignore`、`.gitattributes`、`HARNESS.md`、`docs/audit/stage0-baseline-2026-06-22.md`。
- 清理：删除无提交、无独有文件的误建嵌套仓库 `enterprise-kb/`。
- 备份：`backups/stage0_20260622_125445/`；源与备份 DB SHA-256 一致，双方 `integrity_check=ok`。
- 秘密扫描：`.env` 之外真实 Key 前缀命中 0；通用扫描命中均为占位符或变量名。
- 验证：Python 编译通过；`14 passed`；pip check 通过；LLM/Embedding/Chroma 3/3；Compose config 通过。
- Git：初始化分支 `hardening/production-readiness`；禁止文件暂存数为 0。
- 未决：需账户所有者确认此前暴露的百炼旧 Key 已在控制台吊销。确认前阶段 0 保持 `in_progress`。
- 下一步：收到 Key 吊销确认后，将阶段 0 标记 `complete`；不得提前进入阶段 1。

### 2026-06-22 - 阶段 0 完成

- 状态：complete
- 外部确认：账户所有者已确认此前暴露的百炼旧 Key 已吊销；未记录任何 Key 内容或指纹。
- 本地验收：备份、秘密扫描、Git 忽略、基线测试、连接测试、数据完整性与 Compose 配置均通过。
- Git 基线：分支 `hardening/production-readiness`，基线提交 `678638d`。
- 已知遗留：生产安全问题按阶段 1～12 处理，本阶段未提前修改业务功能。
- 下一步：下一次执行从阶段 1“紧急暴露面收敛”开始。

### 2026-06-22 - 阶段 1 开始

- 状态：in_progress
- 范围：本机端口绑定、环境模式、生产文档关闭、最小健康响应、安全响应头和部署警示。
- 边界：本阶段不提前实现认证、角色或租户隔离。
- 下一步：修改配置与应用工厂，补充自动化和 Compose 验收。

### 2026-06-22 13:08 - 阶段 1：紧急暴露面收敛

- 状态：complete
- 修改文件：
  - `.env.example`
  - `docker-compose.yml`
  - `app/config.py`
  - `app/main.py`
  - `tests/test_api.py`
  - `README.md`
  - `HARNESS.md`
- 数据迁移：无；未修改 `.env`、SQLite、Chroma 或上传数据。
- 验证命令：
  - `.\.venv\Scripts\python.exe -m compileall -q app tests`
  - `.\.venv\Scripts\python.exe -m pytest -v`
  - `.\.venv\Scripts\python.exe -m pip check`
  - `docker compose config --format json`（仅提取端口字段）
- 验证结果：16 passed；无损坏依赖；Compose 解析成功，端口为 `127.0.0.1:8000:8000/tcp`；生产模式 `/docs`、`/redoc`、`/openapi.json` 均返回 404。
- 安全影响：未完成鉴权前默认限制为本机访问；生产环境关闭文档端点；健康响应最小化；统一添加基础安全响应头。
- 已知遗留：身份认证、授权与租户隔离尚未实现，由阶段 2 处理；`langchain-community` 弃用警告按后续依赖阶段处理。
- 下一步：停止本次执行；下一次从阶段 2 开始。

### 2026-06-22 - 阶段 2 开始

- 状态：in_progress
- 范围：JWT 验证、角色授权、可信身份、关系库与向量库租户隔离、服务端线程标识。
- 数据保护：数据库结构修改前创建新的 `storage`、`chroma_db` 快照，不覆盖已有备份。
- 下一步：完成备份后实施并验证阶段 2；验收未通过不进入阶段 3。

### 2026-06-22 13:25 - 阶段 2：身份认证、授权与租户隔离

- 状态：complete
- 修改文件：
  - `.env.example`、`requirements.txt`、`README.md`
  - `app/core/auth.py`、`app/core/database.py`、`app/core/retriever_tool.py`、`app/core/vectorstore.py`
  - `app/api/admin.py`、`app/api/documents.py`、`app/api/qa.py`
  - `app/models/chat_record.py`、`app/models/document.py`
  - `app/schemas/document.py`、`app/schemas/qa.py`
  - `app/agent/__init__.py`、`app/agent/middleware.py`、`app/main.py`、`app/services/ingest.py`
  - `tests/conftest.py`、`tests/test_agent.py`、`tests/test_auth.py`
- 数据迁移：执行前备份至 `backups/stage2_20260622_131157/`，源与备份 SQLite SHA-256 一致；正式库新增 tenant/user 字段和复合索引，旧关系记录与 1 条旧向量归入 `legacy`；二次执行更新数为 0。
- 验证命令：
  - `.\.venv\Scripts\python.exe -m compileall -q app tests`
  - `.\.venv\Scripts\python.exe -m pytest -q`
  - `.\.venv\Scripts\python.exe -m pip check`
  - SQLite 完整性、记录数、NULL 身份字段和 Chroma tenant metadata 聚合检查
  - Git 跟踪文件秘密候选扫描
- 验证结果：25 passed；无损坏依赖；OpenAPI 声明 `BearerAuth`；匿名业务请求 401、普通用户访问管理接口 403、跨用户读取 404；跨租户列表/详情/检索均隔离；秘密候选 0。
- 数据证据：迁移前后均为 documents=1、chat_records=4、vectors=1；`integrity_check=ok`；身份字段 NULL=0；缺少 tenant metadata 的向量=0。
- 安全影响：身份只取自固定 HS256 算法验签后的 claims；示例/弱密钥失败关闭；无 Token 签发接口；thread ID、关系查询、管理统计与向量检索均带租户边界。
- 已知遗留：正式运行前需在 `.env`/秘密管理系统配置至少 32 字符随机 `AUTH_JWT_SECRET` 并由可信身份系统签发 Token；持久化会话和可信来源由后续阶段处理；`langchain-community` 弃用警告仍留待依赖阶段。
- 下一步：停止本次执行；下一次从阶段 3 开始。

### 2026-06-22 - 阶段 3 开始

- 状态：in_progress
- 范围：工具 artifact、稳定 chunk ID、Agent 证据状态、服务端来源、结构化拒答与文档提示词注入防护。
- 数据保护：新增 `refused` 字段和补齐向量 metadata 前，新建 `storage`、`chroma_db` 快照。
- 下一步：验收可信工具回环和拒答统计；未通过不得进入阶段 4。

### 2026-06-22 13:42 - 阶段 3：可信检索、结构化来源与拒答

- 状态：complete
- 修改文件：
  - `app/agent/context.py`、`app/agent/agent.py`、`app/agent/middleware.py`
  - `app/core/evidence.py`、`app/core/retriever_tool.py`、`app/core/vectorstore.py`、`app/core/database.py`
  - `app/api/qa.py`、`app/api/admin.py`
  - `app/models/chat_record.py`、`app/schemas/qa.py`、`app/services/ingest.py`
  - `tests/conftest.py`、`tests/test_agent.py`、`tests/test_api.py`、`tests/test_auth.py`、`tests/test_ingest.py`
  - `README.md`、`HARNESS.md`
- 数据迁移：执行前备份至 `backups/stage3_20260622_132948/` 且 SQLite SHA-256 一致；正式库新增 `chat_records.refused`，旧拒答迁移 2 条；1 条旧向量固化 legacy chunk ID；二次迁移更新数为 0。
- 验证命令：
  - `.\.venv\Scripts\python.exe -m compileall -q app tests`
  - `.\.venv\Scripts\python.exe -m pytest -q`
  - `.\.venv\Scripts\python.exe -m pip check`
  - SQLite 完整性、`refused` 列、Chroma `chunk_id` 聚合检查
  - QA 文本真实性依据、管理拒答启发式、fake tool-loop 静态证据检查
  - Git 提交范围秘密候选扫描
- 验证结果：29 passed；无损坏依赖；QA 文本真实性标记 0；管理拒答话术启发式 0；fake tool-loop 断言 7；秘密候选 0。
- 数据证据：迁移前后 chat_records=4、vectors=1；`integrity_check=ok`；正式向量缺少 chunk ID 数=0。
- 安全影响：API sources、`has_source`、`refused` 和管理统计只认真实 ToolMessage artifact/结构化字段；无证据强制拒答；模型自报引用被清除；文档内容显式标记为不可信数据。
- 已知遗留：当前 relevance 由 Chroma L2 distance 单调换算，仍需按真实 embedding 校准；持久化 evidence 审计、重排与更强注入检测留待后续阶段；`langchain-community` 弃用警告留待依赖阶段。
- 下一步：停止本次执行；下一次从阶段 4 开始。

### 2026-06-22 - 阶段 4 开始

- 状态：in_progress
- 范围：请求/费用/并发边界、文件真实性与展开限制、隔离目录、恶意软件扫描接口、解析进程与超时。
- 阶段边界：解析使用独立进程池；持久化摄入队列仍由阶段 5 实现。
- 数据保护：新增每日用量账本前创建新的 `storage`、`chroma_db` 快照。
- 下一步：逐项完成资源限制和必测场景，验收未通过不得进入阶段 5。

### 2026-06-22 14:12 - 阶段 4：输入、上传与解析安全

- 状态：complete
- 修改文件：
  - `.env.example`、`README.md`、`HARNESS.md`
  - `app/config.py`、`app/core/auth.py`、`app/core/llm.py`
  - `app/core/limits.py`、`app/core/process_pool.py`
  - `app/services/file_security.py`、`app/services/ingest.py`
  - `app/api/qa.py`、`app/api/documents.py`、`app/api/admin.py`、`app/agent/agent.py`、`app/main.py`
  - `app/models/usage_daily.py`、`app/models/__init__.py`、`app/schemas/qa.py`
  - `tests/conftest.py`、`tests/test_ingest.py`、`tests/test_limits.py`
- 数据迁移：执行前备份至 `backups/stage4_20260622_134704/` 且 SQLite SHA-256 一致；新增空 `usage_daily` 表；二次迁移幂等。
- 验证命令：
  - `.\.venv\Scripts\python.exe -m compileall -q app tests`
  - `.\.venv\Scripts\python.exe -m pytest -q`
  - `.\.venv\Scripts\python.exe -m pip check`
  - SQLite 完整性、原表计数与 `usage_daily` 聚合检查
  - 资源配置覆盖、异常直出、Git 提交范围秘密候选扫描
- 验证结果：54 passed；无损坏依赖；资源配置缺失 0；异常对象直出模式 0；秘密候选 0。
- 数据证据：迁移前后 documents=1、chat_records=4；`integrity_check=ok`；usage_daily=0。
- 安全影响：问题/会话/文件名、单文件、压缩展开、页/表/单元格/文本均有配置上限；QA/上传/管理具备速率与并发限制；模型调用和 Token 预算按用户/租户持久化预留；文件在 quarantine 完成扫描/隔离解析后才晋升；超时 Worker 会被硬终止；客户端错误不含路径或堆栈。
- 已知遗留：分钟限流是当前单 API 进程内状态，多进程部署需共享限流后端；`BackgroundTasks` 将由阶段 5 持久任务队列替换；生产需接入实际恶意软件扫描器并启用 required；`langchain-community` 弃用警告留待依赖阶段。
- 下一步：停止本次执行；下一次从阶段 5 开始。

### 2026-06-22 - 阶段 5 开始

- 状态：in_progress
- 范围：持久化 ingest_jobs、独立 Worker 租约/恢复/重试、SHA-256 幂等、删除/重建与一致性巡检。
- 阶段边界：只持久化摄入工作流；会话与人工介入持久化仍由阶段 6 处理。
- 数据保护：新增任务表和文档哈希字段前创建新的 `storage`、`chroma_db` 快照。
- 下一步：实现可恢复任务和三存储补偿，验收未通过不得进入阶段 6。

### 2026-06-22 18:47 - 阶段 5：持久化摄入任务与数据一致性

- 状态：complete
- 修改文件：
  - `.env.example`、`README.md`、`HARNESS.md`、`docker-compose.yml`
  - `app/config.py`、`app/core/database.py`、`app/main.py`、`app/worker.py`
  - `app/models/document.py`、`app/models/ingest_job.py`、`app/models/__init__.py`
  - `app/api/documents.py`、`app/schemas/document.py`
  - `app/services/ingest.py`、`app/services/ingest_jobs.py`、`app/services/vector_ops.py`、`app/services/consistency.py`
  - `app/commands/check_consistency.py`
  - `tests/conftest.py`、`tests/test_api.py`、`tests/test_auth.py`、`tests/test_ingest.py`、`tests/test_ingest_jobs.py`、`tests/test_limits.py`
- 数据迁移：执行前备份至 `backups/stage5_20260622_182858/` 且源与备份 SQLite SHA-256 一致；正式库新增 `documents.content_sha256`、租户内部分唯一索引和空 `ingest_jobs` 表；迁移连续执行两次幂等。
- 验证命令：
  - `.\.venv\Scripts\python.exe -m compileall -q app tests`
  - `.\.venv\Scripts\python.exe -m pytest -q`
  - `.\.venv\Scripts\python.exe -m app.commands.check_consistency`
  - `.\.venv\Scripts\python.exe -m pip check`
  - `docker compose config --quiet`
  - SQLite 完整性、表/列/索引、原表计数与 Git 提交范围秘密候选检查
- 验证结果：64 passed；无损坏依赖；Compose 配置解析通过；API 新实例仍能读取 pending Job；向量前/后崩溃、DB 提交失败补偿、重复 Job、重试/取消/重建及三层删除用例全绿。
- 数据证据：迁移前后 documents=1、chat_records=4、usage_daily=0；新增 ingest_jobs=0；`integrity_check=ok`；正式一致性巡检 missing/extra/orphan 六项与 total_issues 均为 0。
- 可靠性影响：上传与 Job 同事务落库；独立 Worker 通过租约、心跳、指数退避和启动修复恢复；租户内文件 SHA-256 与稳定 chunk ID 保证幂等；向量/DB 失败有补偿删除；文档删除覆盖关系库、文件和 Chroma。
- 已知遗留：SQLite 适合当前单机部署，多主机 Worker 需迁移 PostgreSQL 并采用行锁领取；分钟限流仍为单 API 进程内状态；`langchain-community` 弃用警告留待阶段 8。
- 下一步：停止本次执行；下一次从阶段 6 开始。

### 2026-06-22 - 阶段 6 开始

- 状态：in_progress
- 范围：持久化 Checkpointer、会话生命周期、可靠审计、人工任务状态流、可配置敏感规则与分类访问策略。
- 阶段边界：只处理会话、审计和人工介入；LangSmith 数据治理仍由阶段 7 处理。
- 数据保护：结构迁移前备份至 `backups/stage6_20260622_185311/`，源与备份 SQLite SHA-256 一致。
- 下一步：完成跨重启/多 Worker 会话和人工任务验收；未通过不得进入阶段 7。

### 2026-06-22 19:21 - 阶段 6：会话、审计与人工介入持久化

- 状态：complete
- 修改文件：
  - `.env.example`、`requirements.txt`、`README.md`、`HARNESS.md`
  - `config/sensitive_rules.json`
  - `app/config.py`、`app/main.py`、`app/core/database.py`、`app/core/checkpointer.py`
  - `app/agent/agent.py`、`app/agent/context.py`、`app/agent/middleware.py`
  - `app/api/qa.py`、`app/api/admin.py`、`app/schemas/qa.py`
  - `app/models/chat_record.py`、`app/models/conversation_session.py`、`app/models/human_task.py`、`app/models/__init__.py`
  - `app/services/audit.py`、`app/services/conversations.py`、`app/services/sensitive_policy.py`
  - `app/commands/cleanup_sessions.py`
  - `tests/conftest.py`、`tests/test_agent.py`、`tests/test_auth.py`、`tests/test_persistence.py`
- 数据迁移：执行前备份至 `backups/stage6_20260622_185311/` 且源与备份 SQLite SHA-256 一致；正式库新增审计列、`conversation_sessions`、`human_tasks`、`human_task_events`，并创建 `storage/checkpoints.db`；迁移连续执行两次幂等。
- 验证命令：
  - `.\.venv\Scripts\python.exe -m compileall -q app tests`
  - `.\.venv\Scripts\python.exe -m pytest -q`
  - `.\.venv\Scripts\python.exe -m pip check`
  - `.\.venv\Scripts\python.exe -m app.commands.cleanup_sessions`
  - `.\.venv\Scripts\python.exe -m app.commands.check_consistency`
  - `docker compose config --quiet`
  - 业务/Checkpoint SQLite 完整性、表/列/计数、Git 差异与秘密候选检查
- 验证结果：76 passed；无损坏依赖；Compose 配置解析通过；跨重启与两个并存 Checkpointer 连接共享会话；同会话租约拒绝并发写；TTL、消息裁剪和清理用例全绿。
- 数据证据：迁移前后 documents=1、chat_records=4、usage_daily=0、ingest_jobs=0；新增会话/人工表均为 0；业务库与 checkpoint 库 `integrity_check=ok`；正式三存储巡检 total_issues=0。
- 可靠性与治理影响：问答先预登记审计，写入重试后仍失败则 503 fail-closed，pending 记录可由管理接口观测；审计记录结构化 tool/sources/trace/model/tokens/latency；人工任务支持 pending→claimed→completed 且全程事件审计；工资/健康/法律规则按可信 JWT 角色拒绝越权。
- 已知遗留：SQLite Checkpointer 支持当前单机多进程部署；跨主机或高写入生产规模应迁移 PostgreSQL Checkpointer/数据库行锁；LangSmith 数据治理由阶段 7 处理；`langchain-community` 弃用警告留待阶段 8。
- 下一步：停止本次执行；下一次从阶段 7 开始。
