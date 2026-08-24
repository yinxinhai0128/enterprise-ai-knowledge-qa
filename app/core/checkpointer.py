"""进程级异步 LangGraph Checkpointer 生命周期。

Windows 环境限制：asyncpg（主 DB）占用 SelectorEventLoop 的 I/O 注册表，
psycopg async 在同一 loop 下连接会永久挂起。
因此 checkpoint 保留 AsyncSqliteSaver（aiosqlite 跑在线程池，不触碰事件循环）。
PostgreSQL checkpoint 可在 Linux 生产部署时切换。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.config import settings

_connection: aiosqlite.Connection | None = None
_checkpointer: AsyncSqliteSaver | None = None
_init_lock: asyncio.Lock | None = None


async def init_checkpointer(path: Path | None = None) -> AsyncSqliteSaver:
    global _connection, _checkpointer, _init_lock
    if _checkpointer is not None:
        return _checkpointer
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    async with _init_lock:
        if _checkpointer is not None:
            return _checkpointer
        if path is None:
            path = settings.checkpoint_db_path
        path.parent.mkdir(parents=True, exist_ok=True)
        _connection = await aiosqlite.connect(str(path))
        _checkpointer = AsyncSqliteSaver(_connection)
        await _checkpointer.setup()
        return _checkpointer


def get_checkpointer() -> Any:
    if _checkpointer is None:
        raise RuntimeError("持久化 Checkpointer 尚未初始化")
    return _checkpointer


async def close_checkpointer() -> None:
    global _connection, _checkpointer, _init_lock
    conn = _connection
    _checkpointer = None
    _connection = None
    _init_lock = None
    if conn is not None:
        await conn.close()
