"""向量库：Chroma 单例。

集合名固定 enterprise_kb，向量化器走百炼（见 app/core/llm.py），
持久化目录取 settings.chroma_dir（与 Docker 卷对齐）。
"""
from __future__ import annotations

from functools import lru_cache

from langchain_chroma import Chroma

from app.config import settings
from app.core.llm import init_embeddings

LEGACY_TENANT_ID = "legacy"
_MIGRATION_BATCH_SIZE = 500


@lru_cache(maxsize=1)
def get_vectorstore() -> Chroma:
    """进程内单例向量库。"""
    return Chroma(
        collection_name="enterprise_kb",
        embedding_function=init_embeddings(),
        persist_directory=str(settings.chroma_dir),
    )


def migrate_legacy_vector_metadata() -> int:
    """为阶段 2 前的向量补齐租户标签，返回更新数量。

    旧数据统一归入受控的 ``legacy`` 租户；检索始终带 tenant filter，
    因此迁移中断时缺少标签的向量也不会泄露给任何租户。
    """
    collection = get_vectorstore()._collection
    total = collection.count()
    updated = 0
    for offset in range(0, total, _MIGRATION_BATCH_SIZE):
        batch = collection.get(
            limit=_MIGRATION_BATCH_SIZE,
            offset=offset,
            include=["metadatas"],
        )
        ids_to_update: list[str] = []
        metadatas_to_update: list[dict] = []
        for item_id, metadata in zip(
            batch.get("ids", []),
            batch.get("metadatas", []),
            strict=True,
        ):
            normalized = dict(metadata or {})
            changed = False
            if "tenant_id" not in normalized:
                normalized["tenant_id"] = LEGACY_TENANT_ID
                normalized.setdefault("uploaded_by", LEGACY_TENANT_ID)
                changed = True
            if "chunk_id" not in normalized:
                # 旧 Chroma ID 已持久化且不可原地重命名；将其固化为 legacy chunk ID。
                normalized["chunk_id"] = item_id
                changed = True
            if not changed:
                continue
            ids_to_update.append(item_id)
            metadatas_to_update.append(normalized)
        if ids_to_update:
            collection.update(ids=ids_to_update, metadatas=metadatas_to_update)
            updated += len(ids_to_update)
    return updated
