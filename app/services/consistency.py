"""SQLite、文件系统与 pgvector 切片表的只读一致性巡检。"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.ingest_job import IngestJob
from app.models.user import User


@dataclass(frozen=True, slots=True)
class ConsistencyReport:
    missing_files: int = 0
    missing_vectors: int = 0
    extra_vectors: int = 0
    orphan_vectors: int = 0
    orphan_files: int = 0
    orphan_jobs: int = 0
    orphan_tenant_docs: int = 0  # 文档所属 tenant 已无对应用户

    @property
    def total_issues(self) -> int:
        return sum(asdict(self).values())

    def to_dict(self) -> dict[str, int]:
        result = asdict(self)
        result["total_issues"] = self.total_issues
        return result


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
        vector_rows = [
            (str(tenant_id), int(doc_id))
            for tenant_id, doc_id in (
                await db.execute(
                    select(DocumentChunk.tenant_id, DocumentChunk.doc_id)
                )
            ).all()
        ]
        valid_tenants = {row[0] for row in (await db.execute(select(User.tenant_id).distinct())).all()}

    document_keys = {(doc.tenant_id, doc.id) for doc in documents}
    referenced_files = {Path(doc.file_path).resolve() for doc in documents}
    missing_files = sum(1 for path in referenced_files if not path.is_file())

    files = await asyncio.to_thread(_storage_files)
    vector_counts: dict[tuple[str, int], int] = {}
    orphan_vectors = 0
    for key in vector_rows:
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
    orphan_tenant_docs = (
        sum(1 for doc in documents if doc.tenant_id not in valid_tenants)
        if valid_tenants
        else 0
    )
    return ConsistencyReport(
        missing_files=missing_files,
        missing_vectors=missing_vectors,
        extra_vectors=extra_vectors,
        orphan_vectors=orphan_vectors,
        orphan_files=orphan_files,
        orphan_jobs=orphan_jobs,
        orphan_tenant_docs=orphan_tenant_docs,
    )
