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


def add_documents_to_faiss(documents: list[Document]) -> None:
    """Append documents to the FAISS store, creating it if needed. Thread-safe.

    Uses chunk_id from metadata as the explicit FAISS vector ID so that
    re-indexing the same content is idempotent (delete-then-add).
    """
    global _store
    with _lock:
        from app.core.llm import init_embeddings
        embeddings = init_embeddings()
        texts = [doc.page_content for doc in documents]
        metadatas = [doc.metadata for doc in documents]
        ids = [str(doc.metadata.get("chunk_id")) for doc in documents]
        index_file = FAISS_INDEX_DIR / "index.faiss"
        if _store is None:
            if index_file.exists():
                _store = LangchainFAISS.load_local(
                    str(FAISS_INDEX_DIR),
                    embeddings,
                    allow_dangerous_deserialization=True,
                )
            else:
                FAISS_INDEX_DIR.mkdir(parents=True, exist_ok=True)
                _store = LangchainFAISS.from_texts(
                    texts, embeddings, metadatas=metadatas, ids=ids
                )
                _store.save_local(str(FAISS_INDEX_DIR))
                return
        # Idempotency: remove existing vectors with same chunk_ids before re-adding
        existing = [id_ for id_ in ids if id_ in _store.docstore._dict]
        if existing:
            _store.delete(existing)
        _store.add_texts(texts, metadatas=metadatas, ids=ids)
        _store.save_local(str(FAISS_INDEX_DIR))


def delete_documents_from_faiss(tenant_id: str, doc_id: int) -> int:
    """Delete all FAISS vectors for the given document. Returns count deleted. Thread-safe."""
    global _store
    with _lock:
        if _store is None:
            index_file = FAISS_INDEX_DIR / "index.faiss"
            if not index_file.exists():
                return 0
            from app.core.llm import init_embeddings
            _store = LangchainFAISS.load_local(
                str(FAISS_INDEX_DIR),
                init_embeddings(),
                allow_dangerous_deserialization=True,
            )
        ids_to_delete = [
            vid
            for vid, doc in _store.docstore._dict.items()
            if str(doc.metadata.get("tenant_id")) == str(tenant_id)
            and int(doc.metadata.get("doc_id", -1)) == int(doc_id)
        ]
        if not ids_to_delete:
            return 0
        _store.delete(ids_to_delete)
        _store.save_local(str(FAISS_INDEX_DIR))
        return len(ids_to_delete)
