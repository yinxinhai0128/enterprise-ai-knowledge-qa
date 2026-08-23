# 云棉家居电商售后知识库改造 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把企业 RAG 模板落地为「云棉家居跨境电商售后知识库」：12 文档 3500+ 行语料、120 题三层黄金评测集、检索/端到端双评测脚本，实测指标落 README。

**Architecture:** 只加不改——检索（pgvector top-5 + distance≤0.8）、Agent、审计、缓存核心逻辑全部不动。新增内容全在外围：语料文档（`docs/demo_data/cloudcotton/`）、评测资产（`evals/`）、评估脚本（`scripts/`）、指标纯函数（`app/core/eval_metrics.py`）、词典与文案。

**Tech Stack:** Python 3.12 / FastAPI / LangChain（现有）；评测脚本仅用标准库 + 现有依赖（urllib, json, argparse）；前端 React 18 + TS（现有）。

**Spec:** `docs/superpowers/specs/2026-08-23-cloudcotton-ecommerce-kb-design.md`

## Global Constraints

- 后端测试命令：`PYTHONPATH= ./.venv/Scripts/python.exe -m pytest tests/<file> -q`（Windows Git-Bash；当前基线 166 tests collected 全过）
- 前端命令在 `frontend/` 下执行：`npx tsc --noEmit`、`npx vitest run`
- 禁止修改 `app/api/`、`app/services/`、`app/agent/`、`app/models/` 下任何文件（安全与业务核心冻结）
- 允许新增/修改：`docs/demo_data/cloudcotten/**`（注意拼写为 cloudcotton）、`evals/**`、`scripts/evaluate_*.py`、`scripts/validate_golden.py`、`config/query_synonyms.json`、`app/core/eval_metrics.py`、`tests/test_evaluation.py`、`README.md`、`frontend/src/pages/ChatPage.tsx`、`frontend/src/pages/DocumentsPage.tsx`、`app/main.py` 的 FastAPI title/description 两行
- 所有实测数字必须来自真实运行输出，禁止编造；报告落 `evals/reports/`
- 语料数字纪律：与原 `docs/demo_data/云棉家居知识库.md` 一致或显式标注"示例"；新增内容须内部自洽
- git 提交用 Conventional Commits；push 用 `git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 -c http.sslBackend=openssl push origin main`

---

### Task 1: 评测指标纯函数模块（TDD）

**Files:**
- Create: `app/core/eval_metrics.py`
- Test: `tests/test_evaluation.py`

**Interfaces:**
- Produces:
  - `hit_at_k(ranked_docs: list[str], expected_prefix: str, k: int) -> bool`
  - `reciprocal_rank(ranked_docs: list[str], expected_prefix: str) -> float`
  - `keyword_coverage(answer: str, keywords: list[str]) -> bool`（命中 ≥1 即 True）
  - `aggregate(reports: list[dict]) -> dict`（输入逐题结果 dict 列表，输出总体+分类别+分层通过率）
  - 常量 `LEVELS = ("L1", "L2", "L3", "OOS")`、`CATEGORIES = ("RT", "LG", "PAY", "PROMO", "PROD", "CARE", "B2B", "COMP", "CS", "OOS")`

- [ ] **Step 1: Write the failing test**

```python
"""eval_metrics 纯函数单测：不碰网络、不碰数据库。"""
from app.core.eval_metrics import (
    aggregate, hit_at_k, keyword_coverage, reciprocal_rank,
)


def test_hit_at_k_basic() -> None:
    docs = ["06-物流配送政策.md", "07-退换货与退款政策.md"]
    assert hit_at_k(docs, "07-退换货", k=2) is True
    assert hit_at_k(docs, "07-退换货", k=1) is False


def test_hit_at_k_empty() -> None:
    assert hit_at_k([], "07-退换货", k=5) is False


def test_reciprocal_rank() -> None:
    assert reciprocal_rank(["a", "07-退换货"], "07-退换货") == 0.5
    assert reciprocal_rank(["a", "b"], "07-退换货") == 0.0


def test_keyword_coverage() -> None:
    assert keyword_coverage("30 天内可退货", ["7 天", "30 天"]) is True
    assert keyword_coverage("不支持退货", ["7 天", "30 天"]) is False
    assert keyword_coverage("任意回答", []) is False  # 空 keywords 视为未覆盖


def test_aggregate_counts_by_level_and_category() -> None:
    rows = [
        {"id": "RT-L1-001", "category": "RT", "level": "L1", "passed": True},
        {"id": "RT-L2-001", "category": "RT", "level": "L2", "passed": False},
        {"id": "OOS-001", "category": "OOS", "level": "OOS", "passed": True},
    ]
    out = aggregate(rows)
    assert out["total"] == 3
    assert out["passed"] == 2
    assert abs(out["pass_rate"] - 2 / 3) < 1e-9
    assert out["by_level"]["L1"]["passed"] == 1
    assert out["by_level"]["L2"]["passed"] == 0
    assert out["by_category"]["RT"]["total"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH= ./.venv/Scripts/python.exe -m pytest tests/test_evaluation.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.eval_metrics'`

- [ ] **Step 3: Write minimal implementation**

```python
"""评测指标纯函数：检索命中、MRR、关键词覆盖、聚合统计。

只做确定性计算，不做 IO —— 便于 CI 单测与两个评测脚本复用。
"""
from __future__ import annotations

LEVELS = ("L1", "L2", "L3", "OOS")
CATEGORIES = ("RT", "LG", "PAY", "PROMO", "PROD", "CARE", "B2B", "COMP", "CS", "OOS")


def hit_at_k(ranked_docs: list[str], expected_prefix: str, k: int) -> bool:
    """前 k 个文档名中存在 expected_prefix 前缀匹配即命中。"""
    return any(doc.startswith(expected_prefix) for doc in ranked_docs[:k])


def reciprocal_rank(ranked_docs: list[str], expected_prefix: str) -> float:
    """首个命中文档的倒数排名；无命中返回 0.0。"""
    for index, doc in enumerate(ranked_docs, start=1):
        if doc.startswith(expected_prefix):
            return 1.0 / index
    return 0.0


def keyword_coverage(answer: str, keywords: list[str]) -> bool:
    """答案命中任一关键词即算覆盖；空关键词列表视为未覆盖。"""
    if not keywords:
        return False
    return any(keyword in answer for keyword in keywords)


def aggregate(rows: list[dict]) -> dict:
    """按 total/passed/pass_rate 聚合，并输出 by_level 与 by_category 分组。"""
    total = len(rows)
    passed = sum(1 for row in rows if row["passed"])
    result: dict = {
        "total": total,
        "passed": passed,
        "pass_rate": (passed / total) if total else 0.0,
        "by_level": {},
        "by_category": {},
    }
    for level in LEVELS:
        subset = [row for row in rows if row.get("level") == level]
        if subset:
            ok = sum(1 for row in subset if row["passed"])
            result["by_level"][level] = {
                "total": len(subset),
                "passed": ok,
                "pass_rate": ok / len(subset),
            }
    for category in CATEGORIES:
        subset = [row for row in rows if row.get("category") == category]
        if subset:
            ok = sum(1 for row in subset if row["passed"])
            result["by_category"][category] = {
                "total": len(subset),
                "passed": ok,
                "pass_rate": ok / len(subset),
            }
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH= ./.venv/Scripts/python.exe -m pytest tests/test_evaluation.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add app/core/eval_metrics.py tests/test_evaluation.py
git commit -m "feat: add eval metrics pure functions with unit tests"
```

---

### Task 2: 同义词典扩充电商口语词

**Files:**
- Modify: `config/query_synonyms.json`（在现有 JSON 对象内追加词条）
- Test: `tests/test_query_rewriter.py`（追加用例）

**Interfaces:**
- Consumes: 现有 `RuleBasedRewriter.expand()`（别名命中 → 追加规范词，不替换原词）
- Produces: 新增规范词组 `退款/多久到/尺码/运费/打折/发票/积分/投诉/包邮/客服电话/尺寸对照/蓬松度/防水量/账期/样品` 等 ≥15 组（每组 2–5 个别名），总词条组数 ≥39

- [ ] **Step 1: Write the failing test**

在 `tests/test_query_rewriter.py` 追加：

```python
_ECOMMERCE_SYNONYMS = {
    "退款": ["退钱", "退还货款"],
    "退货": ["退回去", "退掉"],
}


@pytest.fixture()
def ecommerce_rewriter() -> RuleBasedRewriter:
    r = RuleBasedRewriter(synonyms_path=Path("nonexistent"))
    r._data = dict(_ECOMMERCE_SYNONYMS)
    return r


def test_expand_colloquial_refund(ecommerce_rewriter: RuleBasedRewriter) -> None:
    result = ecommerce_rewriter.expand("买错了能退钱吗")
    assert "退款" in result


def test_expand_colloquial_return(ecommerce_rewriter: RuleBasedRewriter) -> None:
    result = ecommerce_rewriter.expand("不想要了想退掉")
    assert "退货" in result


def test_real_synonym_file_loads_with_ecommerce_entries() -> None:
    from app.core.query_rewriter import _SYNONYMS_PATH

    data = RuleBasedRewriter(_SYNONYMS_PATH)._load()
    for key in ("退款", "退货", "多久到", "尺码", "运费", "发票", "积分"):
        assert key in data, f"词典缺少电商词条: {key}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH= ./.venv/Scripts/python.exe -m pytest tests/test_query_rewriter.py -q`
Expected: FAIL — `test_real_synonym_file_loads_with_ecommerce_entries` 报 KeyError（真实词典还没有这些词条）

- [ ] **Step 3: Update the dictionary**

在 `config/query_synonyms.json` 对象末尾（`"档案"` 条目之后）追加（保持合法 JSON，逗号衔接）：

```json
  "退款": ["退钱", "退还货款", "把钱退给我", "refund"],
  "退货": ["退回去", "退掉", "return", "寄回"],
  "换货": ["换一件", "换个", "exchange", "调换"],
  "多久到": ["几天送达", "什么时候到", "啥时候能到", "配送时间", "物流时效"],
  "运费": ["邮费", "快递费", "shipping fee", "配送费"],
  "包邮": ["免运费", "免邮", "free shipping"],
  "尺码": ["尺寸", "大小", "规格对照", "床品尺寸"],
  "发票": ["收据", "invoice", "报销凭证", "开票"],
  "积分": ["CloudCoins", "会员积分", "点数", "reward points"],
  "优惠券": ["折扣码", "优惠码", "promo code", "coupon"],
  "折扣": ["打折", "优惠", "划算", "discount"],
  "礼品卡": ["gift card", "礼品券"],
  "分期": ["分期付款", "BNPL", "先享后付", "installment"],
  "拒付": ["chargeback", "退单争议"],
  "清关": ["海关", "customs", "关税"],
  "追踪号": ["物流单号", "快递单号", "tracking number"],
  "丢件": ["包裹丢失", "没收到货", "包裹不见了"],
  "破损": ["损坏", "破了", "damaged"],
  "质量保证": ["质保", "warranty", "质量问题保障"],
  "赔偿": ["补偿", "compensation"],
  "投诉": ["不满", "客诉", "complaint"],
  "客服": ["人工客服", "customer service", "联系客服"],
  "蓬松度": ["fill power", "羽绒蓬松"],
  "长绒棉": ["埃及棉", "egyptian cotton"],
  "天丝": ["莱赛尔", "lyocell", "tencel"],
  "有机棉": ["organic cotton", "GOTS认证棉"],
  "法兰绒": ["flannel", "珊瑚绒替代"],
  "羽绒被": ["鹅绒被", "down comforter", "duvet"],
  "床垫保护垫": ["床笠保护垫", "mattress protector"],
  "四件套": ["床上四件套", "bedding set", "被套床单枕套"],
  "批发": ["批量采购", "wholesale", "团购"],
  "账期": ["Net 30", "月结", "payment terms"],
  "样品": ["sample", "打样"],
  "定制": ["刺绣", "embroidery", "LOGO定制"],
  "会员等级": ["会员体系", "membership tier"],
  "生日优惠": ["生日礼遇", "birthday discount"],
  "亚马逊订单": ["Amazon订单", "站外订单"],
  "PO Box": ["邮政信箱", "邮箱地址收货"],
  "偏远地区": ["remote area", "附加费地区"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH= ./.venv/Scripts/python.exe -m pytest tests/test_query_rewriter.py -q`
Expected: PASS（8 existing + 3 new）

- [ ] **Step 5: Commit**

```bash
git add config/query_synonyms.json tests/test_query_rewriter.py
git commit -m "feat: expand query synonyms with ecommerce colloquial terms"
```

---

### Task 3: 语料工程 I — 拆分原知识库为 6 个基础主题文档

> 本任务与 Task 4 是纯文档工作。每个文档结构：导语（1–2 行）→ 正文（保留原文全部事实）→ 版本行。
> 内容来源统一为 `docs/demo_data/云棉家居知识库.md`（下称"原文档"，行号以它为准）。

**Files:**
- Create: `docs/demo_data/cloudcotton/01-公司概况与品牌认证.md`（原「一」+「十三」可持续发展，扩写发展历程表、认证清单表，目标 150+ 行）
- Create: `docs/demo_data/cloudcotton/02-产品目录与SKU规则.md`（原「二」，扩写各系列卖点小节，目标 200+ 行）
- Create: `docs/demo_data/cloudcotton/03-尺寸规格对照.md`（原「三」，扩写儿童尺寸/枕头被芯尺寸/误差说明，目标 180+ 行）
- Create: `docs/demo_data/cloudcotton/04-材质详解与性能对比.md`（原「四」，扩写横向对比表/选购建议，目标 220+ 行）
- Create: `docs/demo_data/cloudcotton/05-洗涤护理指南.md`（原「五」+ 原「十六」中洗护相关 FAQ，目标 200+ 行）

**Interfaces:**
- Produces: 5 个 Markdown 文档；Task 5 的 12 号文档与 Task 7 的导入、Task 8 的评测都依赖全部 12 个文件就位

- [ ] **Step 1: 创建目录与 01 号文档**

从原文档第 7–41 行（一、公司概况）+ 562–583 行（十三、可持续发展）取材：
- 导语："本文档供市场与合规团队查询公司背景、资质认证与可持续发展政策使用。"
- 正文：保留原文档 1.1/1.2/1.3 全部事实（简介、品牌定位、资质认证），扩写「发展历程」表（2018 创立→2026 现状，年份与事件须与原文档简介中的信息自洽）、「认证清单汇总」表（把散落的 OEKO-TEX/GOTS/BCI 等聚合成一张表，证书编号沿用原文档数值）、可持续发展三小节全文
- 版本行：`> 版本 v1.0 · 2026-08 · 知识库管理员维护`

- [ ] **Step 2: 创建 02 号文档**

取材原文档第 42–94 行（二、产品目录）：系列总览表、品类明细、SKU 规则全部保留；扩写每个系列一小节「定位与目标人群」（如 Cloud Luxe→高端礼赠、Hotel Collection→B2B），不得引入新价格

- [ ] **Step 3: 创建 03 号文档**

取材原文档第 95–137 行（三、尺寸规格）：三张市场对照表 + 深兜适配说明保留；扩写「 pillow/被芯尺寸通用表」（数据从原文档 10.2 FAQ 中 Queen 枕套 20×30 英寸等提取）、「尺寸误差说明」（引用原文 ±5% 口径，若无则标注"行业惯例约 2–3cm，以实物为准"）

- [ ] **Step 4: 创建 04 号文档**

取材原文档第 138–191 行（四、材质说明）：五种材质小节保留；扩写「材质横向对比表」（列：材质/透气性/柔软度/耐用性/适合季节/价格带——价格带引用 02 号文档区间）、「选购建议决策树」（文字版：怕热选天丝/敏感肌选有机棉…）

- [ ] **Step 5: 创建 05 号文档**

取材原文档第 192–233 行（五、洗涤护理）+ 第 657–676 行（十六、技术FAQ 中可机洗/晾晒相关条目）：分材质护理保留；技术 FAQ 的洗护条目并入对应材质小节后扩写「常见误洗场景与补救」（缩水/串色/羽绒结块——补救方法须符合纺织常识）

- [ ] **Step 6: 校验行数与事实抽查**

Run:
```bash
wc -l docs/demo_data/cloudcotton/0*.md   # 每个 ≥150 行
grep -c "OEKO-TEX\|GOTS" docs/demo_data/cloudcotton/01-公司概况与品牌认证.md  # ≥1
```
Expected: 5 个文件均达标；抽查 3 个数字（如免邮门槛 $49、600TC、180 天质保）与原文档一致

- [ ] **Step 7: Commit**

```bash
git add docs/demo_data/cloudcotton/
git commit -m "docs: split knowledge base into themed corpus docs 01-05"
```

---

### Task 4: 语料工程 II — 政策与运营类 6 个文档

**Files:**
- Create: `docs/demo_data/cloudcotton/06-物流配送政策.md`（原「六」+ PO Box/确认邮件 FAQ，扩写加拿大墨西哥线路表、旺季时效表、清关说明，目标 260+ 行）
- Create: `docs/demo_data/cloudcotton/07-退换货与退款政策.md`（原「七」+ 订单修改取消 FAQ，扩写换货流程步骤化 5 步、部分退款情形表，目标 240+ 行）
- Create: `docs/demo_data/cloudcotton/08-支付货币与发票.md`（原「八」+「十四」市场合规，扩写各市场本地支付方式表、chargeback 处理流程，目标 240+ 行）
- Create: `docs/demo_data/cloudcotton/09-促销积分与礼品卡.md`（原「九」，扩写会员等级表、历史大促折扣参考，目标 200+ 行）
- Create: `docs/demo_data/cloudcotton/10-客户服务与FAQ.md`（原「十」+ 原「十六」产品技术 FAQ 非洗护条目，FAQ 扩到 25+ 条，目标 300+ 行）
- Create: `docs/demo_data/cloudcotton/11-B2B批发与企业采购.md`（原「十一」，扩写样品政策、Incoterms 说明、合规文件清单，目标 200+ 行）
- Create: `docs/demo_data/cloudcotton/12-投诉处理与赔偿标准.md`（原「十五」独立成文，扩写客服 SOP 视角话术要点，目标 160+ 行）

**Interfaces:**
- Consumes: Task 3 已建立的文档结构约定（导语/正文/版本行）
- Produces: 完整 12 文档语料；文档名前缀即评测集 `expected_doc` 取值

- [ ] **Step 1: 创建 06 号文档**

原文档 234–296 行（六、物流）+ 10.2 中 PO Box/确认邮件两条 FAQ。仓库表、承运商表、运费表、时效、追踪、特殊情况全部保留；扩写：加拿大/墨西哥线路（承运商 Canada Post/Estafeta 标注"参考美国线路时效+1–3 工作日"）、旺季时效对照表（黑五/圣诞 vs 平常，延长 1–2 工作日口径与原文一致）、跨境直发清关说明（可能产生的进口税由买家承担——标注"以各国海关规定为准"）

- [ ] **Step 2: 创建 07 号文档**

原文档 297–344 行（七、退换货）+ 10.2 中修改/取消订单两条 FAQ。扩写「换货流程五步」（联系客服→提供订单号与照片→审核 1–2 工作日→寄回旧件→发出新件，各环节时效与原文一致）；新增「部分退款情形表」（瑕疵轻微客户愿意保留→退 10–30% 协商等，标注"以客服审核为准"）；退款时间线表保留

- [ ] **Step 3: 创建 08 号文档**

原文档 345–391 行（八、支付）+ 585–620 行（十四、合规）。支付方式表、BNPL、货币汇率、发票税务保留；扩写「各市场本地支付」（美国 PayPal/Apple Pay、德国 Klarna/SOFORT、日本 Konbini——标注"以结账页实际展示为准"）；「拒付(chargeback)处理流程」5 步（收到通知→7 日内提交证据（物流签收证明/沟通记录）→平台裁决→败诉则接受扣款并分析原因→高风险订单预防性核实）；市场合规五小节全文保留并入

- [ ] **Step 4: 创建 09 号文档**

原文档 392–437 行（九、促销）。常规促销表、优惠券规则、CloudCoins 表、礼品卡保留；扩写「会员等级示例表」（Silver/Gold/Platinum 三级——升级条件与权益标注"示例配置，以官网为准"；积分倍率须与 CloudCoins 基础规则不打架：Platinum 1.5× 等）；「历史大促节奏参考」小节（把 9.1 的活动表改写成客服应答视角：什么时间该预期什么折扣）

- [ ] **Step 5: 创建 10 号文档**

原文档 438–497 行（十、客户服务）+ 657–676 行（十六）非洗护 FAQ。联系方式表、响应时效、原有 11 条 FAQ 保留；补入技术 FAQ 的拉链/松紧带/漏绒/枕芯更换/色差/被套被芯分洗条目；再扩写至 25+ 条（新增方向：会员/积分类 3 条、跨境类 3 条、售后进度查询 2 条），每条 Q/A 都须能在本套文档其他章节找到依据或属常识范围

- [ ] **Step 6: 创建 11 号文档**

原文档 498–534 行（十一、B2B）。客户类型、折扣梯度、定制、账期保留；扩写「样品政策」（样品下单全价、合作后首单抵扣——标注"示例政策"）；「贸易术语说明」（FOB/CIF/DDP 三行通俗解释，标注供参考）；「B2B 合规文件清单」（W-9/W-8BEN/VAT 号——按客户所在国区分）

- [ ] **Step 7: 创建 12 号文档**

原文档 621–656 行（十五、售后与投诉）。投诉流程 5 步、升级投诉、负面评价原则、赔偿标准表全部保留；扩写每步的「客服动作要点」（话术框架：先共情→核实→给方案→确认满意；禁止承诺超出赔偿标准表的补偿）

- [ ] **Step 8: 全量校验**

Run:
```bash
wc -l docs/demo_data/cloudcotton/*.md | tail -1   # 总行数 ≥3500
ls docs/demo_data/cloudcotton/ | wc -l            # = 12
rg -n "云棉家居知识库" --glob '!*.pyc' -l          # 除 spec 外无引用残留
```
Expected: 达标；然后删除原单文件 `git rm docs/demo_data/云棉家居知识库.md`

- [ ] **Step 9: Commit**

```bash
git add -A docs/demo_data/
git commit -m "docs: complete 12-doc cloudcotton corpus (3500+ lines)"
```

---

### Task 5: 黄金评测集 120 题 + 出题校验脚本

**Files:**
- Create: `evals/golden_set.jsonl`（120 行）
- Create: `evals/validate_golden.py`
- Test: `tests/test_evaluation.py`（追加 schema 测试）

**Interfaces:**
- Consumes: Task 3/4 的 12 个文档名前缀（作为 `expected_doc` 合法值）
- Produces: JSONL 每行 schema：
  ```json
  {"id": "RT-L1-001", "category": "RT", "level": "L1", "question": "...", "expected_doc": "07-退换货与退款政策", "expected_keywords": ["30 天"], "should_refuse": false}
  ```
  OOS 题 `expected_doc` 为 `null` 且 `should_refuse` 为 `true`；id 格式 `<类别>-<层级|-序号>`；类别 ∈ eval_metrics.CATEGORIES

- [ ] **Step 1: 写校验脚本 `evals/validate_golden.py`**

```python
"""黄金评测集校验：schema、枚举值、id 唯一性、OOS 约定。

用法：python scripts/../evals/validate_golden.py [--golden evals/golden_set.jsonl]
退出码 0=通过；非 0=失败并列出问题行。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.eval_metrics import CATEGORIES, LEVELS  # noqa: E402

REQUIRED_KEYS = {
    "id", "category", "level", "question",
    "expected_doc", "expected_keywords", "should_refuse",
}


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    lines = path.read_text(encoding="utf-8").splitlines()
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"L{lineno}: JSON 解析失败 {exc}")
            continue
        missing = REQUIRED_KEYS - set(row)
        if missing:
            errors.append(f"L{lineno}: 缺字段 {missing}")
            continue
        if row["id"] in seen_ids:
            errors.append(f"L{lineno}: id 重复 {row['id']}")
        seen_ids.add(row["id"])
        if row["category"] not in CATEGORIES:
            errors.append(f"L{lineno}: category 非法 {row['category']}")
        if row["level"] not in LEVELS:
            errors.append(f"L{lineno}: level 非法 {row['level']}")
        if row["should_refuse"]:
            if row["expected_doc"] is not None or row["level"] != "OOS":
                errors.append(f"L{lineno}: OOS 题 expected_doc 必须为 null 且 level=OOS")
            if row["expected_keywords"]:
                errors.append(f"L{lineno}: OOS 题 expected_keywords 必须为空")
        else:
            if not row["expected_doc"] or not row["expected_keywords"]:
                errors.append(f"L{lineno}: 非 OOS 题必须给 expected_doc 和 expected_keywords")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", default=str(Path(__file__).parent / "golden_set.jsonl"))
    args = parser.parse_args()
    errors = validate(Path(args.golden))
    if errors:
        print("\n".join(errors))
        return 1
    count = sum(1 for line in Path(args.golden).read_text(encoding="utf-8").splitlines() if line.strip())
    print(f"OK: {count} questions valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 追加单测（用临时 JSONL 验证校验器逻辑）**

在 `tests/test_evaluation.py` 追加：

```python
def test_validate_golden_rejects_bad_rows(tmp_path) -> None:
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
    from validate_golden import validate

    good = {"id": "RT-L1-001", "category": "RT", "level": "L1",
            "question": "q", "expected_doc": "07-x", "expected_keywords": ["k"],
            "should_refuse": False}
    bad_oos = dict(good, id="OOS-001", category="OOS", level="OOS",
                   should_refuse=True, expected_doc="07-x", expected_keywords=["k"])
    dup = dict(good)
    file = tmp_path / "g.jsonl"
    file.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                              for r in (good, bad_oos, dup)), encoding="utf-8")
    errors = validate(file)
    assert any("OOS" in e for e in errors)
    assert any("重复" in e for e in errors)
```

Run: `PYTHONPATH= ./.venv/Scripts/python.exe -m pytest tests/test_evaluation.py -q`
Expected: PASS

- [ ] **Step 3: 编写 120 题评测集**

出题规则（对照已定稿的 12 个文档逐题写）：
- 分布：RT 22 / LG 16 / PAY 12 / PROMO 14 / PROD 20 / CARE 12 / B2B 10 / COMP 6 / CS 8 = 120 含 OOS 10（OOS 单列为 category=OOS, level=OOS）
- L1 约 48 题（问法贴近原文）、L2 约 42 题（口语化：退钱/多久到/划不划算）、L3 约 20 题（跨段落综合，expected_keywords 选结论性数字如"$10–$20 礼品卡"）
- 每题 expected_keywords ≥1 且答案原文确含该词；expected_doc 用文档名去 `.md` 后的前缀
- OOS 10 题：竞品价格、编造的"太空棉系列"、实时库存、明天天气、法律建议、竞品退货政策、员工工资、仓库地址精确坐标、股票代码、政治话题

写入 `evals/golden_set.jsonl`，同时在 `evals/README.md` 记录出题依据索引（题号 → 文档 → 大致小节，不入 JSONL）。

- [ ] **Step 4: 跑校验脚本**

Run: `PYTHONPATH= ./.venv/Scripts/python.exe evals/validate_golden.py`
Expected: `OK: 120 questions valid`

- [ ] **Step 5: Commit**

```bash
git add evals/ tests/test_evaluation.py
git commit -m "feat: add 120-question golden eval set with validator"
```

---

### Task 6: 检索评测脚本 evaluate_retrieval.py

**Files:**
- Create: `scripts/evaluate_retrieval.py`

**Interfaces:**
- Consumes:
  - `app.core.query_rewriter.rewrite_query(query: str) -> str`
  - `app.core.pgvector_store.pgvector_similarity_search_with_score(query: str, k: int, tenant_id: str) -> list[tuple[Document, float]]`（distance 0–2，越小越相似）
  - `retriever_tool.MAX_DISTANCE = 0.8`（阈值与其保持一致，直接 import）
  - `app.core.eval_metrics.hit_at_k / reciprocal_rank / aggregate`
- Produces: markdown + json 报告落 `evals/reports/retrieval-<YYYYMMDD-HHMMSS>.{md,json}`

- [ ] **Step 1: 实现脚本**

```python
"""检索层离线评测：rewrite → embed → pgvector top-k → distance 过滤。

只评检索不调 LLM；需要 .env 配置 DASHSCOPE_API_KEY 且语料已导入指定租户。
用法：
  python scripts/evaluate_retrieval.py --tenant-id cloudcotton [--k 5] [--limit N]
输出：evals/reports/retrieval-<时间戳>.md / .json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.eval_metrics import aggregate, hit_at_k, reciprocal_rank  # noqa: E402
from app.core.pgvector_store import pgvector_similarity_search_with_score  # noqa: E402
from app.core.query_rewriter import rewrite_query  # noqa: E402
from app.core.retriever_tool import MAX_DISTANCE  # noqa: E402


def load_golden(path: Path, limit: int | None) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows[:limit] if limit else rows


def evaluate_one(row: dict, k: int, tenant_id: str) -> dict:
    started = time.perf_counter()
    query = rewrite_query(row["question"])
    results = run_async(pgvector_similarity_search_with_score(query, k=k, tenant_id=tenant_id))
    latency_ms = (time.perf_counter() - started) * 1000
    ranked = [doc.metadata.get("source", "") for doc, _ in results]
    distances = [score for _, score in results]
    kept = [doc for doc, score in zip(ranked, distances) if score <= MAX_DISTANCE]
    expected = row.get("expected_doc")
    if expected is None:  # OOS 题：判定期望"检索不到"
        passed = len(kept) == 0
        hit5 = passed
        rr = 1.0 if passed else 0.0
    else:
        base = Path(str(ranked[0])).name if ranked else ""
        # source 可能是完整路径/URL，统一取文件名做前缀比较
        ranked_names = [Path(str(s)).name for s in ranked]
        kept_names = [Path(str(s)).name for s in kept]
        hit5 = hit_at_k(kept_names or ranked_names, expected, k)
        rr = reciprocal_rank(ranked_names, expected)
        passed = hit5 and rr > 0
    return {"id": row["id"], "category": row["category"], "level": row["level"],
            "passed": passed, "hit": hit5, "rr": rr, "latency_ms": latency_ms,
            "top_sources": ranked_names[:3], "distances": [round(d, 4) for d in distances[:3]]}


def run_async(coro):
    import asyncio
    return asyncio.run(coro)


def write_report(rows: list[dict], summary: dict, report_dir: Path) -> tuple[Path, Path]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_dir.mkdir(parents=True, exist_ok=True)
    md_path = report_dir / f"retrieval-{stamp}.md"
    json_path = report_dir / f"retrieval-{stamp}.json"
    mrr = sum(r["rr"] for r in rows) / len(rows) if rows else 0.0
    latencies = sorted(r["latency_ms"] for r in rows)
    p50 = latencies[len(latencies) // 2] if latencies else 0.0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
    lines = [
        "# 检索评测报告", "",
        f"- 时间：{stamp}｜题目：{summary['total']}｜hit@5 通过：{summary['passed']}（{summary['pass_rate']:.1%}）",
        f"- MRR：{mrr:.3f}｜延迟 p50={p50:.0f}ms p95={p95:.0f}ms", "",
        "## 分层", "",
        "| 层级 | total | passed | pass_rate |", "|---|---|---|---|",
    ]
    for level, stat in summary["by_level"].items():
        lines.append(f"| {level} | {stat['total']} | {stat['passed']} | {stat['pass_rate']:.1%} |")
    lines += ["", "## 未命中题目（迭代抓手）", ""]
    for r in rows:
        if not r["hit"]:
            lines.append(f"- `{r['id']}` top3={r['top_sources']} dist={r['distances']}")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    json_path.write_text(json.dumps({"rows": rows, "summary": summary, "mrr": mrr},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path, json_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", default=str(ROOT / "evals" / "golden_set.jsonl"))
    parser.add_argument("--tenant-id", default="cloudcotton")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--report-dir", default=str(ROOT / "evals" / "reports"))
    args = parser.parse_args()

    golden = load_golden(Path(args.golden), args.limit)
    print(f"评测 {len(golden)} 题（tenant={args.tenant_id}, k={args.k}, MAX_DISTANCE={MAX_DISTANCE}）")
    rows = [evaluate_one(row, args.k, args.tenant_id) for row in golden]
    summary = aggregate([{k: r[k] for k in ("id", "category", "level", "passed")} for r in rows])
    md_path, json_path = write_report(rows, summary, Path(args.report_dir))
    print(f"hit@5={summary['pass_rate']:.1%} 报告：{md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

实现时允许微调（asyncio 调用方式、source 字段形态），但 CLI 参数与报告路径契约不变。

- [ ] **Step 2: 冒烟验证（连真实库跑 3 题）**

前置：Task 3/4 语料已导入 cloudcotton 租户（若尚未导入，先跳到 Task 7 Step 1–3 再回来）。

Run: `PYTHONPATH= ./.venv/Scripts/python.exe scripts/evaluate_retrieval.py --tenant-id cloudcotton --limit 3`
Expected: 输出 hit@5 数字并在 `evals/reports/` 生成 md/json；无异常栈

- [ ] **Step 3: Commit**

```bash
git add scripts/evaluate_retrieval.py evals/reports/.gitkeep
git commit -m "feat: add offline retrieval evaluation script"
```

---

### Task 7: 语料导入 + 真实检索评测首轮

**Files:**
- 无新文件；产出评测报告与实测记录

**Interfaces:**
- Consumes: `scripts/import_demo_data.py --data-dir docs/demo_data/cloudcotton`（现有脚本，走 `/documents/upload` 异步索引）；`scripts/create_dev_token.py --roles user,uploader`
- Produces: cloudcotton 租户下 12 文档全部 indexed；首轮 hit@k 实测报告

- [ ] **Step 1: 启动后端与 Worker（若未运行）**

```bash
cd /d/企业级AI知识问答系统
./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8765 &   # 或已有进程则跳过
./.venv/Scripts/python.exe -m app.worker &
sleep 5 && curl -s http://127.0.0.1:8765/health/ready | head -c 200
```
Expected: `{"status":"ready"...}`

- [ ] **Step 2: 签发 token 并导入 12 个文档**

```bash
TOKEN=$(./.venv/Scripts/python.exe scripts/create_dev_token.py --user-id importer --roles user,uploader --ttl-seconds 900 | grep -oE 'ey[A-Za-z0-9._-]+')
./.venv/Scripts/python.exe scripts/import_demo_data.py --token "$TOKEN" --data-dir docs/demo_data/cloudcotton --base-url http://127.0.0.1:8765
sleep 30   # Worker 索引 500-800 chunk 需要一点时间
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/documents | python -c "import sys,json; docs=json.load(sys.stdin); print(len(docs), 'docs;', sum(1 for d in docs if d['status']=='indexed'), 'indexed')"
```
注：若 `/documents` 响应包一层 `{"documents":[...]}` 则相应调整解析。租户参数按 upload 接口实际语义（dev token 默认租户）为准——若 create_dev_token 支持 `--tenant-id` 则显式传 `cloudcotton`。

Expected: 12 docs 全部 indexed

- [ ] **Step 3: 跑首轮全量检索评测**

```bash
PYTHONPATH= ./.venv/Scripts/python.exe scripts/evaluate_retrieval.py --tenant-id <实际租户> 
```
Expected: 报告生成。**若 hit@5 < 0.90**：打开报告"未命中题目"清单，按两类迭代——① 口语词未覆盖 → 补词典（回 Task 2 模式）；② 语料表述问题 → 微调对应文档句子（不改事实）。每轮迭代后重跑，直到 ≥0.90 或确认瓶颈在 embedding 本身（此时如实记录，README 写实测值与分析）。

- [ ] **Step 4: 记录迭代过程**

创建 `evals/reports/tuning-log.md`：每轮记录改动（加了哪些词/改了哪句）与当轮 hit@1/@5、MRR。这是面试讲"评测驱动迭代"的核心证据。

- [ ] **Step 5: Commit**

```bash
git add evals/reports/
git commit -m "test: first-round retrieval eval on real pgvector + tuning log"
```

---

### Task 8: 端到端问答评测脚本 evaluate_qa.py

**Files:**
- Create: `scripts/evaluate_qa.py`

**Interfaces:**
- Consumes: `POST {base}/qa/ask`（Bearer JWT；请求 `{question, session_id}`；响应 `{answer, sources:[{source,...}], refused, need_human, human_task_id}`）
  - `app.core.eval_metrics.keyword_coverage / aggregate`
- Produces: markdown + json 报告落 `evals/reports/qa-<时间戳>.{md,json}`；支持 `--limit/--level/--category` 分片

- [ ] **Step 1: 实现脚本**

```python
"""端到端 QA 评测：走真实 /qa/ask 链路（Agent+检索+拒答+引用）。

消耗真实百炼 token，手动触发；CI 不跑。
用法：
  python scripts/evaluate_qa.py --base-url http://127.0.0.1:8765 --token <JWT> \
      [--limit 20] [--level L2,L3] [--category RT,LG]
判定三关：① refused == should_refuse ② 关键词覆盖(≥1) ③ 来源含 expected_doc 前缀
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.eval_metrics import aggregate, keyword_coverage  # noqa: E402


def ask(base_url: str, token: str, question: str, session_id: str) -> dict:
    body = json.dumps({"question": question, "session_id": session_id}).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/qa/ask", data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def judge(row: dict, resp: dict) -> dict:
    reasons: list[str] = []
    refuse_ok = resp.get("refused") is row["should_refuse"] or resp.get("refused") == row["should_refuse"]
    if not refuse_ok:
        reasons.append("refused_mismatch")
    kw_ok = src_ok = True
    if not row["should_refuse"]:
        kw_ok = keyword_coverage(resp.get("answer", ""), row["expected_keywords"])
        if not kw_ok:
            reasons.append("keyword_miss")
        src_names = [Path(str(s.get("source", ""))).name for s in resp.get("sources", [])]
        src_ok = any(name.startswith(row["expected_doc"]) for name in src_names)
        if not src_ok:
            reasons.append("source_miss")
    return {"id": row["id"], "category": row["category"], "level": row["level"],
            "passed": refuse_ok and kw_ok and src_ok,
            "refuse_ok": refuse_ok, "kw_ok": kw_ok, "src_ok": src_ok,
            "reasons": reasons, "answer_head": resp.get("answer", "")[:120],
            "sources": [s.get("source") for s in resp.get("sources", [])][:3]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", default=str(ROOT / "evals" / "golden_set.jsonl"))
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--token", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--level", default=None, help="逗号分隔，如 L2,L3")
    parser.add_argument("--category", default=None, help="逗号分隔，如 RT,LG")
    parser.add_argument("--report-dir", default=str(ROOT / "evals" / "reports"))
    args = parser.parse_args()

    rows = [json.loads(l) for l in Path(args.golden).read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.level:
        levels = set(args.level.split(","))
        rows = [r for r in rows if r["level"] in levels]
    if args.category:
        cats = set(args.category.split(","))
        rows = [r for r in rows if r["category"] in cats]
    if args.limit:
        rows = rows[:args.limit]

    results = []
    for i, row in enumerate(rows, 1):
        try:
            resp = ask(args.base_url, args.token, row["question"], session_id=f"eval-{row['id']}")
            results.append(judge(row, resp))
        except Exception as exc:  # noqa: BLE001
            results.append({"id": row["id"], "category": row["category"], "level": row["level"],
                            "passed": False, "reasons": [f"http_error:{exc}"]})
        print(f"[{i}/{len(rows)}] {results[-1]['id']} {'PASS' if results[-1]['passed'] else 'FAIL ' + ','.join(results[-1]['reasons'])}")

    summary = aggregate(results)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"qa-{stamp}.json").write_text(
        json.dumps({"rows": results, "summary": summary}, ensure_ascii=False, indent=2), encoding="utf-8")
    md = [f"# QA 端到端评测 {stamp}", "",
          f"通过率 {summary['passed']}/{summary['total']} = {summary['pass_rate']:.1%}", "", "## 分层", ""]
    for level, stat in summary["by_level"].items():
        md.append(f"- {level}: {stat['passed']}/{stat['total']} = {stat['pass_rate']:.1%}")
    md += ["", "## 失败题", ""]
    md += [f"- `{r['id']}` {r.get('reasons')} 答:{r.get('answer_head','')[:60]}"
           for r in results if not r["passed"]]
    (out_dir / f"qa-{stamp}.md").write_text("\n".join(md), encoding="utf-8")
    print(f"报告：{out_dir}/qa-{stamp}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 小样冒烟（L1 前 5 题）**

Run: `PYTHONPATH= ./.venv/Scripts/python.exe scripts/evaluate_qa.py --token "$TOKEN" --limit 5`
Expected: 5 题跑完出报告；OOS 题若混入且系统正确拒答则 PASS

- [ ] **Step 3: 全量 120 题评测**

Run: `PYTHONPATH= ./.venv/Scripts/python.exe scripts/evaluate_qa.py --token "$TOKEN"`
Expected: 全部跑完；记录总体与分层通过率进 tuning-log.md。失败题逐条归因（检索没中→回 Task 7 迭代；答非所问但检索中了→prompt/Agent 层问题如实记录——核心层冻结，只记录不擅改）

- [ ] **Step 4: Commit**

```bash
git add scripts/evaluate_qa.py evals/reports/
git commit -m "feat: add end-to-end QA evaluation script and full-run report"
```

---

### Task 9: README 业务化 + FastAPI 元数据 + 前端文案

**Files:**
- Modify: `README.md`（标题区、业务场景节、评测体系节、Quick Start 三步体验、实测指标表）
- Modify: `app/main.py:135-138`（FastAPI title/description 两行）
- Modify: `frontend/src/pages/ChatPage.tsx:20-25`（SUGGESTIONS 数组）
- Modify: `frontend/src/pages/DocumentsPage.tsx:220-221`（空状态提示）

**Interfaces:**
- Consumes: Task 7/8 的实测报告数字（README 只填真实值）

- [ ] **Step 1: README 标题与定位段**

标题下副标改为：

```markdown
# 企业级 AI 知识问答系统

> 以 **云棉家居（CloudCotton Home）跨境电商售后知识库** 为落地场景的生产级 Agentic RAG：
> 有据可依 · 无据拒答 · 来源可溯 · 效果可测
```

紧随其后新增「业务场景」节：

```markdown
## 业务场景

云棉家居是一家面向北美/欧洲/日本市场的跨境家纺电商。一线客服每天面对大量政策咨询：
退换货怎么走、黑五发货慢了算不算延误、CloudCoins 怎么用、德国客户要 VAT 发票……
传统客服靠翻 Wiki 和问老员工，新人上手慢、答复口径不一。

本系统让客服用自然语言直查内部知识库：LangGraph Agent 决策是否检索，
pgvector 在租户隔离的向量分区里召回证据，LLM 只依据证据作答；
知识库没有的内容**强制拒答并转人工**，杜绝电商场景最致命的"幻觉承诺"（如乱承诺退款金额引发纠纷）。
```

- [ ] **Step 2: README 新增「评测体系」节（数字占位，Task 7/8 完成后填实测值）**

```markdown
## 评测体系

| 指标 | 实测值 |
|---|---|
| 语料规模 | 12 文档 / XXXX 行 / XXX chunks（实测） |
| 检索 hit@5 | XX.X%（120 题，L1/L2/L3 分层见报告） |
| 检索 MRR | X.XXX |
| 端到端通过率 | XX.X%（拒答正确率 XX/X） |

- 黄金集：`evals/golden_set.jsonl`（120 题 = L1 直查 48 / L2 口语改写 42 / L3 多跳 20 / OOS 拒答 10）
- 检索评测：`python scripts/evaluate_retrieval.py --tenant-id cloudcotton`
- 端到端评测（耗 token，手动）：`python scripts/evaluate_qa.py --token <JWT>`
- 历史报告：`evals/reports/`；调优记录：`evals/reports/tuning-log.md`

> 以上数字均为本地实测（百炼 embedding + pgvector），随词典与语料迭代更新。
```

- [ ] **Step 3: Quick Start 插入电商体验三步**

在现有「导入演示数据」节替换为：

```markdown
### 导入云棉家居演示知识库（可选）

​```powershell
$env:TOKEN = python scripts\create_dev_token.py --roles user,uploader --ttl-seconds 900
python scripts\import_demo_data.py --token $env:TOKEN --data-dir docs\demo_data\cloudcotton
​```

上传后即可体验典型售后问题：`独立站买的四件套能退货吗？`、`发美国多久到？`、
`CloudCoins 怎么获得？`，以及故意刁难：`你们和 Brooklinen 哪个便宜？`（正确行为是拒答）。
```

同时删除旧 demo 数据描述（6 篇 Claude/RAG 教程文档的提法改为"通用模板演示文档仍在 docs/demo_data/ 根目录"）。

- [ ] **Step 4: FastAPI 元数据两行**

```python
    application = FastAPI(
        title="云棉家居跨境电商售后知识库",
        description="LangChain + LangGraph Agentic RAG：有据可依、无据拒答、来源可溯、效果可测",
```

- [ ] **Step 5: 前端文案**

`ChatPage.tsx:20` SUGGESTIONS 改为：

```typescript
const SUGGESTIONS = [
  '独立站买的四件套可以退货吗？',
  '发美国一般多久能到？',
  'CloudCoins 积分怎么获得和使用？',
  '你们和 Brooklinen 比哪个好？',
]
```

空态标题 `企业知识问答助手` → `云棉家居售后知识助手`；副标改为"查询售后/物流/支付政策，答案均标注来源文档"。

`DocumentsPage.tsx:221` 空状态第二行改为：

```tsx
<p className="text-sm text-gray-400 mb-6">支持 PDF · DOCX · XLSX · TXT · MD，可用 scripts/import_demo_data.py 一键导入云棉家居演示知识库</p>
```

- [ ] **Step 6: 前端验证**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: tsc 无错；vitest 全过（若有快照断言涉及旧文案则同步更新）

- [ ] **Step 7: Commit**

```bash
git add README.md app/main.py frontend/src/pages/ChatPage.tsx frontend/src/pages/DocumentsPage.tsx
git commit -m "docs: rebrand to cloudcotton ecommerce KB with measured metrics"
```

---

### Task 10: 全量回归 + 推送

**Files:** 无新改动；纯验证与推送

- [ ] **Step 1: 后端全量回归**

Run: `PYTHONPATH= ./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 全绿（166 + 新增 ≈ 175）

- [ ] **Step 2: 前端回归**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: 全绿

- [ ] **Step 3: 校验器最后一跑**

Run: `PYTHONPATH= ./.venv/Scripts/python.exe evals/validate_golden.py`
Expected: `OK: 120 questions valid`

- [ ] **Step 4: push**

```bash
git log --oneline origin/main..HEAD   # 确认提交序列干净
git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 -c http.sslBackend=openssl push origin main
```
Expected: push 成功

---

## 执行顺序说明

Task 1 → 2 →（3 ∥ 4）→ 5 → 6 → 7 → 8 → 9 → 10。

- Task 3/4（语料）工作量最大，建议子代理并行分工（01-05 一组、06-12 一组），完成后人工抽查一致性（对照原 679 行文档核价格/天数）
- Task 6 Step 2 依赖 Task 7 的导入完成——首次执行时可先跑 Task 7 Step 1–3 再回到 Task 6 冒烟
- 全程不动 `app/api|services|agent|models`，若发现必须改核心才能达标的情形，停下来向用户说明而非擅自改
