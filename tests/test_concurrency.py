"""端到端并发验收：真实 API 路径、临时 SQLite 与持久化审计。"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

import app.core.database as database_module
from app.models.chat_record import ChatRecord


async def test_concurrent_distinct_uploads_are_both_persisted(client, worker_once):
    responses = await asyncio.gather(
        client.post(
            "/documents/upload",
            files={"file": ("concurrent-a.txt", b"concurrent upload A", "text/plain")},
        ),
        client.post(
            "/documents/upload",
            files={"file": ("concurrent-b.txt", b"concurrent upload B", "text/plain")},
        ),
    )
    assert [response.status_code for response in responses] == [201, 201]
    assert len({response.json()["id"] for response in responses}) == 2
    assert await worker_once() is True
    assert await worker_once() is True

    listing = await client.get("/documents")
    filenames = {item["filename"] for item in listing.json()}
    assert {"concurrent-a.txt", "concurrent-b.txt"} <= filenames


async def test_concurrent_questions_use_independent_sessions(
    client,
    agent_factory,
):
    agent_factory(["并发回答 A", "并发回答 B"])
    responses = await asyncio.gather(
        client.post(
            "/qa/ask",
            json={"question": "并发问题 A", "session_id": "concurrent-a"},
        ),
        client.post(
            "/qa/ask",
            json={"question": "并发问题 B", "session_id": "concurrent-b"},
        ),
    )
    assert [response.status_code for response in responses] == [200, 200]

    async with database_module.AsyncSessionLocal() as db:
        records = (
            await db.execute(
                select(ChatRecord).where(
                    ChatRecord.session_id.in_(
                        (
                            "tenant-a:user-a:concurrent-a",
                            "tenant-a:user-a:concurrent-b",
                        )
                    )
                )
            )
        ).scalars().all()
    assert {record.question for record in records} == {"并发问题 A", "并发问题 B"}
    assert all(record.audit_status == "completed" for record in records)
