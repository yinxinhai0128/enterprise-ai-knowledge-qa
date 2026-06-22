"""持久化摄入 Job：创建、租约领取、心跳、执行、重试与恢复。"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from loguru import logger
from sqlalchemy import and_, or_, select, text, update

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.models.document import Document
from app.models.ingest_job import IngestJob
from app.services.ingest import IngestResult, ingest_document
from app.services.vector_ops import delete_document_vectors

ACTIVE_JOB_STATUSES = ("pending", "running", "retry")
AfterIngestHook = Callable[[IngestJob, Document, IngestResult], Awaitable[None]]
BeforeFinalizeHook = Callable[[IngestJob, Document, IngestResult], Awaitable[None]]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_worker_id() -> str:
    return f"worker-{uuid4().hex}"


def create_ingest_job(
    document: Document,
    *,
    job_type: str = "ingest",
) -> IngestJob:
    """构造待提交 Job；调用方与 Document 在同一事务写入。"""
    return IngestJob(
        document_id=document.id,
        tenant_id=document.tenant_id,
        job_type=job_type,
        status="pending",
        attempt=0,
        max_attempts=settings.ingest_job_max_attempts,
        next_retry_at=utcnow(),
    )


def _repair_promoted_path(document: Document) -> None:
    """崩溃可能发生在文件归档后、DB 路径提交前；恢复确定性归档路径。"""
    current = Path(document.file_path)
    if current.is_file():
        return
    promoted = settings.storage_dir / "documents" / document.tenant_id / current.name
    if promoted.is_file():
        document.file_path = str(promoted)


async def recover_stale_ingest_state() -> dict[str, int]:
    """回收过期租约，并为无活动 Job 的 uploading/parsing 文档补任务。"""
    now = utcnow()
    recovered_jobs = 0
    repaired_documents = 0
    async with AsyncSessionLocal() as db:
        if db.bind is not None and db.bind.dialect.name == "sqlite":
            await db.execute(text("BEGIN IMMEDIATE"))

        expired = list(
            (
                await db.execute(
                    select(IngestJob).where(
                        IngestJob.status == "running",
                        IngestJob.lease_expires_at.is_not(None),
                        IngestJob.lease_expires_at <= now,
                    )
                )
            ).scalars()
        )
        for job in expired:
            job.lease_owner = None
            job.lease_expires_at = None
            if job.attempt >= job.max_attempts:
                job.status = "failed"
                job.error_msg = "任务租约过期且已达到最大重试次数"
            else:
                job.status = "retry"
                job.next_retry_at = now
                job.error_msg = "任务租约过期，等待恢复"
            document = await db.get(Document, job.document_id)
            if document is not None:
                _repair_promoted_path(document)
                document.status = "failed" if job.status == "failed" else "uploading"
                document.error_msg = job.error_msg
            recovered_jobs += 1

        stuck_documents = list(
            (
                await db.execute(
                    select(Document).where(Document.status.in_(("uploading", "parsing")))
                )
            ).scalars()
        )
        for document in stuck_documents:
            _repair_promoted_path(document)
            active_job = (
                await db.execute(
                    select(IngestJob.id).where(
                        IngestJob.document_id == document.id,
                        IngestJob.status.in_(ACTIVE_JOB_STATUSES),
                    )
                )
            ).scalar_one_or_none()
            if active_job is not None:
                continue
            if not Path(document.file_path).is_file():
                document.status = "failed"
                document.error_msg = "源文件不存在，无法恢复摄入"
            else:
                db.add(create_ingest_job(document))
                document.status = "uploading"
                document.error_msg = None
            repaired_documents += 1

        await db.commit()
    return {"jobs": recovered_jobs, "documents": repaired_documents}


async def claim_next_ingest_job(worker_id: str) -> int | None:
    """原子领取一个到期任务并写入租约。"""
    now = utcnow()
    lease_expires = now + timedelta(seconds=settings.ingest_job_lease_seconds)
    async with AsyncSessionLocal() as db:
        if db.bind is not None and db.bind.dialect.name == "sqlite":
            await db.execute(text("BEGIN IMMEDIATE"))
        eligible = or_(
            and_(
                IngestJob.status.in_(("pending", "retry")),
                or_(
                    IngestJob.next_retry_at.is_(None),
                    IngestJob.next_retry_at <= now,
                ),
            ),
            and_(
                IngestJob.status == "running",
                IngestJob.lease_expires_at.is_not(None),
                IngestJob.lease_expires_at <= now,
            ),
        )
        job = (
            await db.execute(
                select(IngestJob)
                .where(eligible, IngestJob.attempt < IngestJob.max_attempts)
                .order_by(IngestJob.created_at, IngestJob.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if job is None:
            await db.rollback()
            return None
        job.status = "running"
        job.attempt += 1
        job.lease_owner = worker_id
        job.lease_expires_at = lease_expires
        job.error_msg = None
        document = await db.get(Document, job.document_id)
        if document is None:
            job.status = "failed"
            job.error_msg = "文档记录不存在"
            job.lease_owner = None
            job.lease_expires_at = None
            await db.commit()
            return None
        document.status = "parsing"
        document.error_msg = None
        await db.commit()
        return job.id


async def _lease_heartbeat(job_id: int, worker_id: str) -> None:
    interval = max(5.0, settings.ingest_job_lease_seconds / 3)
    try:
        while True:
            await asyncio.sleep(interval)
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    update(IngestJob)
                    .where(
                        IngestJob.id == job_id,
                        IngestJob.status == "running",
                        IngestJob.lease_owner == worker_id,
                    )
                    .values(
                        lease_expires_at=utcnow()
                        + timedelta(seconds=settings.ingest_job_lease_seconds)
                    )
                )
                await db.commit()
                if result.rowcount == 0:
                    return
    except asyncio.CancelledError:
        raise


async def _mark_job_failure(
    job_id: int,
    worker_id: str,
    result: IngestResult,
) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(IngestJob, job_id)
        if job is None or job.lease_owner != worker_id or job.status != "running":
            return
        document = await db.get(Document, job.document_id)
        if result.trusted_path is not None and document is not None:
            document.file_path = result.trusted_path
        job.lease_owner = None
        job.lease_expires_at = None
        job.error_msg = result.error_msg or "文档摄入失败"
        if job.attempt >= job.max_attempts:
            job.status = "failed"
            job.next_retry_at = None
            if document is not None:
                document.status = "failed"
        else:
            job.status = "retry"
            delay = settings.ingest_job_retry_base_seconds * (2 ** (job.attempt - 1))
            job.next_retry_at = utcnow() + timedelta(seconds=delay)
            if document is not None:
                document.status = "uploading"
        if document is not None:
            document.error_msg = job.error_msg
        await db.commit()


async def execute_claimed_ingest_job(
    job_id: int,
    worker_id: str,
    *,
    after_ingest_hook: AfterIngestHook | None = None,
    before_finalize_hook: BeforeFinalizeHook | None = None,
) -> None:
    """执行已领取任务；意外异常保留租约以模拟/支持崩溃恢复。"""
    async with AsyncSessionLocal() as db:
        job = await db.get(IngestJob, job_id)
        if job is None or job.status != "running" or job.lease_owner != worker_id:
            return
        document = await db.get(Document, job.document_id)
        if document is None:
            return
        # 分离 ORM 生命周期，后续不持有长事务。
        job_type = job.job_type
        tenant_id = document.tenant_id
        document_id = document.id
        file_path = document.file_path
        filename = document.filename
        uploaded_by = document.uploaded_by

    if job_type == "reindex":
        await asyncio.to_thread(delete_document_vectors, tenant_id, document_id)

    heartbeat = asyncio.create_task(_lease_heartbeat(job_id, worker_id))
    try:
        result = await ingest_document(
            doc_id=document_id,
            file_path=file_path,
            source=filename,
            tenant_id=tenant_id,
            uploaded_by=uploaded_by,
        )
        if after_ingest_hook is not None:
            async with AsyncSessionLocal() as hook_db:
                hook_job = await hook_db.get(IngestJob, job_id)
                hook_document = await hook_db.get(Document, document_id)
                if hook_job is not None and hook_document is not None:
                    await after_ingest_hook(hook_job, hook_document, result)
    finally:
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass

    if not result.success:
        await asyncio.to_thread(delete_document_vectors, tenant_id, document_id)
        await _mark_job_failure(job_id, worker_id, result)
        return

    try:
        async with AsyncSessionLocal() as db:
            job = await db.get(IngestJob, job_id)
            document = await db.get(Document, document_id)
            if job is None or document is None:
                raise RuntimeError("finalize target missing")
            if job.status == "cancelled":
                await db.rollback()
                await asyncio.to_thread(delete_document_vectors, tenant_id, document_id)
                return
            if job.status != "running" or job.lease_owner != worker_id:
                await db.rollback()
                return
            if before_finalize_hook is not None:
                await before_finalize_hook(job, document, result)
            if result.trusted_path is not None:
                document.file_path = result.trusted_path
            document.status = "indexed"
            document.chunk_count = result.chunk_count
            document.error_msg = None
            job.status = "succeeded"
            job.next_retry_at = None
            job.lease_owner = None
            job.lease_expires_at = None
            job.error_msg = None
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("摄入完成但数据库状态提交失败 job_id={}", job_id)
        await asyncio.to_thread(delete_document_vectors, tenant_id, document_id)
        await _mark_job_failure(
            job_id,
            worker_id,
            IngestResult(
                success=False,
                error_msg="状态提交失败，已补偿删除向量",
                trusted_path=result.trusted_path,
            ),
        )


async def run_worker_once(
    worker_id: str | None = None,
    *,
    after_ingest_hook: AfterIngestHook | None = None,
    before_finalize_hook: BeforeFinalizeHook | None = None,
) -> bool:
    """领取并执行一个任务；返回是否处理了任务。"""
    owner = worker_id or new_worker_id()
    job_id = await claim_next_ingest_job(owner)
    if job_id is None:
        return False
    await execute_claimed_ingest_job(
        job_id,
        owner,
        after_ingest_hook=after_ingest_hook,
        before_finalize_hook=before_finalize_hook,
    )
    return True
