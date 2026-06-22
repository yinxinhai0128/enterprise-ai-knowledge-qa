"""独立摄入 Worker 入口：``python -m app.worker``。"""
from __future__ import annotations

import asyncio

from loguru import logger

from app.config import settings
from app.core.database import engine, init_db
from app.core.process_pool import shutdown_parser_pool
from app.services.ingest_jobs import new_worker_id, recover_stale_ingest_state, run_worker_once


async def _worker_loop(slot: int) -> None:
    worker_id = f"{new_worker_id()}-{slot}"
    logger.info("摄入 Worker 启动 worker_id={}", worker_id)
    while True:
        try:
            handled = await run_worker_once(worker_id)
            if not handled:
                await asyncio.sleep(settings.ingest_job_poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            # 未捕获异常按“Worker 崩溃”语义保留租约，过期后由任意实例恢复。
            logger.exception("Worker 执行异常，任务将由租约恢复 worker_id={}", worker_id)
            await asyncio.sleep(settings.ingest_job_poll_seconds)


async def main() -> None:
    settings.ensure_dirs()
    await init_db()
    recovered = await recover_stale_ingest_state()
    logger.info("启动恢复完成 {}", recovered)
    tasks = [
        asyncio.create_task(_worker_loop(slot))
        for slot in range(settings.ingest_worker_concurrency)
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        shutdown_parser_pool()
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
