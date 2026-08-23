"""eval_metrics 纯函数单测：不碰网络、不碰数据库。"""
from __future__ import annotations

from app.core.eval_metrics import aggregate, hit_at_k, keyword_coverage, reciprocal_rank


def test_hit_at_k_basic() -> None:
    docs = ["06-物流配送政策.md", "07-退换货与退款政策.md"]
    assert hit_at_k(docs, "07-退换货", k=2) is True
    assert hit_at_k(docs, "07-退换货", k=1) is False


def test_hit_at_k_prefix_semantics() -> None:
    # expected_doc 是文件名去 .md 的前缀；startswith 判定
    docs = ["07-退换货与退款政策.md"]
    assert hit_at_k(docs, "07-退换货", k=1) is True
    assert hit_at_k(docs, "08-支付", k=1) is False


def test_hit_at_k_empty() -> None:
    assert hit_at_k([], "07-退换货", k=5) is False


def test_hit_at_k_k_zero() -> None:
    assert hit_at_k(["a"], "a", k=0) is False


def test_reciprocal_rank_first_position() -> None:
    assert reciprocal_rank(["07-退换货", "06-物流"], "07-退换货") == 1.0


def test_reciprocal_rank_second_position() -> None:
    assert reciprocal_rank(["a", "07-退换货"], "07-退换货") == 0.5


def test_reciprocal_rank_miss() -> None:
    assert reciprocal_rank(["a", "b"], "07-退换货") == 0.0


def test_keyword_coverage_hit_any() -> None:
    assert keyword_coverage("30 天内可退货", ["7 天", "30 天"]) is True


def test_keyword_coverage_miss() -> None:
    assert keyword_coverage("不支持退货", ["7 天", "30 天"]) is False


def test_keyword_coverage_empty_keywords() -> None:
    assert keyword_coverage("任意回答", []) is False


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
    assert out["by_level"]["L1"]["pass_rate"] == 1.0
    assert out["by_level"]["L2"]["passed"] == 0
    assert out["by_level"]["OOS"]["passed"] == 1
    assert out["by_category"]["RT"]["total"] == 2
    assert out["by_category"]["OOS"]["total"] == 1


def test_aggregate_empty() -> None:
    out = aggregate([])
    assert out["total"] == 0
    assert out["pass_rate"] == 0.0
    assert out["by_level"] == {}
