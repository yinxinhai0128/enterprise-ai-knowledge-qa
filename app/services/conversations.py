"""会话目录、跨进程租约、消息上限与过期清理。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from langchain_core.messages import HumanMessage, RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from sqlalchemy import or_, select, text

from app.config import settings
from app.core.checkpointer import get_checkpointer
from app.core.database import AsyncSessionLocal
from app.models.conversation_session import ConversationSession


class SessionBusyError(RuntimeError):
    """同一会话正由另一个 API Worker 执行。"""


@dataclass(frozen=True, slots=True)
class ConversationLease:
    thread_id: str
    owner: str
    reset_checkpoint: bool


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


async def acquire_conversation(
    *,
    thread_id: str,
    tenant_id: str,
    user_id: str,
    client_session_id: str,
) -> ConversationLease:
    now = utcnow()
    owner = uuid4().hex
    expires = now + timedelta(seconds=settings.conversation_lease_seconds)
    ttl = now + timedelta(days=settings.conversation_ttl_days)
    async with AsyncSessionLocal() as db:
        if db.bind is not None and db.bind.dialect.name == "sqlite":
            await db.execute(text("BEGIN IMMEDIATE"))
        session = await db.get(ConversationSession, thread_id)
        reset_checkpoint = False
        if session is None:
            session = ConversationSession(
                thread_id=thread_id,
                tenant_id=tenant_id,
                user_id=user_id,
                client_session_id=client_session_id,
                message_count=0,
                expires_at=ttl,
            )
            db.add(session)
        else:
            if session.tenant_id != tenant_id or session.user_id != user_id:
                await db.rollback()
                raise SessionBusyError("会话身份边界冲突")
            if (
                session.lease_owner is not None
                and session.lease_expires_at is not None
                and _as_utc(session.lease_expires_at) > now
            ):
                await db.rollback()
                raise SessionBusyError("会话正在处理中")
            if _as_utc(session.expires_at) <= now:
                reset_checkpoint = True
                session.message_count = 0
        session.lease_owner = owner
        session.lease_expires_at = expires
        session.last_activity_at = now
        session.expires_at = ttl
        await db.commit()
    return ConversationLease(thread_id, owner, reset_checkpoint)


async def release_conversation(lease: ConversationLease, message_count: int) -> None:
    async with AsyncSessionLocal() as db:
        session = await db.get(ConversationSession, lease.thread_id)
        if session is None or session.lease_owner != lease.owner:
            return
        session.message_count = max(0, message_count)
        session.last_activity_at = utcnow()
        session.expires_at = utcnow() + timedelta(days=settings.conversation_ttl_days)
        session.lease_owner = None
        session.lease_expires_at = None
        await db.commit()


async def enforce_message_limit(agent, config: dict, messages: list) -> list:
    """删除最旧消息并写入新 checkpoint，确保状态不无限增长。"""
    limit = settings.conversation_max_messages
    if len(messages) <= limit:
        return messages
    kept = list(messages[-limit:])
    first_human = next(
        (index for index, message in enumerate(kept) if isinstance(message, HumanMessage)),
        None,
    )
    if first_human is not None:
        kept = kept[first_human:]
    await agent.aupdate_state(
        config,
        {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *kept]},
    )
    return kept


async def cleanup_expired_conversations() -> int:
    """幂等删除过期会话目录及对应 checkpoint。"""
    now = utcnow()
    async with AsyncSessionLocal() as db:
        sessions = list(
            (
                await db.execute(
                    select(ConversationSession)
                    .where(
                        ConversationSession.expires_at <= now,
                        or_(
                            ConversationSession.lease_owner.is_(None),
                            ConversationSession.lease_expires_at <= now,
                        ),
                    )
                    .order_by(ConversationSession.expires_at)
                    .limit(settings.conversation_cleanup_batch)
                )
            ).scalars()
        )
        saver = get_checkpointer()
        for session in sessions:
            await saver.adelete_thread(session.thread_id)
            await db.delete(session)
        await db.commit()
    return len(sessions)


async def conversation_is_active(
    thread_id: str, tenant_id: str, user_id: str
) -> bool:
    """历史读取也执行 TTL 与身份校验，不等待批量清理后才失效。"""
    async with AsyncSessionLocal() as db:
        session = await db.get(ConversationSession, thread_id)
        return bool(
            session is not None
            and session.tenant_id == tenant_id
            and session.user_id == user_id
            and _as_utc(session.expires_at) > utcnow()
        )
