"""清理过期会话：``python -m app.commands.cleanup_sessions``。"""
from __future__ import annotations

import asyncio
import json
import sys

from app.core.checkpointer import close_checkpointer, init_checkpointer
from app.core.database import engine, init_db
from app.services.conversations import cleanup_expired_conversations


async def main() -> int:
    await init_db()
    await init_checkpointer()
    try:
        count = await cleanup_expired_conversations()
        print(json.dumps({"expired_sessions_deleted": count}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        await close_checkpointer()
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
