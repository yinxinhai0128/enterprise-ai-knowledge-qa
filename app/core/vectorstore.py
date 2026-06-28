"""向量库迁移兼容层：ChromaDB → FAISS（faiss-cpu）。

ChromaDB 1.5.x Rust compactor 在本 Windows 机器上无法完成 HNSW 构建，
已迁移至 faiss-cpu（app/core/faiss_store.py）。本模块仅保留：
  - init_embeddings 引用（tests/conftest.py monkeypatch 需要）
  - migrate_legacy_vector_metadata 工具函数
原 Chroma 实现（get_vectorstore / close_vectorstore / vectorstore_lock）已移除。
"""
from __future__ import annotations

from typing import Any

from app.core.llm import init_embeddings  # noqa: F401  — conftest monkeypatches this

LEGACY_TENANT_ID = "legacy"


def migrate_legacy_vector_metadata() -> int:
    """为缺少 tenant_id 的旧向量补齐 'legacy' 标签，返回更新数量。

    旧数据统一归入受控的 ``legacy`` 租户；检索始终带 tenant filter，
    因此迁移中断时缺少标签的向量也不会泄露给任何租户。
    """
    from langchain_core.documents import Document as LCDocument

    from app.core.faiss_store import FAISS_INDEX_DIR, get_faiss_store

    store = get_faiss_store()
    if store is None:
        return 0

    to_migrate = [
        (vid, doc)
        for vid, doc in list(store.docstore._dict.items())
        if "tenant_id" not in doc.metadata
    ]
    if not to_migrate:
        return 0

    ids = [vid for vid, _ in to_migrate]
    new_docs: list[LCDocument] = []
    for vid, doc in to_migrate:
        new_meta: dict[str, Any] = dict(doc.metadata)
        new_meta["tenant_id"] = LEGACY_TENANT_ID
        new_meta.setdefault("uploaded_by", LEGACY_TENANT_ID)
        new_meta.setdefault("chunk_id", vid)
        new_docs.append(LCDocument(page_content=doc.page_content, metadata=new_meta))

    store.delete(ids)
    store.add_texts(
        [doc.page_content for doc in new_docs],
        metadatas=[doc.metadata for doc in new_docs],
        ids=ids,
    )

    if (FAISS_INDEX_DIR / "index.faiss").exists():
        store.save_local(str(FAISS_INDEX_DIR))

    return len(ids)
