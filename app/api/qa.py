"""问答接口：提问（ask）与会话历史（history）。

提问走 Agent.ainvoke（自主决定是否检索）；历史从 checkpointer 的
状态快照取 messages；会话由共享 SQLite Checkpointer 跨重启保存。
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from loguru import logger

from app.agent.agent import build_agent
from app.agent.middleware import EnterpriseContext
from app.config import settings
from app.core.auth import build_thread_id
from app.core.checkpointer import get_checkpointer
from app.core.evidence import validated_evidence_list
from app.core.database import get_session
from app.core.limits import QAAuth, reserve_daily_model_budget
from app.models.chat_record import ChatRecord as _ChatRecord
from pydantic import BaseModel
from sqlalchemy import select as _select
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.qa import (
    AskRequest,
    AskResponse,
    EvidenceSource,
    HistoryMessage,
    HistoryResponse,
)
from app.services.audit import AuditWriteError, complete_audit, fail_audit, start_audit
from app.services.conversations import (
    SessionBusyError,
    acquire_conversation,
    conversation_is_active,
    enforce_message_limit,
    release_conversation,
)
from app.services.sensitive_policy import classify_question, denied_match

router = APIRouter(prefix="/qa", tags=["qa"])


class FeedbackRequest(BaseModel):
    record_id: int
    rating: str
    comment: str | None = None


class SessionSearchItem(BaseModel):
    record_id: int
    session_id: str
    question: str
    created_at: str


# 消息类型 -> 角色
_ROLE_MAP = {
    HumanMessage: "user",
    AIMessage: "assistant",
    ToolMessage: "tool",
    SystemMessage: "system",
}


async def _fail_audit_safely(audit_id: int, message: str, started: float) -> None:
    try:
        await fail_audit(audit_id, message, (perf_counter() - started) * 1000)
    except AuditWriteError:
        logger.exception("审计失败状态写入失败 audit_id={}", audit_id)


def _text(msg) -> str:
    """把消息内容规整成纯文本（兼容多模态 list 内容）。"""
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content)


def _role_of(msg) -> str:
    """消息对象映射成角色名。"""
    for cls, role in _ROLE_MAP.items():
        if isinstance(msg, cls):
            return role
    return getattr(msg, "type", "unknown")


@router.post("/ask", response_model=AskResponse, summary="提问")
async def ask(req: AskRequest, auth: QAAuth) -> AskResponse:
    """单轮提问；同一 session_id 自动带多轮记忆。"""
    if not req.question.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="问题不能为空"
        )

    thread_id = build_thread_id(auth, req.session_id)
    trace_id = uuid4().hex
    started = perf_counter()
    try:
        audit_id = await start_audit(
            trace_id=trace_id,
            session_id=thread_id,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            question=req.question,
        )
    except AuditWriteError as exc:
        logger.exception("审计预登记失败 trace={}", trace_id)
        raise HTTPException(status_code=503, detail="审计服务暂不可用") from exc

    try:
        policy_matches = classify_question(req.question)
    except Exception as exc:  # noqa: BLE001
        await _fail_audit_safely(audit_id, "敏感规则加载失败", started)
        raise HTTPException(status_code=503, detail="访问策略暂不可用") from exc
    denied = denied_match(policy_matches, auth.roles)
    if denied is not None:
        answer = f"该问题属于受限的 {denied.category} 数据，当前角色无权访问。"
        try:
            task_id = await complete_audit(
                audit_id=audit_id,
                trace_id=trace_id,
                session_id=thread_id,
                tenant_id=auth.tenant_id,
                user_id=auth.user_id,
                question=req.question,
                answer=answer,
                has_source=False,
                refused=True,
                need_human=True,
                tool_used=False,
                sources=[],
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                latency_ms=(perf_counter() - started) * 1000,
                policy_matches=policy_matches,
            )
        except AuditWriteError as exc:
            raise HTTPException(status_code=503, detail="审计服务暂不可用") from exc
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": answer,
                "trace_id": trace_id,
                "human_task_id": task_id,
            },
        )

    try:
        await reserve_daily_model_budget(auth, req.question)
    except HTTPException:
        await _fail_audit_safely(audit_id, "请求预算限制", started)
        raise
    agent = build_agent()
    try:
        lease = await acquire_conversation(
            thread_id=thread_id,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            client_session_id=req.session_id,
        )
    except SessionBusyError as exc:
        await _fail_audit_safely(audit_id, "会话并发冲突", started)
        raise HTTPException(status_code=409, detail="同一会话正在处理，请稍后重试") from exc
    if lease.reset_checkpoint:
        await get_checkpointer().adelete_thread(thread_id)

    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": settings.agent_max_steps,
    }
    logger.info(
        "提问 tenant={} user={} session={}",
        auth.tenant_id,
        auth.user_id,
        req.session_id,
    )

    final_messages: list = []
    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": req.question}]},
            config=config,
            context=EnterpriseContext(
                session_id=thread_id,
                tenant_id=auth.tenant_id,
                user_id=auth.user_id,
                roles=auth.roles,
                audit_id=audit_id,
                trace_id=trace_id,
                started_monotonic=started,
            ),
        )
        final_messages = await enforce_message_limit(
            agent, config, list(result.get("messages", []))
        )
    except (ModelCallLimitExceededError, ToolCallLimitExceededError) as exc:
        await _fail_audit_safely(audit_id, "Agent 调用预算已用尽", started)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="单次 Agent 调用预算已用尽",
            headers={"Retry-After": "1"},
        ) from exc
    except AuditWriteError as exc:
        logger.exception("审计完成失败，响应 fail-closed trace={}", trace_id)
        raise HTTPException(status_code=503, detail="审计写入失败，请稍后重试") from exc
    except Exception as exc:  # noqa: BLE001
        await _fail_audit_safely(audit_id, "Agent 执行失败", started)
        logger.exception("Agent 执行失败 trace={}", trace_id)
        raise HTTPException(status_code=503, detail="问答服务暂不可用") from exc
    finally:
        await release_conversation(lease, len(final_messages))

    messages = final_messages
    answer = _text(messages[-1]) if messages else ""
    sources = validated_evidence_list(result.get("retrieved_evidence"))
    refused = bool(result.get("refused", not sources))
    need_human = bool(result.get("need_human", False))
    human_task_id = result.get("human_task_id")

    return AskResponse(
        answer=answer,
        sources=[EvidenceSource(**item) for item in sources],
        refused=refused,
        need_human=need_human,
        human_task_id=human_task_id,
    )


# 持有 detached 收尾 Task 的强引用，避免事件循环在其完成前将其 GC（否则
# 会出现 "Task was destroyed but it is pending" 且释放写可能未跑完）。
_PENDING_FINALIZERS: set[asyncio.Task] = set()


def _spawn_detached_finalizer(coro) -> asyncio.Task:
    """把收尾协程作为独立 Task 调度，并保持强引用直至其完成。"""
    task = asyncio.ensure_future(coro)
    _PENDING_FINALIZERS.add(task)
    task.add_done_callback(_PENDING_FINALIZERS.discard)
    return task


def _sse_frame(event: str, data: dict) -> str:
    """组装单个 SSE 帧；中文不转义，便于浏览器侧 JSON 解析。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _finalize_stream(
    *,
    agent,
    config: dict,
    lease,
    final_state: dict,
    trace_id: str,
) -> None:
    """流式收尾：历史裁剪 + 释放会话租约。

    本协程被设计为「即使所在任务被取消也要跑完」的兜底：调用方用
    asyncio.shield 包裹并把它作为独立 Task 调度，因此客户端突发断开
    导致请求任务被 CancelledError 打断时，这里的 DB 写仍能在事件循环上
    跑到底。release_conversation 在 lease_owner 已变更时幂等，重复调用无害。
    """
    messages = final_state.get("messages", []) or []
    if messages:
        # 与 /ask 一致：流式完成后裁剪历史长度并回写 checkpoint，避免状态无限增长。
        try:
            messages = await enforce_message_limit(agent, config, list(messages))
        except Exception:  # noqa: BLE001
            logger.exception("流式历史裁剪失败（不阻断释放） trace={}", trace_id)
            messages = list(messages)
    await release_conversation(lease, len(messages))


@router.post("/stream", summary="提问（流式 SSE）")
async def stream(req: AskRequest, auth: QAAuth, request: Request) -> StreamingResponse:
    """与 /ask 等价的前置检查，但答案以 SSE token 流逐字返回。

    前置检查（审计预登记 / 敏感分类 / 每日预算 / 会话租约）在返回
    StreamingResponse 之前同步执行，与 ask 保持一致：命中越权 403、
    预算超限 429、会话冲突 409 都以普通 HTTP 错误返回，不进流。
    """
    if not req.question.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="问题不能为空"
        )

    thread_id = build_thread_id(auth, req.session_id)
    trace_id = uuid4().hex
    started = perf_counter()
    try:
        audit_id = await start_audit(
            trace_id=trace_id,
            session_id=thread_id,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            question=req.question,
        )
    except AuditWriteError as exc:
        logger.exception("审计预登记失败 trace={}", trace_id)
        raise HTTPException(status_code=503, detail="审计服务暂不可用") from exc

    try:
        policy_matches = classify_question(req.question)
    except Exception as exc:  # noqa: BLE001
        await _fail_audit_safely(audit_id, "敏感规则加载失败", started)
        raise HTTPException(status_code=503, detail="访问策略暂不可用") from exc
    denied = denied_match(policy_matches, auth.roles)
    if denied is not None:
        answer = f"该问题属于受限的 {denied.category} 数据，当前角色无权访问。"
        try:
            task_id = await complete_audit(
                audit_id=audit_id,
                trace_id=trace_id,
                session_id=thread_id,
                tenant_id=auth.tenant_id,
                user_id=auth.user_id,
                question=req.question,
                answer=answer,
                has_source=False,
                refused=True,
                need_human=True,
                tool_used=False,
                sources=[],
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                latency_ms=(perf_counter() - started) * 1000,
                policy_matches=policy_matches,
            )
        except AuditWriteError as exc:
            raise HTTPException(status_code=503, detail="审计服务暂不可用") from exc
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": answer,
                "trace_id": trace_id,
                "human_task_id": task_id,
            },
        )

    try:
        await reserve_daily_model_budget(auth, req.question)
    except HTTPException:
        await _fail_audit_safely(audit_id, "请求预算限制", started)
        raise
    agent = build_agent()
    try:
        lease = await acquire_conversation(
            thread_id=thread_id,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            client_session_id=req.session_id,
        )
    except SessionBusyError as exc:
        await _fail_audit_safely(audit_id, "会话并发冲突", started)
        raise HTTPException(status_code=409, detail="同一会话正在处理，请稍后重试") from exc
    if lease.reset_checkpoint:
        await get_checkpointer().adelete_thread(thread_id)

    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": settings.agent_max_steps,
    }
    logger.info(
        "流式提问 tenant={} user={} session={}",
        auth.tenant_id,
        auth.user_id,
        req.session_id,
    )

    async def event_stream() -> AsyncIterator[str]:
        final_state: dict = {}
        disconnected = False
        try:
            stream_iter = agent.astream(
                {"messages": [{"role": "user", "content": req.question}]},
                config=config,
                context=EnterpriseContext(
                    session_id=thread_id,
                    tenant_id=auth.tenant_id,
                    user_id=auth.user_id,
                    roles=auth.roles,
                    audit_id=audit_id,
                    trace_id=trace_id,
                    started_monotonic=started,
                ),
                stream_mode=["messages", "values"],
            )
            async for mode, payload in stream_iter:
                # 主动探测客户端断开：Starlette StreamingResponse 在快速冲出
                # token/done 帧后断开时不保证取消本生成器（其 finally 可能不触发），
                # 故每轮自检 is_disconnected，发现断开就 break 走 finally 释放租约。
                if await request.is_disconnected():
                    disconnected = True
                    break
                if mode == "messages":
                    chunk, _metadata = payload
                    if isinstance(chunk, AIMessageChunk):
                        text = _text(chunk)
                        if text:
                            yield _sse_frame("token", {"text": text})
                elif mode == "values":
                    final_state = payload
        except (ModelCallLimitExceededError, ToolCallLimitExceededError):
            await _fail_audit_safely(audit_id, "Agent 调用预算已用尽", started)
            logger.warning("流式 Agent 调用预算用尽 trace={}", trace_id)
            yield _sse_frame(
                "error",
                {"detail": "单次 Agent 调用预算已用尽", "error_code": "agent_budget_exhausted"},
            )
            return
        except AuditWriteError:
            logger.exception("流式审计完成失败 fail-closed trace={}", trace_id)
            yield _sse_frame(
                "error",
                {"detail": "审计写入失败，请稍后重试", "error_code": "audit_write_failed"},
            )
            return
        except Exception:  # noqa: BLE001
            await _fail_audit_safely(audit_id, "Agent 执行失败", started)
            logger.exception("流式 Agent 执行失败 trace={}", trace_id)
            yield _sse_frame(
                "error",
                {"detail": "问答服务暂不可用", "error_code": "qa_unavailable"},
            )
            return
        finally:
            # 断开时主动关闭 astream 迭代器，取消底层 agent 运行（best-effort）。
            if disconnected:
                try:
                    await stream_iter.aclose()
                except Exception:  # noqa: BLE001
                    logger.exception("关闭 astream 迭代器失败 trace={}", trace_id)
            # 收尾（裁剪 + 释放租约）必须对「任务取消」鲁棒：把它作为独立 Task
            # 调度并用 asyncio.shield 保护——客户端突发断开导致本生成器任务被
            # CancelledError 打断时，shield 把取消挡在外层，detached Task 仍在
            # 事件循环上把 DB 释放写跑完，从而保证 lease_owner 一定被清空。
            finalize_task = _spawn_detached_finalizer(
                _finalize_stream(
                    agent=agent,
                    config=config,
                    lease=lease,
                    final_state=final_state,
                    trace_id=trace_id,
                )
            )
            try:
                await asyncio.shield(finalize_task)
            except asyncio.CancelledError:
                # 本帧的 await 被取消，但 finalize_task 已 detached，会自行跑完释放。
                logger.info("流式任务被取消，租约释放已 detached 兜底 trace={}", trace_id)
                raise
            except Exception:  # noqa: BLE001
                logger.exception("流式收尾失败 trace={}", trace_id)

        # 客户端已断开则无需再发 done（socket 已不可写）；租约已在 finally 释放。
        if disconnected:
            logger.info("流式客户端中途断开，已释放租约 trace={}", trace_id)
            return

        # 取中间件改写后的可信最终答案（final_state messages 最后一条 AIMessage）
        answer = ""
        for msg in reversed(final_state.get("messages", []) or []):
            if isinstance(msg, AIMessage):
                answer = _text(msg)
                break
        sources = validated_evidence_list(final_state.get("retrieved_evidence"))
        refused = bool(final_state.get("refused", not sources))
        need_human = bool(final_state.get("need_human", False))
        human_task_id = final_state.get("human_task_id")
        yield _sse_frame(
            "done",
            {
                "answer": answer,
                "sources": [EvidenceSource(**item).model_dump() for item in sources],
                "refused": refused,
                "need_human": need_human,
                "human_task_id": human_task_id,
                "record_id": audit_id,
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get(
    "/history/{session_id}",
    response_model=HistoryResponse,
    summary="会话历史",
)
async def history(session_id: str, auth: QAAuth) -> HistoryResponse:
    """从当前租户、当前用户专属 thread 读取消息历史。"""
    try:
        thread_id = build_thread_id(auth, session_id)
    except ValueError as exc:
        # 不接受客户端传入内部 tenant:user:session 标识，避免用户枚举他人 thread。
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在",
        ) from exc
    agent = build_agent()
    config = {"configurable": {"thread_id": thread_id}}

    if not await conversation_is_active(thread_id, auth.tenant_id, auth.user_id):
        return HistoryResponse(session_id=session_id, messages=[])

    snapshot = await agent.aget_state(config)
    raw_messages = snapshot.values.get("messages", []) if snapshot.values else []

    messages = [
        HistoryMessage(role=_role_of(msg), content=text)
        for msg in raw_messages
        if (text := _text(msg))
    ]
    return HistoryResponse(session_id=session_id, messages=messages)


@router.post("/feedback", summary="提交回答反馈")
async def submit_feedback(
    req: FeedbackRequest,
    auth: QAAuth,
    db: AsyncSession = Depends(get_session),
) -> dict:
    if req.rating not in ("up", "down"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="rating 只能是 up 或 down",
        )
    if req.comment and len(req.comment) > 200:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="comment 最多 200 字",
        )
    result = await db.execute(
        _select(_ChatRecord).where(
            _ChatRecord.id == req.record_id,
            _ChatRecord.user_id == auth.user_id,
            _ChatRecord.tenant_id == auth.tenant_id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="记录不存在或无权访问",
        )
    record.feedback_rating = req.rating
    record.feedback_comment = req.comment
    await db.commit()
    return {"ok": True}


@router.get(
    "/sessions/search",
    response_model=list[SessionSearchItem],
    summary="搜索历史会话",
)
async def search_sessions(
    auth: QAAuth,
    q: str | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
) -> list[SessionSearchItem]:
    if not q or not q.strip():
        return []
    result = await db.execute(
        _select(_ChatRecord)
        .where(
            _ChatRecord.tenant_id == auth.tenant_id,
            _ChatRecord.user_id == auth.user_id,
            _ChatRecord.question.contains(q.strip()),
        )
        .order_by(_ChatRecord.created_at.desc(), _ChatRecord.id.desc())
        .limit(50)
    )
    records = list(result.scalars().all())
    return [
        SessionSearchItem(
            record_id=r.id,
            session_id=r.session_id,
            question=r.question[:100],
            created_at=r.created_at.isoformat(),
        )
        for r in records
    ]
