"""文档接口：上传、列表、详情。

上传流程：落盘 storage/ -> 写 DB（uploading）-> BackgroundTasks 异步索引。
索引在后台独立会话中推进状态：parsing -> indexed / failed。
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

import anyio
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import UserAuth
from app.core.database import get_session
from app.core.limits import UploadAuth
from app.core.process_pool import run_in_parser_process
from app.models.document import Document
from app.models.ingest_job import IngestJob
from app.schemas.document import DocumentOut, IngestJobOut
from app.services.file_security import (
    FileValidationError,
    current_file_validation_limits,
    normalize_filename,
    scan_quarantined_file,
    validate_uploaded_file,
)
from app.services.ingest_jobs import ACTIVE_JOB_STATUSES, create_ingest_job, utcnow
from app.services.vector_ops import delete_document_vectors

router = APIRouter(prefix="/documents", tags=["documents"])


async def _tenant_document(db: AsyncSession, doc_id: int, tenant_id: str) -> Document:
    document = (
        await db.execute(
            select(Document).where(
                Document.id == doc_id,
                Document.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    return document


@router.post(
    "/upload",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    summary="上传文档并异步索引",
)
async def upload_document(
    file: UploadFile,
    response: Response,
    auth: UploadAuth,
    db: AsyncSession = Depends(get_session),
) -> Document:
    """接收单个文件，校验、落盘、登记，并异步触发索引。"""
    try:
        original_name, ext = normalize_filename(file.filename)
    except FileValidationError as exc:
        await file.close()
        raise HTTPException(status_code=exc.status_code, detail=exc.safe_message) from exc

    # 未完成格式校验、恶意软件扫描和解析前，只能进入隔离目录。
    tenant_storage = settings.storage_dir / "quarantine" / auth.tenant_id
    await asyncio.to_thread(tenant_storage.mkdir, parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}_{original_name}"
    dest = tenant_storage / stored_name

    size = 0
    file_digest = hashlib.sha256()
    try:
        async with asyncio.timeout(settings.upload_write_timeout_seconds):
            async with await anyio.open_file(dest, "wb") as buffer:
                while chunk := await file.read(settings.upload_chunk_bytes):
                    size += len(chunk)
                    if size > settings.max_file_size_bytes:
                        raise FileValidationError(
                            f"文件超过 {settings.max_file_size_bytes} 字节上限",
                            status.HTTP_413_CONTENT_TOO_LARGE,
                        )
                    file_digest.update(chunk)
                    await buffer.write(chunk)
        if size == 0:
            raise FileValidationError("空文件")
        try:
            await run_in_parser_process(
                validate_uploaded_file,
                dest,
                ext,
                file.content_type,
                current_file_validation_limits(),
                timeout=settings.file_validation_timeout_seconds,
            )
            await asyncio.wait_for(
                scan_quarantined_file(dest),
                timeout=settings.file_validation_timeout_seconds,
            )
        except TimeoutError as exc:
            raise FileValidationError("文件安全校验超时", 408) from exc
    except FileValidationError as exc:
        await asyncio.to_thread(dest.unlink, missing_ok=True)
        raise HTTPException(status_code=exc.status_code, detail=exc.safe_message) from exc
    except TimeoutError as exc:
        await asyncio.to_thread(dest.unlink, missing_ok=True)
        raise HTTPException(status_code=408, detail="文件写入超时") from exc
    except OSError as exc:
        await asyncio.to_thread(dest.unlink, missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail="文件写入失败",
        ) from exc
    finally:
        await file.close()

    content_sha256 = file_digest.hexdigest()
    existing = (
        await db.execute(
            select(Document).where(
                Document.tenant_id == auth.tenant_id,
                Document.content_sha256 == content_sha256,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        await asyncio.to_thread(dest.unlink, missing_ok=True)
        response.headers["X-Idempotent-Replay"] = "true"
        return existing

    # Document 与 Job 同事务提交，API 进程不执行摄入。
    doc = Document(
        tenant_id=auth.tenant_id,
        uploaded_by=auth.user_id,
        content_sha256=content_sha256,
        filename=original_name,
        file_path=str(dest),
        status="uploading",
    )
    try:
        db.add(doc)
        await db.flush()
        db.add(create_ingest_job(doc))
        await db.commit()
        await db.refresh(doc)
    except IntegrityError:
        await db.rollback()
        await asyncio.to_thread(dest.unlink, missing_ok=True)
        existing = (
            await db.execute(
                select(Document).where(
                    Document.tenant_id == auth.tenant_id,
                    Document.content_sha256 == content_sha256,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise HTTPException(status_code=409, detail="重复上传冲突")
        response.headers["X-Idempotent-Replay"] = "true"
        return existing
    except SQLAlchemyError as exc:
        await db.rollback()
        await asyncio.to_thread(dest.unlink, missing_ok=True)
        raise HTTPException(status_code=503, detail="摄入任务创建失败") from exc
    logger.info(
        "已接收文档 tenant={} user={} doc_id={} filename={}",
        auth.tenant_id,
        auth.user_id,
        doc.id,
        original_name,
    )
    return doc


@router.get("", response_model=list[DocumentOut], summary="文档列表")
async def list_documents(
    auth: UserAuth,
    db: AsyncSession = Depends(get_session),
) -> list[Document]:
    """返回当前租户文档，按创建时间倒序。"""
    result = await db.execute(
        select(Document)
        .where(Document.tenant_id == auth.tenant_id)
        .order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{doc_id}", response_model=DocumentOut, summary="文档详情")
async def get_document(
    doc_id: int,
    auth: UserAuth,
    db: AsyncSession = Depends(get_session),
) -> Document:
    """按 id 返回当前租户内的单个文档。"""
    doc = (
        await db.execute(
            select(Document).where(
                Document.id == doc_id,
                Document.tenant_id == auth.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在"
        )
    return doc


@router.get(
    "/{doc_id}/jobs",
    response_model=list[IngestJobOut],
    summary="文档摄入任务",
)
async def list_document_jobs(
    doc_id: int,
    auth: UserAuth,
    db: AsyncSession = Depends(get_session),
) -> list[IngestJob]:
    await _tenant_document(db, doc_id, auth.tenant_id)
    jobs = await db.execute(
        select(IngestJob)
        .where(
            IngestJob.document_id == doc_id,
            IngestJob.tenant_id == auth.tenant_id,
        )
        .order_by(IngestJob.created_at.desc(), IngestJob.id.desc())
    )
    return list(jobs.scalars())


@router.post(
    "/{doc_id}/retry",
    response_model=IngestJobOut,
    summary="重试失败任务",
)
async def retry_document_ingest(
    doc_id: int,
    auth: UploadAuth,
    db: AsyncSession = Depends(get_session),
) -> IngestJob:
    document = await _tenant_document(db, doc_id, auth.tenant_id)
    job = (
        await db.execute(
            select(IngestJob)
            .where(
                IngestJob.document_id == doc_id,
                IngestJob.tenant_id == auth.tenant_id,
            )
            .order_by(IngestJob.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if job is None:
        job = create_ingest_job(document)
        db.add(job)
    elif job.status in ACTIVE_JOB_STATUSES:
        raise HTTPException(status_code=409, detail="任务仍在处理中")
    elif job.status == "succeeded":
        raise HTTPException(status_code=409, detail="任务已成功，请使用重新索引")
    else:
        job.status = "pending"
        job.attempt = 0
        job.max_attempts = settings.ingest_job_max_attempts
        job.next_retry_at = utcnow()
        job.lease_owner = None
        job.lease_expires_at = None
        job.error_msg = None
    document.status = "uploading"
    document.error_msg = None
    await db.commit()
    await db.refresh(job)
    return job


@router.post(
    "/{doc_id}/cancel",
    response_model=IngestJobOut,
    summary="取消摄入任务",
)
async def cancel_document_ingest(
    doc_id: int,
    auth: UploadAuth,
    db: AsyncSession = Depends(get_session),
) -> IngestJob:
    document = await _tenant_document(db, doc_id, auth.tenant_id)
    job = (
        await db.execute(
            select(IngestJob)
            .where(
                IngestJob.document_id == doc_id,
                IngestJob.tenant_id == auth.tenant_id,
                IngestJob.status.in_(ACTIVE_JOB_STATUSES),
            )
            .order_by(IngestJob.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=409, detail="没有可取消的任务")
    job.status = "cancelled"
    job.next_retry_at = None
    job.lease_owner = None
    job.lease_expires_at = None
    job.error_msg = "任务已由用户取消"
    document.status = "failed"
    document.error_msg = job.error_msg
    await db.commit()
    await db.refresh(job)
    return job


@router.post(
    "/{doc_id}/reindex",
    response_model=IngestJobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="重新索引文档",
)
async def reindex_document(
    doc_id: int,
    auth: UploadAuth,
    db: AsyncSession = Depends(get_session),
) -> IngestJob:
    document = await _tenant_document(db, doc_id, auth.tenant_id)
    active = (
        await db.execute(
            select(IngestJob.id).where(
                IngestJob.document_id == doc_id,
                IngestJob.status.in_(ACTIVE_JOB_STATUSES),
            )
        )
    ).scalar_one_or_none()
    if active is not None:
        raise HTTPException(status_code=409, detail="已有任务正在处理")
    if not Path(document.file_path).is_file():
        raise HTTPException(status_code=409, detail="源文件不存在，无法重新索引")
    job = create_ingest_job(document, job_type="reindex")
    db.add(job)
    document.status = "uploading"
    document.error_msg = None
    await db.commit()
    await db.refresh(job)
    return job


@router.delete(
    "/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除文档及全部数据",
)
async def delete_document(
    doc_id: int,
    auth: UploadAuth,
    db: AsyncSession = Depends(get_session),
) -> Response:
    document = await _tenant_document(db, doc_id, auth.tenant_id)
    jobs = list(
        (
            await db.execute(
                select(IngestJob).where(IngestJob.document_id == document.id)
            )
        ).scalars()
    )
    for job in jobs:
        if job.status in ACTIVE_JOB_STATUSES:
            job.status = "cancelled"
            job.lease_owner = None
            job.lease_expires_at = None
            job.error_msg = "文档删除，任务取消"
    await db.commit()

    try:
        await asyncio.to_thread(
            delete_document_vectors,
            document.tenant_id,
            document.id,
        )
        await asyncio.to_thread(Path(document.file_path).unlink, missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.exception("文档三层删除失败 doc_id={}", document.id)
        raise HTTPException(status_code=503, detail="文档存储清理失败") from exc

    for job in jobs:
        await db.delete(job)
    await db.delete(document)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
