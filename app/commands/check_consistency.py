"""运行三存储一致性巡检：``python -m app.commands.check_consistency``。"""
from __future__ import annotations

import asyncio
import json

from app.core.database import engine, init_db
from app.services.consistency import inspect_consistency


async def main() -> int:
    await init_db()
    report = await inspect_consistency()
    print(json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True))
    await engine.dispose()
    return 0 if report.total_issues == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
