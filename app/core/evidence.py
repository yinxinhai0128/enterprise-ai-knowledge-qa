"""检索证据的结构化类型与验证辅助。"""
from __future__ import annotations

import math
from typing import Any, TypedDict


class Evidence(TypedDict):
    """单个真实向量命中的可审计证据。"""

    doc_id: int
    chunk_id: str
    source: str
    page: int | None
    sheet_name: str | None
    distance: float
    relevance: float


_REQUIRED_FIELDS = frozenset(Evidence.__required_keys__)


def validated_evidence_list(artifact: Any) -> list[Evidence]:
    """只接受检索工具生成的完整 evidence 列表，异常项失败关闭。"""
    if not isinstance(artifact, list):
        return []
    evidence: list[Evidence] = []
    seen: set[str] = set()
    for item in artifact:
        if not isinstance(item, dict) or not _REQUIRED_FIELDS <= item.keys():
            continue
        try:
            normalized: Evidence = {
                "doc_id": int(item["doc_id"]),
                "chunk_id": str(item["chunk_id"]),
                "source": str(item["source"]),
                "page": None if item["page"] is None else int(item["page"]),
                "sheet_name": (
                    None if item["sheet_name"] is None else str(item["sheet_name"])
                ),
                "distance": float(item["distance"]),
                "relevance": float(item["relevance"]),
            }
        except (TypeError, ValueError):
            continue
        if (
            normalized["doc_id"] <= 0
            or not normalized["chunk_id"]
            or normalized["chunk_id"] in seen
            or not math.isfinite(normalized["distance"])
            or not math.isfinite(normalized["relevance"])
        ):
            continue
        seen.add(normalized["chunk_id"])
        evidence.append(normalized)
    return evidence


def evidence_label(item: Evidence) -> str:
    """生成仅供展示的可信来源标签。"""
    if item["page"] is not None:
        return f'{item["source"]} 第{item["page"] + 1}页'
    if item["sheet_name"]:
        return f'{item["source"]} 工作表 {item["sheet_name"]}'
    return item["source"]
