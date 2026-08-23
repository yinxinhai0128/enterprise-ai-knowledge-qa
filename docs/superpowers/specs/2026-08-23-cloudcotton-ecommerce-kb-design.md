# 云棉家居电商售后知识库改造 — 设计文档（Spec）

> 日期：2026-08-23 ｜ 状态：待用户确认
> 项目仓库：`D:\企业级AI知识问答系统`（GitHub: yinxinhai0128/enterprise-ai-knowledge-qa）

## 1. 背景与目标

### 1.1 为什么改

当前项目是一个**工程质量很高但定位悬浮**的企业 RAG 模板：

| 已有资产（保留不动） | 问题 |
|---|---|
| LangGraph Agentic RAG（检索即工具） | README 定位是泛泛的"企业知识库模板"，说不出解决谁的什么问题 |
| PostgreSQL + pgvector + Redis 缓存 | 「电商售后」只散落在 1 个测试文件和 1 个 demo 文档里 |
| 租户隔离 / JWT / PII 脱敏 / 审计 | **没有任何评测体系**——检索好不好、答得对不对，全靠感觉 |
| 无证据强制拒答 + 人工转派闭环 | 679 行的云棉家居知识库是单一大文件，检索粒度和来源展示都不理想 |
| 用户反馈（赞/踩）+ 审批率统计 | 前端引导文案与业务场景无关 |
| 119 个后端测试全过、CI 三件套 | |

### 1.2 改造后的一句话定位

> **面向跨境电商（云棉家居 CloudCotton Home）的售后智能客服知识库**：客服/运营上传内部知识文档，一线客服用自然语言查询退换货、物流、支付等政策，系统保证**有据可依、无据拒答、来源可溯、效果可测**。

面试故事从"我搭了一个 RAG 模板"升级为：
"我把一个生产级 RAG 系统（租户隔离、审计、拒答机制）落到**具体业务**（跨境家居电商售后），并建立了**黄金评测集 + 检索命中率/回答质量评估体系**，用实测数据驱动迭代。"

### 1.3 成功标准（可验证）

1. 全部既有测试保持通过（119 后端 + 35 前端）
2. 新增评测集 60 题、评测脚本可一键运行并输出报告
3. 检索评测在真实 pgvector + 百炼 embedding 上跑出**实测数字**写入 README（目标 hit@5 ≥ 0.90，以实测为准，不编造）
4. 拆分后的主题文档通过现有 `/documents/upload` 链路导入成功
5. README / 前端文案对齐电商场景

## 2. 方案总览

```text
┌─ 语料层 ──────────────────────────────────────────┐
│ docs/demo_data/cloudcotton/                        │
│   01-公司概况与认证.md                              │
│   02-产品目录与尺寸规格.md                          │
│   03-材质与洗涤护理.md                              │
│   04-物流与配送.md                                  │
│   05-售后与退换货政策.md   ← 客服最高频              │
│   06-支付促销与客户服务.md                          │
│   07-B2B批发与市场合规.md                           │
│ （由现有 679 行单文件拆分，内容不删减，仅重排+补导语）│
└──────────────┬─────────────────────────────────────┘
               │ scripts/import_demo_data.py（现有）
               ▼
┌─ 检索层 ──────────────────────────────────────────┐
│ query_rewriter 同义词典扩充（电商口语词）           │
│ pgvector top-5 + MAX_DISTANCE=0.8（现有逻辑不动）   │
└──────────────┬─────────────────────────────────────┘
               ▼
┌─ 评测层（新增）───────────────────────────────────┐
│ evals/golden_set.jsonl        60 题黄金集          │
│ scripts/evaluate_retrieval.py  检索命中评估        │
│ scripts/evaluate_qa.py        端到端问答评估       │
│ tests/test_evaluation.py      指标计算单测(CI安全) │
└───────────────────────────────────────────────────┘
```

**原则：只加不改**——检索、Agent、审计、缓存的核心逻辑一律不动；所有新代码都在外围（脚本、数据、文档、文案）。

## 3. 详细设计

### 3.1 知识语料重组

把 `docs/demo_data/云棉家居知识库.md`（679 行）拆成上述 7 个主题文件，放入 `docs/demo_data/cloudcotton/`。原单文件删除（git 历史可追溯）。

拆分规则：
- 每个文件开头加一行导语（"本文档供客服团队查询 XX 政策使用"），提升 chunk 语义完整性
- 表格、编号列表保持原样（ingest 的 Markdown loader 已支持）
- 每个文件控制在 60–120 行，避免单 chunk 过长稀释相关性
- 原第十五章「售后与投诉处理」并入 05（售后场景聚合）

理由：来源归因更清晰——前端 SourceCard 会显示"参考了 N 份文档"，拆分后能显示"参考了《售后与退换货政策》"，演示效果和评测的 expected_doc 判定都依赖这个。

### 3.2 黄金评测集 `evals/golden_set.jsonl`

JSONL 格式，每行一题：

```json
{"id": "RT-001", "category": "退换货", "question": "独立站买的四件套签收后还能无理由退货吗？", "expected_doc": "05-售后与退换货政策", "expected_keywords": ["7", "吊牌"], "should_refuse": false}
{"id": "OOS-001", "category": "拒答测试", "question": "你们公司的竞品 Sleep Number 的床垫多少钱？", "expected_doc": null, "expected_keywords": [], "should_refuse": true}
```

字段说明：
- `id`：类别前缀 + 序号（RT=退换货 LG=物流 PAY=支付 PROMO=促销 PROD=产品 CARE=护理 B2B COMP=合规 OOS=拒答）
- `expected_doc`：期望命中的文档名前缀（检索评测判定用）；拒答题为 null
- `expected_keywords`：答案必须覆盖的关键词（≥1 个即算过；端到端评测用）
- `should_refuse`：true 时要求系统拒答（无证据拒答机制的正确性验证）

题目分布（共 60 题）：

| 类别 | 数量 | 示例 |
|---|---|---|
| RT 退换货 | 12 | 亚马逊买的怎么退？质量问题的赔偿标准？ |
| LG 物流 | 8 | 发美国用什么快递？偏远地区附加费？ |
| PAY 支付 | 6 | 支持分期吗？日元结算有手续费吗？ |
| PROMO 促销 | 6 | CloudCoins 怎么攒怎么花？折扣码能叠加吗？ |
| PROD 产品 | 10 | 云奢系列是什么棉？日本市场的床品尺寸？ |
| CARE 护理 | 6 | 天丝四件套能机洗吗？羽绒被怎么存？ |
| B2B | 4 | 酒店批量采购有折扣吗？账期政策？ |
| COMP 合规 | 4 | OEKO-TEX 证书编号？欧盟合规要求？ |
| OOS 拒答 | 8 | 竞品价格 / 天气 / 编造的产品系列 / 库存实时数 等 |

出题纪律：**每一题的答案必须能在对应主题文档中找到原文依据**，出题时标注原文行号（写在评测集维护说明里，不入 JSONL）。拒答题必须是知识库确实不涵盖的。

### 3.3 检索评测脚本 `scripts/evaluate_retrieval.py`

职责：只评检索层（rewrite → embed → pgvector top-k → distance 过滤），不调 LLM。

```text
用法：
  python scripts/evaluate_retrieval.py --golden evals/golden_set.jsonl \
      [--k 5] [--tenant-id cloudcotton] [--report evals/reports/retrieval-<date>.md]

流程：
  对每题：
    q = rewrite_query(question)                    # 复用现有规则改写
    results = pgvector_similarity_search_with_score(q, k, tenant_id)
    hits = [r for r in results if r.distance <= MAX_DISTANCE]
    hit@i = hits 中前 i 个里出现 expected_doc 前缀匹配
  输出：
    hit@1 / hit@3 / hit@5（总体 + 分类别）
    MRR（mean reciprocal rank）
    平均检索延迟 p50/p95
    未命中题目清单（题号 + 检索到的 top5 来源 + 各自 distance）← 迭代抓手
```

两种运行模式：
- **真实模式**（默认）：连 `.env` 的百炼 embedding + Postgres，需要先导入语料。产出 README 引用的实测数字。
- **CI 安全单测**：指标计算函数抽成纯函数放 `app/core/eval_metrics.py`，`tests/test_evaluation.py` 用构造数据测 hit/MRR/分类聚合的正确性，不碰网络。

### 3.4 端到端问答评测 `scripts/evaluate_qa.py`

职责：走完整 `/qa/ask` 链路（含 Agent 决策、拒答、引用），评最终答案质量。

```text
用法：
  python scripts/evaluate_qa.py --golden evals/golden_set.jsonl \
      --base-url http://127.0.0.1:8765 --token <JWT> \
      [--limit 10] [--report ...]

判定规则（每题）：
  ① 拒答正确性：response.refused == should_refuse
  ② 关键词覆盖：非拒答题，answer 中命中 ≥1 个 expected_keywords
  ③ 来源一致性：非拒答题，sources 里存在 expected_doc 前缀匹配
输出：
  通过率（三关全过）、各单项通过率、分类别矩阵、失败题明细（问题/回答/来源/原因标签）
  报告同时落 markdown + json（json 供后续对比趋势）
```

注意：此脚本消耗真实百炼 token，明确标注为**手动触发**（README 写清预估成本：60 题 × 约 2K token ≈ 单次几毛钱量级，用 qwen-turbo 档更省）；CI 不跑它。

### 3.5 同义词典扩充

`query_rewriter` 的 `RuleBasedRewriter` 从 YAML 词典加载同义词。新增电商口语映射（追加进现有词典文件）：

```yaml
退款: [退货退款, 退钱, 返还货款]
多久到: [物流时效, 配送时间, 几天送达]
尺码: [尺寸, 规格对照, 床品尺寸]
运费: [邮费, 快递费, shipping]
打折: [优惠, 折扣, promo]
发票: [收据, invoice]
```

配一条单测：`"买错了能退钱吗"` 改写后包含"退货退款"。（词典路径沿用现有 `_SYNONYMS_PATH` 机制。）

### 3.6 README 与前端文案对齐

**README**（改动点，不推倒重写）：
- 标题下副标改为："以**云棉家居（CloudCotton Home）跨境电商售后知识库**为落地场景"
- 新增「业务场景」一节：角色（客服坐席/运营/合规）、高频问题类型、为什么必须拒答而非瞎编
- 新增「评测体系」一节：评测集构成、两个脚本的用法、**实测指标表**（占位表格，跑完真实评测后填入数字）
- Quick Start 增加"三步体验电商场景"（起 infra → 导入 cloudcotton 语料 → 用示例问题提问）

**前端**（最小改动）：
- `ChatPage.tsx` 输入框空态的示例问题改为电商场景 4 条（"亚马逊订单怎么退货？"、"CloudCoins 积分怎么用？"、"发票怎么开？"、"你们和某竞品哪个好？"——最后一条展示拒答）
- `DocumentsPage.tsx` 空状态提示补一句"可用 scripts/import_demo_data.py 一键导入云棉家居演示知识库"
- 页面标题/描述里的通用措辞对齐（如"企业知识库"→"售后知识库"）

### 3.7 明确不做（YAGNI）

- ❌ 不引入 Reranker 模型（当前 TOP_K=5 + distance 阈值够用；若实测 hit@3 低再议，属于后续迭代项）
- ❌ 不做多轮对话评测（首轮命中率是主要指标；多轮记忆已有单测覆盖）
- ❌ 不动 ingest 分块策略、不动审计/预算/隔离任何安全机制
- ❌ 不做自动化 LLM-as-judge 打分（关键词+拒答+来源三关已可量化，judge 反而引入不可复现性）
- ❌ 不新增 Python 依赖（评测脚本只用标准库 + 现有 httpx/sqlalchemy）

## 4. 任务分解概览（供实施计划展开）

1. 拆分语料 → cloudcotton/ 七文件（纯文档工作）
2. 出黄金评测集 60 题（对照文档出题，标注依据）
3. `app/core/eval_metrics.py` 纯函数 + `tests/test_evaluation.py` 单测（TDD）
4. `scripts/evaluate_retrieval.py`
5. `scripts/evaluate_qa.py`
6. 同义词典扩充 + 单测
7. 导入语料跑真实检索评测 → 记录实测数字
8. README 改写（填实测数字）+ 前端文案
9. 全量回归（pytest + vitest + tsc）→ commit/push

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| 百炼 embedding 对中文长尾口语召回差 → hit@5 不达标 | 评测报告自带未命中清单，优先调同义词典而非改核心代码；仍不行则在计划外提 reranker 议题 |
| 真实评测烧 token | 检索评测只耗 embedding（极便宜）；QA 评测默认 --limit 10 且手动触发 |
| 单测污染正式库 | 沿用 conftest 全 mock 约定；评测脚本只读向量库，不做写操作（导入走现有 upload 接口） |
| 拆分文档导致旧引用失效 | 全仓 rg 检查 `云棉家居知识库.md` 引用点一并更新 |

## 6. 验收清单

- [ ] `pytest tests/ -q` 全绿（119+ 新增）
- [ ] `cd frontend && npx tsc --noEmit && npx vitest run` 全绿
- [ ] `scripts/import_demo_data.py` 导入 cloudcotton/ 七文件成功，文档状态 indexed
- [ ] 检索评测报告生成，README 实测表已填真实数字
- [ ] QA 端到端评测子集（10 题）跑通，拒答题全部正确拒答
- [ ] git 提交历史干净（Conventional Commits），推送 GitHub
