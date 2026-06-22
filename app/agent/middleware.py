"""企业审计中间件：证据收敛、强制拒答、敏感词与问答落库。

基于 LangChain 1.3 的 AgentMiddleware 钩子：
  - before_agent：每轮开始重置证据状态并检查敏感词
  - after_agent：只认 ToolMessage.artifact，清洗模型引用并把结构化结果落库

自定义状态键（need_human / has_source）通过 state_schema 扩展 AgentState 声明，
钩子返回 dict 即合并进 Agent 状态。DB 写入用异步钩子 aafter_model。
"""
from __future__ import annotations

import re
from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime
from loguru import logger
from typing_extensions import NotRequired

from app.agent.context import EnterpriseContext
from app.core.database import AsyncSessionLocal
from app.core.evidence import Evidence, evidence_label, validated_evidence_list
from app.models.chat_record import ChatRecord

# 敏感词：命中即标记需人工介入
SENSITIVE_WORDS = (
    "薪资", "工资", "绩效", "裁员", "法律", "诉讼", "投诉", "隐私", "病假",
)

REFUSAL_ANSWER = "知识库中没有找到相关资料，无法基于可信证据回答。"
# 仅用于清除模型生成的非可信展示文本；真实性始终由 artifact 决定。
_MODEL_CITATION_RE = re.compile(r"\s*\[来源:([^\]]+)\]")


class EnterpriseState(AgentState):
    """在内置 AgentState 上扩展服务端可信状态。"""

    need_human: NotRequired[bool]
    has_source: NotRequired[bool]
    refused: NotRequired[bool]
    retrieved_evidence: NotRequired[list[Evidence]]


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


def _current_turn_evidence(messages: list) -> list[Evidence]:
    """仅收集最新用户问题之后由工具节点产生的 artifact。"""
    start = 0
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            start = index + 1
            break
    evidence: list[Evidence] = []
    seen: set[str] = set()
    for message in messages[start:]:
        if not isinstance(message, ToolMessage) or message.status != "success":
            continue
        for item in validated_evidence_list(message.artifact):
            if item["chunk_id"] not in seen:
                seen.add(item["chunk_id"])
                evidence.append(item)
    return evidence


def _trusted_answer(model_answer: str, evidence: list[Evidence], session_id: str) -> str:
    """移除模型自报引用，并只用真实 artifact 重建展示来源。"""
    if not evidence:
        return REFUSAL_ANSWER

    claimed = {claim.strip() for claim in _MODEL_CITATION_RE.findall(model_answer)}
    trusted = {evidence_label(item) for item in evidence}
    unsupported = claimed - trusted
    if unsupported:
        logger.warning(
            "模型生成未经证据支持的引用，已移除 count={} session={}",
            len(unsupported),
            session_id,
        )

    clean_answer = _MODEL_CITATION_RE.sub("", model_answer).strip()
    labels = list(dict.fromkeys(evidence_label(item) for item in evidence))
    citations = "\n".join(f"- [来源:{label}]" for label in labels)
    return f"{clean_answer}\n\n参考来源：\n{citations}".strip()


class EnterpriseAuditMiddleware(AgentMiddleware):
    """证据收敛、敏感词检测与问答审计落库。"""

    state_schema = EnterpriseState

    async def abefore_agent(
        self, state: EnterpriseState, runtime: Runtime[EnterpriseContext]
    ) -> dict[str, Any] | None:
        """每轮开始：重置可信状态并执行敏感词检测。"""
        question = _latest_question(state.get("messages", []))
        hit = next((w for w in SENSITIVE_WORDS if w in question), None)
        if hit:
            logger.warning("命中敏感词「{}」，标记需人工介入", hit)
        return {
            "need_human": hit is not None,
            "has_source": False,
            "refused": False,
            "retrieved_evidence": [],
        }

    async def aafter_agent(
        self, state: EnterpriseState, runtime: Runtime[EnterpriseContext]
    ) -> dict[str, Any] | None:
        """整个工具回环结束后，以 artifact 生成最终状态并落库。"""
        messages = state.get("messages", [])
        if not messages:
            return None

        last = messages[-1]
        if not isinstance(last, AIMessage):
            return None

        evidence = _current_turn_evidence(messages)
        question = _latest_question(messages)
        need_human = bool(state.get("need_human", False))
        refused = not evidence
        has_source = bool(evidence)
        session_id = (
            runtime.context.session_id if runtime.context is not None else "missing-context"
        )
        answer = _trusted_answer(_text(last), evidence, session_id)

        # add_messages 对相同 id 执行替换；无 id 的测试模型则安全地原地改内容。
        message_update: list[AIMessage] = []
        if last.id is None:
            last.content = answer
        else:
            message_update = [last.model_copy(update={"content": answer})]

        if runtime.context is None:
            logger.error("缺少 Agent 可信运行时上下文，拒绝写入审计记录")
            update_without_audit: dict[str, Any] = {
                "has_source": has_source,
                "refused": refused,
                "retrieved_evidence": evidence,
            }
            if message_update:
                update_without_audit["messages"] = message_update
            return update_without_audit

        await self._save(
            session_id=session_id,
            tenant_id=runtime.context.tenant_id,
            user_id=runtime.context.user_id,
            question=question,
            answer=answer,
            has_source=has_source,
            refused=refused,
            need_human=need_human,
        )
        update: dict[str, Any] = {
            "has_source": has_source,
            "refused": refused,
            "retrieved_evidence": evidence,
        }
        if message_update:
            update["messages"] = message_update
        return update

    @staticmethod
    async def _save(
        *,
        session_id: str,
        tenant_id: str,
        user_id: str,
        question: str,
        answer: str,
        has_source: bool,
        refused: bool,
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
                        refused=refused,
                        need_human=need_human,
                    )
                )
                await db.commit()
        except Exception:  # noqa: BLE001
            # 审计落库失败不应中断对话
            logger.exception("问答落库失败 session={}", session_id)
