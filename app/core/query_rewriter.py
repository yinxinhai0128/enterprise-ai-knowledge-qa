"""Query 改写层：规则改写（同步）+ 模型改写（异步可选）。

流水线：normalize → synonym_expand
规则层在 retriever_tool 内部自动调用；模型层保留接口供显式启用。
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

_SYNONYMS_PATH = Path(__file__).parent.parent.parent / "config" / "query_synonyms.json"


class RuleBasedRewriter:
    def __init__(self, synonyms_path: Path = _SYNONYMS_PATH) -> None:
        self._path = synonyms_path
        self._data: dict[str, list[str]] | None = None

    def _load(self) -> dict[str, list[str]]:
        if self._data is None:
            if self._path.is_file():
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            else:
                self._data = {}
        return self._data

    def normalize(self, query: str) -> str:
        """NFKC 规范化，去除尾部问句标记。"""
        q = unicodedata.normalize("NFKC", query).strip()
        q = re.sub(r"[？?]+$", "", q).strip()
        q = re.sub(r"[吗呢啊啦哦]+$", "", q).strip()
        return q

    def expand(self, query: str) -> str:
        """同义词展开：匹配别名或规范词 → 追加规范词（不替换原词）。"""
        data = self._load()
        additions: list[str] = []
        lower_q = query.lower()
        for canonical, aliases in data.items():
            canonical_lower = canonical.lower()
            hit = canonical_lower in lower_q or any(a.lower() in lower_q for a in aliases)
            if hit and canonical_lower not in lower_q:
                additions.append(canonical)
        if additions:
            return query + " " + " ".join(additions)
        return query

    def rewrite(self, query: str) -> str:
        return self.expand(self.normalize(query))


_rule_rewriter = RuleBasedRewriter()


def rewrite_query(query: str) -> str:
    """规则改写入口（同步）：normalize + synonym_expand。"""
    return _rule_rewriter.rewrite(query)


async def model_rewrite_query(query: str) -> str:
    """模型改写（异步，可选）：用 LLM 将问句改写为检索关键词短语。

    适合在召回率不足时显式调用，不在 retriever_tool 默认路径中。
    """
    from app.core.llm import init_llm  # 延迟导入，避免循环依赖

    llm = init_llm()
    prompt = (
        "将以下问题改写为向量检索优化的关键词短语（3-6个关键词，空格分隔，"
        "不要标点，不要解释）：\n" + query
    )
    result = await llm.ainvoke(prompt)
    return result.content.strip()
