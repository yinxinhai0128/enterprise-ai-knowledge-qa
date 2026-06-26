"""FAISS-based vector store replacing ChromaDB for similarity search.

ChromaDB 1.5.x Rust backend cannot build HNSW binary on this Windows system
(compactor fails with "Error loading hnsw index"). faiss-cpu has a pre-built
wheel (no MSVC required) and IndexFlatL2 returns the same L2 distances as
ChromaDB's default metric — so existing MAX_DISTANCE thresholds stay valid.
"""
from __future__ import annotations

import threading
from pathlib import Path

from langchain_community.vectorstores import FAISS as LangchainFAISS
from langchain_core.documents import Document

# FAISS C++ FileIOWriter uses fopen() which cannot handle Unicode paths on Windows.
# Use a path under the user's home directory (no Chinese characters).
FAISS_INDEX_DIR = Path.home() / "faiss_kb"

_lock = threading.Lock()
_store: LangchainFAISS | None = None


def get_faiss_store() -> LangchainFAISS | None:
    """Return cached FAISS store, loading from disk on first call."""
    global _store
    if _store is not None:
        return _store
    index_file = FAISS_INDEX_DIR / "index.faiss"
    if not index_file.exists():
        return None
    with _lock:
        if _store is not None:
            return _store
        from app.core.llm import init_embeddings
        _store = LangchainFAISS.load_local(
            str(FAISS_INDEX_DIR),
            init_embeddings(),
            allow_dangerous_deserialization=True,
        )
    return _store


def reload_faiss_store() -> None:
    """Force reload from disk (call after reindex completes)."""
    global _store
    with _lock:
        _store = None


def faiss_similarity_search_with_score(
    query: str,
    k: int = 5,
    tenant_id: str = "local-tenant",
) -> list[tuple[Document, float]]:
    """Search FAISS index; post-filter by tenant_id (FAISS has no native filter)."""
    store = get_faiss_store()
    if store is None:
        return []
    # Fetch extra candidates to absorb post-filter shrinkage
    candidates = store.similarity_search_with_score(query, k=k * 10)
    filtered = [
        (doc, score)
        for doc, score in candidates
        if doc.metadata.get("tenant_id") == tenant_id
    ]
    return filtered[:k]
