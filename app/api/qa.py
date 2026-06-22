"""问答接口：提问（ask）与会话历史（history）。

提问走 Agent.ainvoke（自主决定是否检索）；历史从 checkpointer 的
状态快照取 messages。注意 InMemorySaver 是进程内记忆，重启即清空。
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, status
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from loguru import logger

from app.agent.agent import build_agent
from app.agent.middleware import EnterpriseContext
from app.schemas.qa import (
    AskRequest,
    AskResponse,
    HistoryMessage,
    HistoryResponse,
)

router = APIRouter(prefix="/qa", tags=["qa"])

# 从回答中提取 [来源:xxx] 标注
_SOURCE_RE = re.compile(r"\[来源:([^\]]+)\]")
# 拒答话术标记（与 system_prompt 中的拒绝口径对应）
_REFUSAL_MARKERS = ("没有找到相关", "未找到相关", "知识库中没有", "无法回答")

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


def _extract_sources(answer: str) -> list[str]:
    """提取回答里的来源标注，去重并保序。"""
    seen: dict[str, None] = {}
    for match in _SOURCE_RE.findall(answer):
        seen.setdefault(match.strip(), None)
    return list(seen)


def _role_of(msg) -> str:
    """消息对象映射成角色名。"""
    for cls, role in _ROLE_MAP.items():
        if isinstance(msg, cls):
            return role
    return getattr(msg, "type", "unknown")


@router.post("/ask", response_model=AskResponse, summary="提问")
async def ask(req: AskRequest) -> AskResponse:
    """单轮提问；同一 session_id 自动带多轮记忆。"""
    if not req.question.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="问题不能为空"
        )

    agent = build_agent()
    config = {"configurable": {"thread_id": req.session_id}}
    logger.info("提问 user={} session={}", req.user_id, req.session_id)

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": req.question}]},
        config=config,
        context=EnterpriseContext(session_id=req.session_id),
    )

    messages = result.get("messages", [])
    answer = _text(messages[-1]) if messages else ""
    sources = _extract_sources(answer)
    refused = not sources and any(mark in answer for mark in _REFUSAL_MARKERS)
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
async def history(session_id: str) -> HistoryResponse:
    """从 checkpointer 取该会话的消息历史。"""
    agent = build_agent()
    config = {"configurable": {"thread_id": session_id}}

    snapshot = await agent.aget_state(config)
    raw_messages = snapshot.values.get("messages", []) if snapshot.values else []

    messages = [
        HistoryMessage(role=_role_of(msg), content=text)
        for msg in raw_messages
        if (text := _text(msg))
    ]
    return HistoryResponse(session_id=session_id, messages=messages)
