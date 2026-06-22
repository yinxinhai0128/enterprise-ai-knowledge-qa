"""问答接口：提问（ask）与会话历史（history）。

提问走 Agent.ainvoke（自主决定是否检索）；历史从 checkpointer 的
状态快照取 messages；会话由共享 SQLite Checkpointer 跨重启保存。
"""
from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from loguru import logger

from app.agent.agent import build_agent
from app.agent.middleware import EnterpriseContext
from app.config import settings
from app.core.auth import build_thread_id
from app.core.checkpointer import get_checkpointer
from app.core.evidence import validated_evidence_list
from app.core.limits import QAAuth, reserve_daily_model_budget
from app.services.audit import AuditWriteError, complete_audit, fail_audit, start_audit
from app.services.conversations import (
    SessionBusyError,
    acquire_conversation,
    conversation_is_active,
    enforce_message_limit,
    release_conversation,
)
from app.services.sensitive_policy import classify_question, denied_match
from app.schemas.qa import (
    AskRequest,
    AskResponse,
    HistoryMessage,
    HistoryResponse,
)

router = APIRouter(prefix="/qa", tags=["qa"])

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
        sources=sources,
        refused=refused,
        need_human=need_human,
        human_task_id=human_task_id,
    )


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
