"""阶段 5：持久化摄入任务、崩溃恢复、幂等与一致性验收。"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

import app.core.database as database_module
from app.models.document import Document
from app.models.ingest_job import IngestJob
from app.services.consistency import inspect_consistency
from app.services.health import probe_vectorstore
from app.services.ingest import IngestResult
from app.services.ingest_jobs import (
    claim_next_ingest_job,
    execute_claimed_ingest_job,
    recover_stale_ingest_state,
    run_worker_once,
    utcnow,
)
from app.services.vector_ops import document_vector_ids


async def _upload(client, name: str = "policy.txt", content: bytes = b"annual leave"):
    response = await client.post(
        "/documents/upload",
        files={"file": (name, content, "text/plain")},
    )
    assert response.status_code == 201, response.text
    return response


async def _expire_job(job_id: int) -> None:
    async with database_module.AsyncSessionLocal() as db:
        job = await db.get(IngestJob, job_id)
        assert job is not None
        job.lease_expires_at = utcnow() - timedelta(seconds=1)
        await db.commit()


async def _vector_ids(doc_id: int) -> list[str]:
    return await document_vector_ids("tenant-a", doc_id)


async def test_job_survives_fresh_api_app_and_duplicate_upload_is_idempotent(
    client, auth_headers, worker_once
):
    first = await _upload(client, content=b"same tenant content")
    duplicate = await _upload(client, name="renamed.txt", content=b"same tenant content")
    assert duplicate.json()["id"] == first.json()["id"]
    assert duplicate.headers["X-Idempotent-Replay"] == "true"

    async with database_module.AsyncSessionLocal() as db:
        document_count = await db.scalar(select(func.count()).select_from(Document))
        job_count = await db.scalar(select(func.count()).select_from(IngestJob))
    assert document_count == 1
    assert job_count == 1

    # 新建 API 应用对象模拟 API 进程重启；待处理 Job 来自 SQLite，不依赖进程内存。
    from app.main import create_app

    async with AsyncClient(
        transport=ASGITransport(app=create_app()),
        base_url="http://restarted",
        headers=auth_headers(),
    ) as restarted:
        jobs = await restarted.get(f"/documents/{first.json()['id']}/jobs")
    assert jobs.status_code == 200
    assert jobs.json()[0]["status"] == "pending"

    assert await worker_once() is True
    assert await _vector_ids(first.json()["id"])


async def test_crash_before_vector_write_is_reclaimed(client, worker_once):
    uploaded = await _upload(client, content=b"crash before vector")
    job_id = await claim_next_ingest_job("dead-worker")
    assert job_id is not None
    assert await _vector_ids(uploaded.json()["id"]) == []

    await _expire_job(job_id)
    recovered = await recover_stale_ingest_state()
    assert recovered["jobs"] == 1
    assert await worker_once() is True
    detail = await client.get(f"/documents/{uploaded.json()['id']}")
    assert detail.json()["status"] == "indexed"
    assert await _vector_ids(uploaded.json()["id"])


async def test_crash_after_vector_write_recovers_path_and_upserts_same_chunk(
    client,
):
    uploaded = await _upload(client, content=b"crash after vector")

    async def crash_after_vector(*_args):
        raise RuntimeError("simulated process death")

    with pytest.raises(RuntimeError, match="simulated process death"):
        await run_worker_once(
            worker_id="dead-after-vector",
            after_ingest_hook=crash_after_vector,
        )
    assert await _vector_ids(uploaded.json()["id"])

    async with database_module.AsyncSessionLocal() as db:
        job = (await db.execute(select(IngestJob))).scalar_one()
        document = await db.get(Document, uploaded.json()["id"])
        stale_path = Path(document.file_path)
        assert job.status == "running"
        assert not stale_path.exists()
        job_id = job.id

    await _expire_job(job_id)
    assert (await recover_stale_ingest_state())["jobs"] == 1
    assert await run_worker_once(worker_id="recovery-worker") is True
    assert len(await _vector_ids(uploaded.json()["id"])) == 1
    async with database_module.AsyncSessionLocal() as db:
        document = await db.get(Document, uploaded.json()["id"])
        assert document.status == "indexed"
        assert Path(document.file_path).is_file()


async def test_vector_failure_never_marks_document_indexed(
    client, monkeypatch, worker_once
):
    uploaded = await _upload(client, content=b"vector service failure")

    async def fail_vector_write(*_args, **_kwargs):
        raise RuntimeError("vector unavailable")

    monkeypatch.setattr("app.services.ingest.add_documents_to_pgvector", fail_vector_write)
    assert await worker_once() is True
    detail = await client.get(f"/documents/{uploaded.json()['id']}")
    assert detail.json()["status"] != "indexed"
    assert await _vector_ids(uploaded.json()["id"]) == []
    jobs = (await client.get(f"/documents/{uploaded.json()['id']}/jobs")).json()
    assert jobs[0]["status"] in {"retry", "failed"}


async def test_database_finalize_failure_compensates_vectors(
    client, worker_once
):
    uploaded = await _upload(client, content=b"database finalize failure")

    async def fail_finalize(*_args):
        raise RuntimeError("database unavailable")

    assert await worker_once(before_finalize_hook=fail_finalize) is True
    assert await _vector_ids(uploaded.json()["id"]) == []
    detail = await client.get(f"/documents/{uploaded.json()['id']}")
    assert detail.json()["status"] != "indexed"
    assert "补偿删除向量" in detail.json()["error_msg"]


async def test_reexecuting_same_job_does_not_duplicate_chunks(
    client, worker_once
):
    uploaded = await _upload(client, content=b"stable chunk identity")
    assert await worker_once() is True
    initial_ids = await _vector_ids(uploaded.json()["id"])
    assert len(initial_ids) == 1

    async with database_module.AsyncSessionLocal() as db:
        job = (await db.execute(select(IngestJob))).scalar_one()
        document = await db.get(Document, uploaded.json()["id"])
        job.status = "pending"
        job.attempt = 0
        job.next_retry_at = utcnow()
        document.status = "uploading"
        await db.commit()

    assert await worker_once() is True
    assert await _vector_ids(uploaded.json()["id"]) == initial_ids


async def test_cancel_retry_and_reindex_endpoints(
    client, worker_once
):
    uploaded = await _upload(client, content=b"lifecycle endpoints")
    doc_id = uploaded.json()["id"]
    cancelled = await client.post(f"/documents/{doc_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    retried = await client.post(f"/documents/{doc_id}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "pending"
    assert await worker_once() is True
    original_ids = await _vector_ids(doc_id)

    reindex = await client.post(f"/documents/{doc_id}/reindex")
    assert reindex.status_code == 202
    assert reindex.json()["job_type"] == "reindex"
    assert await worker_once() is True
    assert await _vector_ids(doc_id) == original_ids


async def test_delete_removes_database_file_vectors_and_jobs(
    client, worker_once
):
    uploaded = await _upload(client, content=b"delete every layer")
    doc_id = uploaded.json()["id"]
    assert await worker_once() is True
    async with database_module.AsyncSessionLocal() as db:
        document = await db.get(Document, doc_id)
        file_path = Path(document.file_path)
    assert file_path.is_file()
    assert await _vector_ids(doc_id)

    deleted = await client.delete(f"/documents/{doc_id}")
    assert deleted.status_code == 204
    assert not file_path.exists()
    assert await _vector_ids(doc_id) == []
    async with database_module.AsyncSessionLocal() as db:
        assert await db.get(Document, doc_id) is None
        assert await db.scalar(select(func.count()).select_from(IngestJob)) == 0


async def test_startup_repairs_stuck_document_without_job(client):
    uploaded = await _upload(client, content=b"repair missing job")
    doc_id = uploaded.json()["id"]
    async with database_module.AsyncSessionLocal() as db:
        job = (await db.execute(select(IngestJob))).scalar_one()
        await db.delete(job)
        document = await db.get(Document, doc_id)
        document.status = "parsing"
        await db.commit()

    repaired = await recover_stale_ingest_state()
    assert repaired["documents"] == 1
    async with database_module.AsyncSessionLocal() as db:
        job = (await db.execute(select(IngestJob))).scalar_one()
        assert job.status == "pending"


async def test_reindex_awaits_vector_delete(client, monkeypatch):
    uploaded = await _upload(client, content=b"await reindex delete")
    doc_id = uploaded.json()["id"]
    worker_id = "reindex-await-worker"
    async with database_module.AsyncSessionLocal() as db:
        document = await db.get(Document, doc_id)
        job = (await db.execute(select(IngestJob))).scalar_one()
        job.status = "running"
        job.job_type = "reindex"
        job.lease_owner = worker_id
        await db.commit()
        job_id = job.id
        file_path = document.file_path
        filename = document.filename
        uploaded_by = document.uploaded_by

    async def fake_ingest_document(**_kwargs) -> IngestResult:
        return IngestResult(success=True, chunk_count=1)

    delete_vectors = AsyncMock(return_value=0)
    monkeypatch.setattr("app.services.ingest_jobs.ingest_document", fake_ingest_document)
    monkeypatch.setattr("app.services.ingest_jobs.delete_document_vectors", delete_vectors)

    await execute_claimed_ingest_job(job_id, worker_id)

    delete_vectors.assert_awaited_once_with("tenant-a", doc_id)
    async with database_module.AsyncSessionLocal() as db:
        document = await db.get(Document, doc_id)
        assert document.file_path == file_path
        assert document.filename == filename
        assert document.uploaded_by == uploaded_by


async def test_failed_ingest_awaits_vector_delete(client, monkeypatch):
    uploaded = await _upload(client, content=b"await failed delete")
    doc_id = uploaded.json()["id"]

    async def fake_ingest_document(**_kwargs) -> IngestResult:
        return IngestResult(success=False, error_msg="boom")

    delete_vectors = AsyncMock(return_value=0)
    monkeypatch.setattr("app.services.ingest_jobs.ingest_document", fake_ingest_document)
    monkeypatch.setattr("app.services.ingest_jobs.delete_document_vectors", delete_vectors)

    assert await run_worker_once(worker_id="failed-await-worker") is True

    delete_vectors.assert_awaited_once_with("tenant-a", doc_id)


async def test_cancelled_after_ingest_awaits_vector_delete(client, monkeypatch):
    uploaded = await _upload(client, content=b"await cancel delete")
    doc_id = uploaded.json()["id"]

    async def cancel_after_ingest(*_args) -> None:
        async with database_module.AsyncSessionLocal() as db:
            job = (await db.execute(select(IngestJob))).scalar_one()
            job.status = "cancelled"
            job.lease_owner = None
            await db.commit()

    delete_vectors = AsyncMock(return_value=0)
    monkeypatch.setattr("app.services.ingest_jobs.delete_document_vectors", delete_vectors)

    assert await run_worker_once(
        worker_id="cancel-await-worker",
        after_ingest_hook=cancel_after_ingest,
    ) is True

    delete_vectors.assert_awaited_once_with("tenant-a", doc_id)


async def test_delete_document_awaits_vector_delete(client, worker_once, monkeypatch):
    uploaded = await _upload(client, content=b"await endpoint delete")
    doc_id = uploaded.json()["id"]
    assert await worker_once() is True

    delete_vectors = AsyncMock(return_value=1)
    monkeypatch.setattr("app.api.documents.delete_document_vectors", delete_vectors)

    deleted = await client.delete(f"/documents/{doc_id}")

    assert deleted.status_code == 204
    delete_vectors.assert_awaited_once_with("tenant-a", doc_id)


async def test_vectorstore_probe_uses_document_chunks_not_faiss():
    await probe_vectorstore()


async def test_consistency_report_is_zero_after_success(client, worker_once):
    await _upload(client, content=b"consistent state")
    assert await worker_once() is True
    assert (await inspect_consistency()).to_dict() == {
        "missing_files": 0,
        "missing_vectors": 0,
        "extra_vectors": 0,
        "orphan_vectors": 0,
        "orphan_files": 0,
        "orphan_jobs": 0,
        "orphan_tenant_docs": 0,
        "total_issues": 0,
    }
