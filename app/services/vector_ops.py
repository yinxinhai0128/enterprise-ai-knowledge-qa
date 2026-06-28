"""FAISS-based document vector operations."""
from __future__ import annotations

from app.core.faiss_store import delete_documents_from_faiss, get_faiss_store


def document_vector_ids(tenant_id: str, doc_id: int) -> list[str]:
    """Return all vector IDs for the given document."""
    store = get_faiss_store()
    if store is None:
        return []
    return [
        vid
        for vid, doc in store.docstore._dict.items()
        if str(doc.metadata.get("tenant_id")) == str(tenant_id)
        and int(doc.metadata.get("doc_id", -1)) == int(doc_id)
    ]


def delete_document_vectors(tenant_id: str, doc_id: int) -> int:
    """Idempotently delete all vectors for a document. Returns count deleted."""
    return delete_documents_from_faiss(tenant_id, doc_id)
