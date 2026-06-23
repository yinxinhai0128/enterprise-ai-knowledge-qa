"""不消耗模型费用的存活与就绪探针。"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable

from loguru import logger
from sqlalchemy import func, or_, select, text

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.core.vectorstore import close_vectorstore, get_vectorstore, vectorstore_lock
from app.models.ingest_job import IngestJob

Probe = Callable[[], Awaitable[None]]


async def probe_database() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT 1"))


async def probe_vectorstore() -> None:
    def _count() -> None:
        with vectorstore_lock():
            try:
                get_vectorstore()._collection.count()
            finally:
                close_vectorstore()

    await asyncio.to_thread(_count)


async def probe_worker_leases() -> None:
    """运行中任务必须有未过期租约；空队列无需模型或 Worker 外部调用。"""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        stale = (
            await db.execute(
                select(func.count(IngestJob.id)).where(
                    IngestJob.status == "running",
                    or_(
                        IngestJob.lease_owner.is_(None),
                        IngestJob.lease_expires_at.is_(None),
                        IngestJob.lease_expires_at <= now,
                    ),
                )
            )
        ).scalar_one()
    if stale:
        raise RuntimeError("stale worker lease")


async def _run_probe(component: str, error_code: str, probe: Probe) -> dict[str, str]:
    try:
        await asyncio.wait_for(probe(), timeout=settings.readiness_timeout_seconds)
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        logger.bind(
            event="readiness_failed",
            component=component,
            error_code=error_code,
            failure_type=type(exc).__name__,
        ).error("readiness_component_failed")
        return {"status": "error", "error_code": error_code}


async def evaluate_readiness() -> tuple[bool, dict[str, dict[str, str]]]:
    results = await asyncio.gather(
        _run_probe("sqlite", "READINESS_DATABASE_UNAVAILABLE", probe_database),
        _run_probe("vectorstore", "READINESS_VECTORSTORE_UNAVAILABLE", probe_vectorstore),
        _run_probe("worker_lease", "READINESS_WORKER_LEASE_STALE", probe_worker_leases),
    )
    components = dict(zip(("database", "vectorstore", "worker_lease"), results, strict=True))
    return all(item["status"] == "ok" for item in results), components
