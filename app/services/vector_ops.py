"""向量库操作封装：pgvector 替代 FAISS。"""
from __future__ import annotations

from app.core.pgvector_store import (
    delete_documents_from_pgvector,
    pgvector_document_vector_ids,
)


async def document_vector_ids(tenant_id: str, doc_id: int) -> list[str]:
    """返回文档所有向量的 chunk_id 列表。"""
    return await pgvector_document_vector_ids(tenant_id, doc_id)


async def delete_document_vectors(tenant_id: str, doc_id: int) -> int:
    """删除文档所有向量，返回删除数量。"""
    return await delete_documents_from_pgvector(tenant_id, doc_id)
