"""预登记、可重试且 fail-closed 的问答审计写入。"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.models.chat_record import ChatRecord
from app.models.human_task import HumanTask, HumanTaskEvent
from app.services.notification import notify_human_review
from app.services.sensitive_policy import PolicyMatch


class AuditWriteError(RuntimeError):
    """审计写入在配置次数内仍失败；调用方必须 fail-closed。"""


async def _commit(db) -> None:
    await db.commit()


async def start_audit(
    *, trace_id: str, session_id: str, tenant_id: str, user_id: str, question: str
) -> int:
    last_error: Exception | None = None
    for attempt in range(settings.audit_write_retries):
        try:
            async with AsyncSessionLocal() as db:
                record = ChatRecord(
                    trace_id=trace_id,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    question=question,
                    answer="",
                    has_source=False,
                    refused=False,
                    need_human=False,
                    tool_used=False,
                    sources=[],
                    model=settings.llm_model,
                    audit_status="pending",
                )
                db.add(record)
                await _commit(db)
                await db.refresh(record)
                return record.id
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt + 1 < settings.audit_write_retries:
                await asyncio.sleep(0.05 * (attempt + 1))
    raise AuditWriteError("审计预登记失败") from last_error


async def complete_audit(
    *,
    audit_id: int | None,
    trace_id: str,
    session_id: str,
    tenant_id: str,
    user_id: str,
    question: str,
    answer: str,
    has_source: bool,
    refused: bool,
    need_human: bool,
    tool_used: bool,
    sources: list[dict],
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    latency_ms: float,
    policy_matches: list[PolicyMatch],
) -> int | None:
    last_error: Exception | None = None
    for attempt in range(settings.audit_write_retries):
        try:
            async with AsyncSessionLocal() as db:
                record = await db.get(ChatRecord, audit_id) if audit_id is not None else None
                if record is None:
                    record = ChatRecord(
                        trace_id=trace_id,
                        session_id=session_id,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        question=question,
                        answer="",
                    )
                    db.add(record)
                    await db.flush()
                record.answer = answer
                record.has_source = has_source
                record.refused = refused
                record.need_human = need_human
                record.tool_used = tool_used
                record.sources = sources
                record.model = settings.llm_model
                record.input_tokens = input_tokens
                record.output_tokens = output_tokens
                record.total_tokens = total_tokens
                record.latency_ms = latency_ms
                record.audit_status = "completed"
                record.audit_error = None
                primary = policy_matches[0] if policy_matches else None
                record.policy_category = primary.category if primary else None
                record.policy_rule_version = primary.version if primary else None

                task_id: int | None = None
                review_match = next(
                    (match for match in policy_matches if match.human_review), None
                )
                if need_human and review_match is not None:
                    task = (
                        await db.execute(
                            select(HumanTask).where(HumanTask.chat_record_id == record.id)
                        )
                    ).scalar_one_or_none()
                    if task is None:
                        task = HumanTask(
                            chat_record_id=record.id,
                            tenant_id=tenant_id,
                            user_id=user_id,
                            session_id=session_id,
                            category=review_match.category,
                            rule_id=review_match.rule_id,
                            rule_version=review_match.version,
                            reason=f"命中规则 {review_match.rule_id}",
                            status="pending",
                        )
                        db.add(task)
                        await db.flush()
                        db.add(
                            HumanTaskEvent(
                                task_id=task.id,
                                tenant_id=tenant_id,
                                actor_user_id="system",
                                action="created",
                                from_status=None,
                                to_status="pending",
                                note=task.reason,
                            )
                        )
                    task_id = task.id
                await _commit(db)
                if need_human and settings.wechat_work_webhook_url:
                    asyncio.ensure_future(
                        notify_human_review(
                            question=question,
                            category=review_match.category if review_match else "",
                            task_id=task_id,
                            webhook_url=settings.wechat_work_webhook_url,
                        )
                    )
                return task_id
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt + 1 < settings.audit_write_retries:
                await asyncio.sleep(0.05 * (attempt + 1))
    raise AuditWriteError("审计完成写入失败，记录保留为 pending") from last_error


async def fail_audit(audit_id: int, safe_error: str, latency_ms: float) -> None:
    last_error: Exception | None = None
    for attempt in range(settings.audit_write_retries):
        try:
            async with AsyncSessionLocal() as db:
                record = await db.get(ChatRecord, audit_id)
                if record is not None and record.audit_status == "pending":
                    record.audit_status = "failed"
                    record.audit_error = safe_error
                    record.latency_ms = latency_ms
                    await _commit(db)
                return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt + 1 < settings.audit_write_retries:
                await asyncio.sleep(0.05 * (attempt + 1))
    raise AuditWriteError("审计失败状态写入失败") from last_error
