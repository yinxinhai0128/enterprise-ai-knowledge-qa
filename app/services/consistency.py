"""SQLite、文件系统与 Chroma 的只读一致性巡检。"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.core.vectorstore import close_vectorstore, get_vectorstore, vectorstore_lock
from app.models.document import Document
from app.models.ingest_job import IngestJob


@dataclass(frozen=True, slots=True)
class ConsistencyReport:
    missing_files: int = 0
    missing_vectors: int = 0
    extra_vectors: int = 0
    orphan_vectors: int = 0
    orphan_files: int = 0
    orphan_jobs: int = 0

    @property
    def total_issues(self) -> int:
        return sum(asdict(self).values())

    def to_dict(self) -> dict[str, int]:
        result = asdict(self)
        result["total_issues"] = self.total_issues
        return result


def _vector_metadata() -> list[dict]:
    with vectorstore_lock():
        try:
            result = get_vectorstore()._collection.get(include=["metadatas"])
            return [dict(item or {}) for item in (result.get("metadatas") or [])]
        finally:
            close_vectorstore()


def _storage_files() -> set[Path]:
    files: set[Path] = set()
    for directory in ("quarantine", "documents"):
        root = settings.storage_dir / directory
        if root.is_dir():
            files.update(path.resolve() for path in root.rglob("*") if path.is_file())
    return files


async def inspect_consistency() -> ConsistencyReport:
    async with AsyncSessionLocal() as db:
        documents = list((await db.execute(select(Document))).scalars())
        jobs = list((await db.execute(select(IngestJob))).scalars())

    document_keys = {(doc.tenant_id, doc.id) for doc in documents}
    referenced_files = {Path(doc.file_path).resolve() for doc in documents}
    missing_files = sum(1 for path in referenced_files if not path.is_file())

    metadatas, files = await asyncio.gather(
        asyncio.to_thread(_vector_metadata),
        asyncio.to_thread(_storage_files),
    )
    vector_counts: dict[tuple[str, int], int] = {}
    orphan_vectors = 0
    for metadata in metadatas:
        try:
            key = (str(metadata["tenant_id"]), int(metadata["doc_id"]))
        except (KeyError, TypeError, ValueError):
            orphan_vectors += 1
            continue
        if key not in document_keys:
            orphan_vectors += 1
            continue
        vector_counts[key] = vector_counts.get(key, 0) + 1

    missing_vectors = 0
    extra_vectors = 0
    for document in documents:
        if document.status != "indexed":
            continue
        actual = vector_counts.get((document.tenant_id, document.id), 0)
        if actual < document.chunk_count:
            missing_vectors += document.chunk_count - actual
        elif actual > document.chunk_count:
            extra_vectors += actual - document.chunk_count

    document_ids = {doc.id for doc in documents}
    orphan_jobs = sum(1 for job in jobs if job.document_id not in document_ids)
    orphan_files = len(files - referenced_files)
    return ConsistencyReport(
        missing_files=missing_files,
        missing_vectors=missing_vectors,
        extra_vectors=extra_vectors,
        orphan_vectors=orphan_vectors,
        orphan_files=orphan_files,
        orphan_jobs=orphan_jobs,
    )
