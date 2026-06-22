"""文档摄入接口测试：上传成功、类型校验、落库。"""
from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook
from pypdf import PdfWriter
from sqlalchemy import select

import app.core.database as database_module
from app.config import settings
from app.core.process_pool import get_parser_pool
from app.models.document import Document
from app.services.file_security import (
    MalwareScanResult,
    configure_malware_scanner,
    reset_malware_scanner,
)
from app.services.ingest import IngestResult, ingest_document


def _pdf_bytes(pages: int) -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    writer.write(output)
    return output.getvalue()


def _xlsx_bytes(*, cells: int = 1, sheets: int = 1) -> bytes:
    output = io.BytesIO()
    workbook = Workbook()
    first = workbook.active
    first.title = "sheet-1"
    for index in range(cells):
        first.cell(row=1, column=index + 1, value="x")
    for index in range(1, sheets):
        workbook.create_sheet(f"sheet-{index + 1}")
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _oversized_docx_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "x" * 2048)
    return output.getvalue()


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
    stored = vectorstore._collection.get(include=["metadatas"])
    assert stored["ids"][0] == stored["metadatas"][0]["chunk_id"]
    assert len(stored["ids"][0]) == 64  # SHA-256 稳定 ID，而非 Chroma 自动 UUID


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


async def test_300_character_filename_rejected(client):
    filename = f"{'a' * 296}.txt"
    response = await client.post(
        "/documents/upload",
        files={"file": (filename, b"safe", "text/plain")},
    )
    assert response.status_code == 400
    assert "文件名" in response.json()["detail"]


async def test_empty_file_rejected(client):
    response = await client.post(
        "/documents/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "空文件"


async def test_configured_file_size_limit_returns_413(client, monkeypatch):
    assert settings.max_file_size_bytes == 50 * 1024 * 1024
    monkeypatch.setattr(settings, "max_file_size_bytes", 10)
    response = await client.post(
        "/documents/upload",
        files={"file": ("large.txt", b"x" * 11, "text/plain")},
    )
    assert response.status_code == 413


async def test_extension_spoofing_rejected(client):
    response = await client.post(
        "/documents/upload",
        files={"file": ("fake.pdf", b"this is not a pdf", "application/pdf")},
    )
    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]


async def test_mime_mismatch_rejected(client):
    response = await client.post(
        "/documents/upload",
        files={"file": ("fake.txt", b"plain text", "application/pdf")},
    )
    assert response.status_code == 400
    assert "MIME" in response.json()["detail"]


async def test_total_text_limit_returns_413(client, monkeypatch):
    monkeypatch.setattr(settings, "max_parsed_chars", 3)
    response = await client.post(
        "/documents/upload",
        files={"file": ("text.txt", b"four", "text/plain")},
    )
    assert response.status_code == 413
    assert "字符数" in response.json()["detail"]


async def test_pdf_page_limit_returns_413(client, monkeypatch):
    monkeypatch.setattr(settings, "max_pdf_pages", 1)
    response = await client.post(
        "/documents/upload",
        files={"file": ("pages.pdf", _pdf_bytes(2), "application/pdf")},
    )
    assert response.status_code == 413
    assert "页上限" in response.json()["detail"]


async def test_xlsx_cell_and_sheet_limits(client, monkeypatch):
    monkeypatch.setattr(settings, "max_xlsx_cells", 1)
    cells = await client.post(
        "/documents/upload",
        files={
            "file": (
                "cells.xlsx",
                _xlsx_bytes(cells=2),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert cells.status_code == 413
    assert "单元格" in cells.json()["detail"]

    monkeypatch.setattr(settings, "max_xlsx_cells", 100)
    monkeypatch.setattr(settings, "max_xlsx_sheets", 1)
    sheets = await client.post(
        "/documents/upload",
        files={
            "file": (
                "sheets.xlsx",
                _xlsx_bytes(sheets=2),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert sheets.status_code == 413
    assert "工作表" in sheets.json()["detail"]


async def test_archive_expansion_limit_returns_413(client, monkeypatch):
    monkeypatch.setattr(settings, "max_archive_uncompressed_bytes", 100)
    monkeypatch.setattr(settings, "max_archive_compression_ratio", 10_000.0)
    response = await client.post(
        "/documents/upload",
        files={
            "file": (
                "bomb.docx",
                _oversized_docx_zip(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 413
    assert "展开后" in response.json()["detail"]


async def test_successful_file_promoted_out_of_quarantine(client, vectorstore):
    response = await client.post(
        "/documents/upload",
        files={"file": ("trusted.txt", b"trusted text", "text/plain")},
    )
    assert response.status_code == 201
    async with database_module.AsyncSessionLocal() as db:
        document = (
            await db.execute(select(Document).where(Document.id == response.json()["id"]))
        ).scalar_one()
    parts = Path(document.file_path).parts
    assert "documents" in parts
    assert "quarantine" not in parts


async def test_parser_error_is_sanitized(tmp_path):
    missing = tmp_path / "private" / "secret.txt"
    result = await ingest_document(
        doc_id=1,
        file_path=str(missing),
        source="secret.txt",
        tenant_id="tenant-a",
        uploaded_by="user-a",
    )
    assert result.success is False
    assert result.error_msg == "文档解析失败"
    assert str(tmp_path) not in result.error_msg


def test_parser_uses_independent_process_pool():
    from concurrent.futures import ProcessPoolExecutor

    assert isinstance(get_parser_pool(), ProcessPoolExecutor)


async def test_parser_timeout_is_explicit_and_stays_quarantined(
    client,
    monkeypatch,
):
    monkeypatch.setattr(settings, "parser_timeout_seconds", 0.000001)
    response = await client.post(
        "/documents/upload",
        files={"file": ("timeout.txt", b"safe text", "text/plain")},
    )
    assert response.status_code == 201
    detail = await client.get(f"/documents/{response.json()['id']}")
    assert detail.json()["status"] == "failed"
    assert detail.json()["error_msg"] == "文档解析超时"
    async with database_module.AsyncSessionLocal() as db:
        document = await db.get(Document, response.json()["id"])
    assert "quarantine" in Path(document.file_path).parts


async def test_malware_scanner_can_reject_quarantined_file(client):
    class RejectingScanner:
        async def scan(self, path: Path) -> MalwareScanResult:
            return MalwareScanResult(clean=False, scanned=True)

    configure_malware_scanner(RejectingScanner())
    try:
        response = await client.post(
            "/documents/upload",
            files={"file": ("malware.txt", b"test payload", "text/plain")},
        )
    finally:
        reset_malware_scanner()
    assert response.status_code == 400
    assert "恶意软件" in response.json()["detail"]


async def test_slow_upload_background_work_does_not_block_health(
    client,
    monkeypatch,
):
    monkeypatch.setattr(settings, "upload_max_concurrency", 1)
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_ingest(**kwargs) -> IngestResult:
        started.set()
        await release.wait()
        return IngestResult(success=True, chunk_count=1)

    monkeypatch.setattr("app.api.documents.ingest_document", slow_ingest)
    upload = asyncio.create_task(
        client.post(
            "/documents/upload",
            files={"file": ("slow.txt", b"safe", "text/plain")},
        )
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    concurrent = await client.post(
        "/documents/upload",
        files={"file": ("second.txt", b"second", "text/plain")},
    )
    assert concurrent.status_code == 429
    health = await asyncio.wait_for(client.get("/health"), timeout=0.5)
    assert health.status_code == 200
    release.set()
    assert (await upload).status_code == 201
