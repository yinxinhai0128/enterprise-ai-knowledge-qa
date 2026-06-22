"""阶段 6：会话、审计、人工任务和分类访问策略验收。"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import select

import app.core.database as database_module
import app.services.audit as audit_service
from app.agent.agent import create_enterprise_agent
from app.agent.context import EnterpriseContext
from app.config import settings
from app.core.checkpointer import close_checkpointer, init_checkpointer
from app.models.chat_record import ChatRecord
from app.models.conversation_session import ConversationSession
from app.models.human_task import HumanTask, HumanTaskEvent
from app.services.audit import AuditWriteError, complete_audit, start_audit
from app.services.conversations import (
    SessionBusyError,
    acquire_conversation,
    cleanup_expired_conversations,
    release_conversation,
    utcnow,
)
from app.services.sensitive_policy import classify_question, denied_match


class FakeModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
        return self


def _context(session: str) -> EnterpriseContext:
    return EnterpriseContext(
        session_id=f"tenant-a:user-a:{session}",
        tenant_id="tenant-a",
        user_id="user-a",
    )


def _config(session: str) -> dict:
    return {"configurable": {"thread_id": f"tenant-a:user-a:{session}"}}


async def test_checkpoint_survives_restart_and_two_worker_connections(tmp_path):
    path = tmp_path / "shared-checkpoints.db"
    config = _config("persist")
    async with AsyncSqliteSaver.from_conn_string(str(path)) as first_saver:
        first = create_enterprise_agent(
            model=FakeModel(messages=iter([AIMessage(content="第一轮")])),
            checkpointer=first_saver,
        )
        await first.ainvoke(
            {"messages": [{"role": "user", "content": "第一问"}]},
            config=config,
            context=_context("persist"),
        )

    # 新连接和新 Agent 模拟进程重启/另一 Worker。
    async with AsyncSqliteSaver.from_conn_string(str(path)) as second_saver:
        second = create_enterprise_agent(
            model=FakeModel(messages=iter([AIMessage(content="第二轮")])),
            checkpointer=second_saver,
        )
        await second.ainvoke(
            {"messages": [{"role": "user", "content": "第二问"}]},
            config=config,
            context=_context("persist"),
        )
        snapshot = await second.aget_state(config)
    humans = [m.content for m in snapshot.values["messages"] if isinstance(m, HumanMessage)]
    assert humans == ["第一问", "第二问"]


async def test_two_open_checkpointer_connections_share_latest_state(tmp_path):
    path = tmp_path / "multi-worker.db"
    connection_a = await aiosqlite.connect(path)
    connection_b = await aiosqlite.connect(path)
    saver_a = AsyncSqliteSaver(connection_a)
    saver_b = AsyncSqliteSaver(connection_b)
    await saver_a.setup()
    await saver_b.setup()
    config = _config("workers")
    try:
        worker_a = create_enterprise_agent(
            model=FakeModel(messages=iter([AIMessage(content="A 回答")])),
            checkpointer=saver_a,
        )
        worker_b = create_enterprise_agent(
            model=FakeModel(messages=iter([AIMessage(content="B 回答")])),
            checkpointer=saver_b,
        )
        await worker_a.ainvoke(
            {"messages": [{"role": "user", "content": "A 问题"}]},
            config=config,
            context=_context("workers"),
        )
        await worker_b.ainvoke(
            {"messages": [{"role": "user", "content": "B 问题"}]},
            config=config,
            context=_context("workers"),
        )
        snapshot = await worker_a.aget_state(config)
        humans = [
            message.content
            for message in snapshot.values["messages"]
            if isinstance(message, HumanMessage)
        ]
        assert humans == ["A 问题", "B 问题"]
    finally:
        await connection_a.close()
        await connection_b.close()


async def test_conversation_lease_serializes_workers():
    first = await acquire_conversation(
        thread_id="tenant-a:user-a:locked",
        tenant_id="tenant-a",
        user_id="user-a",
        client_session_id="locked",
    )
    with pytest.raises(SessionBusyError):
        await acquire_conversation(
            thread_id="tenant-a:user-a:locked",
            tenant_id="tenant-a",
            user_id="user-a",
            client_session_id="locked",
        )
    await release_conversation(first, 2)
    second = await acquire_conversation(
        thread_id="tenant-a:user-a:locked",
        tenant_id="tenant-a",
        user_id="user-a",
        client_session_id="locked",
    )
    await release_conversation(second, 4)


async def test_api_enforces_message_limit(client, agent_factory, monkeypatch):
    monkeypatch.setattr(settings, "conversation_max_messages", 4)
    agent_factory(["回答一", "回答二", "回答三"])
    for index in range(3):
        response = await client.post(
            "/qa/ask",
            json={"question": f"问题{index}", "session_id": "bounded"},
        )
        assert response.status_code == 200
    history = await client.get("/qa/history/bounded")
    assert len(history.json()["messages"]) <= 4
    async with database_module.AsyncSessionLocal() as db:
        session = await db.get(ConversationSession, "tenant-a:user-a:bounded")
        assert session.message_count <= 4


async def test_cleanup_deletes_expired_session_and_checkpoint(tmp_path):
    await close_checkpointer()
    saver = await init_checkpointer(tmp_path / "cleanup.db")
    config = _config("expired")
    agent = create_enterprise_agent(
        model=FakeModel(messages=iter([AIMessage(content="旧回答")])),
        checkpointer=saver,
    )
    try:
        await agent.ainvoke(
            {"messages": [{"role": "user", "content": "旧问题"}]},
            config=config,
            context=_context("expired"),
        )
        async with database_module.AsyncSessionLocal() as db:
            db.add(
                ConversationSession(
                    thread_id="tenant-a:user-a:expired",
                    tenant_id="tenant-a",
                    user_id="user-a",
                    client_session_id="expired",
                    expires_at=utcnow() - timedelta(days=1),
                )
            )
            await db.commit()
        assert await cleanup_expired_conversations() == 1
        assert (await agent.aget_state(config)).values == {}
        async with database_module.AsyncSessionLocal() as db:
            assert await db.get(ConversationSession, "tenant-a:user-a:expired") is None
    finally:
        await close_checkpointer()


async def test_audit_retries_then_completes_and_persistent_failure_stays_pending(
    monkeypatch, auth_headers
):
    audit_id = await start_audit(
        trace_id="trace-retry",
        session_id="tenant-a:user-a:audit",
        tenant_id="tenant-a",
        user_id="user-a",
        question="审计重试",
    )
    original_commit = audit_service._commit
    calls = 0

    async def fail_once(db):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient")
        await original_commit(db)

    monkeypatch.setattr(audit_service, "_commit", fail_once)
    await complete_audit(
        audit_id=audit_id,
        trace_id="trace-retry",
        session_id="tenant-a:user-a:audit",
        tenant_id="tenant-a",
        user_id="user-a",
        question="审计重试",
        answer="完成",
        has_source=False,
        refused=True,
        need_human=False,
        tool_used=False,
        sources=[],
        input_tokens=1,
        output_tokens=2,
        total_tokens=3,
        latency_ms=12.5,
        policy_matches=[],
    )
    assert calls == 2
    async with database_module.AsyncSessionLocal() as db:
        record = await db.get(ChatRecord, audit_id)
        assert record.audit_status == "completed"
        assert record.total_tokens == 3

    monkeypatch.setattr(audit_service, "_commit", original_commit)
    pending_id = await start_audit(
        trace_id="trace-pending",
        session_id="tenant-a:user-a:pending",
        tenant_id="tenant-a",
        user_id="user-a",
        question="持久失败",
    )

    async def always_fail(db):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(audit_service, "_commit", always_fail)
    monkeypatch.setattr(settings, "audit_write_retries", 2)
    with pytest.raises(AuditWriteError):
        await complete_audit(
            audit_id=pending_id,
            trace_id="trace-pending",
            session_id="tenant-a:user-a:pending",
            tenant_id="tenant-a",
            user_id="user-a",
            question="持久失败",
            answer="不得交付",
            has_source=False,
            refused=True,
            need_human=False,
            tool_used=False,
            sources=[],
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            latency_ms=1,
            policy_matches=[],
        )
    async with database_module.AsyncSessionLocal() as db:
        record = await db.get(ChatRecord, pending_id)
        assert record.audit_status == "pending"
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=auth_headers(roles=("admin",)),
    ) as admin:
        pending = await admin.get("/admin/audits/pending")
    assert [record["id"] for record in pending.json()] == [pending_id]


async def test_salary_policy_denies_user_and_human_task_lifecycle(
    client, auth_headers
):
    denied = await client.post(
        "/qa/ask",
        json={"question": "我工资为什么这么低", "session_id": "salary"},
    )
    assert denied.status_code == 403
    task_id = denied.json()["detail"]["human_task_id"]
    assert task_id is not None

    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=auth_headers(user_id="admin-a", roles=("admin",)),
    ) as admin:
        queued = await admin.get("/admin/human-tasks?status=pending")
        assert [task["id"] for task in queued.json()] == [task_id]
        claimed = await admin.post(f"/admin/human-tasks/{task_id}/claim")
        assert claimed.json()["status"] == "claimed"
        completed = await admin.post(
            f"/admin/human-tasks/{task_id}/complete",
            json={"resolution": "已由 HR 线下答复"},
        )
        assert completed.json()["status"] == "completed"
        events = await admin.get(f"/admin/human-tasks/{task_id}/events")
    assert [event["action"] for event in events.json()] == [
        "created",
        "claimed",
        "completed",
    ]


async def test_authorized_hr_can_continue_but_still_creates_review_task(
    auth_headers, agent_factory
):
    from app.main import app

    agent_factory(["HR 可查看该受控问题。"])
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=auth_headers(roles=("user", "hr")),
    ) as hr:
        response = await hr.post(
            "/qa/ask",
            json={"question": "查询我的薪资明细", "session_id": "hr-access"},
        )
    assert response.status_code == 200
    assert response.json()["need_human"] is True
    assert response.json()["human_task_id"] is not None


@pytest.mark.parametrize(
    ("question", "category"),
    [
        ("查询我的薪资明细", "salary"),
        ("查询我的健康记录", "health"),
        ("我想发起诉讼", "legal"),
    ],
)
def test_classified_data_requires_role(question, category):
    matches = classify_question(question)
    denied = denied_match(matches, frozenset({"user"}))
    assert denied is not None
    assert denied.category == category


def test_rules_avoid_plain_substring_false_positive():
    assert classify_question("这份工资质检算法说明") == []
    assert classify_question("公司的病假制度有多少天") == []
