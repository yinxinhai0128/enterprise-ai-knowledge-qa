"""企业审计中间件：可信证据、规则分类、人工任务与 fail-closed 审计。"""
from __future__ import annotations

import re
from time import perf_counter
from typing import Any
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime
from loguru import logger
from typing_extensions import NotRequired

from app.agent.context import EnterpriseContext
from app.core.evidence import Evidence, evidence_label, validated_evidence_list
from app.services.audit import AuditWriteError, complete_audit
from app.services.sensitive_policy import classify_question

REFUSAL_ANSWER = "知识库中没有找到相关资料，无法基于可信证据回答。"
_MODEL_CITATION_RE = re.compile(r"\s*\[来源:([^\]]+)\]")


class EnterpriseState(AgentState):
    need_human: NotRequired[bool]
    has_source: NotRequired[bool]
    refused: NotRequired[bool]
    retrieved_evidence: NotRequired[list[Evidence]]
    human_task_id: NotRequired[int | None]
    policy_category: NotRequired[str | None]
    policy_rule_version: NotRequired[str | None]


def _latest_question(messages: list) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return _text(msg)
    return ""


def _text(msg) -> str:
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


def _current_turn_tool_used(messages: list) -> bool:
    start = 0
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            start = index + 1
            break
    return any(isinstance(message, ToolMessage) for message in messages[start:])


def _trusted_answer(model_answer: str, evidence: list[Evidence], session_id: str) -> str:
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


def _token_usage(messages: list) -> tuple[int, int, int]:
    """汇总供应商结构化 usage；缺失时保持 0，不做猜测。"""
    input_tokens = output_tokens = total_tokens = 0
    start = 0
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            start = index + 1
            break
    for message in messages[start:]:
        if not isinstance(message, AIMessage):
            continue
        usage = getattr(message, "usage_metadata", None) or {}
        input_tokens += int(usage.get("input_tokens", 0) or 0)
        output_tokens += int(usage.get("output_tokens", 0) or 0)
        total_tokens += int(usage.get("total_tokens", 0) or 0)
    return input_tokens, output_tokens, total_tokens or input_tokens + output_tokens


class EnterpriseAuditMiddleware(AgentMiddleware):
    state_schema = EnterpriseState

    async def abefore_agent(
        self, state: EnterpriseState, runtime: Runtime[EnterpriseContext]
    ) -> dict[str, Any] | None:
        question = _latest_question(state.get("messages", []))
        matches = classify_question(question)
        review = next((item for item in matches if item.human_review), None)
        if review:
            logger.warning(
                "命中敏感规则 category={} rule={} version={}",
                review.category,
                review.rule_id,
                review.version,
            )
        return {
            "need_human": review is not None,
            "has_source": False,
            "refused": False,
            "retrieved_evidence": [],
            "human_task_id": None,
            "policy_category": review.category if review else None,
            "policy_rule_version": review.version if review else None,
        }

    async def aafter_agent(
        self, state: EnterpriseState, runtime: Runtime[EnterpriseContext]
    ) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages or not isinstance(messages[-1], AIMessage):
            return None
        if runtime.context is None:
            logger.error("缺少 Agent 可信运行时上下文，审计 fail-closed")
            raise AuditWriteError("缺少可信审计上下文")

        last = messages[-1]
        evidence = _current_turn_evidence(messages)
        question = _latest_question(messages)
        need_human = bool(state.get("need_human", False))
        refused = not evidence
        session_id = runtime.context.session_id
        answer = _trusted_answer(_text(last), evidence, session_id)

        message_update: list[AIMessage] = []
        if last.id is None:
            last.content = answer
        else:
            message_update = [last.model_copy(update={"content": answer})]

        input_tokens, output_tokens, total_tokens = _token_usage(messages)
        trace_id = (
            runtime.context.trace_id
            if runtime.context.audit_id is not None
            else uuid4().hex
        )
        task_id = await complete_audit(
            audit_id=runtime.context.audit_id,
            trace_id=trace_id,
            session_id=session_id,
            tenant_id=runtime.context.tenant_id,
            user_id=runtime.context.user_id,
            question=question,
            answer=answer,
            has_source=bool(evidence),
            refused=refused,
            need_human=need_human,
            tool_used=_current_turn_tool_used(messages),
            sources=[dict(item) for item in evidence],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=max(
                0.0, (perf_counter() - runtime.context.started_monotonic) * 1000
            ),
            policy_matches=classify_question(question),
        )
        update: dict[str, Any] = {
            "has_source": bool(evidence),
            "refused": refused,
            "retrieved_evidence": evidence,
            "human_task_id": task_id,
        }
        if message_update:
            update["messages"] = message_update
        return update
