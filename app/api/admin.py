"""管理接口：文档与问答统计、拒答列表、人工介入列表。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AdminAuth
from app.core.database import get_session
from app.models.chat_record import ChatRecord
from app.models.document import Document

router = APIRouter(prefix="/admin", tags=["admin"])

class DocumentStats(BaseModel):
    """文档摄入统计。"""

    total: int
    indexed: int
    failed: int


class QAStats(BaseModel):
    """问答审计统计；比率范围为 0.0～1.0。"""

    total: int
    refused_rate: float
    human_rate: float


class AdminStats(BaseModel):
    """管理看板汇总。"""

    documents: DocumentStats
    qa: QAStats


class AdminQARecord(BaseModel):
    """管理列表中的单条问答记录。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: str
    user_id: str
    session_id: str
    question: str
    answer: str
    has_source: bool
    refused: bool
    need_human: bool
    created_at: datetime


@router.get("/stats", response_model=AdminStats, summary="管理统计")
async def get_stats(
    auth: AdminAuth,
    db: AsyncSession = Depends(get_session),
) -> AdminStats:
    """返回当前租户文档与问答统计。"""
    document_row = (
        await db.execute(
            select(
                func.count(Document.id),
                func.coalesce(
                    func.sum(case((Document.status == "indexed", 1), else_=0)), 0
                ),
                func.coalesce(
                    func.sum(case((Document.status == "failed", 1), else_=0)), 0
                ),
            ).where(Document.tenant_id == auth.tenant_id)
        )
    ).one()

    qa_row = (
        await db.execute(
            select(
                func.count(ChatRecord.id),
                func.coalesce(
                    func.sum(case((ChatRecord.refused.is_(True), 1), else_=0)), 0
                ),
                func.coalesce(
                    func.sum(case((ChatRecord.need_human.is_(True), 1), else_=0)),
                    0,
                ),
            ).where(ChatRecord.tenant_id == auth.tenant_id)
        )
    ).one()

    document_total, indexed, failed = map(int, document_row)
    qa_total, refused, human = map(int, qa_row)

    return AdminStats(
        documents=DocumentStats(
            total=document_total,
            indexed=indexed,
            failed=failed,
        ),
        qa=QAStats(
            total=qa_total,
            refused_rate=round(refused / qa_total, 4) if qa_total else 0.0,
            human_rate=round(human / qa_total, 4) if qa_total else 0.0,
        ),
    )


@router.get(
    "/refused",
    response_model=list[AdminQARecord],
    summary="最近拒答问题",
)
async def list_refused(
    auth: AdminAuth,
    db: AsyncSession = Depends(get_session),
) -> list[ChatRecord]:
    """返回最近 20 条知识库无答案的问答记录。"""
    result = await db.execute(
        select(ChatRecord)
        .where(
            ChatRecord.tenant_id == auth.tenant_id,
            ChatRecord.refused.is_(True),
        )
        .order_by(ChatRecord.created_at.desc(), ChatRecord.id.desc())
        .limit(20)
    )
    return list(result.scalars().all())


@router.get(
    "/human",
    response_model=list[AdminQARecord],
    summary="最近转人工问题",
)
async def list_human(
    auth: AdminAuth,
    db: AsyncSession = Depends(get_session),
) -> list[ChatRecord]:
    """返回最近 20 条命中敏感词、需要人工介入的问答记录。"""
    result = await db.execute(
        select(ChatRecord)
        .where(
            ChatRecord.tenant_id == auth.tenant_id,
            ChatRecord.need_human.is_(True),
        )
        .order_by(ChatRecord.created_at.desc(), ChatRecord.id.desc())
        .limit(20)
    )
    return list(result.scalars().all())
