import asyncio
import sys

sys.path.insert(0, '.')

async def main():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import settings
    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        tables = [r[0] for r in result]
        print('Tables:', tables)
        for t in tables:
            r2 = await conn.execute(text(f"SELECT COUNT(*) FROM {t}"))
            cnt = r2.scalar()
            print(f"  {t}: {cnt} rows")
            # print columns
            r3 = await conn.execute(text(f"PRAGMA table_info({t})"))
            cols = [f"{r['name']}({r['type']})" for r in r3.mappings()]
            print(f"    cols: {', '.join(cols[:8])}")

asyncio.run(main())
