"""文档接口：上传、列表、详情。

上传流程：落盘 storage/ -> 写 DB（uploading）-> BackgroundTasks 异步索引。
索引在后台独立会话中推进状态：parsing -> indexed / failed。
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

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
from app.models.document import Document
from app.schemas.document import DocumentOut
from app.services.ingest import ingest_document

router = APIRouter(prefix="/documents", tags=["documents"])

# 允许的扩展名与体积上限
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".txt"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
_CHUNK = 1024 * 1024  # 流式落盘块大小 1 MB


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
    auth: UserAuth,
    db: AsyncSession = Depends(get_session),
) -> Document:
    """接收单个文件，校验、落盘、登记，并异步触发索引。"""
    # 取纯文件名，防路径穿越
    original_name = Path(file.filename or "").name
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型：{ext or '未知'}，仅支持 pdf/docx/xlsx/txt",
        )

    # 文件名加 uuid 前缀，避免冲突
    tenant_storage = settings.storage_dir / "uploads" / auth.tenant_id
    tenant_storage.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}_{original_name}"
    dest = tenant_storage / stored_name

    # 流式落盘，边写边校验大小
    size = 0
    try:
        with dest.open("wb") as buffer:
            while chunk := await file.read(_CHUNK):
                size += len(chunk)
                if size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="文件超过 50MB 上限",
                    )
                buffer.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="空文件"
        )

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
