"""文档摄入接口测试：上传成功、类型校验、落库。"""
from __future__ import annotations

import pytest


async def test_upload_success_then_indexed(client, vectorstore):
    """上传合法 txt：返回 201；后台索引跑完后状态变 indexed 且切片数 > 0。"""
    files = {"file": ("guide.txt", "公司报销流程：先在系统提单，再上传发票。".encode(), "text/plain")}
    resp = await client.post("/documents/upload", files=files)

    assert resp.status_code == 201
    body = resp.json()
    doc_id = body["id"]
    # POST 返回时状态还是 uploading（后台任务在响应后回填）
    assert body["status"] == "uploading"

    # 再查一次：ASGI 直连下 BackgroundTasks 已执行完，应为 indexed
    detail = await client.get(f"/documents/{doc_id}")
    assert detail.status_code == 200
    data = detail.json()
    assert data["status"] == "indexed"
    assert data["chunk_count"] > 0
    # 切片确实进了向量库
    assert vectorstore._collection.count() > 0


@pytest.mark.parametrize("filename", ["bad.zip", "evil.exe", "noext"])
async def test_upload_rejects_invalid_type(client, filename):
    """非 pdf/docx/xlsx/txt 一律 400，不落盘不索引。"""
    files = {"file": (filename, b"whatever", "application/octet-stream")}
    resp = await client.post("/documents/upload", files=files)
    assert resp.status_code == 400


async def test_upload_writes_db_and_lists(client, vectorstore):
    """上传后能在列表与详情接口查到该文档（验证写库）。"""
    files = {"file": ("policy.txt", b"hello knowledge base", "text/plain")}
    resp = await client.post("/documents/upload", files=files)
    doc_id = resp.json()["id"]

    listing = await client.get("/documents")
    assert listing.status_code == 200
    ids = [d["id"] for d in listing.json()]
    assert doc_id in ids

    detail = await client.get(f"/documents/{doc_id}")
    assert detail.json()["filename"] == "policy.txt"


async def test_get_missing_document_404(client):
    """查询不存在的文档返回 404。"""
    resp = await client.get("/documents/999999")
    assert resp.status_code == 404
