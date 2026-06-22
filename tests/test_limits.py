"""阶段 4：请求限流、并发和每日模型预算验收。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from sqlalchemy import select

import app.core.database as database_module
from app.config import settings
from app.core.limits import request_limiter
from app.models.usage_daily import UsageDaily


async def test_million_character_question_returns_422(client):
    response = await client.post(
        "/qa/ask",
        json={"question": "x" * 1_000_000, "session_id": "huge"},
    )
    assert response.status_code == 422


async def test_overlong_session_id_returns_422(client):
    response = await client.post(
        "/qa/ask",
        json={
            "question": "正常问题",
            "session_id": "s" * (settings.max_session_id_chars + 1),
        },
    )
    assert response.status_code == 422


async def test_qa_ask_rate_limit_returns_429(client, agent_factory, monkeypatch):
    monkeypatch.setattr(settings, "qa_rate_limit_per_minute", 1)
    agent_factory(["第一轮无证据回答。"])
    first = await client.post(
        "/qa/ask",
        json={"question": "第一问", "session_id": "rate-1"},
    )
    second = await client.post(
        "/qa/ask",
        json={"question": "第二问", "session_id": "rate-2"},
    )
    assert first.status_code == 200
    assert second.status_code == 429
    assert "Retry-After" in second.headers


async def test_upload_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(settings, "upload_rate_limit_per_minute", 1)
    first = await client.post(
        "/documents/upload",
        files={"file": ("one.txt", b"one", "text/plain")},
    )
    second = await client.post(
        "/documents/upload",
        files={"file": ("two.txt", b"two", "text/plain")},
    )
    assert first.status_code == 201
    assert second.status_code == 429


async def test_admin_rate_limit_returns_429(auth_headers, monkeypatch):
    from app.main import app

    monkeypatch.setattr(settings, "admin_rate_limit_per_minute", 1)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=auth_headers(roles=("admin",)),
    ) as admin:
        first = await admin.get("/admin/stats")
        second = await admin.get("/admin/stats")
    assert first.status_code == 200
    assert second.status_code == 429


async def test_concurrency_limit_rejects_second_active_request():
    async with request_limiter.limit(
        scope="concurrency-test",
        identity="tenant:user",
        per_minute=10,
        max_concurrency=1,
    ):
        with pytest.raises(HTTPException) as caught:
            async with request_limiter.limit(
                scope="concurrency-test",
                identity="tenant:user",
                per_minute=10,
                max_concurrency=1,
            ):
                pass
    assert caught.value.status_code == 429


async def test_daily_model_call_budget_is_persistent(
    client,
    agent_factory,
    monkeypatch,
):
    monkeypatch.setattr(settings, "daily_user_model_calls", 4)
    monkeypatch.setattr(settings, "daily_tenant_model_calls", 4)
    monkeypatch.setattr(settings, "daily_user_token_budget", 1_000_000)
    monkeypatch.setattr(settings, "daily_tenant_token_budget", 1_000_000)
    agent_factory(["第一轮回答。"])

    first = await client.post(
        "/qa/ask",
        json={"question": "预算第一问", "session_id": "budget-1"},
    )
    second = await client.post(
        "/qa/ask",
        json={"question": "预算第二问", "session_id": "budget-2"},
    )
    assert first.status_code == 200
    assert second.status_code == 429

    async with database_module.AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(UsageDaily).where(
                    UsageDaily.usage_date == datetime.now(timezone.utc).date()
                )
            )
        ).scalar_one()
    assert row.model_calls_reserved == settings.max_model_calls_per_request
    assert row.tokens_reserved > 0


async def test_daily_token_budget_rejects_before_model(client, monkeypatch):
    monkeypatch.setattr(settings, "daily_user_token_budget", 1)
    monkeypatch.setattr(settings, "daily_tenant_token_budget", 1)
    response = await client.post(
        "/qa/ask",
        json={"question": "不会调用模型", "session_id": "token-budget"},
    )
    assert response.status_code == 429
    assert "Token" in response.json()["detail"]


async def test_single_request_model_call_limit_returns_429(
    client,
    vectorstore,
    agent_factory,
    monkeypatch,
):
    monkeypatch.setattr(settings, "max_model_calls_per_request", 1)
    monkeypatch.setattr(settings, "max_retrieval_calls_per_request", 10)
    agent_factory(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_knowledge_base",
                        "args": {"query": "first"},
                        "id": "limit-model-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="第二次模型调用不应发生"),
        ]
    )
    response = await client.post(
        "/qa/ask",
        json={"question": "模型调用限制", "session_id": "model-limit"},
    )
    assert response.status_code == 429
    assert "Agent" in response.json()["detail"]


def test_all_resource_limits_have_safe_configured_defaults():
    positive_limits = (
        "llm_max_output_tokens",
        "agent_max_steps",
        "max_model_calls_per_request",
        "max_retrieval_calls_per_request",
        "max_question_chars",
        "max_session_id_chars",
        "max_filename_chars",
        "max_file_size_bytes",
        "upload_chunk_bytes",
        "upload_write_timeout_seconds",
        "file_validation_timeout_seconds",
        "parser_timeout_seconds",
        "parser_workers",
        "max_archive_entries",
        "max_archive_uncompressed_bytes",
        "max_archive_compression_ratio",
        "max_pdf_pages",
        "max_xlsx_sheets",
        "max_xlsx_cells",
        "max_parsed_chars",
        "qa_rate_limit_per_minute",
        "upload_rate_limit_per_minute",
        "admin_rate_limit_per_minute",
        "qa_max_concurrency",
        "upload_max_concurrency",
        "admin_max_concurrency",
        "daily_user_model_calls",
        "daily_tenant_model_calls",
        "daily_user_token_budget",
        "daily_tenant_token_budget",
    )
    assert all(getattr(settings, name) > 0 for name in positive_limits)
