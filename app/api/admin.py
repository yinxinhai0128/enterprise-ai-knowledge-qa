"""管理接口：文档与问答统计、拒答列表、人工介入列表。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.limits import LimitedAdminAuth
from app.models.chat_record import ChatRecord
from app.models.document import Document
from app.models.human_task import HUMAN_TASK_STATUS, HumanTask, HumanTaskEvent
from app.services.consistency import ConsistencyReport, inspect_consistency

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
    tool_used: bool
    sources: list[dict]
    trace_id: str | None
    model: str | None
    total_tokens: int
    latency_ms: float
    audit_status: str
    audit_error: str | None
    created_at: datetime


class HumanTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chat_record_id: int
    tenant_id: str
    user_id: str
    session_id: str
    category: str
    rule_id: str
    rule_version: str
    reason: str
    status: str
    assigned_to: str | None
    claimed_at: datetime | None
    completed_at: datetime | None
    resolution: str | None
    created_at: datetime
    updated_at: datetime


class HumanTaskEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    actor_user_id: str
    action: str
    from_status: str | None
    to_status: str
    note: str | None
    created_at: datetime


class CompleteHumanTaskRequest(BaseModel):
    resolution: str = Field(min_length=1, max_length=4000)


@router.get("/stats", response_model=AdminStats, summary="管理统计")
async def get_stats(
    auth: LimitedAdminAuth,
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
    auth: LimitedAdminAuth,
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
    auth: LimitedAdminAuth,
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


@router.get(
    "/human-tasks",
    response_model=list[HumanTaskOut],
    summary="人工任务队列",
)
async def list_human_tasks(
    auth: LimitedAdminAuth,
    task_status: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_session),
) -> list[HumanTask]:
    if task_status is not None and task_status not in HUMAN_TASK_STATUS:
        raise HTTPException(status_code=422, detail="人工任务状态无效")
    statement = select(HumanTask).where(HumanTask.tenant_id == auth.tenant_id)
    if task_status is not None:
        statement = statement.where(HumanTask.status == task_status)
    result = await db.execute(
        statement.order_by(HumanTask.created_at.desc(), HumanTask.id.desc()).limit(100)
    )
    return list(result.scalars())


@router.post(
    "/human-tasks/{task_id}/claim",
    response_model=HumanTaskOut,
    summary="领取人工任务",
)
async def claim_human_task(
    task_id: int,
    auth: LimitedAdminAuth,
    db: AsyncSession = Depends(get_session),
) -> HumanTask:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(HumanTask)
        .where(
            HumanTask.id == task_id,
            HumanTask.tenant_id == auth.tenant_id,
            HumanTask.status == "pending",
        )
        .values(status="claimed", assigned_to=auth.user_id, claimed_at=now)
    )
    if getattr(result, "rowcount", 0) != 1:
        task = await db.get(HumanTask, task_id)
        if task is None or task.tenant_id != auth.tenant_id:
            raise HTTPException(status_code=404, detail="人工任务不存在")
        raise HTTPException(status_code=409, detail="人工任务已被领取或已结束")
    db.add(
        HumanTaskEvent(
            task_id=task_id,
            tenant_id=auth.tenant_id,
            actor_user_id=auth.user_id,
            action="claimed",
            from_status="pending",
            to_status="claimed",
        )
    )
    await db.commit()
    task = await db.get(HumanTask, task_id)
    if task is None:  # pragma: no cover - committed row disappearing is an infrastructure fault
        raise HTTPException(status_code=500, detail="人工任务状态读取失败")
    return task


@router.post(
    "/human-tasks/{task_id}/complete",
    response_model=HumanTaskOut,
    summary="完成人工任务",
)
async def complete_human_task(
    task_id: int,
    payload: CompleteHumanTaskRequest,
    auth: LimitedAdminAuth,
    db: AsyncSession = Depends(get_session),
) -> HumanTask:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(HumanTask)
        .where(
            HumanTask.id == task_id,
            HumanTask.tenant_id == auth.tenant_id,
            HumanTask.status == "claimed",
            HumanTask.assigned_to == auth.user_id,
        )
        .values(
            status="completed",
            completed_at=now,
            resolution=payload.resolution,
        )
    )
    if getattr(result, "rowcount", 0) != 1:
        task = await db.get(HumanTask, task_id)
        if task is None or task.tenant_id != auth.tenant_id:
            raise HTTPException(status_code=404, detail="人工任务不存在")
        raise HTTPException(status_code=409, detail="任务未由当前管理员领取或已结束")
    db.add(
        HumanTaskEvent(
            task_id=task_id,
            tenant_id=auth.tenant_id,
            actor_user_id=auth.user_id,
            action="completed",
            from_status="claimed",
            to_status="completed",
            note=payload.resolution,
        )
    )
    await db.commit()
    task = await db.get(HumanTask, task_id)
    if task is None:  # pragma: no cover - committed row disappearing is an infrastructure fault
        raise HTTPException(status_code=500, detail="人工任务状态读取失败")
    return task


@router.get(
    "/human-tasks/{task_id}/events",
    response_model=list[HumanTaskEventOut],
    summary="人工任务审计事件",
)
async def list_human_task_events(
    task_id: int,
    auth: LimitedAdminAuth,
    db: AsyncSession = Depends(get_session),
) -> list[HumanTaskEvent]:
    task = await db.get(HumanTask, task_id)
    if task is None or task.tenant_id != auth.tenant_id:
        raise HTTPException(status_code=404, detail="人工任务不存在")
    result = await db.execute(
        select(HumanTaskEvent)
        .where(
            HumanTaskEvent.task_id == task_id,
            HumanTaskEvent.tenant_id == auth.tenant_id,
        )
        .order_by(HumanTaskEvent.id)
    )
    return list(result.scalars())


@router.get(
    "/audits/pending",
    response_model=list[AdminQARecord],
    summary="待补偿审计记录",
)
async def list_pending_audits(
    auth: LimitedAdminAuth,
    db: AsyncSession = Depends(get_session),
) -> list[ChatRecord]:
    result = await db.execute(
        select(ChatRecord)
        .where(
            ChatRecord.tenant_id == auth.tenant_id,
            ChatRecord.audit_status == "pending",
        )
        .order_by(ChatRecord.created_at, ChatRecord.id)
        .limit(100)
    )
    return list(result.scalars())


@router.get(
    "/consistency",
    response_model=dict,
    summary="SQLite / 文件系统 / Chroma 一致性巡检",
)
async def consistency_check(auth: LimitedAdminAuth) -> dict:
    """只读一致性检查：对比 SQLite 文档记录、磁盘文件、向量库是否一致。"""
    report: ConsistencyReport = await inspect_consistency()
    return report.to_dict()
