"""LangSmith 显式治理门与最终外发载荷最小化。"""
from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import langsmith as ls
from langsmith import Client
from loguru import logger

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.models.trace_governance_event import TraceGovernanceEvent

TRACE_POLICY_VERSION = "2026-06-22.v1"
_MIN_REDACTION_SECRET_LENGTH = 32
_SAFE_METADATA_KEYS = {
    "environment",
    "langgraph_node",
    "langgraph_step",
    "ls_max_tokens",
    "ls_model_name",
    "ls_model_type",
    "ls_provider",
    "ls_temperature",
    "trace_policy_version",
}
_SAFE_PAYLOAD_KEYS = {
    "answer",
    "artifact",
    "chunk_id",
    "content",
    "doc_id",
    "hmac_sha256",
    "input",
    "inputs",
    "length",
    "message",
    "messages",
    "metadata",
    "output",
    "outputs",
    "query",
    "question",
    "redacted",
    "role",
    "source",
    "text",
    "tool_call_id",
    "type",
}
_active_client: Client | None = None


@dataclass(frozen=True, slots=True)
class TracePolicyDecision:
    enabled: bool
    decision: str
    reason: str
    policy_version: str
    environment: str
    project: str
    sampling_rate: float
    data_region: str
    retention_days: int
    approval_reference: str | None
    workspace_fingerprint: str | None


class TracePolicyError(RuntimeError):
    def __init__(self, decision: TracePolicyDecision):
        super().__init__("LangSmith 追踪未通过治理审批")
        self.decision = decision


def _fingerprint(text: str, secret: str) -> str:
    return hmac.new(secret.encode(), text.encode(), hashlib.sha256).hexdigest()


def minimize_trace_payload(value: Any, *, secret: str | None = None, depth: int = 0) -> Any:
    """所有字符串在 SDK 发送前替换为带密钥 HMAC 和长度。"""
    key = secret if secret is not None else settings.langsmith_redaction_secret.get_secret_value()
    if depth > 12:
        return {"redacted": True, "reason": "max_depth"}
    if isinstance(value, str):
        return {
            "redacted": True,
            "type": "string",
            "length": len(value),
            "hmac_sha256": _fingerprint(value, key),
        }
    if isinstance(value, bytes):
        digest = hmac.new(key.encode(), value, hashlib.sha256).hexdigest()
        return {
            "redacted": True,
            "type": "bytes",
            "length": len(value),
            "hmac_sha256": digest,
        }
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {
            (
                str(field)
                if str(field) in _SAFE_PAYLOAD_KEYS
                else f"field_{_fingerprint(str(field), key)[:16]}"
            ): minimize_trace_payload(item, secret=key, depth=depth + 1)
            for field, item in value.items()
        }
    if isinstance(value, Sequence):
        return [
            minimize_trace_payload(item, secret=key, depth=depth + 1)
            for item in value
        ]
    return {"redacted": True, "type": type(value).__name__}


def minimize_trace_metadata(metadata: dict) -> dict:
    """metadata 仅保留固定技术字段，丢弃 thread/user/tenant 等标识。"""
    return {
        key: value
        for key, value in metadata.items()
        if key in _SAFE_METADATA_KEYS and isinstance(value, (str, int, float, bool))
    }


def sanitize_trace_run_ops(
    operations: Sequence[dict], *, secret: str | None = None
) -> list[dict]:
    """二次清洗错误、事件、附件和运行时信息，覆盖 inputs/outputs 之外的出口。"""
    key = secret if secret is not None else settings.langsmith_redaction_secret.get_secret_value()
    sanitized: list[dict] = []
    for operation in operations:
        item = deepcopy(operation)
        if item.get("error") is not None:
            item["error"] = minimize_trace_payload(item["error"], secret=key)
        item["events"] = []
        item["attachments"] = {}
        item.pop("serialized", None)
        extra = item.get("extra")
        if isinstance(extra, dict):
            item["extra"] = {
                "metadata": minimize_trace_metadata(extra.get("metadata", {}))
            }
        sanitized.append(item)
    return sanitized


def _workspace_fingerprint(workspace_id: str) -> str | None:
    if not workspace_id:
        return None
    return hashlib.sha256(workspace_id.encode()).hexdigest()


def _decision(*, enabled: bool, decision: str, reason: str) -> TracePolicyDecision:
    return TracePolicyDecision(
        enabled=enabled,
        decision=decision,
        reason=reason,
        policy_version=TRACE_POLICY_VERSION,
        environment=settings.app_env,
        project=settings.langchain_project,
        sampling_rate=settings.langsmith_tracing_sampling_rate,
        data_region=settings.langsmith_data_region,
        retention_days=settings.langsmith_retention_days,
        approval_reference=settings.langsmith_approval_reference or None,
        workspace_fingerprint=_workspace_fingerprint(settings.langsmith_workspace_id),
    )


def _validation_errors() -> list[str]:
    errors: list[str] = []
    secret = settings.langsmith_redaction_secret.get_secret_value()
    if not settings.langsmith_org_approved:
        errors.append("organization approval missing")
    if len(settings.langsmith_approval_reference.strip()) < 3:
        errors.append("approval reference missing")
    if not settings.langsmith_remote_policy_confirmed:
        errors.append("workspace permission/retention confirmation missing")
    if not settings.langsmith_api_key.strip():
        errors.append("API key missing")
    if not settings.langsmith_workspace_id.strip():
        errors.append("workspace ID missing")
    if not settings.langsmith_endpoint.startswith("https://"):
        errors.append("approved HTTPS endpoint missing")
    if settings.langsmith_data_region == "disabled":
        errors.append("data region missing")
    if not (0 < settings.langsmith_tracing_sampling_rate <= 1):
        errors.append("sampling rate must be greater than zero")
    if len(secret) < _MIN_REDACTION_SECRET_LENGTH:
        errors.append("redaction secret too short")
    return errors


def _safe_trace_error(exc: Exception) -> None:
    logger.error("LangSmith 追踪发送失败 type={}", type(exc).__name__)


def configure_langsmith() -> TracePolicyDecision:
    """应用启动早期执行；未请求则强制关闭，请求但未审批则失败关闭。"""
    global _active_client
    if not settings.langchain_tracing_v2:
        ls.configure(
            client=None,
            enabled=False,
            project_name=None,
            tags=None,
            metadata=None,
        )
        _active_client = None
        return _decision(enabled=False, decision="disabled", reason="tracing not requested")

    errors = _validation_errors()
    if errors:
        ls.configure(client=None, enabled=False, project_name=None)
        decision = _decision(
            enabled=False,
            decision="denied",
            reason="; ".join(errors),
        )
        raise TracePolicyError(decision)

    secret = settings.langsmith_redaction_secret.get_secret_value()
    client = Client(
        api_url=settings.langsmith_endpoint,
        api_key=settings.langsmith_api_key,
        workspace_id=settings.langsmith_workspace_id,
        tracing_sampling_rate=settings.langsmith_tracing_sampling_rate,
        hide_inputs=lambda data: minimize_trace_payload(data, secret=secret),
        hide_outputs=lambda data: minimize_trace_payload(data, secret=secret),
        hide_metadata=minimize_trace_metadata,
        omit_traced_runtime_info=True,
        process_buffered_run_ops=lambda operations: sanitize_trace_run_ops(
            operations, secret=secret
        ),
        run_ops_buffer_size=50,
        tracing_error_callback=_safe_trace_error,
        disable_prompt_cache=True,
        # 不在启动时额外读取远端 /info；远端能力/保留/权限由治理确认项管理。
        info={},
    )
    ls.configure(
        client=client,
        enabled=True,
        project_name=settings.langchain_project,
        tags=["governed", TRACE_POLICY_VERSION],
        metadata={
            "environment": settings.app_env,
            "trace_policy_version": TRACE_POLICY_VERSION,
        },
    )
    _active_client = client
    return _decision(enabled=True, decision="approved", reason="all governance gates passed")


async def record_trace_decision(decision: TracePolicyDecision) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            TraceGovernanceEvent(
                enabled=decision.enabled,
                decision=decision.decision,
                reason=decision.reason,
                policy_version=decision.policy_version,
                environment=decision.environment,
                project=decision.project,
                sampling_rate=decision.sampling_rate,
                data_region=decision.data_region,
                retention_days=decision.retention_days,
                approval_reference=decision.approval_reference,
                workspace_fingerprint=decision.workspace_fingerprint,
            )
        )
        await db.commit()


def shutdown_langsmith() -> None:
    global _active_client
    client = _active_client
    _active_client = None
    if client is not None:
        try:
            client.flush()
            client.close()
        except Exception as exc:  # noqa: BLE001
            _safe_trace_error(exc)
    ls.configure(client=None, enabled=False, project_name=None, tags=None, metadata=None)
