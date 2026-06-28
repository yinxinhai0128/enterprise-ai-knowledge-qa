"""在隔离目录中验证当前数据库初始化/迁移的幂等性。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
from pathlib import Path


def _configure(root: Path) -> Path:
    """在导入应用配置前，将所有可写路径限制到验收目录。"""
    root = root.resolve()
    storage = root / "storage"
    database = storage / "app.db"
    os.environ.update(
        {
            "APP_ENV": "development",
            "APP_HOST": "127.0.0.1",
            "DASHSCOPE_API_KEY": "stage12-schema-validation-only",
            "AUTH_JWT_SECRET": "stage12-schema-validation-secret-32-bytes",
            "DATABASE_URL": f"sqlite+aiosqlite:///{database.as_posix()}",
            "STORAGE_DIR": str(storage),
            "LOG_DIR": str(root / "logs"),
            "CHECKPOINT_DB_PATH": str(storage / "checkpoints.db"),
            "LANGCHAIN_TRACING_V2": "false",
            "LANGSMITH_API_KEY": "",
        }
    )
    return database


async def _run_migrations() -> None:
    # 配置依赖导入时创建单例，必须晚于 _configure。
    from app.config import settings
    from app.core.database import engine, init_db

    settings.ensure_dirs()
    try:
        await init_db()
        await init_db()
    finally:
        await engine.dispose()


def _inspect(database: Path) -> dict[str, str | int]:
    with sqlite3.connect(database) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        schema_rows = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
    schema = json.dumps(schema_rows, ensure_ascii=False, separators=(",", ":"))
    return {
        "integrity_check": integrity,
        "schema_objects": len(schema_rows),
        "schema_sha256": hashlib.sha256(schema.encode("utf-8")).hexdigest(),
    }


def _row_counts(database: Path) -> dict[str, int]:
    if not database.is_file():
        return {}
    with sqlite3.connect(database) as connection:
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        counts: dict[str, int] = {}
        for table in tables:
            quoted = table.replace('"', '""')
            counts[table] = int(
                connection.execute(f'SELECT COUNT(*) FROM "{quoted}"').fetchone()[0]
            )
        return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--show-objects", action="store_true")
    args = parser.parse_args()

    database = _configure(args.root)
    before = _row_counts(database)
    asyncio.run(_run_migrations())
    after = _row_counts(database)
    preserved = all(after.get(table) == count for table, count in before.items())
    result: dict[str, object] = {
        "label": args.label,
        **_inspect(database),
        "rows": sum(after.values()),
        "row_counts_preserved": preserved,
    }
    if args.show_objects:
        with sqlite3.connect(database) as connection:
            result["objects"] = [
                f"{row[0]}:{row[1]}"
                for row in connection.execute(
                    "SELECT type, name FROM sqlite_master "
                    "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
                )
            ]
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["integrity_check"] == "ok" and preserved else 1


if __name__ == "__main__":
    raise SystemExit(main())
