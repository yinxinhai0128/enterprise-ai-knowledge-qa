"""阶段 7：LangSmith 显式授权、外发最小化与无网络验收。"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest
from langsmith import utils as ls_utils
from sqlalchemy import select

import app.core.database as database_module
from app.config import Settings, settings
from app.core.tracing import (
    TRACE_POLICY_VERSION,
    TracePolicyError,
    configure_langsmith,
    minimize_trace_payload,
    record_trace_decision,
    sanitize_trace_run_ops,
    shutdown_langsmith,
)
from app.models.trace_governance_event import TraceGovernanceEvent


def _approve(monkeypatch) -> None:
    monkeypatch.setattr(settings, "langchain_tracing_v2", True)
    monkeypatch.setattr(settings, "langsmith_org_approved", True)
    monkeypatch.setattr(settings, "langsmith_approval_reference", "SEC-2026-001")
    monkeypatch.setattr(settings, "langsmith_remote_policy_confirmed", True)
    monkeypatch.setattr(settings, "langsmith_api_key", "test-langsmith-key")
    monkeypatch.setattr(settings, "langsmith_workspace_id", str(uuid4()))
    monkeypatch.setattr(settings, "langsmith_endpoint", "https://example.invalid")
    monkeypatch.setattr(settings, "langsmith_data_region", "self-hosted")
    monkeypatch.setattr(settings, "langsmith_tracing_sampling_rate", 0.25)
    monkeypatch.setattr(settings, "langsmith_retention_days", 14)
    monkeypatch.setattr(
        settings,
        "langsmith_redaction_secret",
        type(settings.langsmith_redaction_secret)("r" * 32),
    )


def test_test_environment_forces_tracing_off():
    assert settings.langchain_tracing_v2 is False
    assert ls_utils.tracing_is_enabled() is False


def test_production_code_default_is_tracing_off():
    assert Settings.model_fields["langchain_tracing_v2"].default is False
    assert Settings.model_fields["langsmith_tracing_sampling_rate"].default == 0.0


def test_tracing_request_without_approval_is_denied(monkeypatch):
    monkeypatch.setattr(settings, "langchain_tracing_v2", True)
    monkeypatch.setattr(settings, "langsmith_org_approved", False)
    with pytest.raises(TracePolicyError) as caught:
        configure_langsmith()
    assert caught.value.decision.decision == "denied"
    assert caught.value.decision.enabled is False
    assert "approval" in caught.value.decision.reason
    assert ls_utils.tracing_is_enabled() is False


def test_final_outbound_payload_contains_no_sensitive_plaintext(monkeypatch):
    _approve(monkeypatch)
    monkeypatch.setattr(
        "requests.sessions.Session.request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("载荷检查不得访问网络")
        ),
    )
    sensitive_question = "员工张三邮箱 zhangsan@example.com，工资为什么这么低？"
    sensitive_document = "内部病历编号 MED-8848，诊断内容不得外传。"
    sensitive_error = "处理 zhangsan@example.com 时失败"
    decision = configure_langsmith()
    assert decision.enabled is True
    assert decision.sampling_rate == 0.25
    assert decision.policy_version == TRACE_POLICY_VERSION

    from langsmith.run_trees import get_cached_client

    client = get_cached_client()
    transformed = client._run_transform(
        {
            "id": uuid4(),
            "trace_id": uuid4(),
            "dotted_order": "fixed-order",
            "name": "search_knowledge_base",
            "run_type": "tool",
            "inputs": {"question": sensitive_question},
            "outputs": {
                "content": sensitive_document,
                "artifact": [{"doc_id": 7, "chunk_id": "tenant:7:0:secret"}],
            },
            "extra": {
                "metadata": {
                    "ls_model_name": "qwen-test",
                    "thread_id": "tenant-a:user-a:private",
                }
            },
        }
    )
    outbound = sanitize_trace_run_ops(
        [{**transformed, "error": sensitive_error, "events": [{"raw": sensitive_document}]}],
        secret="r" * 32,
    )[0]
    serialized = json.dumps(outbound, ensure_ascii=False, default=str)
    for plaintext in (
        sensitive_question,
        "zhangsan@example.com",
        sensitive_document,
        "MED-8848",
        sensitive_error,
        "tenant-a:user-a:private",
    ):
        assert plaintext not in serialized
    assert outbound["outputs"]["artifact"][0]["doc_id"] == 7
    assert "hmac_sha256" in serialized
    assert outbound["events"] == []
    assert outbound["attachments"] == {}
    assert outbound["extra"]["metadata"] == {"ls_model_name": "qwen-test"}
    shutdown_langsmith()


def test_minimizer_is_deterministic_but_keyed():
    first = minimize_trace_payload("same secret", secret="a" * 32)
    second = minimize_trace_payload("same secret", secret="a" * 32)
    other_key = minimize_trace_payload("same secret", secret="b" * 32)
    assert first == second
    assert first["hmac_sha256"] != other_key["hmac_sha256"]
    assert "same secret" not in json.dumps(first)


async def test_governance_decision_is_audited_without_secrets(monkeypatch):
    _approve(monkeypatch)
    monkeypatch.setattr(
        "requests.sessions.Session.request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("治理审计测试不得访问网络")
        ),
    )
    decision = configure_langsmith()
    await record_trace_decision(decision)
    async with database_module.AsyncSessionLocal() as db:
        event = (await db.execute(select(TraceGovernanceEvent))).scalar_one()
    assert event.enabled is True
    assert event.decision == "approved"
    assert event.approval_reference == "SEC-2026-001"
    assert event.workspace_fingerprint
    assert not hasattr(event, "api_key")
    assert not hasattr(event, "redaction_secret")
    shutdown_langsmith()


async def test_disabled_tracing_creates_no_run_or_network(
    monkeypatch, agent_factory
):
    monkeypatch.setattr(settings, "langchain_tracing_v2", False)
    decision = configure_langsmith()
    assert decision.decision == "disabled"

    def forbidden(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("关闭追踪时不得创建 LangSmith run 或网络请求")

    monkeypatch.setattr("langsmith.client.Client.create_run", forbidden)
    monkeypatch.setattr("langsmith.client.Client.update_run", forbidden)
    monkeypatch.setattr("requests.sessions.Session.request", forbidden)
    agent = agent_factory(["本地假回答"])
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "测试关闭追踪"}]},
        config={"configurable": {"thread_id": "tenant-a:user-a:no-trace"}},
        context=__import__(
            "app.agent.context", fromlist=["EnterpriseContext"]
        ).EnterpriseContext(
            session_id="tenant-a:user-a:no-trace",
            tenant_id="tenant-a",
            user_id="user-a",
        ),
    )
    assert result["messages"]
    assert ls_utils.tracing_is_enabled() is False
