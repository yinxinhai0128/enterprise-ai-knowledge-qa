"""向量库：嵌入式 Chroma 的受控生命周期与跨进程互斥。

集合名固定 enterprise_kb，向量化器走百炼（见 app/core/llm.py），
持久化目录取 settings.chroma_dir（与 Docker 卷对齐）。
"""
from __future__ import annotations

import importlib
import os
import pickle
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

from chromadb.api.types import Metadata
from langchain_chroma import Chroma

from app.config import settings
from app.core.llm import init_embeddings

LEGACY_TENANT_ID = "legacy"
_MIGRATION_BATCH_SIZE = 500


@contextmanager
def vectorstore_lock() -> Iterator[None]:
    """串行化 API/Worker 对嵌入式 Chroma 目录的跨进程访问。"""
    lock_path = settings.storage_dir / ".vectorstore.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            locking_module = importlib.import_module("msvcrt")
            locking_module.locking(handle.fileno(), locking_module.LK_LOCK, 1)
        else:
            locking_module = importlib.import_module("fcntl")
            locking_module.flock(handle.fileno(), locking_module.LOCK_EX)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                locking_module.locking(handle.fileno(), locking_module.LK_UNLCK, 1)
            else:
                locking_module.flock(handle.fileno(), locking_module.LOCK_UN)


@lru_cache(maxsize=1)
def get_vectorstore() -> Chroma:
    """返回当前操作使用的向量库；操作结束必须调用 close_vectorstore。

    Chroma() 构造函数自身会写出 dimensionality=None 的 index_metadata.pickle，
    因此必须在构造之后立即清理，让后续 count()/search() 走纯 SQLite 路径。
    """
    store = Chroma(
        collection_name="enterprise_kb",
        embedding_function=init_embeddings(),
        persist_directory=str(settings.chroma_dir),
    )
    _purge_uninit_hnsw_pickles()
    return store


# 测试会替换公开工厂；生命周期清理始终只处理真实持久化客户端缓存。
_cached_get_vectorstore = get_vectorstore


def _purge_uninit_hnsw_pickles() -> None:
    """删除 dimensionality=None 的 index_metadata.pickle。

    ChromaDB 1.5.x 在 get_or_create_collection() 时立即写出 pickle
    但 dimensionality 仍为 None；后续 count()/search() 触发 compactor
    时会因 "Error loading hnsw index" 崩溃。删掉 pickle 后 ChromaDB
    回退到纯 SQLite 路径，完全正常工作。
    """
    for pickle_path in Path(settings.chroma_dir).rglob("index_metadata.pickle"):
        try:
            with pickle_path.open("rb") as fp:
                meta = pickle.load(fp)
            if isinstance(meta, dict) and meta.get("dimensionality") is None:
                pickle_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pickle_path.unlink(missing_ok=True)


def close_vectorstore() -> None:
    """释放进程内客户端，避免嵌入式 Chroma 跨进程复用旧状态。"""
    if _cached_get_vectorstore.cache_info().currsize:
        store = _cached_get_vectorstore()
        close = getattr(store._client, "close", None)
        if callable(close):
            close()
    _cached_get_vectorstore.cache_clear()
    _purge_uninit_hnsw_pickles()


def migrate_legacy_vector_metadata() -> int:
    """为阶段 2 前的向量补齐租户标签，返回更新数量。

    旧数据统一归入受控的 ``legacy`` 租户；检索始终带 tenant filter，
    因此迁移中断时缺少标签的向量也不会泄露给任何租户。
    """
    with vectorstore_lock():
        try:
            collection = get_vectorstore()._collection
            try:
                total = collection.count()
            except Exception:  # noqa: BLE001
                # ChromaDB 1.5.x HNSW 索引未就绪时 count() 失败；无向量需要迁移。
                return 0
            updated = 0
            for offset in range(0, total, _MIGRATION_BATCH_SIZE):
                batch = collection.get(
                    limit=_MIGRATION_BATCH_SIZE,
                    offset=offset,
                    include=["metadatas"],
                )
                ids_to_update: list[str] = []
                metadatas_to_update: list[Metadata] = []
                metadata_batch = batch.get("metadatas") or []
                for item_id, metadata in zip(
                    batch.get("ids", []),
                    metadata_batch,
                    strict=True,
                ):
                    normalized: dict[str, Any] = dict(metadata or {})
                    changed = False
                    if "tenant_id" not in normalized:
                        normalized["tenant_id"] = LEGACY_TENANT_ID
                        normalized.setdefault("uploaded_by", LEGACY_TENANT_ID)
                        changed = True
                    if "chunk_id" not in normalized:
                        # 旧 ID 不可原地重命名；将其固化为 legacy chunk ID。
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
        finally:
            close_vectorstore()
