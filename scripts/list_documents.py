import asyncio
import sys

sys.path.insert(0, '.')

async def main():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import settings
    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT id, filename, file_path, status, chunk_count FROM documents ORDER BY id"
        ))
        for row in result.mappings():
            print(f"id={row['id']} chunks={row['chunk_count']} status={row['status']}")
            print(f"  path: {row['file_path']}")
            from pathlib import Path
            p = Path(row['file_path'])
            print(f"  exists: {p.exists()} size: {p.stat().st_size if p.exists() else 'N/A'}")

asyncio.run(main())
