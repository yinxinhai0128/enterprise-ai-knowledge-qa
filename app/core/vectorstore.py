"""向量库：Chroma 单例。

集合名固定 enterprise_kb，向量化器走百炼（见 app/core/llm.py），
持久化目录取 settings.chroma_dir（与 Docker 卷对齐）。
"""
from __future__ import annotations

from functools import lru_cache

from langchain_chroma import Chroma

from app.config import settings
from app.core.llm import init_embeddings


@lru_cache(maxsize=1)
def get_vectorstore() -> Chroma:
    """进程内单例向量库。"""
    return Chroma(
        collection_name="enterprise_kb",
        embedding_function=init_embeddings(),
        persist_directory=str(settings.chroma_dir),
    )
