"""进程级异步 SQLite Checkpointer 生命周期。"""
from __future__ import annotations

import asyncio
from pathlib import Path

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
        target = path or settings.checkpoint_db_path
        target.parent.mkdir(parents=True, exist_ok=True)
        connection = await aiosqlite.connect(str(target))
        await connection.execute("PRAGMA busy_timeout=30000")
        saver = AsyncSqliteSaver(connection)
        await saver.setup()
        _connection = connection
        _checkpointer = saver
        return saver


def get_checkpointer() -> AsyncSqliteSaver:
    if _checkpointer is None:
        raise RuntimeError("持久化 Checkpointer 尚未初始化")
    return _checkpointer


async def close_checkpointer() -> None:
    global _connection, _checkpointer, _init_lock
    connection = _connection
    _checkpointer = None
    _connection = None
    _init_lock = None
    if connection is not None:
        await connection.close()
