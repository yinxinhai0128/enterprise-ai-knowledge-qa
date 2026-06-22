"""不可信文档结构校验与解析共用的独立进程池。"""
from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from typing import Any, Callable

from app.config import settings

_parser_pool: ProcessPoolExecutor | None = None


def get_parser_pool() -> ProcessPoolExecutor:
    global _parser_pool
    if _parser_pool is None:
        _parser_pool = ProcessPoolExecutor(max_workers=settings.parser_workers)
    return _parser_pool


async def run_in_parser_process(
    func: Callable[..., Any],
    *args: Any,
    timeout: float,
) -> Any:
    """在独立进程执行可 pickle 的同步函数，并给 API 调用方明确超时。"""
    loop = asyncio.get_running_loop()
    call = partial(func, *args)
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(get_parser_pool(), call),
            timeout=timeout,
        )
    except TimeoutError:
        _terminate_parser_pool()
        raise


def _terminate_parser_pool() -> None:
    """硬终止超时 Worker；Python 3.12 尚无公开 terminate_workers API。"""
    global _parser_pool
    pool = _parser_pool
    _parser_pool = None
    if pool is None:
        return
    processes = list(getattr(pool, "_processes", {}).values())
    for process in processes:
        if process.is_alive():
            process.terminate()
    for process in processes:
        process.join(timeout=1)
    pool.shutdown(wait=False, cancel_futures=True)


def shutdown_parser_pool() -> None:
    _terminate_parser_pool()
