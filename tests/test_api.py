"""端到端测试：上传 -> 索引 -> 问答 -> 历史。"""
from __future__ import annotations

from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import select

import app.core.database as database_module
from app.models.chat_record import ChatRecord


async def test_health_is_minimal_and_has_security_headers(client):
    """健康检查不泄露组件信息，且所有响应都带基础安全头。"""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


async def test_production_disables_api_documentation(monkeypatch):
    """生产模式不注册 Swagger、ReDoc 和 OpenAPI JSON 路由。"""
    from app.config import settings
    from app.main import create_app

    monkeypatch.setattr(settings, "app_env", "production")
    production_app = create_app()
    transport = ASGITransport(app=production_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            response = await client.get(path)
            assert response.status_code == 404
            assert "strict-transport-security" in response.headers


async def test_end_to_end_upload_index_ask(
    client, vectorstore, agent_factory, worker_once
):
    """完整链路：上传文档、确认索引、提问拿到结构化回答、历史可回溯。"""
    # 1) 上传并完成索引
    files = {"file": ("e2e.txt", "差旅报销标准：市内交通每日上限 50 元。".encode(), "text/plain")}
    up = await client.post("/documents/upload", files=files)
    assert up.status_code == 201
    doc_id = up.json()["id"]
    assert await worker_once() is True

    detail = await client.get(f"/documents/{doc_id}")
    assert detail.json()["status"] == "indexed"
    assert vectorstore._collection.count() > 0

    # 2) 假模型先真实调用检索工具，再生成不带可信来源的正文。
    agent = agent_factory(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_knowledge_base",
                        "args": {"query": "市内交通报销上限"},
                        "id": "call-e2e",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="差旅报销市内交通每日上限 50 元。"),
        ]
    )
    ask = await client.post(
        "/qa/ask",
        json={"question": "市内交通报销上限是多少", "user_id": "u1", "session_id": "e2e"},
    )
    assert ask.status_code == 200
    data = ask.json()
    assert "50" in data["answer"]
    assert len(data["sources"]) == 1
    assert data["sources"][0]["source"] == "e2e.txt"
    assert data["sources"][0]["chunk_id"]
    snapshot = await agent.aget_state(
        {"configurable": {"thread_id": "tenant-a:user-a:e2e"}}
    )
    tool_message = next(
        message
        for message in snapshot.values["messages"]
        if isinstance(message, ToolMessage)
    )
    assert data["sources"] == tool_message.artifact
    assert data["refused"] is False
    assert data["need_human"] is False

    # 3) 历史可回溯到刚才的提问
    hist = await client.get("/qa/history/e2e")
    assert hist.status_code == 200
    contents = [m["content"] for m in hist.json()["messages"]]
    assert "市内交通报销上限是多少" in contents


async def test_ask_empty_question_rejected(client, agent_factory):
    """空问题被 400 拦下（pydantic min_length 校验）。"""
    agent_factory(["不该被调用。"])
    resp = await client.post(
        "/qa/ask",
        json={"question": "", "user_id": "u1", "session_id": "x"},
    )
    assert resp.status_code == 422  # 入参校验失败


async def test_structured_refusal_updates_admin_stats(
    client,
    auth_headers,
    vectorstore,
    agent_factory,
):
    """空 artifact 强制 refused=true，并由数据库布尔字段驱动管理统计。"""
    agent_factory(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_knowledge_base",
                        "args": {"query": "不存在的规定"},
                        "id": "call-empty-api",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="模型试图继续回答。"),
        ]
    )
    response = await client.post(
        "/qa/ask",
        json={"question": "不存在的规定", "session_id": "refused-stats"},
    )
    assert response.status_code == 200
    assert response.json()["refused"] is True
    assert response.json()["sources"] == []

    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=auth_headers(roles=("admin",)),
    ) as admin:
        stats = (await admin.get("/admin/stats")).json()
        refused = (await admin.get("/admin/refused")).json()
    assert stats["qa"]["total"] == 1
    assert stats["qa"]["refused_rate"] == 1.0
    assert len(refused) == 1
    assert refused[0]["refused"] is True


async def test_admin_rates_and_recent_lists_are_exact(auth_headers):
    records = [
        ChatRecord(
            tenant_id="tenant-a",
            user_id="user-a",
            session_id=f"admin-rate-{index}",
            question=f"question-{index}",
            answer=f"answer-{index}",
            has_source=not refused,
            refused=refused,
            need_human=need_human,
            tool_used=False,
            sources=[],
            audit_status="completed",
        )
        for index, (refused, need_human) in enumerate(
            ((False, False), (True, False), (False, True), (True, False)),
            start=1,
        )
    ]
    async with database_module.AsyncSessionLocal() as db:
        db.add_all(records)
        await db.commit()

    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=auth_headers(roles=("admin",)),
    ) as admin:
        stats = (await admin.get("/admin/stats")).json()["qa"]
        refused = (await admin.get("/admin/refused")).json()
        human = (await admin.get("/admin/human")).json()

    assert stats == {"total": 4, "refused_rate": 0.5, "human_rate": 0.25}
    assert [row["session_id"] for row in refused] == ["admin-rate-4", "admin-rate-2"]
    assert [row["session_id"] for row in human] == ["admin-rate-3"]

    async with database_module.AsyncSessionLocal() as db:
        rows = (await db.execute(select(ChatRecord))).scalars().all()
    assert len(rows) == 4
