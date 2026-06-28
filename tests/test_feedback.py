"""回答反馈与会话搜索端点的测试。"""
from __future__ import annotations

from datetime import datetime, timezone

import app.core.database as database_module
from app.models.chat_record import ChatRecord


async def _insert_record(
    *,
    tenant_id: str = "tenant-a",
    user_id: str = "user-a",
    session_id: str = "sess-test",
    question: str = "测试问题",
    answer: str = "测试回答",
) -> int:
    """直接往测试库插入一条 ChatRecord，返回其 id。"""
    async with database_module.AsyncSessionLocal() as db:
        record = ChatRecord(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            question=question,
            answer=answer,
            has_source=False,
            refused=False,
            need_human=False,
            tool_used=False,
            sources=[],
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            latency_ms=0.0,
            audit_status="completed",
            created_at=datetime.now(timezone.utc),
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return record.id


# ---- /qa/feedback ----

async def test_submit_feedback_up(client):
    """成功提交 up 反馈，返回 ok=True。"""
    record_id = await _insert_record()
    resp = await client.post(
        "/qa/feedback",
        json={"record_id": record_id, "rating": "up"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # 验证数据库已写入
    async with database_module.AsyncSessionLocal() as db:
        from sqlalchemy import select
        row = (await db.execute(select(ChatRecord).where(ChatRecord.id == record_id))).scalar_one()
    assert row.feedback_rating == "up"
    assert row.feedback_comment is None


async def test_submit_feedback_down_with_comment(client):
    """提交 down + comment，两者都写入数据库。"""
    record_id = await _insert_record(question="另一个问题")
    resp = await client.post(
        "/qa/feedback",
        json={"record_id": record_id, "rating": "down", "comment": "回答不准确"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    async with database_module.AsyncSessionLocal() as db:
        from sqlalchemy import select
        row = (await db.execute(select(ChatRecord).where(ChatRecord.id == record_id))).scalar_one()
    assert row.feedback_rating == "down"
    assert row.feedback_comment == "回答不准确"


async def test_submit_feedback_nonexistent_record(client):
    """不存在的 record_id 返回 404。"""
    resp = await client.post(
        "/qa/feedback",
        json={"record_id": 999999, "rating": "up"},
    )
    assert resp.status_code == 404


async def test_submit_feedback_invalid_rating(client):
    """无效 rating 返回 422。"""
    record_id = await _insert_record(question="rating 校验测试")
    resp = await client.post(
        "/qa/feedback",
        json={"record_id": record_id, "rating": "meh"},
    )
    assert resp.status_code == 422


async def test_submit_feedback_comment_too_long(client):
    """comment 超过 200 字返回 422。"""
    record_id = await _insert_record(question="comment 长度测试")
    resp = await client.post(
        "/qa/feedback",
        json={"record_id": record_id, "rating": "down", "comment": "x" * 201},
    )
    assert resp.status_code == 422


async def test_submit_feedback_cross_tenant_blocked(client, auth_headers):
    """用户 A 的记录对租户 B 不可见，应返回 404。"""
    # 插入 tenant-a 的记录
    record_id = await _insert_record(tenant_id="tenant-a", user_id="user-a")

    # 用 tenant-b 的 token 来访问
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=auth_headers(tenant_id="tenant-b", user_id="user-b"),
    ) as ac:
        resp = await ac.post(
            "/qa/feedback",
            json={"record_id": record_id, "rating": "up"},
        )
    assert resp.status_code == 404


# ---- /qa/sessions/search ----

async def test_search_sessions_empty_query(client):
    """空 q 参数立即返回空列表，不查库。"""
    resp = await client.get("/qa/sessions/search", params={"q": "   "})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_search_sessions_no_q(client):
    """不带 q 参数返回空列表。"""
    resp = await client.get("/qa/sessions/search")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_search_sessions_finds_match(client):
    """关键词能匹配到已有记录，结果包含 record_id 和 session_id。"""
    await _insert_record(question="报销申请流程说明", session_id="sess-search-1")
    await _insert_record(question="年假申请规定", session_id="sess-search-2")

    resp = await client.get("/qa/sessions/search", params={"q": "报销"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["session_id"] == "sess-search-1"
    assert "报销" in data[0]["question"]
    assert "record_id" in data[0]
    assert "created_at" in data[0]


async def test_search_sessions_cross_user_isolated(client, auth_headers):
    """不同用户的记录不会出现在对方的搜索结果中。"""
    # 插入 user-b 的记录
    await _insert_record(
        tenant_id="tenant-a", user_id="user-b", question="user-b 的专属问题"
    )

    # 用 user-a (client 默认) 搜索，不应看到 user-b 的记录
    resp = await client.get("/qa/sessions/search", params={"q": "user-b"})
    assert resp.status_code == 200
    assert resp.json() == []
