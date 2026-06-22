"""阶段 2 验收：JWT、角色、线程与租户隔离。"""
from __future__ import annotations

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import app.core.database as database_module
from app.core.retriever_tool import search_tenant_knowledge_base
from app.models.chat_record import ChatRecord


async def _client(headers: dict[str, str]) -> AsyncClient:
    from app.main import app

    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=headers,
    )


async def test_missing_token_is_401_on_all_business_routes(anonymous_client):
    """健康检查之外的业务入口不允许匿名访问。"""
    requests = (
        ("GET", "/documents", None),
        ("GET", "/documents/1", None),
        ("POST", "/documents/upload", None),
        ("POST", "/qa/ask", {"question": "测试", "session_id": "s1"}),
        ("GET", "/qa/history/s1", None),
        ("GET", "/admin/stats", None),
        ("GET", "/admin/refused", None),
        ("GET", "/admin/human", None),
    )
    for method, path, payload in requests:
        response = await anonymous_client.request(method, path, json=payload)
        assert response.status_code == 401, (method, path, response.text)

    invalid = await anonymous_client.get(
        "/documents",
        headers={"Authorization": "Bearer not-a-valid-jwt"},
    )
    assert invalid.status_code == 401


async def test_user_role_cannot_access_admin(client):
    response = await client.get("/admin/stats")
    assert response.status_code == 403


async def test_openapi_declares_bearer_security(anonymous_client):
    schema = (await anonymous_client.get("/openapi.json")).json()
    schemes = schema["components"]["securitySchemes"]
    assert schemes["BearerAuth"]["type"] == "http"
    assert schemes["BearerAuth"]["scheme"] == "bearer"

    for path, operations in schema["paths"].items():
        if path == "/health":
            continue
        for operation in operations.values():
            assert {"BearerAuth": []} in operation.get("security", []), path


async def test_forged_body_user_id_is_ignored(
    client,
    agent_factory,
):
    agent_factory(["测试回答。"])
    response = await client.post(
        "/qa/ask",
        json={
            "question": "身份来自哪里",
            "session_id": "forged",
            "user_id": "attacker-chosen-user",
        },
    )
    assert response.status_code == 200

    async with database_module.AsyncSessionLocal() as db:
        record = (
            await db.execute(select(ChatRecord).where(ChatRecord.question == "身份来自哪里"))
        ).scalar_one()
    assert record.tenant_id == "tenant-a"
    assert record.user_id == "user-a"
    assert record.session_id == "tenant-a:user-a:forged"


async def test_user_cannot_read_another_users_thread(
    auth_headers,
    agent_factory,
):
    agent_factory(["用户 A 的私有回答。"])
    async with await _client(
        auth_headers(tenant_id="tenant-a", user_id="user-a")
    ) as user_a:
        response = await user_a.post(
            "/qa/ask",
            json={"question": "私有问题", "session_id": "private"},
        )
        assert response.status_code == 200

    async with await _client(
        auth_headers(tenant_id="tenant-a", user_id="user-b")
    ) as user_b:
        # 即使猜到内部 thread ID，也不能作为客户端 session_id 读取。
        forbidden = await user_b.get("/qa/history/tenant-a:user-a:private")
        assert forbidden.status_code == 404

        own_view = await user_b.get("/qa/history/private")
        assert own_view.status_code == 200
        assert own_view.json()["messages"] == []


async def test_tenant_cannot_list_get_or_retrieve_other_tenant_document(
    auth_headers,
    vectorstore,
):
    async with await _client(
        auth_headers(tenant_id="tenant-a", user_id="user-a")
    ) as tenant_a:
        uploaded = await tenant_a.post(
            "/documents/upload",
            files={
                "file": (
                    "tenant-a.txt",
                    "租户 A 的专属报销口令是青松。".encode(),
                    "text/plain",
                )
            },
        )
        assert uploaded.status_code == 201
        doc_id = uploaded.json()["id"]

    async with await _client(
        auth_headers(tenant_id="tenant-b", user_id="user-b")
    ) as tenant_b:
        listing = await tenant_b.get("/documents")
        assert listing.status_code == 200
        assert listing.json() == []
        assert (await tenant_b.get(f"/documents/{doc_id}")).status_code == 404

    assert "青松" in search_tenant_knowledge_base("报销口令", "tenant-a")
    assert search_tenant_knowledge_base("报销口令", "tenant-b") == "未找到相关文档"


async def test_admin_queries_are_limited_to_token_tenant(
    auth_headers,
    vectorstore,
):
    async with await _client(
        auth_headers(tenant_id="tenant-a", user_id="u1")
    ) as tenant_a_user:
        await tenant_a_user.post(
            "/documents/upload",
            files={"file": ("a.txt", b"tenant a", "text/plain")},
        )

    async with await _client(
        auth_headers(tenant_id="tenant-b", user_id="u2", roles=("admin",))
    ) as tenant_b_admin:
        response = await tenant_b_admin.get("/admin/stats")
        assert response.status_code == 200
        assert response.json()["documents"]["total"] == 0
