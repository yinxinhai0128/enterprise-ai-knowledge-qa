"""Business scenario smoke test: e-commerce knowledge-base support flow."""
from __future__ import annotations

from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage


async def test_ecommerce_after_sales_support_flow(
    client,
    auth_headers,
    vectorstore,
    agent_factory,
    worker_once,
):
    """Operations uploads policy docs, support asks, admin reviews, tenant stays isolated."""
    policy = (
        "MallPro after-sales policy. "
        "Orders for apparel can be returned within 7 days after signing if tags are intact. "
        "Refunds are returned to the original payment account within 3 business days after "
        "warehouse inspection. "
        "A consumer electronics price-protection claim can be submitted within 48 hours "
        "after payment if the same SKU drops in price. "
        "Fresh food and customized products are not eligible for no-reason returns."
    )
    upload = await client.post(
        "/documents/upload",
        files={"file": ("mallpro-after-sales.txt", policy.encode(), "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    doc_id = upload.json()["id"]
    assert await worker_once() is True

    detail = await client.get(f"/documents/{doc_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "indexed"
    assert any(
        doc.metadata.get("source") == "mallpro-after-sales.txt"
        for doc in vectorstore.docstore._dict.values()
    )

    agent_factory(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_knowledge_base",
                        "args": {"query": "apparel return 7 days refund 3 business days"},
                        "id": "call-ecommerce-policy",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content=(
                    "Apparel orders can be returned within 7 days after signing if tags "
                    "are intact. After warehouse inspection, the refund returns to the "
                    "original payment account within 3 business days."
                )
            ),
        ]
    )
    ask = await client.post(
        "/qa/ask",
        json={
            "question": "A customer wants to return an apparel order. What is the window and refund SLA?",
            "session_id": "mallpro-cs-001",
        },
    )
    assert ask.status_code == 200, ask.text
    answer = ask.json()
    assert answer["refused"] is False
    assert answer["need_human"] is False
    assert "7 days" in answer["answer"]
    assert "3 business days" in answer["answer"]
    assert len(answer["sources"]) == 1
    assert answer["sources"][0]["source"] == "mallpro-after-sales.txt"
    assert "apparel" in answer["sources"][0]["snippet"].lower()

    history = await client.get("/qa/history/mallpro-cs-001")
    assert history.status_code == 200
    assert any("apparel order" in item["content"] for item in history.json()["messages"])

    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=auth_headers(roles=("admin",)),
    ) as admin:
        stats = (await admin.get("/admin/stats")).json()["qa"]
    assert stats["total"] == 1
    assert stats["refused_rate"] == 0.0

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=auth_headers(tenant_id="tenant-b", user_id="user-b"),
    ) as other_tenant:
        other_docs = await other_tenant.get("/documents")
        other_detail = await other_tenant.get(f"/documents/{doc_id}")
    assert other_docs.status_code == 200
    assert other_docs.json() == []
    assert other_detail.status_code == 404
