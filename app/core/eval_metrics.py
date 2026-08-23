"""评测指标纯函数：检索命中、MRR、关键词覆盖、聚合统计。

只做确定性计算，不做 IO —— 便于 CI 单测与两个评测脚本（evaluate_retrieval /
evaluate_qa）复用。
"""
from __future__ import annotations

LEVELS = ("L1", "L2", "L3", "OOS")
CATEGORIES = ("RT", "LG", "PAY", "PROMO", "PROD", "CARE", "B2B", "COMP", "CS", "OOS")


def hit_at_k(ranked_docs: list[str], expected_prefix: str, k: int) -> bool:
    """前 k 个文档名中存在 expected_prefix 前缀匹配即命中。

    ranked_docs 应为文件名（含或不含 .md 均可）；expected_prefix 为文件名
    去 .md 后的前缀（如 "07-退换货与退款政策"）。
    """
    return any(doc.startswith(expected_prefix) for doc in ranked_docs[:k])


def reciprocal_rank(ranked_docs: list[str], expected_prefix: str) -> float:
    """首个命中文档的倒数排名（1-based）；无命中返回 0.0。"""
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
    """按 total/passed/pass_rate 聚合，并输出 by_level 与 by_category 分组。

    每行至少包含 {"category": str, "level": str, "passed": bool}；
    id 仅透传用途，不参与聚合键。仅输出非空分组的统计。
    """
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
