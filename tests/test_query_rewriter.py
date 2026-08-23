"""规则改写层单元测试。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.query_rewriter import RuleBasedRewriter, model_rewrite_query, rewrite_query

_TEST_SYNONYMS = {
    "绩效": ["KPI", "考核"],
    "薪资": ["工资", "薪水"],
    "人力资源": ["HR", "人资", "人事"],
    "入职": ["onboarding", "入职手续"],
    "请假": ["休假申请", "假期申请"],
}


@pytest.fixture()
def rewriter() -> RuleBasedRewriter:
    # 直接注入 _data，跳过文件 IO，避免沙箱 Temp 目录权限问题。
    r = RuleBasedRewriter(synonyms_path=Path("nonexistent"))
    r._data = dict(_TEST_SYNONYMS)
    return r


def test_normalize_strips_question_mark(rewriter: RuleBasedRewriter) -> None:
    assert "？" not in rewriter.normalize("请假需要几天？")
    assert "?" not in rewriter.normalize("请假需要几天?")


def test_normalize_strips_sentence_ending(rewriter: RuleBasedRewriter) -> None:
    result = rewriter.normalize("怎么报销吗")
    assert result == "怎么报销"


def test_normalize_nfkc(rewriter: RuleBasedRewriter) -> None:
    result = rewriter.normalize("ＨＲ部门")
    assert result == "HR部门"


def test_expand_adds_canonical(rewriter: RuleBasedRewriter) -> None:
    result = rewriter.expand("KPI考核结果怎么查")
    assert "绩效" in result


def test_expand_no_dup_when_canonical_present(rewriter: RuleBasedRewriter) -> None:
    result = rewriter.expand("绩效考核结果")
    # 原词已含规范词"绩效"，不应重复追加
    assert result.count("绩效") == 1


def test_expand_alias_match(rewriter: RuleBasedRewriter) -> None:
    result = rewriter.expand("工资什么时候发")
    assert "薪资" in result


def test_rewrite_query_function() -> None:
    result = rewrite_query("HR入职流程是什么吗")
    # 去除句末"吗"，并追加规范词
    assert "吗" not in result
    assert "人力资源" in result or "入职" in result


@pytest.mark.asyncio
async def test_model_rewrite_serializes_structured_content(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLLM:
        async def ainvoke(self, prompt: str) -> SimpleNamespace:
            return SimpleNamespace(content=["alpha", {"text": "beta"}])

    monkeypatch.setattr("app.core.llm.init_llm", lambda: FakeLLM())

    result = await model_rewrite_query("question")

    assert result == '["alpha", {"text": "beta"}]'


# ---------------- 电商口语同义词（云棉家居场景） ----------------

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
    for key in ("退款", "退货", "换货", "多久到", "尺码", "运费", "发票", "积分"):
        assert key in data, f"词典缺少电商词条: {key}"
