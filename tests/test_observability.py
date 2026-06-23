"""阶段 10：健康探针、安全日志、错误码与指标验收。"""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from io import StringIO

import pytest
from loguru import logger

import app.core.database as database_module
from app.config import settings
from app.core.observability import (
    ObservedModelRetryMiddleware,
    redact_log_text,
    runtime_metrics,
    sanitize_log_record,
)
from app.models.chat_record import ChatRecord
from app.models.document import Document
from app.models.ingest_job import IngestJob
from app.services.ingest_jobs import utcnow


async def _healthy_probe() -> None:
    return None


async def test_live_ready_and_legacy_health_are_distinct(anonymous_client, monkeypatch):
    monkeypatch.setattr("app.services.health.probe_database", _healthy_probe)
    monkeypatch.setattr("app.services.health.probe_vectorstore", _healthy_probe)
    monkeypatch.setattr("app.services.health.probe_worker_leases", _healthy_probe)

    live = await anonymous_client.get("/health/live")
    legacy = await anonymous_client.get("/health")
    ready = await anonymous_client.get("/health/ready")

    assert live.json() == {"status": "ok"}
    assert legacy.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert set(ready.json()["components"]) == {"database", "vectorstore", "worker_lease"}


@pytest.mark.parametrize(
    ("failed_probe", "component", "error_code"),
    (
        ("probe_database", "database", "READINESS_DATABASE_UNAVAILABLE"),
        ("probe_vectorstore", "vectorstore", "READINESS_VECTORSTORE_UNAVAILABLE"),
    ),
)
async def test_readiness_failure_emits_safe_alert(
    anonymous_client, monkeypatch, failed_probe, component, error_code
):
    async def unavailable() -> None:
        raise OSError("sensitive internal path must not be logged")

    for probe in ("probe_database", "probe_vectorstore", "probe_worker_leases"):
        monkeypatch.setattr(f"app.services.health.{probe}", _healthy_probe)
    monkeypatch.setattr(f"app.services.health.{failed_probe}", unavailable)
    events: list[dict] = []
    sink = logger.add(lambda message: events.append(dict(message.record["extra"])))
    try:
        response = await anonymous_client.get("/health/ready")
    finally:
        logger.remove(sink)

    assert response.status_code == 503
    assert response.json()["components"][component]["error_code"] == error_code
    assert any(event.get("error_code") == error_code for event in events)


async def test_stale_worker_lease_blocks_readiness(anonymous_client, monkeypatch):
    monkeypatch.setattr("app.services.health.probe_database", _healthy_probe)
    monkeypatch.setattr("app.services.health.probe_vectorstore", _healthy_probe)
    async with database_module.AsyncSessionLocal() as db:
        document = Document(
            tenant_id="tenant-a",
            uploaded_by="user-a",
            filename="lease.txt",
            file_path="unused",
            status="parsing",
        )
        db.add(document)
        await db.flush()
        db.add(
            IngestJob(
                document_id=document.id,
                tenant_id="tenant-a",
                status="running",
                attempt=1,
                max_attempts=3,
                lease_owner="dead-worker",
                lease_expires_at=utcnow() - timedelta(seconds=1),
            )
        )
        await db.commit()

    response = await anonymous_client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["components"]["worker_lease"] == {
        "status": "error",
        "error_code": "READINESS_WORKER_LEASE_STALE",
    }


async def test_model_timeout_records_retries_and_alert_without_payload():
    middleware = ObservedModelRetryMiddleware(
        max_retries=2,
        initial_delay=0,
        jitter=False,
        on_failure="error",
    )
    events: list[dict] = []
    sink = logger.add(lambda message: events.append(dict(message.record["extra"])))

    async def fail(_request):
        raise TimeoutError("完整敏感问题 Bearer should-never-appear")

    try:
        with pytest.raises(TimeoutError):
            await middleware.awrap_model_call(object(), fail)
    finally:
        logger.remove(sink)

    _, retries, timeouts, _ = runtime_metrics.snapshot()
    assert retries == 2
    assert timeouts == 3
    assert len([event for event in events if event.get("error_code") == "MODEL_TIMEOUT"]) == 3
    assert all("完整敏感问题" not in str(event) for event in events)


async def test_request_id_and_stable_error_code(anonymous_client):
    response = await anonymous_client.get(
        "/does-not-exist", headers={"X-Request-ID": "ops-check-123"}
    )
    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "ops-check-123"
    assert response.json()["request_id"] == "ops-check-123"
    assert response.json()["error_code"] == "NOT_FOUND"


def test_log_redaction_removes_known_and_pattern_secrets():
    value = (
        f"api_key={settings.dashscope_api_key} "
        "Authorization: Bearer abc.def.ghi password=test-secret-value"
    )
    redacted = redact_log_text(value)
    assert settings.dashscope_api_key not in redacted
    assert "abc.def.ghi" not in redacted
    assert "test-secret-value" not in redacted
    assert "[REDACTED]" in redacted


def test_structured_log_patcher_drops_exception_text_and_secrets():
    output = StringIO()
    logger.remove()
    logger.configure(patcher=sanitize_log_record)
    sink = logger.add(output, serialize=True, diagnose=False, backtrace=False)
    try:
        try:
            raise RuntimeError(f"Bearer abc.def.ghi {settings.dashscope_api_key}")
        except RuntimeError:
            logger.bind(api_key=settings.dashscope_api_key).exception("provider failed")
    finally:
        logger.remove(sink)
        logger.configure(patcher=None)
        logger.add(sys.stderr)

    record = json.loads(output.getvalue())["record"]
    serialized = json.dumps(record, ensure_ascii=False)
    assert record["exception"] is None
    assert record["extra"]["exception_type"] == "RuntimeError"
    assert settings.dashscope_api_key not in serialized
    assert "abc.def.ghi" not in serialized


async def test_metrics_cover_business_and_model_costs(anonymous_client, monkeypatch):
    monkeypatch.setattr(settings, "llm_input_cost_per_million", 1.0)
    monkeypatch.setattr(settings, "llm_output_cost_per_million", 2.0)
    async with database_module.AsyncSessionLocal() as db:
        record = ChatRecord(
            tenant_id="tenant-a",
            user_id="user-a",
            session_id="metrics",
            question="not exported",
            answer="not exported",
            has_source=False,
            refused=True,
            need_human=True,
            tool_used=False,
            sources=[],
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            audit_status="completed",
        )
        document = Document(
            tenant_id="tenant-a",
            uploaded_by="user-a",
            filename="not-exported.txt",
            file_path="not-exported",
            status="failed",
        )
        db.add_all((record, document))
        await db.flush()
        db.add(
            IngestJob(
                document_id=document.id,
                tenant_id="tenant-a",
                status="failed",
                attempt=3,
                max_attempts=3,
            )
        )
        await db.commit()

    await anonymous_client.get("/health/live")
    response = await anonymous_client.get("/metrics")
    body = response.text
    assert response.status_code == 200
    for metric in (
        "enterprise_kb_http_requests_total",
        "enterprise_kb_qa_refused_total 1",
        "enterprise_kb_qa_refused_rate 1",
        "enterprise_kb_qa_human_total 1",
        "enterprise_kb_qa_human_rate 1",
        "enterprise_kb_documents_failed_total 1",
        "enterprise_kb_ingest_jobs_failed_total 1",
        "enterprise_kb_ingest_failure_rate 1",
        "enterprise_kb_ingest_retries_total 2",
        "enterprise_kb_model_tokens_total 30",
        "enterprise_kb_model_estimated_cost 5e-05",
        "enterprise_kb_model_retries_total",
        "enterprise_kb_model_timeouts_total",
    ):
        assert metric in body
    assert "not exported" not in body
    assert "not-exported" not in body
