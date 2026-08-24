"""向量库兼容层：FAISS → pgvector 迁移后的存根。

原 ChromaDB → FAISS 迁移工具已不再需要，migrate_legacy_vector_metadata
仅保留接口兼容性（legacy 数据已在迁移至 pgvector 前完成清理）。
init_embeddings 引用保留供 tests/conftest.py monkeypatch 使用。
"""
from __future__ import annotations

from app.core.llm import init_embeddings  # noqa: F401  — conftest monkeypatches this

LEGACY_TENANT_ID = "legacy"


def migrate_legacy_vector_metadata() -> int:
    """legacy 数据已在迁移至 pgvector 前完成清理，直接返回 0。"""
    return 0
