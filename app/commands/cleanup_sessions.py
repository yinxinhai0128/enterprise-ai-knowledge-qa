"""清理过期会话：``python -m app.commands.cleanup_sessions``。"""
from __future__ import annotations

import asyncio

from app.core.checkpointer import close_checkpointer, init_checkpointer
from app.core.database import engine, init_db
from app.services.conversations import cleanup_expired_conversations


async def main() -> int:
    await init_db()
    await init_checkpointer()
    try:
        count = await cleanup_expired_conversations()
        print(f"expired_sessions_deleted={count}")
    finally:
        await close_checkpointer()
        await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
