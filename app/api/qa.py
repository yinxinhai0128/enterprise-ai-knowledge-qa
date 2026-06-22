"""问答接口：提问（ask）与会话历史（history）。

提问走 Agent.ainvoke（自主决定是否检索）；历史从 checkpointer 的
状态快照取 messages。注意 InMemorySaver 是进程内记忆，重启即清空。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from loguru import logger

from app.agent.agent import build_agent
from app.agent.middleware import EnterpriseContext
from app.core.auth import UserAuth, build_thread_id
from app.core.evidence import validated_evidence_list
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
async def ask(req: AskRequest, auth: UserAuth) -> AskResponse:
    """单轮提问；同一 session_id 自动带多轮记忆。"""
    if not req.question.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="问题不能为空"
        )

    agent = build_agent()
    thread_id = build_thread_id(auth, req.session_id)
    config = {"configurable": {"thread_id": thread_id}}
    logger.info(
        "提问 tenant={} user={} session={}",
        auth.tenant_id,
        auth.user_id,
        req.session_id,
    )

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": req.question}]},
        config=config,
        context=EnterpriseContext(
            session_id=thread_id,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
        ),
    )

    messages = result.get("messages", [])
    answer = _text(messages[-1]) if messages else ""
    sources = validated_evidence_list(result.get("retrieved_evidence"))
    refused = bool(result.get("refused", not sources))
    need_human = bool(result.get("need_human", False))

    return AskResponse(
        answer=answer,
        sources=sources,
        refused=refused,
        need_human=need_human,
    )


@router.get(
    "/history/{session_id}",
    response_model=HistoryResponse,
    summary="会话历史",
)
async def history(session_id: str, auth: UserAuth) -> HistoryResponse:
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

    snapshot = await agent.aget_state(config)
    raw_messages = snapshot.values.get("messages", []) if snapshot.values else []

    messages = [
        HistoryMessage(role=_role_of(msg), content=text)
        for msg in raw_messages
        if (text := _text(msg))
    ]
    return HistoryResponse(session_id=session_id, messages=messages)
