"""文档接口：上传、列表、详情。

上传流程：落盘 storage/ -> 写 DB（uploading）-> BackgroundTasks 异步索引。
索引在后台独立会话中推进状态：parsing -> indexed / failed。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import anyio
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    UploadFile,
    status,
)
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import UserAuth
from app.core.database import AsyncSessionLocal, get_session
from app.core.limits import UploadAuth
from app.core.process_pool import run_in_parser_process
from app.models.document import Document
from app.schemas.document import DocumentOut
from app.services.ingest import ingest_document
from app.services.file_security import (
    FileValidationError,
    current_file_validation_limits,
    normalize_filename,
    scan_quarantined_file,
    validate_uploaded_file,
)

router = APIRouter(prefix="/documents", tags=["documents"])

async def _run_ingest(
    doc_id: int,
    file_path: str,
    source: str,
    tenant_id: str,
    uploaded_by: str,
) -> None:
    """后台任务：推进状态机并回填结果（独立 DB 会话）。"""
    async with AsyncSessionLocal() as db:
        doc = (
            await db.execute(
                select(Document).where(
                    Document.id == doc_id,
                    Document.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if doc is None:
            logger.warning("后台索引找不到文档 doc_id={}", doc_id)
            return

        doc.status = "parsing"
        await db.commit()

        result = await ingest_document(
            doc_id=doc_id,
            file_path=file_path,
            source=source,
            tenant_id=tenant_id,
            uploaded_by=uploaded_by,
        )

        if result.trusted_path is not None:
            doc.file_path = result.trusted_path

        if result.success:
            doc.status = "indexed"
            doc.chunk_count = result.chunk_count
            doc.error_msg = None
        else:
            doc.status = "failed"
            doc.error_msg = result.error_msg
        await db.commit()


@router.post(
    "/upload",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    summary="上传文档并异步索引",
)
async def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
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

    # 登记 DB
    doc = Document(
        tenant_id=auth.tenant_id,
        uploaded_by=auth.user_id,
        filename=original_name,
        file_path=str(dest),
        status="uploading",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # 异步索引
    background_tasks.add_task(
        _run_ingest,
        doc.id,
        str(dest),
        original_name,
        auth.tenant_id,
        auth.user_id,
    )
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
