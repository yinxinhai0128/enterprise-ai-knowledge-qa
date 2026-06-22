"""按文档执行 Chroma 查询与补偿删除。"""
from __future__ import annotations

from app.core.vectorstore import get_vectorstore


def document_vector_ids(tenant_id: str, doc_id: int) -> list[str]:
    """返回指定租户文档的全部向量 ID。"""
    collection = get_vectorstore()._collection
    result = collection.get(
        where={
            "$and": [
                {"tenant_id": {"$eq": tenant_id}},
                {"doc_id": {"$eq": doc_id}},
            ]
        },
        include=[],
    )
    return [str(item_id) for item_id in result.get("ids", [])]


def delete_document_vectors(tenant_id: str, doc_id: int) -> int:
    """幂等删除指定文档的向量，返回删除前数量。"""
    ids = document_vector_ids(tenant_id, doc_id)
    if ids:
        get_vectorstore().delete(ids=ids)
    return len(ids)
