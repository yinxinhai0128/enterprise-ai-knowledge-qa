# LangSmith 数据治理

## 1. 默认状态与启用门

LangSmith 属于外部数据处理方。开发、测试和生产默认均关闭：

```dotenv
LANGCHAIN_TRACING_V2=false
LANGSMITH_ORG_APPROVED=false
LANGSMITH_REMOTE_POLICY_CONFIRMED=false
LANGSMITH_TRACING_SAMPLING_RATE=0.0
LANGSMITH_DATA_REGION=disabled
```

启用前必须同时满足：

1. 数据负责人和安全负责人批准，并填写不可为空的 `LANGSMITH_APPROVAL_REFERENCE`。
2. 完成供应商安全评估、数据处理协议（DPA）及适用的跨境/个人信息条款审查。
3. 明确获批的 `LANGSMITH_WORKSPACE_ID`、HTTPS endpoint 和数据驻留区域。
4. 在 LangSmith 工作区确认项目最小权限和远端保留期限，并设置 `LANGSMITH_REMOTE_POLICY_CONFIRMED=true`。
5. 设置大于 0、至多 1 的采样率；生产从最低可观测采样率开始。
6. 配置独立、至少 32 字符的 `LANGSMITH_REDACTION_SECRET`，不得与 API Key/JWT Secret 复用。

任一条件缺失时，代码会强制 `enabled=False`，将决策写入本地 `trace_governance_events`，核心问答服务继续运行。

## 2. 外发数据清单

| 数据类别 | 外发形态 | 明确不外发 |
|---|---|---|
| 用户问题、模型输入/输出 | 每个字符串的 HMAC-SHA256、字符数、类型 | 原文、邮箱、手机号、姓名、工资/健康/法律内容 |
| 检索工具结果 | 数值 `doc_id`、结构、字符串 HMAC/长度 | 文档片段原文、文件名、原始 chunk ID |
| Run 结构 | 固定 run 名/类型、层级 ID、开始/结束时间、状态 | tenant/user/session 标识原文 |
| Token/数值指标 | 数值 | 不适用 |
| Metadata | 固定技术白名单：模型名/类型、provider、节点、环境、策略版本等 | thread ID、租户、用户、任意业务 metadata |
| Error / event / attachment | error 只保留 HMAC/长度；event 内容和 attachment 清空 | 错误原文、流式 token、文件与二进制附件 |
| Runtime / manifest | 不外发 | 主机、环境变量、依赖清单、序列化图 |

HMAC 用于同值关联而不能恢复原文。密钥轮换会切断跨轮换周期的关联；短文本仍不得使用无密钥 SHA 替代 HMAC。

本地 `chat_records` 的问题、答案和证据仍按企业数据保存，受数据库权限和后续备份/删除制度约束；本文件只描述 LangSmith 外发面。

## 3. 项目与权限

- 生产、预发布、开发必须使用不同 workspace/project/API Key。
- 服务账户只授予写入指定 workspace/project 所需权限；禁止使用个人长期 Key。
- 管理员不超过两类：平台管理员和经批准的审计人员。普通开发者默认无生产 trace 读取权。
- 禁止公开分享 trace、公开数据集或创建无需认证的链接。
- 每季度复核成员、服务账户、项目权限和 `LANGSMITH_APPROVAL_REFERENCE`；人员离职或职责变化立即回收。
- `LANGSMITH_REMOTE_POLICY_CONFIRMED=true` 是运维确认，不代替远端实际配置和审计证据。

## 4. 驻留与供应商协议

启用前由法务/隐私/安全共同确认：

- 合同主体、DPA、子处理方清单、数据所有权、模型训练用途限制和事件通知时限。
- 获批 endpoint 与 `LANGSMITH_DATA_REGION` 一致；不得通过 DNS、代理或多写 endpoint 绕过驻留决策。
- 涉及个人信息或跨境传输时，完成适用法律要求的评估、告知/同意或其它合法基础。
- 供应商终止、区域迁移、并购或条款变化时重新审批；审批失效先关闭追踪。

合同和远端配置证据保存在企业合规系统，不写入本仓库。可从 LangChain Trust Center 与当前合同材料核对最新合规状态；仓库文档不构成供应商合规承诺。

## 5. 采样与保留

- `LANGSMITH_TRACING_SAMPLING_RATE` 为 0～1 的根 trace 采样率；默认 0。生产先使用最小必要值，例如 0.01，再按故障诊断需求审批调整。
- `LANGSMITH_RETENTION_DAYS` 默认 14 天；必须在远端项目配置相同或更短期限，再确认 `LANGSMITH_REMOTE_POLICY_CONFIRMED=true`。
- 禁止仅修改本地保留天数而不修改远端。超过审批期限的临时提高采样必须有到期时间和回退负责人。

## 6. 删除与事件流程

正常删除：

1. 将 `LANGCHAIN_TRACING_V2=false` 并重启服务，确认新的治理事件为 `disabled`。
2. 在获批 workspace/project 中按 trace、时间范围或整个项目执行删除；项目级停用优先删除整个项目。
3. 按合同确认主存储、备份和子处理方副本的删除时限，保存供应商删除确认。
4. 删除或轮换服务 API Key 与 `LANGSMITH_REDACTION_SECRET`；清理不再需要的项目成员。
5. 在企业工单记录范围、操作者、时间、供应商确认和抽查结果。不得把真实 trace 内容复制进工单。

疑似泄露：立即关闭追踪、吊销 Key、保全本地 `trace_governance_events` 和访问审计，按企业事件响应流程评估通知义务；不要在聊天、提交或普通日志中粘贴 trace 原文。

## 7. 验收与复核

- 自动化测试强制关闭 LangSmith，并把任何 HTTP 请求视为失败。
- 假敏感数据测试检查最终 SDK run 字典：问题、邮箱、健康/工资内容、错误、thread ID 和文档原文均不可见。
- 每次升级 `langsmith` / `langchain-core` 后复核 Client 的输入、输出、metadata、event、error、attachment 和 runtime 出口，再运行阶段 7 测试。
