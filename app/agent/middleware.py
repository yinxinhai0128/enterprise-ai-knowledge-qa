"""企业审计中间件：敏感词拦截 + 问答落库。

基于 LangChain 1.3 的 AgentMiddleware 钩子：
  - before_model：模型调用前检查用户问题敏感词 -> 标记 need_human
  - after_model：最终回答时检查是否含来源标注，并把问答落库

自定义状态键（need_human / has_source）通过 state_schema 扩展 AgentState 声明，
钩子返回 dict 即合并进 Agent 状态。DB 写入用异步钩子 aafter_model。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime
from loguru import logger
from typing_extensions import NotRequired

from app.core.database import AsyncSessionLocal
from app.models.chat_record import ChatRecord

# 敏感词：命中即标记需人工介入
SENSITIVE_WORDS = (
    "薪资", "工资", "绩效", "裁员", "法律", "诉讼", "投诉", "隐私", "病假",
)

# 来源标注前缀（检索工具产出，回答里复述）
SOURCE_MARK = "[来源:"


@dataclass
class EnterpriseContext:
    """运行时可信上下文：只能由已认证 API 层构造。"""

    session_id: str
    tenant_id: str
    user_id: str


class EnterpriseState(AgentState):
    """在内置 AgentState 上扩展两个自定义状态键。"""

    need_human: NotRequired[bool]
    has_source: NotRequired[bool]


def _latest_question(messages: list) -> str:
    """取最近一条用户消息文本。"""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return _text(msg)
    return ""


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


class EnterpriseAuditMiddleware(AgentMiddleware):
    """敏感词检测 + 问答审计落库。"""

    state_schema = EnterpriseState

    async def abefore_model(
        self, state: EnterpriseState, runtime: Runtime[EnterpriseContext]
    ) -> dict[str, Any] | None:
        """模型调用前：敏感词检测。"""
        question = _latest_question(state.get("messages", []))
        hit = next((w for w in SENSITIVE_WORDS if w in question), None)
        if hit:
            logger.warning("命中敏感词「{}」，标记需人工介入", hit)
        # 每一轮都显式重算，避免上一轮的敏感标记残留到后续普通问题。
        return {"need_human": hit is not None}

    async def aafter_model(
        self, state: EnterpriseState, runtime: Runtime[EnterpriseContext]
    ) -> dict[str, Any] | None:
        """模型调用后：仅在最终回答（无工具调用）时记来源并落库。"""
        messages = state.get("messages", [])
        if not messages:
            return None

        last = messages[-1]
        # 还要继续调用工具的中间消息不落库
        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            return None

        answer = _text(last)
        has_source = SOURCE_MARK in answer
        question = _latest_question(messages)
        need_human = bool(state.get("need_human", False))
        if runtime.context is None:
            logger.error("缺少 Agent 可信运行时上下文，拒绝写入审计记录")
            return {"has_source": has_source}
        session_id = runtime.context.session_id

        await self._save(
            session_id=session_id,
            tenant_id=runtime.context.tenant_id,
            user_id=runtime.context.user_id,
            question=question,
            answer=answer,
            has_source=has_source,
            need_human=need_human,
        )
        return {"has_source": has_source}

    @staticmethod
    async def _save(
        *,
        session_id: str,
        tenant_id: str,
        user_id: str,
        question: str,
        answer: str,
        has_source: bool,
        need_human: bool,
    ) -> None:
        """把一轮问答写入 chat_records。"""
        try:
            async with AsyncSessionLocal() as db:
                db.add(
                    ChatRecord(
                        session_id=session_id,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        question=question,
                        answer=answer,
                        has_source=has_source,
                        need_human=need_human,
                    )
                )
                await db.commit()
        except Exception:  # noqa: BLE001
            # 审计落库失败不应中断对话
            logger.exception("问答落库失败 session={}", session_id)
