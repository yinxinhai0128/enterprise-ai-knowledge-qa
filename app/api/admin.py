"""管理接口：文档与问答统计、拒答列表、人工介入列表、用户管理。"""
from __future__ import annotations

import bcrypt as _bcrypt
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.limits import LimitedAdminAuth
from app.models.chat_record import ChatRecord
from app.models.document import Document
from app.models.human_task import HUMAN_TASK_STATUS, HumanTask, HumanTaskEvent
from app.models.user import User
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


class NegativeFeedback(BaseModel):
    id: int
    user_id: str
    question: str
    comment: str | None
    created_at: datetime

class UserOut(BaseModel):
    """用户列表条目。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    tenant_id: str
    roles: list[str]
    is_active: bool
    created_at: datetime


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._@-]+$")
    password: str = Field(min_length=8, max_length=256)
    roles: list[str] = Field(default_factory=lambda: ["user"])


class FeedbackStats(BaseModel):
    total_rated: int
    up_count: int
    down_count: int
    approval_rate: float
    recent_negatives: list[NegativeFeedback]

class DailyCount(BaseModel):
    date: str
    total: int
    refused: int
    human: int

class ActiveUser(BaseModel):
    user_id: str
    count: int

class TopDocument(BaseModel):
    doc_name: str
    cite_count: int

class UsageReport(BaseModel):
    days: int
    total: int
    today: int
    refused_rate: float
    daily: list[DailyCount]
    top_users: list[ActiveUser]
    top_docs: list[TopDocument]


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
    "/records",
    response_model=list[AdminQARecord],
    summary="最近问答记录（全量审计）",
)
async def list_records(
    auth: LimitedAdminAuth,
    db: AsyncSession = Depends(get_session),
    limit: int = 50,
) -> list[ChatRecord]:
    """返回最近 N 条问答记录（不限拒答状态），用于审计日志。"""
    limit = max(1, min(limit, 200))
    result = await db.execute(
        select(ChatRecord)
        .where(ChatRecord.tenant_id == auth.tenant_id)
        .order_by(ChatRecord.created_at.desc(), ChatRecord.id.desc())
        .limit(limit)
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
    summary="SQLite / 文件系统 / FAISS 一致性巡检",
)
async def consistency_check(auth: LimitedAdminAuth) -> dict:
    """只读一致性检查：对比 SQLite 文档记录、磁盘文件、向量库是否一致。"""
    report: ConsistencyReport = await inspect_consistency()
    return report.to_dict()


@router.get("/feedback-stats", response_model=FeedbackStats, summary="反馈统计")
async def get_feedback_stats(
    auth: LimitedAdminAuth,
    db: AsyncSession = Depends(get_session),
) -> FeedbackStats:
    # 统计
    rows = (await db.execute(
        select(
            func.count(ChatRecord.id),
            func.coalesce(func.sum(case((ChatRecord.feedback_rating == "up", 1), else_=0)), 0),
            func.coalesce(func.sum(case((ChatRecord.feedback_rating == "down", 1), else_=0)), 0),
        ).where(
            ChatRecord.tenant_id == auth.tenant_id,
            ChatRecord.feedback_rating.isnot(None),
        )
    )).one()
    total_rated, up_count, down_count = int(rows[0]), int(rows[1]), int(rows[2])
    approval_rate = round(up_count / (up_count + down_count), 4) if (up_count + down_count) > 0 else 0.0

    # 最近差评
    negatives_result = await db.execute(
        select(ChatRecord)
        .where(
            ChatRecord.tenant_id == auth.tenant_id,
            ChatRecord.feedback_rating == "down",
        )
        .order_by(ChatRecord.created_at.desc(), ChatRecord.id.desc())
        .limit(20)
    )
    negatives = list(negatives_result.scalars().all())

    def mask_uid(uid: str) -> str:
        return f"{uid[:4]}***" if len(uid) > 4 else uid

    return FeedbackStats(
        total_rated=total_rated,
        up_count=up_count,
        down_count=down_count,
        approval_rate=approval_rate,
        recent_negatives=[
            NegativeFeedback(
                id=r.id,
                user_id=mask_uid(r.user_id),
                question=r.question[:100],
                comment=r.feedback_comment,
                created_at=r.created_at,
            )
            for r in negatives
        ],
    )


@router.get("/reports/usage", response_model=UsageReport, summary="使用量报表")
async def get_usage_report(
    auth: LimitedAdminAuth,
    days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_session),
) -> UsageReport:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    # 取该时段所有记录（只取需要的列）
    result = await db.execute(
        select(
            ChatRecord.user_id,
            ChatRecord.refused,
            ChatRecord.need_human,
            ChatRecord.sources,
            ChatRecord.created_at,
        )
        .where(
            ChatRecord.tenant_id == auth.tenant_id,
            ChatRecord.created_at >= start,
        )
        .order_by(ChatRecord.created_at)
    )
    rows = result.all()

    total = len(rows)
    today_date = now.date().isoformat()
    today = sum(1 for r in rows if r.created_at.date().isoformat() == today_date)
    refused_count = sum(1 for r in rows if r.refused)
    refused_rate = round(refused_count / total, 4) if total > 0 else 0.0

    # daily_counts：按日期分组
    daily_dict: dict[str, dict[str, int]] = {}
    for i in range(days):
        d = (now - timedelta(days=days - 1 - i)).date().isoformat()
        daily_dict[d] = {"total": 0, "refused": 0, "human": 0}
    for r in rows:
        d = r.created_at.date().isoformat()
        if d in daily_dict:
            daily_dict[d]["total"] += 1
            if r.refused:
                daily_dict[d]["refused"] += 1
            if r.need_human:
                daily_dict[d]["human"] += 1

    daily = [
        DailyCount(date=d, **counts)
        for d, counts in daily_dict.items()
    ]

    # top_users
    user_counter: Counter = Counter(r.user_id for r in rows)
    top_users = [
        ActiveUser(
            user_id=f"{uid[:4]}***" if len(uid) > 4 else uid,
            count=cnt,
        )
        for uid, cnt in user_counter.most_common(10)
    ]

    # top_docs（从 sources JSON 里提取文档名）
    doc_counter: Counter = Counter()
    for r in rows:
        srcs = r.sources
        if not isinstance(srcs, list):
            continue
        for item in srcs:
            if isinstance(item, dict):
                name = item.get("source")
                if name and isinstance(name, str):
                    doc_counter[name] += 1
    top_docs = [
        TopDocument(doc_name=name, cite_count=cnt)
        for name, cnt in doc_counter.most_common(5)
    ]

    return UsageReport(
        days=days,
        total=total,
        today=today,
        refused_rate=refused_rate,
        daily=daily,
        top_users=top_users,
        top_docs=top_docs,
    )


# ---------- 用户管理 ----------

@router.get("/users", response_model=list[UserOut], summary="用户列表")
async def list_users(
    auth: LimitedAdminAuth,
    db: AsyncSession = Depends(get_session),
) -> list[User]:
    result = await db.execute(
        select(User)
        .where(User.tenant_id == auth.tenant_id)
        .order_by(User.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/users", response_model=UserOut, status_code=201, summary="创建用户")
async def create_user(
    req: CreateUserRequest,
    auth: LimitedAdminAuth,
    db: AsyncSession = Depends(get_session),
) -> User:
    existing = (
        await db.execute(select(User).where(User.username == req.username))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = User(
        username=req.username,
        hashed_password=_bcrypt.hashpw(req.password.encode(), _bcrypt.gensalt()).decode(),
        tenant_id=auth.tenant_id,
        roles=req.roles,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/users/{username}/active", response_model=UserOut, summary="启用/禁用用户")
async def toggle_user_active(
    username: str,
    auth: LimitedAdminAuth,
    db: AsyncSession = Depends(get_session),
) -> User:
    user = (
        await db.execute(
            select(User).where(User.username == username, User.tenant_id == auth.tenant_id)
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.username == auth.user_id:
        raise HTTPException(status_code=400, detail="不能禁用自己的账号")
    user.is_active = not user.is_active
    await db.commit()
    await db.refresh(user)
    return user
