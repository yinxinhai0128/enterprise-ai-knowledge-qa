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
        ("GET", "/admin/human-tasks", None),
        ("GET", "/admin/audits/pending", None),
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

    # /auth/login 是公开端点，无需 Bearer；其余业务路由必须声明安全方案
    public_paths = {"/health", "/health/live", "/health/ready", "/metrics", "/auth/login"}
    for path, operations in schema["paths"].items():
        if path in public_paths:
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
    worker_once,
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
    assert await worker_once() is True

    async with await _client(
        auth_headers(tenant_id="tenant-b", user_id="user-b")
    ) as tenant_b:
        listing = await tenant_b.get("/documents")
        assert listing.status_code == 200
        assert listing.json() == []
        assert (await tenant_b.get(f"/documents/{doc_id}")).status_code == 404

    content_a, evidence_a = search_tenant_knowledge_base("报销口令", "tenant-a")
    assert "青松" in content_a
    assert evidence_a
    assert search_tenant_knowledge_base("报销口令", "tenant-b")[1] == []


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


# ---------- 账号密码认证端点测试 ----------

async def test_register_and_login(client, auth_headers):
    """管理员注册新用户，新用户登录获取 Token。"""
    admin_headers = auth_headers(roles=("admin",))

    resp = await client.post(
        "/auth/register",
        json={"username": "testuser001", "password": "TestPass123", "tenant_id": "test", "roles": ["user"]},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "user_id" in body

    resp = await client.post(
        "/auth/login",
        json={"username": "testuser001", "password": "TestPass123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_login_wrong_password(client, auth_headers):
    admin_headers = auth_headers(roles=("admin",))

    await client.post(
        "/auth/register",
        json={"username": "testuser002", "password": "TestPass123", "tenant_id": "test", "roles": ["user"]},
        headers=admin_headers,
    )
    resp = await client.post(
        "/auth/login",
        json={"username": "testuser002", "password": "WrongPass"},
    )
    assert resp.status_code == 401


async def test_login_nonexistent_user(client):
    resp = await client.post(
        "/auth/login",
        json={"username": "no_such_user", "password": "whatever"},
    )
    assert resp.status_code == 401


async def test_register_requires_admin(client, auth_headers):
    """普通用户无法注册新账号。"""
    user_headers = auth_headers(roles=("user",))
    resp = await client.post(
        "/auth/register",
        json={"username": "testuser003", "password": "TestPass123", "tenant_id": "test", "roles": []},
        headers=user_headers,
    )
    assert resp.status_code == 403


async def test_register_duplicate_username(client, auth_headers):
    """重复注册同名用户返回 409。"""
    admin_headers = auth_headers(roles=("admin",))

    await client.post(
        "/auth/register",
        json={"username": "testuser004", "password": "TestPass123", "tenant_id": "test", "roles": []},
        headers=admin_headers,
    )
    resp = await client.post(
        "/auth/register",
        json={"username": "testuser004", "password": "AnotherPass1", "tenant_id": "test", "roles": []},
        headers=admin_headers,
    )
    assert resp.status_code == 409
