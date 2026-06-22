"""端到端测试：上传 -> 索引 -> 问答 -> 历史。"""
from __future__ import annotations

from httpx import ASGITransport, AsyncClient


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


async def test_end_to_end_upload_index_ask(client, vectorstore, agent_factory):
    """完整链路：上传文档、确认索引、提问拿到结构化回答、历史可回溯。"""
    # 1) 上传并完成索引
    files = {"file": ("e2e.txt", "差旅报销标准：市内交通每日上限 50 元。".encode(), "text/plain")}
    up = await client.post("/documents/upload", files=files)
    assert up.status_code == 201
    doc_id = up.json()["id"]

    detail = await client.get(f"/documents/{doc_id}")
    assert detail.json()["status"] == "indexed"
    assert vectorstore._collection.count() > 0

    # 2) 准备脚本化 Agent（让回答带来源），再提问
    agent_factory(["差旅报销市内交通每日上限 50 元。[来源:e2e.txt]"])
    ask = await client.post(
        "/qa/ask",
        json={"question": "市内交通报销上限是多少", "user_id": "u1", "session_id": "e2e"},
    )
    assert ask.status_code == 200
    data = ask.json()
    assert "50" in data["answer"]
    assert "e2e.txt" in data["sources"]
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
